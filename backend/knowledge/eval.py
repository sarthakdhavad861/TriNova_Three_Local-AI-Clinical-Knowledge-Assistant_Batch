"""
knowledge/eval.py — retrieval evaluation against a gold query set.

  python -m knowledge.eval gold.json [--k 5]

gold.json: [{"id": "q1", "query": "...", "expect_sources": ["drug-list-pdf"], "expect_text": ["eGFR < 30"]},
            {"id": "q2", "query": "unrelated question", "expect_none": true}, ...]
A case passes if any of the top-k evidence items is from an expected source or contains an expected text
(case-insensitive); an `expect_none` case passes only if NOTHING is retrieved (correct abstention).
Prints recall@k, abstention accuracy and the per-case scores, which is what you need to calibrate
SIM_THRESHOLD / MIN_LEXICAL_COVERAGE on YOUR corpus. Uses the real Ollama + Chroma stack from the CLI.
"""
from __future__ import annotations

import argparse
import json
import sys


def evaluate(retriever, cases: list[dict], k: int | None = None) -> dict:
    rows, hits, in_scope, abst_ok, abst_total = [], 0, 0, 0, 0
    for case in cases:
        res = retriever.retrieve(case["query"])
        ev = res.evidence[:k] if k else res.evidence
        row = {"id": case.get("id", case["query"][:30]), "query": case["query"],
               "returned": [{"chunk_id": e.chunk_id, "source_id": e.source_id, "dense": e.dense_score,
                             "coverage": e.lexical_coverage} for e in ev], "notes": res.notes}
        if case.get("expect_none"):
            abst_total += 1
            row["pass"] = not ev
            abst_ok += row["pass"]
        else:
            in_scope += 1
            srcs, texts = set(case.get("expect_sources", [])), [t.lower() for t in case.get("expect_text", [])]
            row["pass"] = any(e.source_id in srcs or any(t in e.text.lower() for t in texts) for e in ev)
            hits += row["pass"]
        rows.append(row)
    return {"k": k, "recall_at_k": (hits / in_scope) if in_scope else None, "in_scope": in_scope,
            "abstention_accuracy": (abst_ok / abst_total) if abst_total else None, "out_of_scope": abst_total,
            "cases": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="knowledge.eval", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gold"); ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args(argv)
    with open(args.gold, encoding="utf-8") as f:
        cases = json.load(f)
    from knowledge.runtime import get_retriever
    report = evaluate(get_retriever(), cases, args.k)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    failed = [c["id"] for c in report["cases"] if not c["pass"]]
    if failed:
        print(f"FAILED cases: {failed}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
