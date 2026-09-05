"""
Settlement Leakage Auditor — REST API

Serves the deterministic engine + classifier pipeline live over HTTP.
The dashboard fetches from this instead of reading a static JSON file, so
every batch, case, and metric on screen reflects an actual pipeline run.

Run:
    uvicorn api:app --reload --port 8000

Endpoints:
    GET  /api/health
    GET  /api/audit                        -> full dashboard payload (cached after first run)
    POST /api/audit/run?seed=42&inject_break=duplicate_webhook
                                            -> regenerate data + rerun pipeline, returns fresh payload
    GET  /api/audit/case/{payment_id}      -> single case detail (evidence chain)
    GET  /api/audit/exceptions             -> exception queue only
"""
import threading
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from pipeline_runner import run_full_pipeline, regenerate_data, DB_PATH

app = FastAPI(
    title="Settlement Leakage Auditor API",
    description="Reconstructs expected settlement per transaction, matches it against "
                "actual settlement, and classifies every gap by cause.",
    version="1.0.0",
)

# Dashboard runs in-browser (or on a different origin/port) — allow it to fetch freely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_lock = threading.Lock()
_cached_payload = None


def _ensure_data_exists():
    import os
    if not os.path.exists(DB_PATH):
        regenerate_data(seed=42)


@app.on_event("startup")
def startup():
    global _cached_payload
    _ensure_data_exists()
    with _lock:
        _cached_payload = run_full_pipeline(DB_PATH)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "settlement-leakage-auditor"}


@app.get("/api/audit")
def get_audit():
    """Returns the last computed dashboard payload (deterministic engine + classifier results)."""
    global _cached_payload
    if _cached_payload is None:
        with _lock:
            _cached_payload = run_full_pipeline(DB_PATH)
    return _cached_payload


@app.post("/api/audit/run")
def run_audit(
    seed: int = Query(42, description="Random seed for the synthetic batch generator"),
    inject_break: Optional[str] = Query(
        None,
        description="Deliberately corrupt one row to test graceful degradation: "
                    "duplicate_webhook | out_of_order | missing_reference",
    ),
):
    """
    Regenerates a fresh synthetic batch (optionally with a Phase-4 injected fault)
    and reruns the full deterministic + classifier pipeline against it.
    """
    global _cached_payload
    valid_faults = {None, "duplicate_webhook", "out_of_order", "missing_reference"}
    if inject_break not in valid_faults:
        raise HTTPException(status_code=400, detail=f"inject_break must be one of {valid_faults}")

    with _lock:
        regenerate_data(seed=seed, inject_break=inject_break)
        _cached_payload = run_full_pipeline(DB_PATH)

    return _cached_payload


@app.get("/api/audit/exceptions")
def get_exceptions():
    global _cached_payload
    if _cached_payload is None:
        with _lock:
            _cached_payload = run_full_pipeline(DB_PATH)
    return _cached_payload["exception_queue"]


@app.get("/api/audit/case/{payment_id}")
def get_case(payment_id: str):
    global _cached_payload
    if _cached_payload is None:
        with _lock:
            _cached_payload = run_full_pipeline(DB_PATH)

    for c in _cached_payload["exception_queue"] + _cached_payload["showcase_cases"]:
        if c["payment_id"] == payment_id:
            return c
    raise HTTPException(status_code=404, detail=f"No case found for payment_id={payment_id}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
