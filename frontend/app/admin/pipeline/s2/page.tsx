"use client";
// app/admin/pipeline/s2/page.tsx — S2 Research Viewer
// GET /v1/acp/runs                       → runs list (run selector)
// GET /v1/acp/runs/{run_id}/context      → keywords + visibility + confidence + gate1
// POST /v1/acp/gate/gate1/approve        → body {run_id}
// POST /v1/acp/gate/gate1/reject         → body {run_id, reason}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckCircle, XCircle, ChevronDown } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, serif, sans, mono, Card, SLabel, Badge, Btn, LoadingScreen } from "../../_components/adminUi";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/cis_api_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}`, "Content-Type": "application/json" } : { "Content-Type": "application/json" };
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface AcpRun {
  run_id: string;
  country: string;
  status: string;
  created_at: string;
}

interface KeywordRow {
  keyword: string;
  volume?: number | null;
  difficulty?: number | null;
  opportunity?: number | null;
}

interface RunContext {
  run_id: string;
  confidence_score: number | null;
  s2_keywords_json: KeywordRow[] | null;
  s2_visibility_report: string | null;
  gate1_status: string | null;
  country?: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function confidenceColor(score: number): string {
  if (score >= 85) return A.green;
  if (score >= 60) return A.amber;
  return A.red;
}

function confidenceBg(score: number): string {
  if (score >= 85) return A.greenSoft;
  if (score >= 60) return A.amberSoft;
  return "#FEE2E2";
}

function gateStatusColor(status: string | null): "green" | "amber" | "red" | "gray" {
  switch (status) {
    case "approved":      return "green";
    case "auto-approved": return "green";
    case "pending-hitl":  return "amber";
    case "rejected":      return "red";
    default:              return "gray";
  }
}

function fmtRunLabel(r: AcpRun): string {
  const date = new Date(r.created_at).toLocaleString();
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${date}`;
}

// ── Keywords Table ─────────────────────────────────────────────────────────────

function KeywordsTable({ rows }: { rows: KeywordRow[] }) {
  if (!rows.length) {
    return <div style={{ fontSize: 13, color: A.muted2, padding: "12px 0" }}>No keyword data available.</div>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            {["Keyword", "Volume", "Difficulty", "Opportunity"].map(h => (
              <th key={h} style={{
                padding: "9px 14px", textAlign: "left", fontSize: 10.5,
                fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase",
                color: A.muted, borderBottom: `1px solid ${A.line}`, background: A.bg,
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : A.bg }}>
              <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, fontWeight: 500, color: A.ink }}>{row.keyword}</td>
              <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, fontFamily: mono, color: A.body }}>{row.volume ?? "—"}</td>
              <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, fontFamily: mono, color: A.body }}>
                {row.difficulty != null ? (
                  <span style={{
                    padding: "2px 7px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                    background: row.difficulty <= 30 ? A.greenSoft : row.difficulty <= 60 ? A.amberSoft : "#FEE2E2",
                    color: row.difficulty <= 30 ? A.green : row.difficulty <= 60 ? A.amber : A.red,
                  }}>{row.difficulty}</span>
                ) : "—"}
              </td>
              <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, fontFamily: mono, color: A.body }}>
                {row.opportunity != null ? (
                  <span style={{
                    padding: "2px 7px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                    background: row.opportunity >= 70 ? A.greenSoft : row.opportunity >= 40 ? A.amberSoft : "#FEE2E2",
                    color: row.opportunity >= 70 ? A.green : row.opportunity >= 40 ? A.amber : A.red,
                  }}>{row.opportunity}</span>
                ) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Visibility Report ─────────────────────────────────────────────────────────

function VisibilityReport({ text }: { text: string }) {
  const [collapsed, setCollapsed] = useState(text.length > 800);
  const display = collapsed ? text.slice(0, 800) + "…" : text;
  return (
    <div>
      <div style={{
        fontSize: 13, color: A.body, lineHeight: 1.8,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>{display}</div>
      {text.length > 800 && (
        <button
          onClick={() => setCollapsed(c => !c)}
          style={{
            marginTop: 8, fontSize: 12, color: A.gold, fontWeight: 600,
            background: "none", border: "none", cursor: "pointer", padding: 0,
            display: "flex", alignItems: "center", gap: 4,
          }}
        >
          <ChevronDown size={12} style={{ transform: collapsed ? "none" : "rotate(180deg)", transition: "transform .2s" }} />
          {collapsed ? "Show full report" : "Collapse"}
        </button>
      )}
    </div>
  );
}

// ── Gate 1 Panel ──────────────────────────────────────────────────────────────

function Gate1Panel({ runId, status, onAction }: {
  runId: string;
  status: string | null;
  onAction: () => void;
}) {
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject]     = useState(false);
  const [busy, setBusy]                 = useState(false);
  const [err, setErr]                   = useState<string | null>(null);

  async function approve() {
    setBusy(true); setErr(null);
    try {
      const res = await fetch(`${API_URL}/v1/acp/gate/gate1/approve`, {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({ run_id: runId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onAction();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    if (!rejectReason.trim()) return;
    setBusy(true); setErr(null);
    try {
      const res = await fetch(`${API_URL}/v1/acp/gate/gate1/reject`, {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({ run_id: runId, reason: rejectReason.trim() }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onAction();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const isPending = status === "pending-hitl";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <SLabel style={{ marginBottom: 0 }}>Gate 1 Status</SLabel>
        <Badge color={gateStatusColor(status)}>{status || "unknown"}</Badge>
      </div>

      {isPending && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <Btn variant="primary" size="md" disabled={busy} onClick={approve}
              style={{ background: "#16A34A", border: "1px solid #16A34A" }}>
              <CheckCircle size={14} /> Approve Gate 1
            </Btn>
            <Btn variant="danger" size="md" disabled={busy}
              onClick={() => setShowReject(v => !v)}>
              <XCircle size={14} /> Reject
            </Btn>
          </div>

          {showReject && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <textarea
                placeholder="Rejection reason (required)…"
                value={rejectReason}
                onChange={e => setRejectReason(e.target.value)}
                rows={3}
                style={{
                  width: "100%", padding: "9px 12px", borderRadius: 8,
                  border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans,
                  resize: "vertical", outline: "none", boxSizing: "border-box",
                }}
              />
              <Btn variant="danger" size="md"
                disabled={busy || !rejectReason.trim()}
                onClick={reject}>
                Confirm Rejection
              </Btn>
            </div>
          )}

          {err && <div style={{ color: A.red, fontSize: 12 }}>{err}</div>}
        </div>
      )}

      {!isPending && status && (
        <div style={{ fontSize: 13, color: A.muted }}>
          {status === "approved" || status === "auto-approved"
            ? "Gate 1 has been approved. S3 pipeline may proceed."
            : status === "rejected"
            ? "Gate 1 was rejected. Run cannot proceed."
            : "Waiting for gate evaluation."}
        </div>
      )}
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ height = 20, width = "100%" }: { height?: number; width?: string }) {
  return (
    <div style={{
      height, width, borderRadius: 6, background: `linear-gradient(90deg, ${A.line} 25%, ${A.line2} 50%, ${A.line} 75%)`,
      backgroundSize: "200% 100%", animation: "shimmer 1.5s infinite",
    }} />
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function S2Page() {
  const [runs, setRuns]           = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [context, setContext]     = useState<RunContext | null>(null);
  const [loadingRuns, setLoadingRuns]   = useState(true);
  const [loadingCtx, setLoadingCtx]     = useState(false);
  const [error, setError]         = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/v1/acp/runs`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setRuns(Array.isArray(d) ? d : (d.data || d.runs || [])))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingRuns(false));
  }, []);

  const loadContext = useCallback((runId: string) => {
    if (!runId) return;
    setLoadingCtx(true);
    setContext(null);
    setError(null);
    fetch(`${API_URL}/v1/acp/runs/${runId}/context`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setContext(d))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingCtx(false));
  }, []);

  function onRunChange(runId: string) {
    setSelectedRunId(runId);
    loadContext(runId);
  }

  const score = context?.confidence_score;
  const keywords: KeywordRow[] = (() => {
    const kw = context?.s2_keywords_json;
    if (!kw) return [];
    if (typeof kw === "string") { try { return JSON.parse(kw); } catch { return []; } }
    return kw;
  })();

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
            S2 Research
          </h1>
          <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
            Keyword research · market visibility · Gate 1 review
          </div>
        </div>

        {/* Run selector */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>Select Run</SLabel>
          {loadingRuns ? (
            <Skeleton height={36} />
          ) : (
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <select
                value={selectedRunId}
                onChange={e => onRunChange(e.target.value)}
                style={{
                  flex: 1, maxWidth: 560, padding: "8px 12px", borderRadius: 8,
                  border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans,
                  background: "#fff", color: A.ink, outline: "none",
                }}
              >
                <option value="">— Select a run to view S2 research —</option>
                {runs.map(r => (
                  <option key={r.run_id} value={r.run_id}>{fmtRunLabel(r)}</option>
                ))}
              </select>
              {selectedRunId && (
                <Btn variant="ghost" size="sm" onClick={() => loadContext(selectedRunId)}>
                  <RefreshCw size={13} /> Refresh
                </Btn>
              )}
            </div>
          )}
          {error && !loadingCtx && (
            <div style={{ marginTop: 10, color: A.red, fontSize: 13 }}>{error}</div>
          )}
        </Card>

        {/* Content */}
        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "60px 0", color: A.muted2, fontSize: 14 }}>
            Select a run above to view its S2 research data.
          </div>
        )}

        {loadingCtx && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Card><Skeleton height={80} /></Card>
            <Card><Skeleton height={200} /></Card>
          </div>
        )}

        {context && !loadingCtx && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {/* Confidence score */}
            <Card>
              <SLabel>Confidence Score</SLabel>
              {score != null ? (
                <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
                  <div style={{
                    width: 80, height: 80, borderRadius: 16, flexShrink: 0,
                    display: "grid", placeItems: "center",
                    background: confidenceBg(score),
                    border: `2px solid ${confidenceColor(score)}33`,
                  }}>
                    <span style={{ fontFamily: serif, fontSize: 28, fontWeight: 700, color: confidenceColor(score) }}>
                      {Math.round(score)}
                    </span>
                  </div>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 600, color: A.ink }}>
                      {score >= 85 ? "High confidence" : score >= 60 ? "Moderate confidence" : "Low confidence"}
                    </div>
                    <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
                      {score >= 85
                        ? "Market data is strong — keyword opportunity is clear."
                        : score >= 60
                        ? "Some uncertainty — review keywords carefully before approving."
                        : "Insufficient market data — consider rejecting and refreshing."}
                    </div>
                    <div style={{
                      marginTop: 8, height: 6, width: 220, borderRadius: 999,
                      background: A.line, overflow: "hidden",
                    }}>
                      <div style={{
                        height: "100%", width: `${Math.min(score, 100)}%`,
                        background: confidenceColor(score), borderRadius: 999,
                        transition: "width 0.6s ease",
                      }} />
                    </div>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: 13, color: A.muted2 }}>No confidence score available for this run.</div>
              )}
            </Card>

            {/* Keywords */}
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "20px 22px 14px" }}>
                <SLabel>Keyword Research</SLabel>
              </div>
              {keywords.length > 0
                ? <KeywordsTable rows={keywords} />
                : <div style={{ padding: "0 22px 20px", fontSize: 13, color: A.muted2 }}>No keyword data available.</div>
              }
            </Card>

            {/* Visibility report */}
            <Card>
              <SLabel>Market Visibility Report</SLabel>
              {context.s2_visibility_report
                ? <VisibilityReport text={context.s2_visibility_report} />
                : <div style={{ fontSize: 13, color: A.muted2 }}>No visibility report available.</div>
              }
            </Card>

            {/* Gate 1 */}
            <Card>
              <Gate1Panel
                runId={context.run_id}
                status={context.gate1_status}
                onAction={() => loadContext(context.run_id)}
              />
            </Card>
          </div>
        )}
      </main>

      <style>{`
        @keyframes shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}
