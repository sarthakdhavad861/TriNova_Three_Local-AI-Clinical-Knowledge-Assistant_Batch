"""
knowledge/cli.py — ingest and inspect the knowledge base from the command line.

Run from the backend/ directory:
  python -m knowledge.cli ingest FILE [--category medicine] [--license "CC BY 4.0"] [--origin URL_OR_NOTE]
  python -m knowledge.cli sources
  python -m knowledge.cli inspect SOURCE_ID [--chunks N]
  python -m knowledge.cli records [--category medicine] [--name paracetamol] [--source ID]
  python -m knowledge.cli events [--status error]
Read-only commands need no Ollama/Chroma; `ingest` needs Ollama (bge-m3) and ChromaDB.
"""
from __future__ import annotations

import argparse
import json
import sys

from knowledge.parsers import CATEGORIES


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="knowledge.cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("file")
    p.add_argument("--category", choices=CATEGORIES); p.add_argument("--license"); p.add_argument("--origin")
    sub.add_parser("sources")
    p = sub.add_parser("inspect"); p.add_argument("source_id"); p.add_argument("--chunks", type=int, default=3)
    p = sub.add_parser("records"); p.add_argument("--category", choices=CATEGORIES)
    p.add_argument("--name"); p.add_argument("--source"); p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("events"); p.add_argument("--status"); p.add_argument("--limit", type=int, default=20)
    args = ap.parse_args(argv)

    from knowledge.runtime import get_store
    store = get_store()
    if args.cmd == "ingest":
        from knowledge.runtime import get_service
        res = get_service().ingest_file(args.file, args.file, category=args.category,
                                        license=args.license, origin=args.origin)
        _print(res.as_dict())
        return 0 if res.status in ("success", "unchanged") else 1
    if args.cmd == "sources":
        _print({"totals": store.totals(), "sources": store.list_sources()})
    elif args.cmd == "inspect":
        src = store.get_source(args.source_id)
        if not src:
            print(f"No such source: {args.source_id}", file=sys.stderr)
            return 1
        src["sample_chunks"] = store.list_chunks(args.source_id, limit=args.chunks)
        _print(src)
    elif args.cmd == "records":
        _print(store.list_records(source_id=args.source, category=args.category, name=args.name, limit=args.limit))
    elif args.cmd == "events":
        _print(store.list_events(limit=args.limit, status=args.status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
