"""
Settlement Leakage Auditor — Deterministic Reconciliation Engine (Phase 1)

Pure arithmetic + rules. No model, no free text. Computes the expected
settlement per Razorpay's public formula, matches it against the actual
settlement row(s), and buckets every delta into:
  - matched            (within tolerance)
  - timing_lag         (a counterpart refund/dispute record exists but
                         falls outside the settlement window — provisional)
  - unclassified       (residual escalated to the local classifier)

Also implements a small set of KNOWN-CAUSE deterministic rules
(Section 5.2) that catch obvious cases (e.g. exact duplicate settlement rows)
before anything reaches the model.
"""
import sqlite3
import json
from datetime import datetime, timedelta

TOLERANCE_RUPEES = 1.0          # rounding tolerance
SETTLEMENT_WINDOW_DAYS = 2      # T+2 working days, standard cycle
WINDOW_GRACE_DAYS = 1           # small grace before calling it "late"

def parse(dt):
    return datetime.fromisoformat(dt) if isinstance(dt, str) else dt


class ReconciliationEngine:
    def __init__(self, db_path="settlement_auditor.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def _fetch_all(self, table):
        return [dict(r) for r in self.conn.execute(f"SELECT * FROM {table}").fetchall()]

    def run(self):
        payments = self._fetch_all("payments")
        refunds_by_payment = {}
        for r in self._fetch_all("refunds"):
            refunds_by_payment.setdefault(r["payment_id"], []).append(r)
        disputes_by_payment = {}
        for d in self._fetch_all("disputes"):
            disputes_by_payment.setdefault(d["payment_id"], []).append(d)
        settlements_by_payment = {}
        for s in self._fetch_all("settlements"):
            settlements_by_payment.setdefault(s["payment_id"], []).append(s)

        cur = self.conn.cursor()
        cur.execute("DELETE FROM expected_settlement")
        cur.execute("DELETE FROM match_results")
        cur.execute("DELETE FROM exceptions")
        cur.execute("DELETE FROM audit_log")

        results = []
        residuals = []  # payments needing the ML classifier

        for p in payments:
            pid = p["payment_id"]
            created = parse(p["created_at"])
            refunds = refunds_by_payment.get(pid, [])
            disputes = disputes_by_payment.get(pid, [])
            settles = settlements_by_payment.get(pid, [])

            # ---- Step 1: expected_settlement formula
            # Amount settled = Payment - Adjustments - Tax - Fees - Transfers + Refunds
            adjustments = 0.0
            transfers = 0.0
            refunds_in_window = [
                rf for rf in refunds
                if parse(rf["created_at"]) <= created + timedelta(days=SETTLEMENT_WINDOW_DAYS + WINDOW_GRACE_DAYS)
            ]
            refunds_total_in_window = sum(rf["amount"] for rf in refunds_in_window)
            refunds_total_all = sum(rf["amount"] for rf in refunds)

            expected_amount = round(
                p["amount"] - adjustments - p["tax"] - p["fees"] - transfers - refunds_total_in_window, 2
            )
            breakdown = {
                "payment": p["amount"], "adjustments": adjustments, "tax": p["tax"],
                "fees": p["fees"], "transfers": transfers,
                "refunds_deducted_in_window": refunds_total_in_window,
                "refunds_total_all_time": refunds_total_all,
                "formula": "Payment - Adjustments - Tax - Fees - Transfers + Refunds(in-window, negative)",
            }
            cur.execute(
                "INSERT INTO expected_settlement VALUES (?,?,?)",
                (pid, expected_amount, json.dumps(breakdown))
            )

            # ---- Step 2: locate settlement record(s) by payment_id within window
            window_end = created + timedelta(days=SETTLEMENT_WINDOW_DAYS + WINDOW_GRACE_DAYS)
            in_window_settles = [s for s in settles if parse(s["settled_at"]) <= window_end]

            if not in_window_settles:
                # No settlement landed at all yet within window -> exception
                self._log_and_queue(cur, pid, p, None, expected_amount, None,
                                     "no_settlement_found", residuals, refunds, disputes, settles)
                continue

            duplicate_extra = None
            if len(in_window_settles) > 1:
                # Deterministic known-cause: duplicate settlement rows (identical payment+amount twice)
                amounts = [s["amount"] for s in in_window_settles]
                if len(set(round(a, 2) for a in amounts)) == 1:
                    primary = in_window_settles[0]
                    duplicate_extra = in_window_settles[1:]
                    actual_amount = primary["amount"]
                    delta = round(actual_amount - expected_amount, 2)
                    classification = "known_cause_duplicate_settlement_row"
                    confidence = 1.0
                    self._finalize(cur, pid, primary["settlement_id"], delta, classification, confidence)
                    self._audit(cur, pid, "rule", p, None, "known_cause_duplicate_row")
                    results.append(dict(payment_id=pid, classification=classification,
                                         delta=delta, confidence=confidence,
                                         duplicate_settlement_ids=[s["settlement_id"] for s in duplicate_extra]))
                    continue

            settlement = in_window_settles[0]
            actual_amount = settlement["amount"]
            delta = round(actual_amount - expected_amount, 2)

            # ---- Step 3: tolerance check
            if abs(delta) <= TOLERANCE_RUPEES:
                self._finalize(cur, pid, settlement["settlement_id"], delta, "matched", 1.0)
                self._audit(cur, pid, "rule", p, None, "matched")
                results.append(dict(payment_id=pid, classification="matched", delta=delta, confidence=1.0))
                continue

            # ---- Step 4: known timing-lag pattern — counterpart refund/dispute exists
            # but falls OUTSIDE the settlement window (this is what actually causes the delta)
            late_refunds = [rf for rf in refunds if rf not in refunds_in_window]
            late_disputes = disputes  # any dispute not yet reflected counts as in-flight

            matched_late_refund = None
            for rf in late_refunds:
                if abs(abs(delta) - rf["amount"]) <= max(TOLERANCE_RUPEES, rf["amount"] * 0.02):
                    matched_late_refund = rf
                    break

            matched_dispute = None
            for d in late_disputes:
                if d["status"] == "lost" and abs(abs(delta) - d["amount"]) <= max(TOLERANCE_RUPEES, d["amount"] * 0.02):
                    matched_dispute = d
                    break

            if matched_late_refund:
                classification = "timing_lag_refund"
                confidence = 0.97
                self._finalize(cur, pid, settlement["settlement_id"], delta, classification, confidence)
                self._audit(cur, pid, "rule", p, {"refund_id": matched_late_refund["refund_id"]}, classification)
                results.append(dict(payment_id=pid, classification=classification, delta=delta,
                                     confidence=confidence, evidence_refund=matched_late_refund["refund_id"]))
                continue

            if matched_dispute:
                classification = "timing_lag_dispute"
                confidence = 0.96
                self._finalize(cur, pid, settlement["settlement_id"], delta, classification, confidence)
                self._audit(cur, pid, "rule", p, {"dispute_id": matched_dispute["dispute_id"]}, classification)
                results.append(dict(payment_id=pid, classification=classification, delta=delta,
                                     confidence=confidence, evidence_dispute=matched_dispute["dispute_id"]))
                continue

            # ---- Step 5: nothing deterministic explains it -> residual for the local classifier
            residuals.append(dict(
                payment_id=pid, payment=p, settlement=settlement, expected_amount=expected_amount,
                delta=delta, refunds=refunds, disputes=disputes,
            ))

        self.conn.commit()
        return {"resolved": results, "residuals": residuals}

    def _finalize(self, cur, pid, settlement_id, delta, classification, confidence):
        cur.execute(
            "INSERT INTO match_results VALUES (?,?,?,?,?)",
            (pid, settlement_id, delta, classification, confidence)
        )

    def _audit(self, cur, pid, actor, input_snapshot, feature_vector, action):
        cur.execute(
            "INSERT INTO audit_log (entity_id, actor, input_snapshot, feature_vector, action, timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (pid, actor, json.dumps(input_snapshot, default=str), json.dumps(feature_vector, default=str),
             action, datetime.utcnow().isoformat())
        )

    def _log_and_queue(self, cur, pid, p, settlement_id, expected_amount, delta, reason,
                        residuals, refunds, disputes, settles):
        cur.execute(
            "INSERT INTO exceptions (payment_id, candidate_causes, chosen_cause, status, reviewer_action) "
            "VALUES (?,?,?,?,?)",
            (pid, json.dumps([reason]), None, "pending_no_settlement", None)
        )
        self._audit(cur, pid, "rule", p, None, reason)

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    engine = ReconciliationEngine()
    out = engine.run()
    print(f"Deterministically resolved: {len(out['resolved'])}")
    print(f"Escalated to classifier: {len(out['residuals'])}")
    engine.close()
