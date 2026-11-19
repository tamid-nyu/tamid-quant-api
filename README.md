# TAMID Quant API
Shared FastAPI backend for TAMID research projects. The first strategy lives in `strategies/kalshi_tail`; shared storage, uploads, ingestion, authentication and Kalshi data belong in `shared`. Vendored strategy Python files are unchanged from `engine/SOURCE_COMMIT`; refresh with `scripts/sync_engine.sh /path/to/source`.

Run `pip install -r requirements.txt` then `uvicorn api.index:app`. Set `BLOB_READ_WRITE_TOKEN` for private Vercel Blob persistence and run `python scripts/seed.py` once. `LAB_API_TOKEN` authenticates writes. Production docs: `/docs`, schema: `/openapi.json` (also `/api/openapi.json`). No credentials belong in git.

Source results are research evidence, not a promise of returns. Frozen settings date: 2026-11-12. The source repository does not commit non-BTC observations or numbered-variant output; these must be ingested or computed, never inferred from trades.
