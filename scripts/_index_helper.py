#!/usr/bin/env python3
import os, sys
root = os.environ["IVCRAG_ROOT"]
docs = os.environ["IVCRAG_DOCS"]
sys.path.insert(0, os.path.join(root, "app"))
try:
    import embedding_server as es
    files = []
    for r, _, fs in os.walk(docs):
        for f in fs:
            if f.startswith("~$") or f.endswith((".tmp", ".bak")):
                continue
            if f.lower().endswith((".xlsx", ".pdf", ".txt", ".docx", ".csv")):
                files.append(os.path.join(r, f))
    print(f"  files to index: {len(files)}")
    if hasattr(es, "index_all_documents"):
        es.index_all_documents(files)
        print("  [ok] via index_all_documents")
    else:
        print("  [WARN] index_all_documents not found; use UI or server API")
except Exception as e:
    print(f"  [WARN] index error: {e}")
