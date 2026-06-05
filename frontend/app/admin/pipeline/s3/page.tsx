"use client";
// app/admin/pipeline/s3/page.tsx — S3 Calendar + Ads Viewer
// GET /v1/acp/runs               → runs list
// GET /v1/s3/runs/{run_id}       → calendar_plan + ads_plan + gate2_status
// POST /v1/acp/gate/s3/approve   → body {run_id}
// POST /v1/acp/gate/s3/reject    → body {run_id, reason}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckCircle, XCircle } from "lucide-react";
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

interface CalendarEntry {
  week?: number | string;
  content_type?: string;
  topic?: string;
  channel?: string;
  notes?: string;
  [key: string]: unknown;
}

interface AdEntry {
  ad_type?: string;
  headline?: string;
  body?: string;
  target_audience?: string;
  [key: string]: unknown;
}

interface S3RunData {
  run_id: string;
  gate2_status: string | null;
  calendar_plan: CalendarEntry[] | string | null;
  ads_plan: AdEntry[] | string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseJson<T>(v: T[] | string | null | undefined): T[] {
  if (!v) return [];
  if (typeof v === "string") { try { return JSON.parse(v); } catch { return []; } }
  return v;
}

function fmtRunLabel(r: AcpRun): string {
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${new Date(r.created_at).toLocaleString()}`;
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

// ── Calendar Table ────────────────────────────────────────────────────────────

function CalendarTable({ rows }: { rows: CalendarEntry[] }) {
  if (!rows.length) {
    return <div style={{ fontSize: 13, color: A.muted2, padding: "12px 0" }}>No calendar data available.</div>;
  }

  const cols: Array<keyof CalendarEntry> = ["week", "content_type", "topic", "channel", "notes"];
  const labels = ["Week", "Type", "Topic", "Channel", "Notes"];

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            {labels.map((h, i) => (
              <th key={i} style={{
                padding: "9px 14px", textAlign: "left", fontSize: 10.5,
                fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase",
                color: A.muted, borderBottom: `1px solid ${A.line}`, background: A.bg,
                whiteSpace: "nowrap",
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : A.bg }}>
              {cols.map(col => (
                <td key={String(col)} style={{
                  padding: "9px 14px", borderBottom: `1px solid ${A.line}`,
                  color: A.body, verticalAlign: "top",
                  ...(col === "week" ? { fontFamily: mono, fontWeight: 600, color: A.ink, whiteSpace: "nowrap" } : {}),
                  ...(col === "notes" ? { maxWidth: 260, fontSize: 12, color: A.muted } : {}),
                }}>
                  {col === "content_type" && row[col] ? (
                    <span style={{
                      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                      background: A.goldTint, color: A.gold,
                    }}>{String(row[col])}</span>
                  ) : col === "channel" && row[col] ? (
                    <ChannelBadge channel={String(row[col])} />
                  ) : (
                    String(row[col] ?? "—")
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Channel Badge ─────────────────────────────────────────────────────────────

function ChannelBadge({ channel }: { channel: string }) {
  const lower = channel.toLowerCase();
  const style = lower.includes("instagram")
    ? { bg: "#FCE7F3", color: "#9D174D" }
    : lower.includes("facebook")
    ? { bg: "#DBEAFE", color: "#1E40AF" }
    : lower.includes("linkedin")
    ? { bg: "#EFF6FF", color: "#1E3A5F" }
    : lower.includes("twitter") || lower.includes("x")
    ? { bg: "#F0F9FF", color: "#0369A1" }
    : lower.includes("email")
    ? { bg: "#F0FDF4", color: "#166534" }
    : lower.includes("blog")
    ? { bg: "#FDF4FF", color: "#6B21A8" }
    : { bg: A.line2, color: A.muted };

  return (
    <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600, background: style.bg, color: style.color }}>
      {channel}
    </span>
  );
}

// ── Ads Table ─────────────────────────────────────────────────────────────────

function AdsTable({ rows }: { rows: AdEntry[] }) {
  if (!rows.length) {
    return <div style={{ fontSize: 13, color: A.muted2, padding: "12px 0" }}>No ads plan data available.</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {rows.map((ad, i) => (
        <div key={i} style={{
          padding: "14px 16px", borderRadius: 10, border: `1px solid ${A.line}`,
          background: "#fff", display: "flex", flexDirection: "column", gap: 8,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {ad.ad_type && (
              <span style={{ padding: "3px 9px", borderRadius: 4, fontSize: 11, fontWeight: 600, background: A.amberSoft, color: A.amber }}>
                {ad.ad_type}
              </span>
            )}
            {ad.target_audience && (
              <span style={{ fontSize: 12, color: A.muted }}>→ {ad.target_audience}</span>
            )}
          </div>
          {ad.headline && (
            <div style={{ fontSize: 14, fontWeight: 600, color: A.ink }}>{ad.headline}</div>
          )}
          {ad.body && (
            <div style={{ fontSize: 13, color: A.body, lineHeight: 1.6 }}>{ad.body}</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Gate 2 Panel ──────────────────────────────────────────────────────────────

function Gate2Panel({ runId, status, onAction }: {
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
      const res = await fetch(`${API_URL}/v1/acp/gate/s3/approve`, {
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
      const res = await fetch(`${API_URL}/v1/acp/gate/s3/reject`, {
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
        <SLabel style={{ marginBottom: 0 }}>Gate 2 Status</SLabel>
        <Badge color={gateStatusColor(status)}>{status || "unknown"}</Badge>
      </div>

      {isPending && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 13, color: A.muted }}>
            Review the calendar and ads plan above, then approve or reject to proceed to S4.
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Btn variant="primary" size="md" disabled={busy} onClick={approve}
              style={{ background: "#16A34A", border: "1px solid #16A34A" }}>
              <CheckCircle size={14} /> Approve Gate 2
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
            ? "Gate 2 approved. S4 pipeline may proceed."
            : status === "rejected"
            ? "Gate 2 was rejected. Run cannot proceed to S4."
            : "Waiting for gate evaluation."}
        </div>
      )}
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ height = 20 }: { height?: number }) {
  return (
    <div style={{
      height, width: "100%", borderRadius: 6,
      background: `linear-gradient(90deg, ${A.line} 25%, ${A.line2} 50%, ${A.line} 75%)`,
      backgroundSize: "200% 100%", animation: "shimmer 1.5s infinite",
    }} />
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function S3Page() {
  const [runs, setRuns]             = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [data, setData]             = useState<S3RunData | null>(null);
  const [loadingRuns, setLoadingRuns]   = useState(true);
  const [loadingData, setLoadingData]   = useState(false);
  const [error, setError]           = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/v1/acp/runs`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setRuns(Array.isArray(d) ? d : (d.data || d.runs || [])))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingRuns(false));
  }, []);

  const loadData = useCallback((runId: string) => {
    if (!runId) return;
    setLoadingData(true);
    setData(null);
    setError(null);
    fetch(`${API_URL}/v1/s3/runs/${runId}`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setData(d))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingData(false));
  }, []);

  function onRunChange(runId: string) {
    setSelectedRunId(runId);
    loadData(runId);
  }

  const calendar = parseJson<CalendarEntry>(data?.calendar_plan);
  const ads      = parseJson<AdEntry>(data?.ads_plan);

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
            S3 Calendar & Ads
          </h1>
          <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
            90-day content calendar · ads strategy · Gate 2 review
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
                <option value="">— Select a run to view S3 output —</option>
                {runs.map(r => (
                  <option key={r.run_id} value={r.run_id}>{fmtRunLabel(r)}</option>
                ))}
              </select>
              {selectedRunId && (
                <Btn variant="ghost" size="sm" onClick={() => loadData(selectedRunId)}>
                  <RefreshCw size={13} /> Refresh
                </Btn>
              )}
            </div>
          )}
          {error && !loadingData && (
            <div style={{ marginTop: 10, color: A.red, fontSize: 13 }}>{error}</div>
          )}
        </Card>

        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "60px 0", color: A.muted2, fontSize: 14 }}>
            Select a run above to view its S3 content calendar and ads plan.
          </div>
        )}

        {loadingData && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Card><Skeleton height={240} /></Card>
            <Card><Skeleton height={160} /></Card>
          </div>
        )}

        {data && !loadingData && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {/* Stats strip */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
              {[
                { label: "Calendar Entries", value: String(calendar.length), color: A.gold },
                { label: "Ad Creatives",     value: String(ads.length),      color: A.amber },
                { label: "Gate 2 Status",    value: data.gate2_status || "—", color: gateStatusColor(data.gate2_status) === "green" ? A.green : gateStatusColor(data.gate2_status) === "amber" ? A.amber : gateStatusColor(data.gate2_status) === "red" ? A.red : A.muted },
              ].map(s => (
                <Card key={s.label}>
                  <SLabel>{s.label}</SLabel>
                  <div style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: s.color }}>{s.value}</div>
                </Card>
              ))}
            </div>

            {/* Calendar */}
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "20px 22px 14px" }}>
                <SLabel>90-Day Content Calendar</SLabel>
              </div>
              <CalendarTable rows={calendar} />
            </Card>

            {/* Ads plan */}
            <Card>
              <SLabel>Ads Plan</SLabel>
              <AdsTable rows={ads} />
            </Card>

            {/* Gate 2 */}
            <Card>
              <Gate2Panel
                runId={data.run_id}
                status={data.gate2_status}
                onAction={() => loadData(data.run_id)}
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
