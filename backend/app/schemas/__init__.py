import sys
import importlib

# Automatically link rag_new schema modules so both `app.schemas.X` and `app.schemas.rag_new.X` resolve cleanly
_RAG_SCHEMAS = [
    "chat", "document", "evidence", "conversation", "retrieval",
    "user", "response", "auth", "chunk", "token", "usage", "rag", "query_analysis"
]

for _mod in _RAG_SCHEMAS:
    try:
        sys.modules[f"app.schemas.{_mod}"] = importlib.import_module(f"app.schemas.rag_new.{_mod}")
    except Exception:
        pass
