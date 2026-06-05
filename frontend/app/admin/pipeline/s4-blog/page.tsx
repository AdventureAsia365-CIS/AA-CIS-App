"use client";
// app/admin/pipeline/s4-blog/page.tsx — S4 Blog Drafts HITL
// GET  /v1/acp/runs                         → runs list
// GET  /v1/acp/s4/blog/drafts?run_id={id}   → array of blog drafts
// PATCH /v1/acp/s4/blog/drafts/{id}/hitl    → {action, feedback?}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckCircle, XCircle, RotateCcw, ChevronDown, ChevronUp } from "lucide-react";
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

interface BlogDraft {
  id: string;
  title: string;
  word_count: number | null;
  quality_score: number | null;
  seo_title: string | null;
  gate3_status: string | null;
  content: string | null;
  feedback: string | null;
}

type HitlAction = "approve" | "reject" | "rewrite";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRunLabel(r: AcpRun): string {
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${new Date(r.created_at).toLocaleString()}`;
}

function qualityColor(score: number | null): string {
  if (score == null) return A.muted2;
  if (score >= 8) return A.green;
  if (score >= 6) return A.amber;
  return A.red;
}

function qualityBg(score: number | null): string {
  if (score == null) return A.line2;
  if (score >= 8) return A.greenSoft;
  if (score >= 6) return A.amberSoft;
  return "#FEE2E2";
}

function statusBadgeColor(status: string | null): "green" | "amber" | "red" | "blue" | "gray" {
  switch (status) {
    case "approved":          return "green";
    case "rejected":          return "red";
    case "pending":           return "amber";
    case "rewrite_requested": return "blue";
    default:                  return "gray";
  }
}

// ── Draft Card ────────────────────────────────────────────────────────────────

function DraftCard({ draft, onAction }: {
  draft: BlogDraft;
  onAction: (id: string, action: HitlAction, feedback?: string) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showFeedback, setShowFeedback] = useState<HitlAction | null>(null);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy]         = useState(false);
  const [err, setErr]           = useState<string | null>(null);

  async function submit(action: HitlAction) {
    if ((action === "reject" || action === "rewrite") && !feedback.trim()) return;
    setBusy(true); setErr(null);
    try {
      await onAction(draft.id, action, feedback.trim() || undefined);
      setShowFeedback(null);
      setFeedback("");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const isPending = draft.gate3_status === "pending" || draft.gate3_status === null;

  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      {/* Summary row */}
      <div style={{ padding: "16px 20px", display: "flex", alignItems: "center", gap: 12 }}>
        {/* Quality score badge */}
        <div style={{
          width: 48, height: 48, borderRadius: 10, flexShrink: 0,
          display: "grid", placeItems: "center",
          background: qualityBg(draft.quality_score),
          border: `1px solid ${qualityColor(draft.quality_score)}33`,
        }}>
          <span style={{ fontFamily: mono, fontWeight: 700, fontSize: 15, color: qualityColor(draft.quality_score) }}>
            {draft.quality_score != null ? draft.quality_score.toFixed(1) : "—"}
          </span>
        </div>

        {/* Title + meta */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, color: A.ink, fontSize: 14, marginBottom: 2 }}>
            {draft.title || "(Untitled)"}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {draft.word_count != null && (
              <span style={{ fontSize: 11, color: A.muted2 }}>{draft.word_count.toLocaleString()} words</span>
            )}
            {draft.seo_title && (
              <span style={{ fontSize: 11, color: A.muted, fontFamily: mono }}>SEO: {draft.seo_title.slice(0, 40)}{draft.seo_title.length > 40 ? "…" : ""}</span>
            )}
          </div>
        </div>

        {/* Status + actions */}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          <Badge color={statusBadgeColor(draft.gate3_status)}>
            {draft.gate3_status || "pending"}
          </Badge>
          {isPending && (
            <>
              <Btn size="sm" variant="ghost" disabled={busy}
                onClick={() => setShowFeedback(f => f === "rewrite" ? null : "rewrite")}
                style={{ color: "#1D4ED8", borderColor: "#BFDBFE" }}>
                <RotateCcw size={12} /> Rewrite
              </Btn>
              <Btn size="sm" variant="danger" disabled={busy}
                onClick={() => setShowFeedback(f => f === "reject" ? null : "reject")}>
                <XCircle size={12} /> Reject
              </Btn>
              <Btn size="sm" variant="primary" disabled={busy}
                onClick={() => submit("approve")}
                style={{ background: "#16A34A", border: "1px solid #16A34A" }}>
                <CheckCircle size={12} /> Approve
              </Btn>
            </>
          )}
          <button
            onClick={() => setExpanded(e => !e)}
            style={{ padding: 7, border: `1px solid ${A.line}`, borderRadius: 8, background: "none", cursor: "pointer", color: A.muted, display: "flex" }}
          >
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        </div>
      </div>

      {/* Feedback input */}
      {showFeedback && (
        <div style={{ padding: "0 20px 16px", borderTop: `1px solid ${A.line}`, paddingTop: 14 }}>
          <textarea
            placeholder={showFeedback === "reject" ? "Rejection reason (required)…" : "Rewrite feedback (required)…"}
            value={feedback}
            onChange={e => setFeedback(e.target.value)}
            rows={3}
            style={{
              width: "100%", padding: "9px 12px", borderRadius: 8,
              border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans,
              resize: "vertical", outline: "none", boxSizing: "border-box",
              marginBottom: 8,
            }}
          />
          <Btn
            size="sm"
            variant={showFeedback === "reject" ? "danger" : "ghost"}
            disabled={busy || !feedback.trim()}
            onClick={() => submit(showFeedback)}
            style={showFeedback === "rewrite" ? { color: "#1D4ED8", borderColor: "#BFDBFE" } : {}}
          >
            {showFeedback === "reject" ? "Confirm Reject" : "Send Rewrite Request"}
          </Btn>
          {err && <div style={{ color: A.red, fontSize: 12, marginTop: 6 }}>{err}</div>}
        </div>
      )}

      {/* Full content expand */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${A.line}`, padding: "16px 20px", background: A.bg }}>
          <SLabel>Full Draft Content</SLabel>
          {draft.content ? (
            <div style={{
              fontSize: 13, color: A.body, lineHeight: 1.8,
              whiteSpace: "pre-wrap", wordBreak: "break-word",
              maxHeight: 480, overflowY: "auto",
              padding: "12px 16px", background: "#fff", borderRadius: 8,
              border: `1px solid ${A.line}`,
            }}>
              {draft.content}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: A.muted2 }}>No content available.</div>
          )}
          {draft.feedback && (
            <div style={{ marginTop: 14 }}>
              <SLabel>Previous Feedback</SLabel>
              <div style={{ fontSize: 13, color: A.body, fontStyle: "italic" }}>{draft.feedback}</div>
            </div>
          )}
        </div>
      )}
    </Card>
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

export default function S4BlogPage() {
  const [runs, setRuns]             = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [drafts, setDrafts]         = useState<BlogDraft[]>([]);
  const [loadingRuns, setLoadingRuns]   = useState(true);
  const [loadingDrafts, setLoadingDrafts] = useState(false);
  const [error, setError]           = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/v1/acp/runs`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setRuns(Array.isArray(d) ? d : (d.data || d.runs || [])))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingRuns(false));
  }, []);

  const loadDrafts = useCallback((runId: string) => {
    if (!runId) return;
    setLoadingDrafts(true);
    setDrafts([]);
    setError(null);
    fetch(`${API_URL}/v1/acp/s4/blog/drafts?run_id=${runId}`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setDrafts(Array.isArray(d) ? d : (d.data || d.drafts || [])))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingDrafts(false));
  }, []);

  function onRunChange(runId: string) {
    setSelectedRunId(runId);
    loadDrafts(runId);
  }

  async function handleAction(id: string, action: HitlAction, feedback?: string) {
    const res = await fetch(`${API_URL}/v1/acp/s4/blog/drafts/${id}/hitl`, {
      method: "PATCH", headers: authHeaders(),
      body: JSON.stringify({ action, ...(feedback ? { feedback } : {}) }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    setDrafts(prev => prev.map(d => d.id === id
      ? { ...d, gate3_status: action === "approve" ? "approved" : action === "reject" ? "rejected" : "rewrite_requested" }
      : d
    ));
  }

  const approvedCount = drafts.filter(d => d.gate3_status === "approved").length;
  const total = drafts.length;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
            S4 Blog Drafts
          </h1>
          <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
            Human-in-the-loop review · approve, reject, or request rewrite
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
                <option value="">— Select a run to review blog drafts —</option>
                {runs.map(r => (
                  <option key={r.run_id} value={r.run_id}>{fmtRunLabel(r)}</option>
                ))}
              </select>
              {selectedRunId && (
                <Btn variant="ghost" size="sm" onClick={() => loadDrafts(selectedRunId)}>
                  <RefreshCw size={13} /> Refresh
                </Btn>
              )}
            </div>
          )}
          {error && !loadingDrafts && (
            <div style={{ marginTop: 10, color: A.red, fontSize: 13 }}>{error}</div>
          )}
        </Card>

        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "60px 0", color: A.muted2, fontSize: 14 }}>
            Select a run above to view its blog drafts.
          </div>
        )}

        {loadingDrafts && <LoadingScreen msg="Loading blog drafts…" />}

        {!loadingDrafts && selectedRunId && drafts.length === 0 && !error && (
          <div style={{ textAlign: "center", padding: "60px 0", color: A.muted2, fontSize: 14 }}>
            No blog drafts found for this run.
          </div>
        )}

        {!loadingDrafts && drafts.length > 0 && (
          <>
            {/* Aggregate */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <div style={{ fontSize: 14, color: A.body }}>
                <span style={{ fontWeight: 700, color: A.green }}>{approvedCount}</span>
                <span style={{ color: A.muted }}> / {total} approved</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {[
                  { label: "Approved", count: approvedCount, color: A.green },
                  { label: "Pending",  count: drafts.filter(d => !d.gate3_status || d.gate3_status === "pending").length, color: A.amber },
                  { label: "Rejected", count: drafts.filter(d => d.gate3_status === "rejected").length, color: A.red },
                  { label: "Rewrite",  count: drafts.filter(d => d.gate3_status === "rewrite_requested").length, color: "#1D4ED8" },
                ].map(s => s.count > 0 && (
                  <span key={s.label} style={{
                    padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600,
                    background: `${s.color}18`, color: s.color,
                  }}>
                    {s.count} {s.label}
                  </span>
                ))}
              </div>
            </div>

            {/* Draft list */}
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {drafts.map(draft => (
                <DraftCard key={draft.id} draft={draft} onAction={handleAction} />
              ))}
            </div>
          </>
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
