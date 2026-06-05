"use client";
// app/admin/pipeline/s2/page.tsx — S2 Market Research
// GET /v1/acp/runs                  → runs list
// GET /v1/acp/runs/{run_id}/context → s2_keyword_clusters, s2_visibility_report, confidence_score, gate1_status
// POST /v1/acp/gate/gate1/approve   → {run_id}
// POST /v1/acp/gate/gate1/reject    → {run_id, reason}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckCircle, XCircle, ChevronDown } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, serif, sans, mono, Card, SLabel, Badge, Btn } from "../../_components/adminUi";

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
  country: string | null;
  status: string;
  started_at: string | null;
}

interface KeywordCluster {
  primary_keyword: string;
  secondary_keywords?: string[];
  search_intent?: string;
  volume?: number | null;
  difficulty?: number | null;
}

interface RunContext {
  run_id: string;
  confidence_score: number | null;
  s2_keyword_clusters: KeywordCluster[] | string | null;
  s2_visibility_report: string | null;
  gate1_status: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function confidenceColor(s: number): string {
  return s >= 85 ? "#16a34a" : s >= 60 ? A.gold : "#dc2626";
}

function confidenceBg(s: number): string {
  return s >= 85 ? A.greenSoft : s >= 60 ? A.amberSoft : "#FEE2E2";
}

function confidenceLabel(s: number): string {
  return s >= 85 ? "High confidence" : s >= 60 ? "Moderate confidence" : "Low confidence";
}

function gateStatusColor(s: string | null): "green" | "amber" | "red" | "gray" | "blue" {
  if (s === "approved" || s === "auto_approved") return "green";
  if (s === "pending") return "amber";
  if (s === "rejected") return "red";
  return "gray";
}

function gateStatusLabel(s: string | null): string {
  if (s === "auto_approved") return "Auto-approved ✅";
  if (s === "approved") return "Approved ✅";
  if (s === "pending") return "Awaiting review ⏳";
  if (s === "rejected") return "Rejected ❌";
  return "—";
}

function intentColor(intent: string | undefined): { bg: string; color: string } {
  switch ((intent || "").toLowerCase()) {
    case "informational": return { bg: "#DBEAFE", color: "#1E40AF" };
    case "commercial":    return { bg: "#EDE9FE", color: "#5B21B6" };
    case "transactional": return { bg: "#D1FAE5", color: "#065F46" };
    case "navigational":  return { bg: "#FEF3C7", color: "#92400E" };
    default:              return { bg: A.line2, color: A.muted };
  }
}

function parseClusters(v: KeywordCluster[] | string | null): KeywordCluster[] {
  if (!v) return [];
  if (typeof v === "string") { try { return JSON.parse(v); } catch { return []; } }
  return v;
}

function fmtRunLabel(r: AcpRun): string {
  const date = r.started_at ? new Date(r.started_at).toLocaleString() : "";
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${r.status}${date ? " · " + date : ""}`;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ height = 20, width = "100%" }: { height?: number; width?: string }) {
  return (
    <div style={{
      height, width, borderRadius: 6,
      background: `linear-gradient(90deg, ${A.line} 25%, ${A.line2} 50%, ${A.line} 75%)`,
      backgroundSize: "200% 100%", animation: "shimmer 1.5s infinite",
    }} />
  );
}

// ── Confidence Gauge ──────────────────────────────────────────────────────────

function ConfidenceGauge({ score, gate1Status }: { score: number; gate1Status: string | null }) {
  const color = confidenceColor(score);
  const bg    = confidenceBg(score);
  const pct   = Math.min(Math.round(score), 100);

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}>
        {/* Score block */}
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{
            width: 88, height: 88, borderRadius: 20, flexShrink: 0,
            display: "grid", placeItems: "center",
            background: bg, border: `2px solid ${color}33`,
          }}>
            <span style={{ fontFamily: serif, fontSize: 30, fontWeight: 700, color }}>{pct}%</span>
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: A.ink, marginBottom: 4 }}>
              {confidenceLabel(score)}
            </div>
            <div style={{ fontSize: 12, color: A.muted, marginBottom: 10 }}>
              Gate 1 SLA: 4h · Reviewer: aa_internal
            </div>
            <div style={{ height: 6, width: 240, borderRadius: 999, background: A.line, overflow: "hidden" }}>
              <div style={{
                height: "100%", width: `${pct}%`, borderRadius: 999,
                background: color, transition: "width .6s ease",
              }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", width: 240, marginTop: 4 }}>
              <span style={{ fontSize: 10, color: A.muted2 }}>0%</span>
              <span style={{ fontSize: 10, color: A.amber }}>60%</span>
              <span style={{ fontSize: 10, color: "#16a34a" }}>85%</span>
              <span style={{ fontSize: 10, color: A.muted2 }}>100%</span>
            </div>
          </div>
        </div>

        {/* Gate status */}
        <div style={{ textAlign: "right" as const }}>
          <SLabel style={{ marginBottom: 8 }}>Gate 1 Status</SLabel>
          <Badge color={gateStatusColor(gate1Status)}>
            {gateStatusLabel(gate1Status)}
          </Badge>
        </div>
      </div>
    </Card>
  );
}

// ── Keyword Clusters ──────────────────────────────────────────────────────────

function KeywordClusters({ clusters }: { clusters: KeywordCluster[] }) {
  if (!clusters.length) {
    return (
      <div style={{ textAlign: "center", padding: "40px 20px", color: A.muted2 }}>
        <div style={{ fontSize: 24, marginBottom: 8 }}>⟳</div>
        <div style={{ fontSize: 13 }}>No keyword data — S2 may still be running</div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {clusters.map((cluster, i) => {
        const ic = intentColor(cluster.search_intent);
        return (
          <div key={i} style={{
            padding: "14px 16px", borderRadius: 10,
            border: `1px solid ${A.line}`, background: "#fff",
            display: "flex", flexDirection: "column", gap: 8,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontWeight: 700, fontSize: 14, color: A.ink, flex: 1 }}>
                {cluster.primary_keyword}
              </span>
              {cluster.search_intent && (
                <span style={{
                  padding: "3px 9px", borderRadius: 999, fontSize: 10.5, fontWeight: 600,
                  background: ic.bg, color: ic.color, textTransform: "capitalize" as const,
                }}>
                  {cluster.search_intent}
                </span>
              )}
              {cluster.volume != null && (
                <span style={{ fontSize: 11, color: A.muted2, fontFamily: mono }}>
                  vol {cluster.volume.toLocaleString()}
                </span>
              )}
              {cluster.difficulty != null && (
                <span style={{
                  fontSize: 11, fontFamily: mono, padding: "2px 7px", borderRadius: 4, fontWeight: 600,
                  background: cluster.difficulty <= 30 ? A.greenSoft : cluster.difficulty <= 60 ? A.amberSoft : "#FEE2E2",
                  color: cluster.difficulty <= 30 ? "#16a34a" : cluster.difficulty <= 60 ? A.amber : "#dc2626",
                }}>
                  KD {cluster.difficulty}
                </span>
              )}
            </div>
            {cluster.secondary_keywords && cluster.secondary_keywords.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {cluster.secondary_keywords.map((kw, j) => (
                  <span key={j} style={{
                    padding: "2px 8px", borderRadius: 4, fontSize: 11,
                    background: A.bg, color: A.muted, border: `1px solid ${A.line}`,
                  }}>{kw}</span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Visibility Report ─────────────────────────────────────────────────────────

function VisibilityReport({ text }: { text: string }) {
  const [collapsed, setCollapsed] = useState(text.length > 900);
  const display = collapsed ? text.slice(0, 900) + "…" : text;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{
        fontSize: 13, color: A.body, lineHeight: 1.85,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
        maxHeight: collapsed ? "auto" : 420, overflowY: collapsed ? "auto" : "auto",
      }}>{display}</div>
      {text.length > 900 && (
        <button onClick={() => setCollapsed(c => !c)} style={{
          fontSize: 12, color: A.gold, fontWeight: 600,
          background: "none", border: "none", cursor: "pointer", padding: 0,
          display: "flex", alignItems: "center", gap: 4, alignSelf: "flex-start",
        }}>
          <ChevronDown size={12} style={{ transform: collapsed ? "none" : "rotate(180deg)", transition: "transform .2s" }} />
          {collapsed ? "Show full report" : "Collapse"}
        </button>
      )}
      <div style={{ fontSize: 11, color: A.muted2, borderTop: `1px solid ${A.line}`, paddingTop: 8, marginTop: 4 }}>
        Generated by LangGraph ReAct · 7 tools · max 5 iterations
      </div>
    </div>
  );
}

// ── Gate 1 HITL Panel ─────────────────────────────────────────────────────────

function Gate1Panel({ runId, onAction }: { runId: string; onAction: () => void }) {
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject]     = useState(false);
  const [notes, setNotes]               = useState("");
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
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
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
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{
        padding: "12px 16px", borderRadius: 8, background: "#FFFBEB",
        border: "1px solid #FDE68A", fontSize: 13, color: "#92400E",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        ⚠️ Manual review required — confidence score below 85% threshold
      </div>
      <div>
        <label style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em", display: "block", marginBottom: 6 }}>
          Reviewer notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={e => setNotes(e.target.value)}
          rows={2}
          placeholder="Add review notes…"
          style={{
            width: "100%", padding: "9px 12px", borderRadius: 8,
            border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans,
            resize: "vertical", outline: "none", boxSizing: "border-box",
          }}
        />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Btn variant="primary" size="md" disabled={busy} onClick={approve}
          style={{ background: "#16a34a", border: "1px solid #16a34a" }}>
          <CheckCircle size={14} /> Approve Research
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
          <Btn variant="danger" size="sm" disabled={busy || !rejectReason.trim()} onClick={reject}>
            Confirm Rejection
          </Btn>
        </div>
      )}
      {err && <div style={{ color: "#dc2626", fontSize: 12 }}>{err}</div>}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function S2Page() {
  const [runs, setRuns]                     = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId]   = useState("");
  const [context, setContext]               = useState<RunContext | null>(null);
  const [loadingRuns, setLoadingRuns]       = useState(true);
  const [loadingCtx, setLoadingCtx]         = useState(false);
  const [error, setError]                   = useState<string | null>(null);

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

  const score    = context?.confidence_score ?? null;
  const clusters = parseClusters(context?.s2_keyword_clusters ?? null);

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>

        {/* Header + run selector */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
              S2 — Market Research
            </h1>
            <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
              Keyword intelligence · market visibility · Gate 1 HITL
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {loadingRuns ? (
              <Skeleton height={36} width="280px" />
            ) : (
              <select
                value={selectedRunId}
                onChange={e => onRunChange(e.target.value)}
                style={{
                  padding: "8px 12px", borderRadius: 8, border: `1px solid ${A.line}`,
                  fontSize: 13, fontFamily: sans, background: "#fff", color: A.ink, outline: "none", minWidth: 280,
                }}
              >
                <option value="">— Select a run —</option>
                {runs.map(r => (
                  <option key={r.run_id} value={r.run_id}>{fmtRunLabel(r)}</option>
                ))}
              </select>
            )}
            {selectedRunId && (
              <Btn variant="ghost" size="sm" onClick={() => loadContext(selectedRunId)}>
                <RefreshCw size={13} />
              </Btn>
            )}
          </div>
        </div>

        {error && <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "#FEE2E2", color: "#dc2626", fontSize: 13 }}>{error}</div>}

        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "80px 0", color: A.muted2, fontSize: 14 }}>
            Select a run above to view its S2 research data.
          </div>
        )}

        {loadingCtx && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Card><Skeleton height={80} /></Card>
            <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 16 }}>
              <Card><Skeleton height={200} /></Card>
              <Card><Skeleton height={200} /></Card>
            </div>
          </div>
        )}

        {context && !loadingCtx && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Section A — Confidence Score */}
            {score != null ? (
              <ConfidenceGauge score={score} gate1Status={context.gate1_status} />
            ) : (
              <Card>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ fontSize: 13, color: A.muted2 }}>No confidence score available for this run.</div>
                  <Badge color={gateStatusColor(context.gate1_status)}>
                    {gateStatusLabel(context.gate1_status)}
                  </Badge>
                </div>
              </Card>
            )}

            {/* Sections B + C side-by-side */}
            <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 20, alignItems: "start" }}>

              {/* Section B — Keyword Clusters */}
              <Card>
                <SLabel>Keyword Intelligence</SLabel>
                <KeywordClusters clusters={clusters} />
              </Card>

              {/* Section C — Visibility Report */}
              <Card style={{ maxHeight: 520, overflowY: "auto" }}>
                <SLabel>Market Visibility Report</SLabel>
                {context.s2_visibility_report ? (
                  <VisibilityReport text={context.s2_visibility_report} />
                ) : (
                  <div style={{ fontSize: 13, color: A.muted2 }}>No visibility report available.</div>
                )}
              </Card>
            </div>

            {/* Section D — Gate 1 HITL (only when pending) */}
            {context.gate1_status === "pending" && (
              <Card>
                <SLabel>Gate 1 Review</SLabel>
                <Gate1Panel runId={context.run_id} onAction={() => loadContext(context.run_id)} />
              </Card>
            )}

            {(context.gate1_status === "approved" || context.gate1_status === "auto_approved") && (
              <Card style={{ background: A.greenSoft, border: "1px solid #86EFAC" }}>
                <div style={{ fontSize: 13, color: "#166534", fontWeight: 600 }}>
                  ✅ Gate 1 approved — S3 pipeline may proceed.
                  {context.gate1_status === "auto_approved" && (
                    <span style={{ fontWeight: 400, marginLeft: 8 }}>(Auto-approved: confidence ≥ 85%)</span>
                  )}
                </div>
              </Card>
            )}

            {context.gate1_status === "rejected" && (
              <Card style={{ background: "#FEE2E2", border: "1px solid #FECACA" }}>
                <div style={{ fontSize: 13, color: "#991B1B", fontWeight: 600 }}>
                  ❌ Gate 1 rejected — run cannot proceed.
                </div>
              </Card>
            )}

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
