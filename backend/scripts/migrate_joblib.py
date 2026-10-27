#!/usr/bin/env python3
"""
scripts/migrate_joblib.py
One-time migration: embeddings.joblib (old format) → ChromaDB (new backend)

Usage:
    cd backend
    python scripts/migrate_joblib.py [--joblib PATH]

Defaults to looking for embeddings.joblib in:
  1. Current directory (backend/)
  2. Parent directory (project root)
  3. Path provided via --joblib argument

Safe to run multiple times — uses chunk_id as ChromaDB document id,
so duplicate inserts are skipped via upsert.
"""
import sys, os, argparse
from pathlib import Path

# Allow running from backend/ or project root
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

def find_joblib(explicit_path=None):
    candidates = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    candidates += [
        BACKEND_DIR / "embeddings.joblib",
        BACKEND_DIR.parent / "embeddings.joblib",
        Path.cwd() / "embeddings.joblib",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def main():
    parser = argparse.ArgumentParser(description="Migrate embeddings.joblib → ChromaDB")
    parser.add_argument("--joblib", help="Explicit path to embeddings.joblib", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without writing")
    parser.add_argument("--batch", type=int, default=100, help="Upsert batch size (default 100)")
    args = parser.parse_args()

    joblib_path = find_joblib(args.joblib)
    if joblib_path is None:
        print("ERROR: embeddings.joblib not found.")
        print("Searched in backend/, project root, and cwd.")
        print("Use --joblib PATH to specify location.")
        sys.exit(1)

    print(f"Found: {joblib_path}")

    # Load joblib
    try:
        import joblib
        df = joblib.load(joblib_path)
    except Exception as e:
        print(f"ERROR loading joblib: {e}")
        sys.exit(1)

    print(f"Loaded DataFrame: {len(df)} rows, columns: {list(df.columns)}")

    # Validate required columns
    required = {"embedding", "text"}
    missing_cols = required - set(df.columns)
    if missing_cols:
        print(f"ERROR: Missing required columns: {missing_cols}")
        print(f"Available columns: {list(df.columns)}")
        sys.exit(1)

    # Map column names flexibly (Processing.py uses Title/Start/number/end/chunk_id)
    col_map = {
        "title":    next((c for c in df.columns if c.lower() == "title"),    None),
        "number":   next((c for c in df.columns if c.lower() == "number"),   None),
        "start":    next((c for c in df.columns if c.lower() == "start"),    None),
        "end":      next((c for c in df.columns if c.lower() == "end"),      None),
        "chunk_id": next((c for c in df.columns if c.lower() == "chunk_id"), None),
    }
    print(f"Column mapping: {col_map}")

    # Connect to ChromaDB
    from config.settings import ensure_dirs, CHROMA_PATH, CHROMA_COLLECTION
    ensure_dirs()

    import chromadb
    from chromadb.config import Settings as ChromaSettings
    client = chromadb.PersistentClient(
        path=str(BACKEND_DIR / "vectorstore" / "chroma_db"),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    before_count = collection.count()
    print(f"\nChromaDB before migration: {before_count} chunks")

    if args.dry_run:
        print(f"DRY RUN — would migrate {len(df)} chunks. No changes made.")
        return

    # Upsert in batches
    import numpy as np
    rows = df.reset_index(drop=True)
    total = len(rows)
    migrated = 0
    skipped  = 0

    for batch_start in range(0, total, args.batch):
        batch = rows.iloc[batch_start:batch_start + args.batch]

        ids, embeddings, documents, metadatas = [], [], [], []

        for i, row in batch.iterrows():
            # Build a stable unique id
            raw_id = row[col_map["chunk_id"]] if col_map["chunk_id"] else i
            doc_id = str(int(raw_id)) if raw_id is not None else str(i)

            emb = row["embedding"]
            if hasattr(emb, "tolist"):
                emb = emb.tolist()
            if not isinstance(emb, list) or len(emb) == 0:
                skipped += 1
                continue

            text = str(row.get("text", "")).strip()
            if not text:
                skipped += 1
                continue

            meta = {
                "title":    str(row[col_map["title"]])    if col_map["title"]    else "",
                "number":   str(row[col_map["number"]])   if col_map["number"]   else "",
                "start":    float(row[col_map["start"]])  if col_map["start"]    else 0.0,
                "end":      float(row[col_map["end"]])    if col_map["end"]      else 0.0,
                "chunk_id": int(raw_id)                   if raw_id is not None  else i,
            }

            ids.append(doc_id)
            embeddings.append(emb)
            documents.append(text)
            metadatas.append(meta)

        if ids:
            collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
            migrated += len(ids)
            print(f"  Upserted batch {batch_start}–{batch_start+len(ids)-1} ({len(ids)} chunks)")

    after_count = collection.count()
    print(f"\n{'='*50}")
    print(f"Migration complete.")
    print(f"  Chunks in joblib:   {total}")
    print(f"  Migrated:           {migrated}")
    print(f"  Skipped (bad data): {skipped}")
    print(f"  ChromaDB before:    {before_count}")
    print(f"  ChromaDB after:     {after_count}")
    print(f"  New chunks added:   {after_count - before_count}")
    print(f"{'='*50}")
    print("Done. You can now query your videos.")

if __name__ == "__main__":
    main()
