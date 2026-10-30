"""Ingest the synthetic demo corpus listed in demo/manifest.json (needs Ollama bge-m3 + ChromaDB; see docs/SETUP.md).
Run from backend/:   python scripts/load_demo.py
Re-running is safe: unchanged files are reported as 'unchanged'."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
DEMO = Path(__file__).resolve().parent.parent.parent / "demo"


def main() -> int:
    from knowledge.runtime import get_service
    manifest = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))
    svc, bad = get_service(), 0
    for item in manifest["files"]:
        path = DEMO / item["file"]
        r = svc.ingest_file(path, path.name, category=item.get("category"), license=item["license"], origin=item["origin"])
        print(f"{r.status:10} {item['file']}  {r.message}")
        bad += r.status not in ("success", "unchanged")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
