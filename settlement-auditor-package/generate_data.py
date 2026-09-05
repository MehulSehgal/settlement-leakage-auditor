"""
Settlement Leakage Auditor — Synthetic Data Generator
Models Razorpay's public Payments / Refunds / Disputes / Settlements schema.
Deliberately plants a known set of leakage cases so results can be scored
against ground truth.
"""
import random
import json
import string
import sqlite3
from datetime import datetime, timedelta
import numpy as np
from faker import Faker

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

N_TRANSACTIONS = 2200
DB_PATH = "settlement_auditor.db"

BALANCE_ACCOUNTS = ["acc_online_primary", "acc_pos_instore", "acc_apm_intl"]
CHANNELS = {"acc_online_primary": "online", "acc_pos_instore": "pos", "acc_apm_intl": "apm_international"}
METHODS = ["card", "upi", "netbanking", "wallet", "emi"]

def rid(prefix, n=14):
    return prefix + "_" + "".join(random.choices(string.ascii_letters + string.digits, k=n))

def rupees(x):
    return round(x, 2)

class LeakageAuditGenerator:
    def __init__(self):
        self.payments = []
        self.refunds = []
        self.disputes = []
        self.settlements = []
        self.ground_truth = {}  # payment_id -> planted cause (None if clean)
        self.start_date = datetime(2026, 6, 1)

    def _base_payment(self, i):
        pid = rid("pay")
        oid = rid("order")
        amount = rupees(random.choice([
            random.uniform(200, 3000),
            random.uniform(3000, 20000),
            random.uniform(20000, 150000),
        ]))
        method = random.choices(METHODS, weights=[35, 40, 12, 8, 5])[0]
        balance_account = random.choices(BALANCE_ACCOUNTS, weights=[70, 22, 8])[0]
        created = self.start_date + timedelta(
            days=random.randint(0, 75),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        fee_rate = 0.02 if method != "emi" else 0.03
        fees = rupees(amount * fee_rate)
        tax = rupees(fees * 0.18)  # GST on fees
        return {
            "payment_id": pid, "order_id": oid, "amount": amount, "method": method,
            "status": "captured", "created_at": created, "balance_account_id": balance_account,
            "channel_type": CHANNELS[balance_account], "fees": fees, "tax": tax,
        }

    def _settle(self, payment, expected_amount, settle_date, extra_fields=None, dup=False):
        sid = rid("setl")
        row = {
            "settlement_id": sid,
            "payment_id": payment["payment_id"],
            "order_id": payment["order_id"],
            "amount": rupees(expected_amount),
            "fees": payment["fees"],
            "tax": payment["tax"],
            "utr": rid("UTR", 10).upper(),
            "balance_account_id": payment["balance_account_id"],
            "channel_type": payment["channel_type"],
            "settled_at": settle_date,
            "is_duplicate_flag": dup,
        }
        if extra_fields:
            row.update(extra_fields)
        self.settlements.append(row)
        return row

    def generate(self):
        n_leak = 0
        target_leak = 20  # planted leakage cases (within 15-25 range)
        leak_types = [
            "partial_refund_mistiming", "dispute_in_flight", "fx_rounding_error",
            "duplicate_settlement_row", "genuinely_unexplained",
        ]
        leak_positions = set(random.sample(range(N_TRANSACTIONS), target_leak))
        leak_assignment = {}
        for idx, pos in enumerate(sorted(leak_positions)):
            leak_assignment[pos] = leak_types[idx % len(leak_types)]

        for i in range(N_TRANSACTIONS):
            payment = self._base_payment(i)
            pid = payment["payment_id"]
            leak_kind = leak_assignment.get(i)

            net_expected = rupees(payment["amount"] - payment["fees"] - payment["tax"])
            settle_date = payment["created_at"] + timedelta(days=2)

            if leak_kind is None:
                # ---- Clean case, may still include normal refund/dispute fully resolved in-window
                sub_case = random.random()
                if sub_case < 0.06:
                    # normal refund processed and reflected same cycle
                    refund_amt = rupees(payment["amount"] * random.uniform(0.1, 1.0))
                    refund_created = payment["created_at"] + timedelta(hours=random.randint(1, 20))
                    self.refunds.append({
                        "refund_id": rid("rfnd"), "payment_id": pid, "amount": refund_amt,
                        "status": "processed", "speed": "normal", "created_at": refund_created,
                    })
                    net_expected = rupees(net_expected - refund_amt)
                self._settle(payment, net_expected, settle_date)
                self.ground_truth[pid] = None

            elif leak_kind == "partial_refund_mistiming":
                # Refund exists but lands AFTER the settlement cycle closes.
                # The settlement engine's expected-in-window formula does NOT deduct
                # this refund (it's outside the window), so expected == full net amount.
                # But the ACTUAL settlement that lands is already net of the refund
                # deduction going through on the bank side later than the payment cycle,
                # which is exactly the gap a naive "totals match" check would miss:
                # here we simulate the bank settlement UNDER-paying relative to the
                # in-window formula, because the processor nets the refund at payout time
                # even though the refund record itself posts a few days later.
                refund_amt = rupees(payment["amount"] * random.uniform(0.15, 0.6))
                refund_created = settle_date + timedelta(days=random.randint(2, 5))
                self.refunds.append({
                    "refund_id": rid("rfnd"), "payment_id": pid, "amount": refund_amt,
                    "status": "processed", "speed": "normal", "created_at": refund_created,
                })
                actual_settled = rupees(net_expected - refund_amt)
                self._settle(payment, actual_settled, settle_date)
                self.ground_truth[pid] = "partial_refund_mistiming"

            elif leak_kind == "dispute_in_flight":
                dispute_amt = rupees(payment["amount"] * random.uniform(0.3, 1.0))
                filed = payment["created_at"] + timedelta(days=random.randint(3, 10))
                resolved = filed + timedelta(days=random.randint(10, 25))
                self.disputes.append({
                    "dispute_id": rid("disp"), "payment_id": pid, "amount": dispute_amt,
                    "phase": "chargeback", "status": "lost", "respond_by": filed + timedelta(days=7),
                    "created_at": filed, "resolved_at": resolved,
                })
                # The chargeback deduction already hit the settlement batch even though
                # the dispute record itself resolves later in the case timeline.
                actual_settled = rupees(net_expected - dispute_amt)
                self._settle(payment, actual_settled, settle_date)
                self.ground_truth[pid] = "dispute_in_flight"

            elif leak_kind == "fx_rounding_error":
                # APM international channel; small persistent rounding gap beyond tolerance
                payment["balance_account_id"] = "acc_apm_intl"
                payment["channel_type"] = "apm_international"
                fx_drift = rupees(payment["amount"] * random.uniform(0.006, 0.018))
                settled_amt = rupees(net_expected - fx_drift)
                self._settle(payment, settled_amt, settle_date)
                self.ground_truth[pid] = "fx_rounding_error"

            elif leak_kind == "duplicate_settlement_row":
                self._settle(payment, net_expected, settle_date)
                # duplicate row: same payment settled twice (batch/webhook replay bug)
                self._settle(payment, net_expected, settle_date + timedelta(minutes=40), dup=True)
                self.ground_truth[pid] = "duplicate_settlement_row"

            else:  # genuinely_unexplained
                mystery_gap = rupees(payment["amount"] * random.uniform(0.03, 0.09))
                settled_amt = rupees(net_expected - mystery_gap)
                self._settle(payment, settled_amt, settle_date)
                self.ground_truth[pid] = "genuinely_unexplained"

            self.payments.append(payment)

        return self

    def to_sqlite(self, path=DB_PATH):
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.executescript("""
        DROP TABLE IF EXISTS payments;
        DROP TABLE IF EXISTS refunds;
        DROP TABLE IF EXISTS disputes;
        DROP TABLE IF EXISTS settlements;
        DROP TABLE IF EXISTS expected_settlement;
        DROP TABLE IF EXISTS match_results;
        DROP TABLE IF EXISTS exceptions;
        DROP TABLE IF EXISTS audit_log;
        DROP TABLE IF EXISTS ground_truth;

        CREATE TABLE payments (
            payment_id TEXT PRIMARY KEY, order_id TEXT, amount REAL, method TEXT,
            status TEXT, created_at TEXT, balance_account_id TEXT, channel_type TEXT,
            fees REAL, tax REAL
        );
        CREATE TABLE refunds (
            refund_id TEXT PRIMARY KEY, payment_id TEXT, amount REAL, status TEXT,
            speed TEXT, created_at TEXT
        );
        CREATE TABLE disputes (
            dispute_id TEXT PRIMARY KEY, payment_id TEXT, amount REAL, phase TEXT,
            status TEXT, respond_by TEXT, created_at TEXT, resolved_at TEXT
        );
        CREATE TABLE settlements (
            settlement_id TEXT PRIMARY KEY, payment_id TEXT, order_id TEXT, amount REAL,
            fees REAL, tax REAL, utr TEXT, balance_account_id TEXT, channel_type TEXT,
            settled_at TEXT, is_duplicate_flag INTEGER
        );
        CREATE TABLE expected_settlement (
            payment_id TEXT PRIMARY KEY, expected_amount REAL, formula_breakdown TEXT
        );
        CREATE TABLE match_results (
            payment_id TEXT, settlement_id TEXT, delta_amount REAL, classification TEXT,
            confidence REAL
        );
        CREATE TABLE exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT, candidate_causes TEXT,
            chosen_cause TEXT, status TEXT, reviewer_action TEXT
        );
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT, actor TEXT,
            input_snapshot TEXT, feature_vector TEXT, action TEXT, timestamp TEXT
        );
        CREATE TABLE ground_truth (
            payment_id TEXT PRIMARY KEY, planted_cause TEXT
        );
        """)

        for p in self.payments:
            cur.execute(
                "INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?,?)",
                (p["payment_id"], p["order_id"], p["amount"], p["method"], p["status"],
                 p["created_at"].isoformat(), p["balance_account_id"], p["channel_type"],
                 p["fees"], p["tax"])
            )
        for r in self.refunds:
            cur.execute(
                "INSERT INTO refunds VALUES (?,?,?,?,?,?)",
                (r["refund_id"], r["payment_id"], r["amount"], r["status"], r["speed"],
                 r["created_at"].isoformat())
            )
        for d in self.disputes:
            cur.execute(
                "INSERT INTO disputes VALUES (?,?,?,?,?,?,?,?)",
                (d["dispute_id"], d["payment_id"], d["amount"], d["phase"], d["status"],
                 d["respond_by"].isoformat(), d["created_at"].isoformat(), d["resolved_at"].isoformat())
            )
        for s in self.settlements:
            cur.execute(
                "INSERT INTO settlements VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (s["settlement_id"], s["payment_id"], s["order_id"], s["amount"], s["fees"],
                 s["tax"], s["utr"], s["balance_account_id"], s["channel_type"],
                 s["settled_at"].isoformat(), int(s["is_duplicate_flag"]))
            )
        for pid, cause in self.ground_truth.items():
            cur.execute("INSERT INTO ground_truth VALUES (?,?)", (pid, cause))

        conn.commit()
        conn.close()
        print(f"Generated {len(self.payments)} payments, "
              f"{len(self.refunds)} refunds, {len(self.disputes)} disputes, "
              f"{len(self.settlements)} settlement rows.")
        print(f"Planted leakage cases: {sum(1 for v in self.ground_truth.values() if v)}")


if __name__ == "__main__":
    gen = LeakageAuditGenerator().generate()
    gen.to_sqlite()
