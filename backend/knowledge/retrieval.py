"""
knowledge/retrieval.py
Hybrid retrieval over the knowledge base: dense vectors (Chroma, via an injected query function)
+ keyword search (SQLite FTS5/BM25), fused with reciprocal-rank fusion.

Safety properties:
  * Every candidate is re-read from SQLite and must belong to an ACTIVE source version. Vectors that
    are orphaned, superseded or legacy (pre-knowledge-base) are dropped, so they can never be cited.
  * Full chunk text and provenance (source, version, page, section) travel with each piece of evidence.
  * A chunk is eligible only if it clears the dense-similarity threshold OR covers enough of the query's
    terms; if nothing is eligible the result is "insufficient" and no answer should be generated.
  * If the embedding service is unavailable, retrieval degrades to keyword-only and says so.
Thresholds are configuration, not calibrated truth: measure them on your corpus with `knowledge.eval`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-/][a-z0-9]+)*")
STOPWORDS = frozenset("""a an the of in on at to for with without and or but if is are was were be been being what which who
whom how when where why do does did can could should would may might must shall will i you we they he she it this that these
those from by as about into than then there their its our your my me us them his her not no yes any some such also very
patient patients please tell give show me explain""".split())


_SUFFIXES = tuple(sorted(("ations", "ation", "ings", "ing", "ments", "ment", "ities", "ity", "ions", "ion", "ated",
                         "ates", "ate", "ied", "ies", "ed", "es", "s", "ly"), key=len, reverse=True))


def stem(tok: str) -> str:
    """Deliberately conservative suffix stripping (calibration/calibrate → calibr; doses → dose). Digits untouched."""
    if len(tok) <= 4 or any(c.isdigit() for c in tok):
        return tok
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def tokens(text: str) -> set[str]:
    """Lower-case tokens, their stems, and the sub-parts of compound tokens ('ml/min/1.73m2' → ml, min, 1, 73m2)."""
    out: set[str] = set()
    for tok in _TOKEN.findall((text or "").lower()):
        parts = re.split(r"[.\-/]", tok) if re.search(r"[.\-/]", tok) else []
        for t in (tok, *parts):
            out.add(t)
            out.add(stem(t))
    return out


def coverage(terms: list[str], toks: set[str]) -> float:
    """Share of query terms present in a token set (exactly or by stem)."""
    return (sum(1 for t in terms if t in toks or stem(t) in toks) / len(terms)) if terms else 0.0


def query_terms(query: str) -> list[str]:
    """Searchable content terms of a question (stop-words and 1-character tokens removed, order kept)."""
    seen: dict[str, None] = {}
    for tok in _TOKEN.findall((query or "").lower()):
        parts = re.split(r"[.\-/]", tok) if re.search(r"[.\-/]", tok) else [tok]
        for part in parts:
            if len(part) >= 2 and part not in STOPWORDS:
                seen.setdefault(part)
    return list(seen)


@dataclass
class Evidence:
    chunk_id: str
    source_id: str
    display_name: str
    version: int
    text: str
    page: int | None = None
    section: str = ""
    kind: str = ""
    category: str | None = None
    license: str | None = None
    origin: str | None = None
    dense_score: float | None = None
    lexical_coverage: float = 0.0
    rrf: float = 0.0
    ref: str = ""                       # "S1", "S2" … assigned when the evidence is put into a prompt

    @property
    def score(self) -> float:
        """Single 0–1 figure for display: cosine similarity if available, else keyword coverage."""
        return round(self.dense_score if self.dense_score is not None else self.lexical_coverage, 4)

    def label(self) -> str:
        bits = [self.display_name]
        if self.page:
            bits.append(f"p.{self.page}")
        if self.section:
            bits.append(f"§ {self.section}")
        bits.append(f"v{self.version}")
        return ", ".join(bits)


@dataclass
class RetrievalResult:
    query: str
    evidence: list[Evidence] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def sufficient(self) -> bool:
        return bool(self.evidence)


class Retriever:
    def __init__(self, store, vector_query: Callable[[list[float], int], list[tuple[str, float]]],
                 embed_query: Callable[[str], list[float]], *, top_k: int = 6, overfetch: int = 4,
                 min_dense: float = 0.25, min_coverage: float = 0.5, rrf_k: int = 60):
        self.store, self.vector_query, self.embed_query = store, vector_query, embed_query
        self.top_k, self.overfetch = top_k, max(1, overfetch)
        self.min_dense, self.min_coverage, self.rrf_k = min_dense, min_coverage, rrf_k

    def retrieve(self, query: str, *, categories: set[str] | None = None) -> RetrievalResult:
        terms = query_terms(query)
        n = self.top_k * self.overfetch
        result = RetrievalResult(query=query, terms=terms)

        dense: dict[str, float] = {}
        try:
            for cid, sim in self.vector_query(self.embed_query(query), n):
                dense[cid] = max(sim, dense.get(cid, float("-inf")))
        except Exception as e:  # noqa: BLE001 - degrade, but never silently
            result.notes.append(f"dense retrieval unavailable ({type(e).__name__}); keyword search only")

        lexical = self.store.search_lexical(terms, n)
        if terms and not self.store.fts_enabled:
            result.notes.append("keyword index unavailable (SQLite without FTS5); dense search only")
        lex_rank = {cid: i for i, cid in enumerate(lexical, start=1)}

        candidates = list(dict.fromkeys([*dense, *lexical]))
        rows = self.store.get_active_chunks(candidates)
        stale = len(candidates) - len(rows)

        scored: list[Evidence] = []
        for cid, row in rows.items():
            if categories and row.get("category") not in categories:
                continue
            cov = coverage(terms, tokens(row["text"]))
            d = dense.get(cid)
            eligible = (d is not None and d >= self.min_dense) or (cid in lex_rank and cov >= self.min_coverage)
            if not eligible:
                continue
            scored.append(Evidence(
                chunk_id=cid, source_id=row["source_id"], display_name=row["display_name"], version=row["version"],
                text=row["text"], page=row["page"], section=row["section"] or "", kind=row["kind"],
                category=row["category"], license=row["license"], origin=row["origin"],
                dense_score=d, lexical_coverage=round(cov, 4)))

        by_dense = sorted((e for e in scored if e.dense_score is not None), key=lambda e: -e.dense_score)
        by_lex = sorted((e for e in scored if e.chunk_id in lex_rank), key=lambda e: lex_rank[e.chunk_id])
        for rank, e in enumerate(by_dense, start=1):
            e.rrf += 1.0 / (self.rrf_k + rank)
        for rank, e in enumerate(by_lex, start=1):
            e.rrf += 1.0 / (self.rrf_k + rank)
        scored.sort(key=lambda e: (-e.rrf, -(e.dense_score or 0.0), e.chunk_id))

        result.evidence = scored[: self.top_k]
        result.stats = {
            "dense_candidates": len(dense), "keyword_candidates": len(lexical),
            "stale_or_legacy_filtered": stale, "eligible": len(scored), "returned": len(result.evidence),
        }
        return result
