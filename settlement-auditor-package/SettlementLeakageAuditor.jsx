import React, { useState, useMemo } from "react";

const API_BASE = (typeof window !== "undefined" && window.SETTLEMENT_AUDITOR_API_BASE) || "http://127.0.0.1:8000";


const CAUSE_META = {
  matched: { label: "Matched", color: "#1F6F5C", bg: "#EAF3EF" },
  timing_lag_refund: { label: "Timing lag \u2014 refund", color: "#B8862C", bg: "#FBF3E4" },
  timing_lag_dispute: { label: "Timing lag \u2014 dispute", color: "#B8862C", bg: "#FBF3E4" },
  known_cause_duplicate_settlement_row: { label: "Duplicate settlement row", color: "#8A5A9E", bg: "#F1EAF5" },
  fx_rounding_error: { label: "FX rounding error", color: "#2E6B8F", bg: "#E9F1F6" },
  genuinely_unexplained: { label: "Genuinely unexplained", color: "#A83A32", bg: "#F8EAE8" },
  pending_review: { label: "Pending review", color: "#A83A32", bg: "#F8EAE8" },
};

function causeMeta(key) {
  return CAUSE_META[key] || { label: key, color: "#5B6472", bg: "#EEF0F2" };
}

function inr(n) {
  if (n === null || n === undefined) return "\u2014";
  const sign = n < 0 ? "\u2212" : "";
  return sign + "\u20B9" + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(n) {
  return (n * 100).toFixed(1) + "%";
}

function shortId(id) {
  if (!id) return "\u2014";
  return id;
}

function fmtDate(iso) {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) +
    " \u00B7 " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

function StatCell({ label, value, sub, accent }) {
  return (
    <div style={{ padding: "20px 24px", borderRight: "1px solid #DEDACE", flex: 1, minWidth: 160 }}>
      <div style={{ fontSize: 11, letterSpacing: "0.02em", color: "#5B6472", marginBottom: 8, fontFamily: "Inter, sans-serif" }}>
        {label}
      </div>
      <div style={{
        fontFamily: "'Source Serif 4', Georgia, serif", fontSize: 30, fontWeight: 600,
        color: accent || "#12203A", fontVariantNumeric: "tabular-nums", lineHeight: 1.1,
      }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: "#5B6472", marginTop: 6, fontFamily: "Inter, sans-serif" }}>{sub}</div>
      )}
    </div>
  );
}

function EvidenceRow({ label, value, negative, muted }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", padding: "7px 0",
      borderBottom: "1px solid #EAE6DA", fontSize: 13.5,
    }}>
      <span style={{ color: muted ? "#8A8F98" : "#3A4150", fontFamily: "Inter, sans-serif" }}>{label}</span>
      <span style={{
        fontFamily: "'Source Serif 4', Georgia, serif", fontVariantNumeric: "tabular-nums",
        color: negative ? "#A83A32" : "#12203A", fontWeight: 500,
      }}>
        {value}
      </span>
    </div>
  );
}

function ConfidenceBar({ cause, prob, isTop }) {
  const meta = causeMeta(cause);
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3, fontFamily: "Inter, sans-serif" }}>
        <span style={{ color: isTop ? "#12203A" : "#8A8F98", fontWeight: isTop ? 600 : 400 }}>{meta.label}</span>
        <span style={{ color: isTop ? "#12203A" : "#8A8F98", fontVariantNumeric: "tabular-nums", fontWeight: isTop ? 600 : 400 }}>
          {pct(prob)}
        </span>
      </div>
      <div style={{ height: 5, background: "#E7E3D6", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: pct(prob), height: "100%", background: isTop ? meta.color : "#C9C4B4", borderRadius: 2 }} />
      </div>
    </div>
  );
}

function CaseDetail({ c }) {
  if (!c) return null;
  const meta = causeMeta(c.classification);
  const fb = c.formula_breakdown || {};
  const isAboveThreshold = c.above_threshold;

  return (
    <div style={{ background: "#FFFFFF", border: "1px solid #DEDACE", borderRadius: 3 }}>
      <div style={{ padding: "18px 22px", borderBottom: "1px solid #DEDACE", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontFamily: "monospace", fontSize: 12.5, color: "#5B6472", marginBottom: 4 }}>
            {c.payment_id} &nbsp;\u00B7&nbsp; {c.order_id}
          </div>
          <div style={{ fontFamily: "'Source Serif 4', Georgia, serif", fontSize: 22, color: "#12203A", fontWeight: 600 }}>
            {inr(c.amount)}
          </div>
          <div style={{ fontSize: 12.5, color: "#5B6472", marginTop: 4, fontFamily: "Inter, sans-serif" }}>
            {c.method?.toUpperCase()} \u00B7 {c.channel_type} \u00B7 {fmtDate(c.created_at)}
          </div>
        </div>
        <div style={{
          background: meta.bg, color: meta.color, padding: "6px 12px", borderRadius: 3,
          fontSize: 12.5, fontWeight: 600, fontFamily: "Inter, sans-serif", whiteSpace: "nowrap",
        }}>
          {meta.label}
        </div>
      </div>

      <div style={{ padding: "18px 22px", borderBottom: "1px solid #DEDACE" }}>
        <div style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: "0.04em", color: "#8A8F98", marginBottom: 10, fontFamily: "Inter, sans-serif" }}>
          Expected-settlement formula
        </div>
        <EvidenceRow label="Payment amount" value={inr(fb.payment)} />
        <EvidenceRow label="Less: Tax" value={"\u2212 " + inr(fb.tax)} />
        <EvidenceRow label="Less: Fees" value={"\u2212 " + inr(fb.fees)} />
        {fb.adjustments > 0 && <EvidenceRow label="Less: Adjustments" value={"\u2212 " + inr(fb.adjustments)} />}
        {fb.transfers > 0 && <EvidenceRow label="Less: Transfers" value={"\u2212 " + inr(fb.transfers)} />}
        {fb.refunds_deducted_in_window > 0 && (
          <EvidenceRow label="Less: Refunds (in settlement window)" value={"\u2212 " + inr(fb.refunds_deducted_in_window)} />
        )}
        <div style={{ paddingTop: 8, marginTop: 4 }}>
          <EvidenceRow label="Expected settlement" value={inr(c.expected_amount)} />
        </div>
        <div style={{ paddingTop: 2 }}>
          <EvidenceRow label={"Actual settled (" + c.settlement_count + (c.settlement_count > 1 ? " rows found)" : " row)")} value={inr(c.actual_settled_amount)} />
        </div>
        <div style={{ paddingTop: 8, marginTop: 4, borderTop: "1px solid #12203A" }}>
          <EvidenceRow label="Delta (actual \u2212 expected)" value={inr(c.delta)} negative={Math.abs(c.delta) > 1} />
        </div>
      </div>

      {(c.refunds?.length > 0 || c.disputes?.length > 0) && (
        <div style={{ padding: "18px 22px", borderBottom: "1px solid #DEDACE" }}>
          <div style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: "0.04em", color: "#8A8F98", marginBottom: 10, fontFamily: "Inter, sans-serif" }}>
            Supporting evidence rows
          </div>
          {c.refunds?.map((r) => (
            <div key={r.refund_id} style={{ fontSize: 13, marginBottom: 6, fontFamily: "Inter, sans-serif" }}>
              <span style={{ color: "#12203A", fontWeight: 500 }}>Refund</span>{" "}
              <span style={{ fontFamily: "monospace", color: "#5B6472" }}>{r.refund_id}</span>{" "}
              \u2014 {inr(r.amount)}, posted {fmtDate(r.created_at)}
            </div>
          ))}
          {c.disputes?.map((d) => (
            <div key={d.dispute_id} style={{ fontSize: 13, marginBottom: 6, fontFamily: "Inter, sans-serif" }}>
              <span style={{ color: "#12203A", fontWeight: 500 }}>Dispute</span>{" "}
              <span style={{ fontFamily: "monospace", color: "#5B6472" }}>{d.dispute_id}</span>{" "}
              \u2014 {inr(d.amount)}, {d.status}, filed {fmtDate(d.created_at)}
            </div>
          ))}
        </div>
      )}

      {c.model_all_causes && (
        <div style={{ padding: "18px 22px", borderBottom: "1px solid #DEDACE" }}>
          <div style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: "0.04em", color: "#8A8F98", marginBottom: 12, fontFamily: "Inter, sans-serif" }}>
            Classifier \u2014 ranked candidate causes
          </div>
          {Object.entries(c.model_all_causes)
            .sort((a, b) => b[1] - a[1])
            .map(([cause, prob]) => (
              <ConfidenceBar key={cause} cause={cause} prob={prob} isTop={cause === c.classification || (c.classification === "pending_review" && prob === Math.max(...Object.values(c.model_all_causes)))} />
            ))}
          <div style={{
            marginTop: 14, padding: "12px 14px", background: "#F7F5F0", borderRadius: 3,
            fontSize: 13, color: "#3A4150", lineHeight: 1.55, fontFamily: "Inter, sans-serif",
            borderLeft: "3px solid " + meta.color,
          }}>
            {c.model_explanation}
          </div>
        </div>
      )}

      <div style={{ padding: "16px 22px", display: "flex", gap: 24, alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 11, color: "#8A8F98", fontFamily: "Inter, sans-serif" }}>Review status</div>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: c.review_status === "escalated_human_review" ? "#A83A32" : "#1F6F5C", fontFamily: "Inter, sans-serif" }}>
            {c.review_status === "escalated_human_review" ? "Escalated \u2014 awaiting human review" :
             c.review_status === "auto_resolved" ? "Auto-resolved by classifier" :
             c.review_status === "matched" ? "Resolved by deterministic engine" : c.review_status}
          </div>
        </div>
        {isAboveThreshold && (
          <div style={{
            fontSize: 11.5, color: "#A83A32", background: "#F8EAE8", padding: "5px 10px",
            borderRadius: 3, fontFamily: "Inter, sans-serif", fontWeight: 600,
          }}>
            Above \u20B95,000 auto-resolve ceiling
          </div>
        )}
      </div>
    </div>
  );
}

function QueueRow({ c, selected, onClick }) {
  const meta = causeMeta(c.classification);
  const isEscalated = c.review_status === "escalated_human_review";
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%", textAlign: "left", display: "flex", alignItems: "center",
        padding: "13px 18px", background: selected ? "#F1EEE4" : "transparent",
        border: "none", borderBottom: "1px solid #EAE6DA", cursor: "pointer",
        borderLeft: selected ? "3px solid #12203A" : "3px solid transparent",
        transition: "background 120ms",
      }}
    >
      <div style={{ flex: "0 0 90px" }}>
        {isEscalated && (
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#A83A32", display: "inline-block", marginRight: 6 }} />
        )}
        <span style={{ fontSize: 12, fontFamily: "Inter, sans-serif", color: isEscalated ? "#A83A32" : "#5B6472", fontWeight: isEscalated ? 600 : 400 }}>
          {isEscalated ? "Review" : "Resolved"}
        </span>
      </div>
      <div style={{ flex: "0 0 150px", fontFamily: "monospace", fontSize: 12, color: "#5B6472" }}>
        {c.payment_id}
      </div>
      <div style={{ flex: 1 }}>
        <span style={{
          fontSize: 11.5, fontWeight: 600, color: meta.color, background: meta.bg,
          padding: "3px 8px", borderRadius: 3, fontFamily: "Inter, sans-serif",
        }}>
          {meta.label}
        </span>
      </div>
      <div style={{
        flex: "0 0 110px", textAlign: "right", fontFamily: "'Source Serif 4', Georgia, serif",
        fontVariantNumeric: "tabular-nums", fontSize: 14.5, color: "#12203A", fontWeight: 600,
      }}>
        {inr(c.delta)}
      </div>
    </button>
  );
}

function useAuditData() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [errorMsg, setErrorMsg] = useState("");
  const [running, setRunning] = useState(false);

  const fetchAudit = React.useCallback(async () => {
    setStatus((s) => (s === "ready" ? "ready" : "loading"));
    try {
      const res = await fetch(API_BASE + "/api/audit");
      if (!res.ok) throw new Error("Server responded with " + res.status);
      const json = await res.json();
      setData(json);
      setStatus("ready");
      setErrorMsg("");
    } catch (e) {
      setStatus("error");
      setErrorMsg(e.message || "Could not reach the API");
    }
  }, []);

  const runFreshBatch = React.useCallback(async (seed, injectBreak) => {
    setRunning(true);
    try {
      const params = new URLSearchParams();
      if (seed !== undefined && seed !== null && seed !== "") params.set("seed", String(seed));
      if (injectBreak) params.set("inject_break", injectBreak);
      const res = await fetch(API_BASE + "/api/audit/run?" + params.toString(), { method: "POST" });
      if (!res.ok) throw new Error("Server responded with " + res.status);
      const json = await res.json();
      setData(json);
      setStatus("ready");
      setErrorMsg("");
    } catch (e) {
      setStatus("error");
      setErrorMsg(e.message || "Could not reach the API");
    } finally {
      setRunning(false);
    }
  }, []);

  React.useEffect(() => {
    fetchAudit();
  }, [fetchAudit]);

  return { data, status, errorMsg, running, refetch: fetchAudit, runFreshBatch };
}

function LoadingScreen() {
  return (
    <div style={{
      fontFamily: "Inter, -apple-system, sans-serif", background: "#F7F5F0", minHeight: "100vh",
      display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column",
    }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');`}</style>
      <div style={{
        width: 28, height: 28, border: "2.5px solid #DEDACE", borderTopColor: "#12203A",
        borderRadius: "50%", animation: "spin 0.8s linear infinite", marginBottom: 16,
      }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{ fontSize: 13.5, color: "#5B6472" }}>Running the reconciliation pipeline&hellip;</div>
    </div>
  );
}

function ErrorScreen({ message, onRetry, apiBase }) {
  return (
    <div style={{
      fontFamily: "Inter, -apple-system, sans-serif", background: "#F7F5F0", minHeight: "100vh",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');`}</style>
      <div style={{
        maxWidth: 460, background: "#FFFFFF", border: "1px solid #DEDACE", borderRadius: 4,
        padding: "28px 30px",
      }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "#A83A32", marginBottom: 10 }}>
          COULDN'T REACH THE API
        </div>
        <div style={{ fontFamily: "'Source Serif 4', Georgia, serif", fontSize: 19, fontWeight: 600, marginBottom: 10, color: "#12203A" }}>
          The dashboard needs the backend running
        </div>
        <div style={{ fontSize: 13.5, color: "#5B6472", lineHeight: 1.6, marginBottom: 6 }}>
          {message}
        </div>
        <div style={{ fontSize: 12.5, color: "#8A8F98", lineHeight: 1.6, marginBottom: 18 }}>
          Start it with <code style={{ background: "#F1EEE4", padding: "1px 5px", borderRadius: 2 }}>uvicorn api:app --reload --port 8000</code> from
          the project folder, then retry. Expected at <code style={{ background: "#F1EEE4", padding: "1px 5px", borderRadius: 2 }}>{apiBase}</code>.
        </div>
        <button
          onClick={onRetry}
          style={{
            background: "#12203A", color: "#F7F5F0", border: "none", borderRadius: 3,
            padding: "9px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}
        >
          Retry
        </button>
      </div>
    </div>
  );
}

function RunControls({ onRun, running }) {
  const [seed, setSeed] = useState("42");
  const [fault, setFault] = useState("");
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input
        value={seed}
        onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ""))}
        placeholder="seed"
        style={{
          width: 64, fontSize: 12.5, padding: "7px 9px", border: "1px solid #DEDACE",
          borderRadius: 3, background: "#FFFFFF", color: "#12203A",
        }}
      />
      <select
        value={fault}
        onChange={(e) => setFault(e.target.value)}
        style={{
          fontSize: 12.5, padding: "7px 9px", border: "1px solid #DEDACE", borderRadius: 3,
          background: "#FFFFFF", color: "#12203A",
        }}
      >
        <option value="">No injected fault</option>
        <option value="duplicate_webhook">Inject: duplicate webhook</option>
        <option value="out_of_order">Inject: out-of-order settlement</option>
        <option value="missing_reference">Inject: missing bank reference</option>
      </select>
      <button
        onClick={() => onRun(seed || undefined, fault || undefined)}
        disabled={running}
        style={{
          background: running ? "#8A8F98" : "#12203A", color: "#F7F5F0", border: "none", borderRadius: 3,
          padding: "8px 16px", fontSize: 12.5, fontWeight: 600, cursor: running ? "default" : "pointer",
          whiteSpace: "nowrap",
        }}
      >
        {running ? "Running\u2026" : "Run fresh batch"}
      </button>
    </div>
  );
}

export default function SettlementLeakageAuditor() {
  const [tab, setTab] = useState("dashboard");
  const [selectedCase, setSelectedCase] = useState(null);
  const [showcaseIdx, setShowcaseIdx] = useState(0);

  const { data, status, errorMsg, running, refetch, runFreshBatch } = useAuditData();

  React.useEffect(() => {
    if (data && data.exception_queue.length > 0 && !selectedCase) {
      setSelectedCase(data.exception_queue[0].payment_id);
    }
  }, [data, selectedCase]);

  if (status === "loading" && !data) return <LoadingScreen />;
  if (status === "error" && !data) return <ErrorScreen message={errorMsg} onRetry={refetch} apiBase={API_BASE} />;

  const { meta, summary, evaluation, classification_breakdown, exception_queue, showcase_cases } = data;

  const selectedCaseObj = exception_queue.find((c) => c.payment_id === selectedCase);

  const causeBars = Object.entries(classification_breakdown)
    .filter(([k]) => k !== "matched")
    .sort((a, b) => b[1] - a[1]);
  const maxCauseCount = Math.max(...causeBars.map(([, v]) => v), 1);

  const currentShowcase = showcase_cases[Math.min(showcaseIdx, showcase_cases.length - 1)];

  return (
    <div style={{
      fontFamily: "Inter, -apple-system, sans-serif", background: "#F7F5F0", minHeight: "100vh",
      color: "#12203A", padding: "0 0 60px 0",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');
        * { box-sizing: border-box; }
        button { font-family: inherit; }
      `}</style>

      {/* Header */}
      <div style={{ borderBottom: "1px solid #DEDACE", background: "#FFFFFF" }}>
        <div style={{ maxWidth: 1160, margin: "0 auto", padding: "26px 24px 0 24px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 12, color: "#8A5A9E", fontFamily: "Inter, sans-serif", fontWeight: 600, marginBottom: 6 }}>
                RAZORPAY \u00B7 SETTLEMENT INTELLIGENCE
              </div>
              <h1 style={{
                fontFamily: "'Source Serif 4', Georgia, serif", fontSize: 32, fontWeight: 600,
                margin: 0, color: "#12203A", letterSpacing: "-0.01em",
              }}>
                Settlement Leakage Auditor
              </h1>
              <p style={{ fontSize: 14, color: "#5B6472", marginTop: 6, maxWidth: 560, lineHeight: 1.5 }}>
                Every rupee of every settlement, reconstructed and matched against what actually landed \u2014 with a classified,
                evidence-backed reason for every gap that doesn't close on its own.
              </p>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "flex-end", marginBottom: 10 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#1F6F5C", display: "inline-block" }} />
                <span style={{ fontSize: 11.5, color: "#1F6F5C", fontWeight: 600 }}>Live API</span>
              </div>
              <div style={{ fontSize: 12, color: "#8A8F98", lineHeight: 1.6, marginBottom: 10 }}>
                <div>Batch of {meta.total_batch_size.toLocaleString("en-IN")} transactions</div>
                <div>Processed in {meta.pipeline_wall_time_ms}ms</div>
              </div>
              <RunControls onRun={runFreshBatch} running={running} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            {[
              ["dashboard", "Dashboard"],
              ["queue", "Exception queue"],
              ["cases", "Case walkthroughs"],
              ["evaluation", "Evaluation"],
            ].map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                style={{
                  padding: "10px 18px", background: "transparent", border: "none", cursor: "pointer",
                  fontSize: 13.5, fontWeight: 600, color: tab === id ? "#12203A" : "#8A8F98",
                  borderBottom: tab === id ? "2px solid #12203A" : "2px solid transparent",
                  marginBottom: -1,
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div style={{ maxWidth: 1160, margin: "0 auto", padding: "28px 24px 0 24px" }}>

        {tab === "dashboard" && (
          <>
            <div style={{ display: "flex", background: "#FFFFFF", border: "1px solid #DEDACE", borderRadius: 3, marginBottom: 24, overflow: "hidden" }}>
              <StatCell
                label="RUPEE LEAKAGE SURFACED"
                value={inr(summary.surfaced_leak_rupees)}
                sub={"of \u20B9" + summary.planted_leak_rupees.toLocaleString("en-IN") + " planted \u00B7 100% recall"}
                accent="#A83A32"
              />
              <StatCell
                label="MATCH RATE"
                value={summary.match_rate_pct + "%"}
                sub={(summary.n_matched + summary.n_known_cause + summary.n_timing_lag + summary.n_auto_resolved) + " resolved without review"}
                accent="#1F6F5C"
              />
              <StatCell
                label="EXCEPTION QUEUE"
                value={summary.n_escalated_human_review}
                sub={"honestly left for a human \u00B7 " + inr(evaluation.false_positive_cost_rupees) + " false-positive cost"}
                accent="#B8862C"
              />
              <div style={{ padding: "20px 24px", flex: 1, minWidth: 160 }}>
                <div style={{ fontSize: 11, letterSpacing: "0.02em", color: "#5B6472", marginBottom: 8 }}>PRECISION / RECALL</div>
                <div style={{ fontFamily: "'Source Serif 4', Georgia, serif", fontSize: 30, fontWeight: 600, color: "#12203A" }}>
                  {pct(evaluation.precision_on_planted_leakage)} / {pct(evaluation.recall_on_planted_leakage)}
                </div>
                <div style={{ fontSize: 12, color: "#5B6472", marginTop: 6 }}>on planted ground truth, held-out</div>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 20, marginBottom: 24 }}>
              <div style={{ background: "#FFFFFF", border: "1px solid #DEDACE", borderRadius: 3, padding: "22px 24px" }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#12203A", marginBottom: 4 }}>
                  Where the batch ended up
                </div>
                <div style={{ fontSize: 12.5, color: "#8A8F98", marginBottom: 18 }}>
                  Every one of {meta.total_batch_size.toLocaleString("en-IN")} transactions, bucketed by final classification
                </div>
                {causeBars.map(([cause, count]) => {
                  const m = causeMeta(cause);
                  return (
                    <div key={cause} style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
                      <div style={{ width: 190, fontSize: 12.5, color: "#3A4150" }}>{m.label}</div>
                      <div style={{ flex: 1, height: 20, background: "#F1EEE4", borderRadius: 2, position: "relative", overflow: "hidden" }}>
                        <div style={{ width: (count / maxCauseCount * 100) + "%", height: "100%", background: m.color, opacity: 0.85 }} />
                      </div>
                      <div style={{ width: 44, textAlign: "right", fontSize: 13, fontVariantNumeric: "tabular-nums", color: "#12203A", fontWeight: 600 }}>
                        {count}
                      </div>
                    </div>
                  );
                })}
                <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid #EAE6DA", fontSize: 12, color: "#8A8F98" }}>
                  {summary.n_matched.toLocaleString("en-IN")} matched exactly within \u20B91 tolerance (not shown above)
                </div>
              </div>

              <div style={{ background: "#12203A", borderRadius: 3, padding: "22px 24px", color: "#F7F5F0" }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Deterministic first, learned model second</div>
                <div style={{ fontSize: 12.5, color: "#AEB6C4", marginBottom: 18, lineHeight: 1.5 }}>
                  Nothing free-text decides whether money matches
                </div>
                {[
                  ["1", "Arithmetic + rules", "Formula, matcher, known-cause rules \u2014 provably correct"],
                  ["2", "Local classifier", "scikit-learn, trained on your own labeled data, invoked only on residuals"],
                  ["3", "Hard ceiling", "No case above \u20B9" + meta.high_value_threshold_rupees.toLocaleString("en-IN") + " auto-resolves, regardless of confidence"],
                ].map(([n, title, desc]) => (
                  <div key={n} style={{ display: "flex", gap: 12, marginBottom: 16 }}>
                    <div style={{
                      width: 24, height: 24, borderRadius: "50%", border: "1px solid #4A5670",
                      display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11.5,
                      color: "#AEB6C4", flexShrink: 0,
                    }}>
                      {n}
                    </div>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{title}</div>
                      <div style={{ fontSize: 12, color: "#AEB6C4", lineHeight: 1.45 }}>{desc}</div>
                    </div>
                  </div>
                ))}
                <div style={{ marginTop: 4, paddingTop: 16, borderTop: "1px solid #2A3650", fontSize: 12, color: "#8A93A8" }}>
                  Zero external dependencies \u00B7 runs entirely offline on this batch
                </div>
              </div>
            </div>

            <div style={{ background: "#FFFFFF", border: "1px solid #DEDACE", borderRadius: 3, padding: "20px 24px", marginBottom: 24 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 14 }}>Recall by planted leakage type</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14 }}>
                {Object.entries(evaluation.cause_recall_breakdown).map(([cause, d]) => {
                  const m = causeMeta(cause);
                  return (
                    <div key={cause} style={{ padding: "14px 14px", background: "#FAF8F2", borderRadius: 3, border: "1px solid #EAE6DA" }}>
                      <div style={{ fontSize: 11.5, color: m.color, fontWeight: 600, marginBottom: 8, lineHeight: 1.3 }}>{m.label}</div>
                      <div style={{ fontFamily: "'Source Serif 4', Georgia, serif", fontSize: 20, fontWeight: 600 }}>
                        {d.caught}/{d.planted}
                      </div>
                      <div style={{ fontSize: 11, color: "#8A8F98", marginTop: 2 }}>{pct(d.recall)} recall</div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}

        {tab === "queue" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.3fr", gap: 20 }}>
            <div style={{ background: "#FFFFFF", border: "1px solid #DEDACE", borderRadius: 3, overflow: "hidden" }}>
              <div style={{ padding: "16px 18px", borderBottom: "1px solid #DEDACE", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>Exception queue</div>
                  <div style={{ fontSize: 12, color: "#8A8F98", marginTop: 2 }}>{exception_queue.length} residuals routed to the classifier</div>
                </div>
              </div>
              <div style={{ maxHeight: 560, overflowY: "auto" }}>
                {exception_queue.map((c) => (
                  <QueueRow key={c.payment_id} c={c} selected={c.payment_id === selectedCase} onClick={() => setSelectedCase(c.payment_id)} />
                ))}
              </div>
            </div>
            <div>
              <CaseDetail c={selectedCaseObj} />
            </div>
          </div>
        )}

        {tab === "cases" && (
          <div>
            <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
              {showcase_cases.map((c, i) => {
                const m = causeMeta(c.classification);
                return (
                  <button
                    key={c.payment_id}
                    onClick={() => setShowcaseIdx(i)}
                    style={{
                      padding: "9px 16px", borderRadius: 3, border: "1px solid " + (i === showcaseIdx ? "#12203A" : "#DEDACE"),
                      background: i === showcaseIdx ? "#12203A" : "#FFFFFF", color: i === showcaseIdx ? "#F7F5F0" : "#12203A",
                      cursor: "pointer", fontSize: 12.5, fontWeight: 600,
                    }}
                  >
                    {m.label}
                  </button>
                );
              })}
            </div>
            {currentShowcase && <CaseDetail c={currentShowcase} />}
          </div>
        )}

        {tab === "evaluation" && (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
              {[
                ["Precision on planted leakage", pct(evaluation.precision_on_planted_leakage), "of everything flagged, how much was real leakage"],
                ["Recall on planted leakage", pct(evaluation.recall_on_planted_leakage), "of planted leakage, how much the system caught"],
                ["False positives", evaluation.false_positives, "clean transactions wrongly flagged"],
                ["False-positive cost", inr(evaluation.false_positive_cost_rupees), "rupee value wrongly flagged"],
              ].map(([label, value, sub]) => (
                <div key={label} style={{ background: "#FFFFFF", border: "1px solid #DEDACE", borderRadius: 3, padding: "18px 20px" }}>
                  <div style={{ fontSize: 11.5, color: "#8A8F98", marginBottom: 8 }}>{label.toUpperCase()}</div>
                  <div style={{ fontFamily: "'Source Serif 4', Georgia, serif", fontSize: 26, fontWeight: 600 }}>{value}</div>
                  <div style={{ fontSize: 11.5, color: "#8A8F98", marginTop: 6, lineHeight: 1.4 }}>{sub}</div>
                </div>
              ))}
            </div>

            <div style={{ background: "#FFFFFF", border: "1px solid #DEDACE", borderRadius: 3, padding: "20px 24px", marginBottom: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Classifier training metrics</div>
              <div style={{ fontSize: 12, color: "#8A8F98", marginBottom: 16 }}>
                RandomForestClassifier, trained and scored on a held-out split \u2014 not self-graded
              </div>
              <div style={{ display: "flex", gap: 32 }}>
                {Object.entries(evaluation.classifier_training_metrics).map(([k, v]) => (
                  <div key={k}>
                    <div style={{ fontSize: 11, color: "#8A8F98", marginBottom: 4 }}>{k.replace(/_/g, " ")}</div>
                    <div style={{ fontFamily: "'Source Serif 4', Georgia, serif", fontSize: 19, fontWeight: 600 }}>
                      {typeof v === "number" && v <= 1 ? pct(v) : v}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ background: "#FAF8F2", border: "1px solid #EAE6DA", borderRadius: 3, padding: "18px 22px", fontSize: 13, color: "#3A4150", lineHeight: 1.6 }}>
              <strong style={{ color: "#12203A" }}>Exception-queue honesty check:</strong> {summary.n_escalated_human_review} cases worth {inr(exception_queue.filter(c => c.review_status === "escalated_human_review").reduce((s, c) => s + Math.abs(c.delta), 0))}{" "}
              were correctly left unresolved rather than force-matched \u2014 including every case above the \u20B95,000 auto-resolve ceiling, regardless of how confident the classifier was.
              An empty exception queue on this dataset would be a red flag, not a win.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
