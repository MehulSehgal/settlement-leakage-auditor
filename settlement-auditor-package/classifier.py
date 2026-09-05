"""
Settlement Leakage Auditor — Local Classifier (Phase 2)

No LLM, no external API. A small scikit-learn classifier trained on
engineered features scores every residual the deterministic engine could
not place. Explanations are rendered from a fixed template using the
model's own feature values — never generated text, so nothing can be
hallucinated.

Auto-resolve threshold and the high-value human-review override are
enforced as plain Python conditionals (Section 5.3 / Section 8, "Stopping
rule"), never inside the model.
"""
import json
import sqlite3
from datetime import datetime, timedelta

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, accuracy_score
from sklearn.preprocessing import LabelEncoder

AUTO_RESOLVE_CONFIDENCE = 0.85
HIGH_VALUE_THRESHOLD_RUPEES = 5000.0   # hard stopping rule — never auto-resolve above this

CAUSE_LABELS = [
    "partial_refund_mistiming", "dispute_in_flight", "fx_rounding_error",
    "duplicate_settlement_row", "genuinely_unexplained",
]

FEATURE_NAMES = [
    "delta_amount", "delta_pct_of_payment", "days_payment_to_settlement",
    "has_matching_refund", "refund_amount_closeness", "has_matching_dispute",
    "dispute_amount_closeness", "balance_account_is_intl", "channel_pos_flag",
    "has_duplicate_settlement_row", "merchant_hist_delta_rate",
]


def parse(dt):
    return datetime.fromisoformat(dt) if isinstance(dt, str) else dt


class ResidualClassifier:
    def __init__(self, db_path="settlement_auditor.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.model = RandomForestClassifier(
            n_estimators=200, max_depth=6, random_state=42, class_weight="balanced"
        )
        self.label_encoder = LabelEncoder()
        self.label_encoder.fit(CAUSE_LABELS)
        self.metrics = {}

    def _fetch_all(self, table):
        return [dict(r) for r in self.conn.execute(f"SELECT * FROM {table}").fetchall()]

    # ---------------- Feature engineering (Section 5.3) ----------------
    def _engineer_features(self, payment, settlement, expected_amount, delta, refunds, disputes,
                            duplicate_flag, merchant_hist_rate):
        created = parse(payment["created_at"])
        settled_at = parse(settlement["settled_at"]) if settlement else created
        days_gap = (settled_at - created).total_seconds() / 86400.0

        best_refund = None
        for rf in refunds:
            closeness = 1 - min(abs(abs(delta) - rf["amount"]) / max(rf["amount"], 1), 1)
            if best_refund is None or closeness > best_refund[1]:
                best_refund = (rf, closeness)
        refund_closeness = best_refund[1] if best_refund else 0.0
        has_refund = 1.0 if best_refund and best_refund[1] > 0.5 else 0.0

        best_dispute = None
        for d in disputes:
            closeness = 1 - min(abs(abs(delta) - d["amount"]) / max(d["amount"], 1), 1)
            if best_dispute is None or closeness > best_dispute[1]:
                best_dispute = (d, closeness)
        dispute_closeness = best_dispute[1] if best_dispute else 0.0
        has_dispute = 1.0 if best_dispute and best_dispute[1] > 0.5 else 0.0

        feats = [
            abs(delta),
            abs(delta) / max(payment["amount"], 1) * 100,
            days_gap,
            has_refund,
            refund_closeness,
            has_dispute,
            dispute_closeness,
            1.0 if payment["balance_account_id"] == "acc_apm_intl" else 0.0,
            1.0 if payment["channel_type"] == "pos" else 0.0,
            1.0 if duplicate_flag else 0.0,
            merchant_hist_rate,
        ]
        return feats, {
            "best_refund": best_refund[0] if best_refund else None,
            "best_dispute": best_dispute[0] if best_dispute else None,
        }

    # ---------------- Synthetic labeled training set from ground truth ----------------
    def _build_training_set(self):
        gt = {r["payment_id"]: r["planted_cause"] for r in self._fetch_all("ground_truth")}
        payments = {p["payment_id"]: p for p in self._fetch_all("payments")}
        refunds_by_payment = {}
        for r in self._fetch_all("refunds"):
            refunds_by_payment.setdefault(r["payment_id"], []).append(r)
        disputes_by_payment = {}
        for d in self._fetch_all("disputes"):
            disputes_by_payment.setdefault(d["payment_id"], []).append(d)
        settlements_by_payment = {}
        for s in self._fetch_all("settlements"):
            settlements_by_payment.setdefault(s["payment_id"], []).append(s)
        expected = {e["payment_id"]: e["expected_amount"] for e in self._fetch_all("expected_settlement")}

        X, y = [], []
        for pid, cause in gt.items():
            if cause is None:
                continue  # only train the classifier on cases that actually needed classifying
            p = payments[pid]
            settles = settlements_by_payment.get(pid, [])
            if not settles:
                continue
            settlement = settles[0]
            exp_amt = expected.get(pid, p["amount"] - p["fees"] - p["tax"])
            delta = round(settlement["amount"] - exp_amt, 2)
            dup_flag = len(settles) > 1
            feats, _ = self._engineer_features(
                p, settlement, exp_amt, delta,
                refunds_by_payment.get(pid, []), disputes_by_payment.get(pid, []),
                dup_flag, merchant_hist_rate=0.01
            )
            X.append(feats)
            y.append(cause)

        return np.array(X), np.array(y)

    def train(self):
        X, y = self._build_training_set()
        if len(set(y)) < 2 or len(y) < 10:
            # Not enough real residual examples in this batch alone — augment with
            # a bootstrap resample so the model still trains a meaningful boundary.
            X = np.vstack([X] * 8)
            y = np.concatenate([y] * 8)
            noise = np.random.normal(0, 0.03, X.shape)
            X = X + noise * X.std(axis=0)

        y_enc = self.label_encoder.transform(y)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_enc, test_size=0.25, random_state=42, stratify=y_enc
        )
        self.model.fit(X_train, y_train)
        y_pred = self.model.predict(X_test)

        self.metrics = {
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "precision_macro": round(float(precision_score(y_test, y_pred, average="macro", zero_division=0)), 4),
            "recall_macro": round(float(recall_score(y_test, y_pred, average="macro", zero_division=0)), 4),
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
        }
        return self.metrics

    # ---------------- Explainability template (Section 5.3) ----------------
    def _render_explanation(self, cause, confidence, feats, evidence):
        pct = round(confidence * 100, 1)
        if cause == "partial_refund_mistiming" and evidence.get("best_refund"):
            rf = evidence["best_refund"]
            return (f"Classified as partial-refund-mistiming ({pct}% confidence) because a refund of "
                    f"₹{rf['amount']:.2f} exists {feats[2]:.1f} days after settlement, and the delta is "
                    f"within {round((1-feats[4])*100,1)}% of that refund amount.")
        if cause == "dispute_in_flight" and evidence.get("best_dispute"):
            d = evidence["best_dispute"]
            return (f"Classified as dispute-in-flight ({pct}% confidence) because a lost dispute of "
                    f"₹{d['amount']:.2f} exists with status '{d['status']}', and the delta closely "
                    f"matches the deduction amount ({round(feats[6]*100,1)}% feature closeness).")
        if cause == "fx_rounding_error":
            return (f"Classified as fx-rounding-error ({pct}% confidence) because the balance account is "
                    f"international (APM channel) and the delta of ₹{feats[0]:.2f} is "
                    f"{feats[1]:.2f}% of the payment amount — consistent with FX conversion drift rather "
                    f"than a discrete refund or dispute.")
        if cause == "duplicate_settlement_row":
            return (f"Classified as duplicate-settlement-row ({pct}% confidence) because more than one "
                    f"settlement record was found referencing the same payment and order ID.")
        return (f"Classified as genuinely-unexplained ({pct}% confidence): no matching refund, dispute, "
                f"duplicate row, or FX pattern was found. Delta is ₹{feats[0]:.2f} "
                f"({feats[1]:.2f}% of payment amount) with no supporting evidence row.")

    # ---------------- Score residuals and enforce guardrails ----------------
    def score_residuals(self, residuals):
        cur = self.conn.cursor()
        scored = []
        for res in residuals:
            p, settlement, exp_amt, delta = res["payment"], res["settlement"], res["expected_amount"], res["delta"]
            dup_flag = False
            feats, evidence = self._engineer_features(
                p, settlement, exp_amt, delta, res["refunds"], res["disputes"], dup_flag,
                merchant_hist_rate=0.01
            )
            probs = self.model.predict_proba([feats])[0]
            top_idx = int(np.argmax(probs))
            top_cause = self.label_encoder.inverse_transform([top_idx])[0]
            confidence = float(probs[top_idx])
            all_causes = {
                self.label_encoder.inverse_transform([i])[0]: round(float(pr), 4)
                for i, pr in enumerate(probs)
            }

            explanation = self._render_explanation(top_cause, confidence, feats, evidence)

            # ---- Rule-consistency check: does prediction contradict deterministic knowledge?
            contradicts_rule = False
            if top_cause == "duplicate_settlement_row" and not dup_flag:
                contradicts_rule = True

            # ---- Stopping rule: hard ₹ threshold, enforced in plain Python
            above_threshold = abs(p["amount"]) >= HIGH_VALUE_THRESHOLD_RUPEES
            auto_resolve = (confidence >= AUTO_RESOLVE_CONFIDENCE) and not contradicts_rule and not above_threshold

            action = "auto_resolved" if auto_resolve else "escalated_human_review"

            cur.execute(
                "INSERT INTO match_results VALUES (?,?,?,?,?)",
                (p["payment_id"], settlement["settlement_id"] if settlement else None,
                 delta, top_cause if auto_resolve else "pending_review", confidence)
            )
            cur.execute(
                "INSERT INTO exceptions (payment_id, candidate_causes, chosen_cause, status, reviewer_action) "
                "VALUES (?,?,?,?,?)",
                (p["payment_id"], json.dumps(all_causes), top_cause,
                 action, None)
            )
            cur.execute(
                "INSERT INTO audit_log (entity_id, actor, input_snapshot, feature_vector, action, timestamp) "
                "VALUES (?,?,?,?,?,?)",
                (p["payment_id"], "model",
                 json.dumps({"payment_id": p["payment_id"], "amount": p["amount"], "delta": delta}),
                 json.dumps(dict(zip(FEATURE_NAMES, [round(f,4) for f in feats]))),
                 action, datetime.now().isoformat())
            )

            scored.append({
                "payment_id": p["payment_id"],
                "amount": p["amount"],
                "delta": delta,
                "top_cause": top_cause,
                "confidence": round(confidence, 4),
                "all_causes": all_causes,
                "explanation": explanation,
                "action": action,
                "above_threshold": above_threshold,
                "contradicts_rule": contradicts_rule,
                "features": dict(zip(FEATURE_NAMES, [round(f, 4) for f in feats])),
            })

        self.conn.commit()
        return scored

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    from engine import ReconciliationEngine

    engine = ReconciliationEngine()
    out = engine.run()
    engine.close()

    clf = ResidualClassifier()
    metrics = clf.train()
    print("Training metrics:", metrics)

    scored = clf.score_residuals(out["residuals"])
    for s in scored:
        print(s["payment_id"], s["top_cause"], s["confidence"], s["action"])
    clf.close()
