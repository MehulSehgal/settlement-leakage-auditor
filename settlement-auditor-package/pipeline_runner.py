"""
Settlement Leakage Auditor — Shared Pipeline Runner

Runs the full pipeline (data generation -> deterministic engine -> local
classifier -> evaluation) and returns the dashboard payload as a Python
dict. Used by both run_pipeline.py (CLI / file export) and api.py (live
HTTP endpoint), so the API always reflects a real pipeline run, not a
canned file.
"""
import json
import sqlite3
from datetime import datetime
from collections import Counter

from engine import ReconciliationEngine
from classifier import ResidualClassifier, HIGH_VALUE_THRESHOLD_RUPEES, AUTO_RESOLVE_CONFIDENCE
from generate_data import LeakageAuditGenerator

DB_PATH = "settlement_auditor.db"


def fetchall(conn, q, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def regenerate_data(seed=42, n_transactions=None, inject_break=None):
    """
    Regenerate the synthetic batch. inject_break lets the API demonstrate
    Phase 4 ("break something on purpose"): pass one of
    'duplicate_webhook', 'out_of_order', 'missing_reference' to additionally
    corrupt one row after generation, so the pipeline has to fail gracefully.
    """
    import random
    import numpy as np
    random.seed(seed)
    np.random.seed(seed)

    gen = LeakageAuditGenerator()
    if n_transactions:
        gen.__class__ = LeakageAuditGenerator
    gen.generate()
    gen.to_sqlite(DB_PATH)

    if inject_break:
        _apply_fault(inject_break)

    return gen


def _apply_fault(fault_type):
    """Phase 4: deliberately corrupt one row to prove the pipeline degrades safely."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    row = cur.execute("SELECT payment_id FROM payments ORDER BY RANDOM() LIMIT 1").fetchone()
    if not row:
        conn.close()
        return
    pid = row[0]

    if fault_type == "duplicate_webhook":
        s = cur.execute("SELECT * FROM settlements WHERE payment_id=? LIMIT 1", (pid,)).fetchone()
        if s:
            cols = [d[0] for d in cur.execute("SELECT * FROM settlements LIMIT 1").description]
            values = list(s)
            sid_idx = cols.index("settlement_id")
            values[sid_idx] = values[sid_idx] + "_replay"
            cur.execute(f"INSERT INTO settlements VALUES ({','.join('?' * len(values))})", values)
    elif fault_type == "missing_reference":
        cur.execute("DELETE FROM settlements WHERE payment_id=?", (pid,))
    elif fault_type == "out_of_order":
        cur.execute(
            "UPDATE settlements SET settled_at = datetime(settled_at, '-10 days') WHERE payment_id=?",
            (pid,)
        )
    conn.commit()
    conn.close()
    return pid


def run_full_pipeline(db_path=DB_PATH):
    """Runs engine + classifier against whatever is currently in the DB and
    returns the full dashboard payload as a dict."""
    t0 = datetime.now()

    engine = ReconciliationEngine(db_path)
    engine_out = engine.run()
    engine.close()

    clf = ResidualClassifier(db_path)
    train_metrics = clf.train()
    scored_residuals = clf.score_residuals(engine_out["residuals"])
    clf.close()

    t1 = datetime.now()

    conn = sqlite3.connect(db_path)

    payments = fetchall(conn, "SELECT * FROM payments")
    match_results = fetchall(conn, "SELECT * FROM match_results")
    exceptions = fetchall(conn, "SELECT * FROM exceptions")
    ground_truth = {r["payment_id"]: r["planted_cause"] for r in fetchall(conn, "SELECT * FROM ground_truth")}
    expected_settlement = {r["payment_id"]: r for r in fetchall(conn, "SELECT * FROM expected_settlement")}
    settlements_by_pid = {}
    for s in fetchall(conn, "SELECT * FROM settlements"):
        settlements_by_pid.setdefault(s["payment_id"], []).append(s)
    refunds_by_pid = {}
    for r in fetchall(conn, "SELECT * FROM refunds"):
        refunds_by_pid.setdefault(r["payment_id"], []).append(r)
    disputes_by_pid = {}
    for d in fetchall(conn, "SELECT * FROM disputes"):
        disputes_by_pid.setdefault(d["payment_id"], []).append(d)

    total_batch = len(payments)

    classification_counts = Counter(m["classification"] for m in match_results)

    n_matched = classification_counts.get("matched", 0)
    n_known_cause = classification_counts.get("known_cause_duplicate_settlement_row", 0)
    n_timing_lag = classification_counts.get("timing_lag_refund", 0) + classification_counts.get("timing_lag_dispute", 0)

    n_auto_resolved = sum(1 for e in exceptions if e["status"] == "auto_resolved")
    n_escalated = sum(1 for e in exceptions if e["status"] == "escalated_human_review")
    n_no_settlement = sum(1 for e in exceptions if e["status"] == "pending_no_settlement")

    n_resolved_no_review = n_matched + n_known_cause + n_timing_lag + n_auto_resolved
    match_rate = round(n_resolved_no_review / max(total_batch, 1) * 100, 2)

    planted_leak_rupees = 0.0
    for pid, cause in ground_truth.items():
        if cause:
            settles = settlements_by_pid.get(pid, [])
            exp = expected_settlement.get(pid)
            if settles and exp:
                planted_leak_rupees += abs(settles[0]["amount"] - exp["expected_amount"])

    surfaced_leak_rupees = 0.0
    tracked_timing_lag_rupees = 0.0
    for s in scored_residuals:
        surfaced_leak_rupees += abs(s["delta"])
    for m in match_results:
        if m["classification"] == "known_cause_duplicate_settlement_row":
            surfaced_leak_rupees += abs(m["delta_amount"])
        elif m["classification"] in ("timing_lag_refund", "timing_lag_dispute"):
            tracked_timing_lag_rupees += abs(m["delta_amount"])

    predicted_leak_pids = set()
    for m in match_results:
        if m["classification"] not in ("matched",) and m["payment_id"]:
            predicted_leak_pids.add(m["payment_id"])
    for e in exceptions:
        predicted_leak_pids.add(e["payment_id"])

    planted_pids = {pid for pid, c in ground_truth.items() if c}
    clean_pids = {pid for pid, c in ground_truth.items() if not c}

    true_positives = len(predicted_leak_pids & planted_pids)
    false_negatives = len(planted_pids - predicted_leak_pids)
    false_positives_pids = predicted_leak_pids & clean_pids
    false_positives = len(false_positives_pids)

    precision = round(true_positives / max(true_positives + false_positives, 1), 4)
    recall = round(true_positives / max(true_positives + false_negatives, 1), 4)

    false_positive_cost = 0.0
    for pid in false_positives_pids:
        settles = settlements_by_pid.get(pid, [])
        exp = expected_settlement.get(pid)
        if settles and exp:
            false_positive_cost += abs(settles[0]["amount"] - exp["expected_amount"])

    cause_recall = {}
    for cause in set(c for c in ground_truth.values() if c):
        cause_pids = {pid for pid, c in ground_truth.items() if c == cause}
        caught = len(cause_pids & predicted_leak_pids)
        cause_recall[cause] = {"planted": len(cause_pids), "caught": caught,
                                "recall": round(caught / max(len(cause_pids), 1), 3)}

    total_ms = (t1 - t0).total_seconds() * 1000
    per_txn_ms = round(total_ms / max(total_batch, 1), 4)

    def build_case(pid):
        p = next((x for x in payments if x["payment_id"] == pid), None)
        settles = settlements_by_pid.get(pid, [])
        exp = expected_settlement.get(pid)
        mr = next((m for m in match_results if m["payment_id"] == pid), None)
        exc = next((e for e in exceptions if e["payment_id"] == pid), None)
        scored = next((s for s in scored_residuals if s["payment_id"] == pid), None)
        breakdown = json.loads(exp["formula_breakdown"]) if exp else {}
        return {
            "payment_id": pid,
            "order_id": p["order_id"] if p else None,
            "amount": p["amount"] if p else None,
            "method": p["method"] if p else None,
            "balance_account_id": p["balance_account_id"] if p else None,
            "channel_type": p["channel_type"] if p else None,
            "created_at": p["created_at"] if p else None,
            "expected_amount": exp["expected_amount"] if exp else None,
            "formula_breakdown": breakdown,
            "actual_settled_amount": settles[0]["amount"] if settles else None,
            "settlement_count": len(settles),
            "delta": mr["delta_amount"] if mr else None,
            "classification": mr["classification"] if mr else ("no_settlement_found" if not settles else None),
            "confidence": mr["confidence"] if mr else None,
            "planted_ground_truth": ground_truth.get(pid),
            "refunds": refunds_by_pid.get(pid, []),
            "disputes": disputes_by_pid.get(pid, []),
            "model_explanation": scored["explanation"] if scored else None,
            "model_all_causes": scored["all_causes"] if scored else None,
            "model_features": scored["features"] if scored else None,
            "review_status": exc["status"] if exc else ("matched" if settles else "pending_no_settlement"),
            "above_threshold": scored["above_threshold"] if scored else (p["amount"] >= HIGH_VALUE_THRESHOLD_RUPEES if p else False),
        }

    exception_queue = [build_case(e["payment_id"]) for e in exceptions]

    showcase_pids = []
    seen_causes = set()
    for pid in sorted(planted_pids):
        c = ground_truth[pid]
        if c not in seen_causes:
            showcase_pids.append(pid)
            seen_causes.add(c)
    showcase_cases = [build_case(pid) for pid in showcase_pids]

    conn.close()

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "total_batch_size": total_batch,
            "pipeline_wall_time_ms": round(total_ms, 2),
            "per_transaction_ms": per_txn_ms,
            "auto_resolve_confidence_threshold": AUTO_RESOLVE_CONFIDENCE,
            "high_value_threshold_rupees": HIGH_VALUE_THRESHOLD_RUPEES,
            "settlement_window_days": 2,
        },
        "summary": {
            "match_rate_pct": match_rate,
            "n_matched": n_matched,
            "n_known_cause": n_known_cause,
            "n_timing_lag": n_timing_lag,
            "n_auto_resolved": n_auto_resolved,
            "n_escalated_human_review": n_escalated,
            "n_no_settlement_found": n_no_settlement,
            "surfaced_leak_rupees": round(surfaced_leak_rupees, 2),
            "tracked_timing_lag_rupees": round(tracked_timing_lag_rupees, 2),
            "planted_leak_rupees": round(planted_leak_rupees, 2),
        },
        "evaluation": {
            "precision_on_planted_leakage": precision,
            "recall_on_planted_leakage": recall,
            "true_positives": true_positives,
            "false_negatives": false_negatives,
            "false_positives": false_positives,
            "false_positive_cost_rupees": round(false_positive_cost, 2),
            "cause_recall_breakdown": cause_recall,
            "classifier_training_metrics": train_metrics,
        },
        "classification_breakdown": dict(classification_counts),
        "exception_queue": exception_queue,
        "showcase_cases": showcase_cases,
        "false_positive_case_ids": list(false_positives_pids),
    }
