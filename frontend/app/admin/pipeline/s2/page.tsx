"use client";
// app/admin/pipeline/s2/page.tsx — S2 Market Intelligence Dashboard
// GET /api/admin/acp/runs                  → runs list
// GET /api/admin/acp/runs/{run_id}/context → s2_keyword_clusters, s2_visibility_report, confidence_score, gate_summary
// POST /api/admin/acp/gate/s2/approve      → {run_id}
// POST /api/admin/acp/gate/s2/reject       → {run_id, reason}

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { RefreshCw, CheckCircle, XCircle, ChevronDown, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, serif, sans, mono, Card, SLabel, Badge, Btn } from "../../_components/adminUi";

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
  cluster?: string | null;
}

interface RunContext {
  run_id: string;
  confidence_score: number | null;
  confidence_breakdown?: {
    keyword?: number | null;
    competitor?: number | null;
    freshness?: number | null;
    gsc?: number | null;
  } | null;
  s2_keyword_clusters: KeywordCluster[] | string | null;
  s2_visibility_report: string | null;
  gate1_status: string | null;
}

type SortKey = "primary_keyword" | "volume" | "search_intent" | "cluster";
type SortDir = "asc" | "desc";

// ── Helpers ───────────────────────────────────────────────────────────────────

function ringColor(s: number): string {
  return s >= 85 ? "#16a34a" : s >= 60 ? A.gold : "#dc2626";
}

function subScoreColor(s: number | null | undefined): string {
  if (s == null) return A.muted2;
  return s >= 85 ? "#16a34a" : s >= 60 ? A.gold : "#dc2626";
}

function subScoreBg(s: number | null | undefined): string {
  if (s == null) return A.line2;
  return s >= 85 ? A.greenSoft : s >= 60 ? A.amberSoft : "#FEE2E2";
}

function gateStatusColor(s: string | null): "green" | "amber" | "red" | "gray" {
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

function intentStyle(intent: string | undefined): { bg: string; color: string } {
  switch ((intent || "").toLowerCase()) {
    case "informational": return { bg: "#DBEAFE", color: "#1E40AF" };
    case "commercial":    return { bg: A.amberSoft, color: "#92400E" };
    case "transactional": return { bg: "#D1FAE5", color: "#065F46" };
    case "navigational":  return { bg: A.line2, color: A.muted };
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

// ── Donut Chart (SVG, no chart lib) ──────────────────────────────────────────

function DonutChart({ score }: { score: number }) {
  const color = ringColor(score);
  const r     = 45;
  const circ  = 2 * Math.PI * r;
  const fill  = (Math.min(Math.max(score, 0), 100) / 100) * circ;
  return (
    <svg width="130" height="130" viewBox="0 0 120 120" style={{ display: "block", flexShrink: 0 }}>
      <circle cx="60" cy="60" r={r} fill="none" stroke={A.line} strokeWidth="12" />
      <circle
        cx="60" cy="60" r={r}
        fill="none" stroke={color} strokeWidth="12"
        strokeDasharray={`${fill} ${circ}`}
        strokeLinecap="round"
        transform="rotate(-90 60 60)"
      />
      <text x="60" y="55" textAnchor="middle" fontSize="24" fontWeight="700" fill={color} fontFamily="Georgia, serif">
        {Math.round(score)}
      </text>
      <text x="60" y="72" textAnchor="middle" fontSize="10.5" fill={A.muted} fontFamily="system-ui, sans-serif">
        Confidence
      </text>
    </svg>
  );
}

// ── Sub-Score Pill ────────────────────────────────────────────────────────────

function SubScorePill({ label, value }: { label: string; value: number | null | undefined }) {
  const color = subScoreColor(value);
  const bg    = subScoreBg(value);
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      padding: "8px 14px", borderRadius: 8, background: bg, minWidth: 72,
    }}>
      <span style={{
        fontSize: 9.5, fontWeight: 600, color: A.muted,
        textTransform: "uppercase" as const, letterSpacing: "0.1em", marginBottom: 3,
      }}>
        {label}
      </span>
      <span style={{ fontFamily: mono, fontSize: 16, fontWeight: 700, color }}>
        {value != null ? Math.round(value) : "—"}
      </span>
    </div>
  );
}

// ── Confidence Section ────────────────────────────────────────────────────────

function ConfidenceSection({ score, breakdown, gate1Status }: {
  score: number;
  breakdown?: RunContext["confidence_breakdown"];
  gate1Status: string | null;
}) {
  const label = score >= 85 ? "High confidence" : score >= 60 ? "Moderate confidence" : "Low confidence";
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <DonutChart score={score} />
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: A.ink, marginBottom: 6 }}>{label}</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <SubScorePill label="Keyword"    value={breakdown?.keyword} />
              <SubScorePill label="Competitor" value={breakdown?.competitor} />
              <SubScorePill label="Freshness"  value={breakdown?.freshness} />
              <SubScorePill label="GSC"        value={breakdown?.gsc} />
            </div>
          </div>
        </div>
        <div style={{ textAlign: "right" as const }}>
          <SLabel style={{ marginBottom: 8 }}>Gate 1 Status</SLabel>
          <Badge color={gateStatusColor(gate1Status)}>{gateStatusLabel(gate1Status)}</Badge>
          <div style={{ fontSize: 11, color: A.muted2, marginTop: 6 }}>SLA: 4h · Reviewer: aa_internal</div>
        </div>
      </div>
    </Card>
  );
}

// ── Keyword Table (sortable) ──────────────────────────────────────────────────

function KeywordTable({ clusters }: { clusters: KeywordCluster[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("volume");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const maxVol = useMemo(
    () => Math.max(...clusters.map(c => c.volume || 0), 1),
    [clusters],
  );

  const sorted = useMemo(() => {
    return [...clusters].sort((a, b) => {
      if (sortKey === "primary_keyword") {
        const av = a.primary_keyword || "";
        const bv = b.primary_keyword || "";
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      if (sortKey === "volume") {
        const av = a.volume ?? -1;
        const bv = b.volume ?? -1;
        return sortDir === "asc" ? av - bv : bv - av;
      }
      if (sortKey === "search_intent") {
        const av = a.search_intent || "";
        const bv = b.search_intent || "";
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const av = a.cluster || "";
      const bv = b.cluster || "";
      return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    });
  }, [clusters, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  }

  function SortIcon({ k }: { k: SortKey }) {
    if (sortKey !== k) return <ArrowUpDown size={11} color={A.muted2} />;
    return sortDir === "asc"
      ? <ArrowUp size={11} color={A.gold} />
      : <ArrowDown size={11} color={A.gold} />;
  }

  function thStyle(k: SortKey): React.CSSProperties {
    return {
      padding: "10px 14px", textAlign: "left" as const, fontSize: 10.5, fontWeight: 600,
      letterSpacing: "0.1em", textTransform: "uppercase" as const,
      color: sortKey === k ? A.gold : A.muted,
      borderBottom: `1px solid ${A.line}`, background: A.bg,
      cursor: "pointer", whiteSpace: "nowrap" as const, userSelect: "none" as const,
    };
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            <th style={thStyle("primary_keyword")} onClick={() => toggleSort("primary_keyword")}>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                Primary Keyword <SortIcon k="primary_keyword" />
              </span>
            </th>
            <th style={thStyle("volume")} onClick={() => toggleSort("volume")}>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                Volume <SortIcon k="volume" />
              </span>
            </th>
            <th style={thStyle("search_intent")} onClick={() => toggleSort("search_intent")}>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                Intent <SortIcon k="search_intent" />
              </span>
            </th>
            <th style={{ ...thStyle("cluster"), cursor: "default" }}>Secondary Keywords</th>
            <th style={thStyle("cluster")} onClick={() => toggleSort("cluster")}>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                Cluster <SortIcon k="cluster" />
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((c, i) => {
            const is     = intentStyle(c.search_intent);
            const volPct = c.volume != null ? Math.round((c.volume / maxVol) * 100) : 0;
            const sec    = c.secondary_keywords || [];
            return (
              <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : A.bg }}>
                <td style={{ padding: "10px 14px", borderBottom: `1px solid ${A.line2}`, fontWeight: 600, color: A.ink, maxWidth: 220 }}>
                  {c.primary_keyword}
                </td>
                <td style={{ padding: "10px 14px", borderBottom: `1px solid ${A.line2}`, minWidth: 130 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ width: 80, height: 6, borderRadius: 999, background: A.line, overflow: "hidden", flexShrink: 0 }}>
                      <div style={{
                        height: "100%", borderRadius: 999, background: A.gold,
                        width: `${volPct}%`, transition: "width .3s",
                      }} />
                    </div>
                    <span style={{ fontFamily: mono, fontSize: 11, color: A.muted, whiteSpace: "nowrap" as const }}>
                      {c.volume != null ? c.volume.toLocaleString() : "—"}
                    </span>
                  </div>
                </td>
                <td style={{ padding: "10px 14px", borderBottom: `1px solid ${A.line2}`, whiteSpace: "nowrap" as const }}>
                  {c.search_intent ? (
                    <span style={{
                      padding: "3px 9px", borderRadius: 999, fontSize: 11, fontWeight: 600,
                      background: is.bg, color: is.color, textTransform: "capitalize" as const,
                    }}>
                      {c.search_intent}
                    </span>
                  ) : "—"}
                </td>
                <td style={{ padding: "10px 14px", borderBottom: `1px solid ${A.line2}`, maxWidth: 220 }}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {sec.slice(0, 3).map((kw, j) => (
                      <span key={j} style={{
                        padding: "2px 7px", borderRadius: 4, fontSize: 11,
                        background: A.line2, color: A.muted, border: `1px solid ${A.line}`,
                      }}>{kw}</span>
                    ))}
                    {sec.length > 3 && (
                      <span
                        title={sec.slice(3).join(", ")}
                        style={{
                          padding: "2px 7px", borderRadius: 4, fontSize: 11,
                          background: A.line2, color: A.muted2, cursor: "help",
                        }}
                      >
                        +{sec.length - 3} more
                      </span>
                    )}
                  </div>
                </td>
                <td style={{ padding: "10px 14px", borderBottom: `1px solid ${A.line2}`, fontSize: 12, color: A.muted }}>
                  {c.cluster || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Visibility Report ─────────────────────────────────────────────────────────

function VisibilityReport({ text }: { text: string }) {
  const [collapsed, setCollapsed] = useState(text.length > 500);
  const display = collapsed ? text.slice(0, 500) + "…" : text;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <pre style={{
        fontSize: 13, color: A.body, lineHeight: 1.85, margin: 0,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
        fontFamily: sans,
      }}>{display}</pre>
      {text.length > 500 && (
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
      const res = await fetch(`/api/admin/acp/gate/s2/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
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
      const res = await fetch(`/api/admin/acp/gate/s2/reject`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, reason: rejectReason.trim() }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onAction();
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  }

  return (
    <Card style={{ border: "2px solid #FDE68A", background: "#FFFBEB" }}>
      <SLabel style={{ color: "#92400E" }}>Gate 1 — Manual Review Required</SLabel>
      <div style={{
        fontSize: 13, color: "#92400E", marginBottom: 14,
        display: "flex", alignItems: "flex-start", gap: 8,
      }}>
        ⚠️ Confidence score below 85% threshold — manual review required before S3 can proceed.
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={{
          fontSize: 11, fontWeight: 600, color: A.muted, display: "block",
          textTransform: "uppercase" as const, letterSpacing: "0.1em", marginBottom: 6,
        }}>
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
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
          <textarea
            placeholder="Rejection reason (required)…"
            value={rejectReason}
            onChange={e => setRejectReason(e.target.value)}
            rows={3}
            style={{
              width: "100%", padding: "9px 12px", borderRadius: 8,
              border: "1px solid #FCA5A5", fontSize: 13, fontFamily: sans,
              resize: "vertical", outline: "none", boxSizing: "border-box",
            }}
          />
          <Btn variant="danger" size="sm" disabled={busy || !rejectReason.trim()} onClick={reject}>
            Confirm Rejection
          </Btn>
        </div>
      )}
      {err && <div style={{ color: "#dc2626", fontSize: 12, marginTop: 8 }}>{err}</div>}
    </Card>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function S2Page() {
  const [runs, setRuns]                   = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [context, setContext]             = useState<RunContext | null>(null);
  const [loadingRuns, setLoadingRuns]     = useState(true);
  const [loadingCtx, setLoadingCtx]       = useState(false);
  const [error, setError]                 = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/admin/acp/runs`)
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
    fetch(`/api/admin/acp/runs/${runId}/context`)
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
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 28, flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
              S2 — Market Intelligence
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

        {error && (
          <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "#FEE2E2", color: "#dc2626", fontSize: 13 }}>
            {error}
          </div>
        )}

        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <div style={{ fontSize: 44, marginBottom: 12 }}>📊</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: A.ink, marginBottom: 6 }}>Select a run to view research data</div>
            <div style={{ fontSize: 13, color: A.muted2 }}>
              Choose a run above to see S2 keyword intelligence and market visibility.
            </div>
          </div>
        )}

        {loadingCtx && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Card><Skeleton height={110} /></Card>
            <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 16 }}>
              <Card><Skeleton height={260} /></Card>
              <Card><Skeleton height={260} /></Card>
            </div>
          </div>
        )}

        {context && !loadingCtx && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Section A — Confidence Score (donut + sub-scores) */}
            {score != null ? (
              <ConfidenceSection
                score={score}
                breakdown={context.confidence_breakdown}
                gate1Status={context.gate1_status}
              />
            ) : (
              <Card>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ fontSize: 13, color: A.muted2 }}>
                    No research data — select a run with completed S2.
                  </div>
                  <Badge color={gateStatusColor(context.gate1_status)}>
                    {gateStatusLabel(context.gate1_status)}
                  </Badge>
                </div>
              </Card>
            )}

            {/* Sections B + C side-by-side */}
            <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 20, alignItems: "start" }}>

              {/* Section B — Keyword Intelligence (sortable table) */}
              <Card style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "16px 20px 12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <SLabel style={{ marginBottom: 0 }}>Keyword Intelligence</SLabel>
                  {clusters.length > 0 && (
                    <span style={{ fontSize: 11, color: A.muted2, fontFamily: mono }}>
                      {clusters.length} clusters
                    </span>
                  )}
                </div>
                {clusters.length === 0 ? (
                  <div style={{ padding: "48px 20px", textAlign: "center" }}>
                    <div style={{ fontSize: 32, marginBottom: 10 }}>🔍</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: A.ink, marginBottom: 4 }}>No keyword clusters yet</div>
                    <div style={{ fontSize: 13, color: A.muted2 }}>Run S2 to populate keyword intelligence.</div>
                  </div>
                ) : (
                  <KeywordTable clusters={clusters} />
                )}
              </Card>

              {/* Section C — Market Visibility Report (collapsible) */}
              <Card>
                <SLabel>Market Visibility Report</SLabel>
                {context.s2_visibility_report ? (
                  <VisibilityReport text={context.s2_visibility_report} />
                ) : (
                  <div style={{ fontSize: 13, color: A.muted2, padding: "24px 0", textAlign: "center" }}>
                    No visibility report available for this run.
                  </div>
                )}
              </Card>
            </div>

            {/* Gate 1 Panel — only when pending */}
            {context.gate1_status === "pending" && (
              <Gate1Panel runId={context.run_id} onAction={() => loadContext(context.run_id)} />
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
                  ❌ Gate 1 rejected — run cannot proceed to S3.
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
