"use client";
// app/admin/pipeline/s4-blog/page.tsx — S4 HITL Editorial Workspace
// GET  /api/admin/acp/runs                              → runs list
// GET  /api/admin/acp/s4/blog/drafts?run_id={id}       → [{draft_id, title, word_count, evaluator_score, hitl_gate3_status, seo_score, review_flags}]
// PATCH /api/admin/acp/s4/blog/drafts/{id}/hitl        → {action, feedback?}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckCircle, XCircle, RotateCcw, ChevronDown, ChevronUp, FileText } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, serif, sans, mono, Card, SLabel, Badge, Btn } from "../../_components/adminUi";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AcpRun {
  run_id: string;
  country: string | null;
  status: string;
  started_at: string | null;
}

interface ReviewFlag {
  rule_id?: string;
  pattern?: string;
  message?: string;
  rule_type?: string;
}

interface BlogDraft {
  draft_id: string;
  title: string | null;
  word_count: number | null;
  evaluator_score: number | null;
  hitl_gate3_status: string | null;
  seo_score: number | null;
  seo_title: string | null;
  seo_meta: string | null;
  target_keywords: string[] | null;
  review_flags: ReviewFlag[] | null;
  run_id?: string;
}

type HitlAction = "approve" | "reject" | "rewrite";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRunLabel(r: AcpRun): string {
  const date = r.started_at ? new Date(r.started_at).toLocaleString() : "";
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${r.status}${date ? " · " + date : ""}`;
}

function evalScoreColor(s: number | null): string {
  if (s == null) return A.muted2;
  if (s >= 8)   return "#16a34a";
  if (s >= 6)   return A.amber;
  return "#dc2626";
}

function evalScoreBg(s: number | null): string {
  if (s == null) return A.line2;
  if (s >= 8)   return A.greenSoft;
  if (s >= 6)   return A.amberSoft;
  return "#FEE2E2";
}

function statusConfig(status: string | null): {
  icon: string; label: string; color: "green" | "amber" | "gray" | "red" | "blue";
} {
  switch (status) {
    case "msthy_approved":                   return { icon: "✅", label: "Approved",          color: "green" };
    case "flagged_human":
    case "escalated_msthy":                  return { icon: "⚠️", label: "Flagged for Review", color: "amber" };
    case "rejected":                         return { icon: "❌", label: "Rejected",           color: "red"   };
    case "pending": default:                 return { icon: "⏳", label: "Pending Review",     color: "gray"  };
  }
}

function isActionable(status: string | null): boolean {
  return status === "pending" || status === null || status === "flagged_human" || status === "escalated_msthy";
}

function flagLabel(f: ReviewFlag): string {
  return f.message || f.pattern || f.rule_id || "Flag";
}

function exportApprovedJSON(drafts: BlogDraft[]) {
  const approved = drafts.filter(d => d.hitl_gate3_status === "msthy_approved");
  const blob = new Blob([JSON.stringify(approved, null, 2)], { type: "application/json" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = "approved-drafts.json"; a.click();
  URL.revokeObjectURL(url);
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

// ── Draft Card ────────────────────────────────────────────────────────────────

function DraftCard({ draft, onAction }: {
  draft: BlogDraft;
  onAction: (id: string, action: HitlAction, feedback?: string) => Promise<void>;
}) {
  const [expanded, setExpanded]     = useState(false);
  const [pendingAction, setPending] = useState<HitlAction | null>(null);
  const [feedback, setFeedback]     = useState("");
  const [busy, setBusy]             = useState(false);
  const [err, setErr]               = useState<string | null>(null);

  const sc     = statusConfig(draft.hitl_gate3_status);
  const flags  = draft.review_flags || [];
  const canAct = isActionable(draft.hitl_gate3_status);
  const isApproved = draft.hitl_gate3_status === "msthy_approved";

  async function submit(action: HitlAction) {
    if ((action === "reject" || action === "rewrite") && !feedback.trim()) return;
    setBusy(true); setErr(null);
    try {
      await onAction(draft.draft_id, action, feedback.trim() || undefined);
      setPending(null);
      setFeedback("");
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  }

  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      {/* Main row */}
      <div style={{ padding: "16px 20px", display: "flex", alignItems: "flex-start", gap: 14 }}>

        {/* Status icon */}
        <div style={{ fontSize: 20, lineHeight: 1, paddingTop: 3, flexShrink: 0 }}>
          {sc.icon}
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: A.ink, marginBottom: 6 }}>
            {draft.title || "(Untitled)"}
          </div>

          {/* Score row */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: flags.length ? 10 : 0 }}>
            {draft.word_count != null && (
              <span style={{ fontSize: 11, color: A.muted2 }}>
                {draft.word_count.toLocaleString()} words
              </span>
            )}
            {draft.evaluator_score != null && (
              <span style={{
                fontFamily: mono, fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
                background: evalScoreBg(draft.evaluator_score), color: evalScoreColor(draft.evaluator_score),
              }}>
                Score {draft.evaluator_score.toFixed(1)}/10
              </span>
            )}
            {draft.seo_score != null && (
              <span style={{
                fontFamily: mono, fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
                background: evalScoreBg(draft.seo_score), color: evalScoreColor(draft.seo_score),
              }}>
                SEO {draft.seo_score.toFixed(1)}/10
              </span>
            )}
            <Badge color={sc.color}>{sc.label}</Badge>
          </div>

          {/* Review flags — chips, max 3 visible */}
          {flags.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {flags.slice(0, 3).map((f, i) => (
                <span key={i} style={{
                  padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 500,
                  background: "#FEF3C7", color: "#92400E", border: "1px solid #FDE68A",
                  display: "flex", alignItems: "center", gap: 4,
                }}>
                  ⚠️ {flagLabel(f)}
                </span>
              ))}
              {flags.length > 3 && (
                <span
                  title={flags.slice(3).map(f => flagLabel(f)).join(", ")}
                  style={{
                    padding: "2px 8px", borderRadius: 4, fontSize: 11,
                    background: A.line2, color: A.muted2, cursor: "help",
                  }}
                >
                  +{flags.length - 3} more
                </span>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
          {canAct && (
            <>
              <Btn size="sm" variant="ghost" disabled={busy}
                onClick={() => setPending(p => p === "rewrite" ? null : "rewrite")}
                style={{ color: "#1D4ED8", borderColor: "#BFDBFE" }}>
                <RotateCcw size={12} /> Rewrite
              </Btn>
              <Btn size="sm" variant="danger" disabled={busy}
                onClick={() => setPending(p => p === "reject" ? null : "reject")}>
                <XCircle size={12} /> Reject
              </Btn>
              <Btn size="sm" variant="primary" disabled={busy}
                onClick={() => submit("approve")}
                style={{ background: "#16a34a", border: "1px solid #16a34a" }}>
                <CheckCircle size={12} /> Approve
              </Btn>
            </>
          )}
          {isApproved && (
            <Btn size="sm" variant="ghost" disabled={busy}
              onClick={() => submit("reject")}
              style={{ fontSize: 11 }}>
              Revoke
            </Btn>
          )}
          <button
            onClick={() => setExpanded(e => !e)}
            style={{
              padding: 7, border: `1px solid ${A.line}`, borderRadius: 8,
              background: "none", cursor: "pointer", color: A.muted, display: "flex",
            }}
          >
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        </div>
      </div>

      {/* Feedback textarea */}
      {pendingAction && (
        <div style={{ padding: "12px 20px 16px", borderTop: `1px solid ${A.line}` }}>
          <textarea
            placeholder={pendingAction === "reject" ? "Rejection reason (required)…" : "Rewrite instructions (required)…"}
            value={feedback}
            onChange={e => setFeedback(e.target.value)}
            rows={3}
            style={{
              width: "100%", padding: "9px 12px", borderRadius: 8,
              border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans,
              resize: "vertical", outline: "none", boxSizing: "border-box", marginBottom: 8,
            }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <Btn size="sm"
              variant={pendingAction === "reject" ? "danger" : "ghost"}
              disabled={busy || !feedback.trim()}
              onClick={() => submit(pendingAction)}
              style={pendingAction === "rewrite" ? { color: "#1D4ED8", borderColor: "#BFDBFE" } : {}}>
              {pendingAction === "reject" ? "Confirm Reject" : "Send Rewrite Request"}
            </Btn>
            <Btn size="sm" variant="ghost" onClick={() => { setPending(null); setFeedback(""); }}>
              Cancel
            </Btn>
          </div>
          {err && <div style={{ color: "#dc2626", fontSize: 12, marginTop: 6 }}>{err}</div>}
        </div>
      )}

      {/* Expanded detail */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${A.line}`, padding: "14px 20px", background: A.bg }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {draft.seo_title && (
              <div>
                <SLabel style={{ marginBottom: 4 }}>SEO Title</SLabel>
                <div style={{ fontSize: 13, color: A.ink, fontWeight: 500 }}>{draft.seo_title}</div>
              </div>
            )}
            {draft.seo_meta && (
              <div>
                <SLabel style={{ marginBottom: 4 }}>SEO Meta</SLabel>
                <div style={{ fontSize: 12, color: A.body, lineHeight: 1.6, fontStyle: "italic" }}>
                  {draft.seo_meta}
                </div>
              </div>
            )}
            {draft.target_keywords && draft.target_keywords.length > 0 && (
              <div>
                <SLabel style={{ marginBottom: 6 }}>Target Keywords</SLabel>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {draft.target_keywords.map((kw, i) => (
                    <span key={i} style={{
                      padding: "2px 8px", borderRadius: 4, fontSize: 11,
                      background: "#EFF6FF", color: "#1E40AF", border: "1px solid #BFDBFE",
                    }}>{kw}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

// ── Aggregate Stats Bar (sticky) ──────────────────────────────────────────────

function AggregateBar({ drafts }: { drafts: BlogDraft[] }) {
  const total    = drafts.length;
  const approved = drafts.filter(d => d.hitl_gate3_status === "msthy_approved").length;
  const pending  = drafts.filter(d => !d.hitl_gate3_status || d.hitl_gate3_status === "pending").length;
  const flagged  = drafts.filter(d => d.hitl_gate3_status === "flagged_human" || d.hitl_gate3_status === "escalated_msthy").length;
  const rejected = drafts.filter(d => d.hitl_gate3_status === "rejected").length;
  const pct      = total > 0 ? (approved / total) * 100 : 0;

  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 20,
      background: A.card, border: `1px solid ${A.line}`, borderRadius: 12,
      padding: "14px 20px", marginBottom: 16,
      boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 10 }}>
        <div style={{ fontSize: 14, color: A.body }}>
          <span style={{ fontWeight: 700, color: "#16a34a", fontSize: 18 }}>{approved}</span>
          <span style={{ color: A.muted }}> / {total} drafts approved</span>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {[
            { label: "Pending",  count: pending,  color: A.amber },
            { label: "Flagged",  count: flagged,  color: A.gold },
            { label: "Rejected", count: rejected, color: "#dc2626" },
          ].filter(s => s.count > 0).map(s => (
            <span key={s.label} style={{
              padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600,
              background: `${s.color}18`, color: s.color,
            }}>
              {s.label}: {s.count}
            </span>
          ))}
        </div>
      </div>
      <div style={{ height: 6, borderRadius: 999, background: A.line, overflow: "hidden" }}>
        <div style={{
          height: "100%", borderRadius: 999, background: "#16a34a",
          width: `${pct}%`, transition: "width .5s ease",
        }} />
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function S4BlogPage() {
  const [runs, setRuns]                   = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [drafts, setDrafts]               = useState<BlogDraft[]>([]);
  const [loadingRuns, setLoadingRuns]     = useState(true);
  const [loadingDrafts, setLoadingDrafts] = useState(false);
  const [error, setError]                 = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/admin/acp/runs`)
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
    fetch(`/api/admin/acp/s4/blog/drafts?run_id=${runId}`)
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
    const res = await fetch(`/api/admin/acp/s4/blog/drafts/${id}/hitl`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...(feedback ? { feedback } : {}) }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const newStatus = action === "approve" ? "msthy_approved" : action === "reject" ? "rejected" : "flagged_human";
    setDrafts(prev => prev.map(d => d.draft_id === id ? { ...d, hitl_gate3_status: newStatus } : d));
  }

  const approvedCount = drafts.filter(d => d.hitl_gate3_status === "msthy_approved").length;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>

        {/* Header + run selector */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
              S4 — Editorial Workspace
            </h1>
            <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
              Human-in-the-loop review · approve, reject, or request rewrite
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {loadingRuns ? (
              <Skeleton height={36} />
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
                {runs.map(r => <option key={r.run_id} value={r.run_id}>{fmtRunLabel(r)}</option>)}
              </select>
            )}
            {selectedRunId && (
              <Btn variant="ghost" size="sm" onClick={() => loadDrafts(selectedRunId)}>
                <RefreshCw size={13} />
              </Btn>
            )}
            {drafts.length > 0 && (
              <Btn variant="ghost" size="sm" onClick={() => exportApprovedJSON(drafts)}
                title={approvedCount === 0 ? "No approved drafts to export" : `Export ${approvedCount} approved drafts`}>
                <FileText size={13} /> Export ({approvedCount})
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
            <div style={{ fontSize: 44, marginBottom: 12 }}>✍️</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: A.ink, marginBottom: 6 }}>Select a run to review blog drafts</div>
            <div style={{ fontSize: 13, color: A.muted2 }}>Blog drafts appear after Gate 2 approval triggers S4.1.</div>
          </div>
        )}

        {loadingDrafts && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[1, 2, 3].map(i => <Card key={i}><Skeleton height={70} /></Card>)}
          </div>
        )}

        {!loadingDrafts && selectedRunId && drafts.length === 0 && !error && (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <div style={{ fontSize: 44, marginBottom: 12 }}>📝</div>
            <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 500, color: A.ink, marginBottom: 8 }}>
              No blog drafts for this run
            </div>
            <div style={{ fontSize: 13, color: A.muted, maxWidth: 440, margin: "0 auto", lineHeight: 1.7 }}>
              S4.1 Blog Engine may not have run yet. Blog drafts appear here after Gate 2 approval triggers S4.
            </div>
          </div>
        )}

        {!loadingDrafts && drafts.length > 0 && (
          <>
            <AggregateBar drafts={drafts} />
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {drafts.map(draft => (
                <DraftCard key={draft.draft_id} draft={draft} onAction={handleAction} />
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
