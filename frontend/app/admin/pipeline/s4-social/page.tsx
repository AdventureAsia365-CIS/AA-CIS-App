"use client";
// app/admin/pipeline/s4-social/page.tsx — S4 Social Batch Review Grid
// GET  /api/admin/acp/runs                        → runs list
// GET  /api/admin/acp/s4/social?run_id={id}       → social_content rows
// POST /api/admin/acp/s4/social/batch-review      → {run_id, approved_ids, rejected_ids}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckSquare, Square, CheckCircle, XCircle, Download } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, serif, sans, mono, Badge, Btn } from "../../_components/adminUi";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AcpRun {
  run_id: string;
  country: string | null;
  status: string;
  started_at: string | null;
}

type JsonObj = Record<string, unknown>;

interface QualityScore {
  overall?: number;
}

interface SocialPost {
  id: string;
  social_id?: string;
  channel: string;
  formula_used?: string | null;
  formula?: string | null;
  mode?: string | null;
  tiktok?: JsonObj | null;
  facebook_post?: JsonObj | null;
  facebook_ad?: JsonObj | null;
  quality_score?: QualityScore | number | null;
  hitl_status?: string | null;
  validation_status?: string | null;
  status?: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRunLabel(r: AcpRun): string {
  const date = r.started_at ? new Date(r.started_at).toLocaleString() : "";
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${r.status}${date ? " · " + date : ""}`;
}

function getPostId(p: SocialPost): string {
  return p.social_id || p.id;
}

function getQualityOverall(qs: QualityScore | number | null | undefined): number | null {
  if (qs == null) return null;
  if (typeof qs === "number") return qs;
  return qs.overall ?? null;
}

function qualityColor(v: number | null): string {
  if (v == null) return A.muted2;
  if (v >= 0.8) return "#16a34a";
  if (v >= 0.6) return A.amber;
  return "#dc2626";
}

function qualityBg(v: number | null): string {
  if (v == null) return A.line2;
  if (v >= 0.8) return A.greenSoft;
  if (v >= 0.6) return A.amberSoft;
  return "#FEE2E2";
}

function qualityLabel(v: number | null): string {
  if (v == null) return "N/A";
  return `${Math.round(v * 100)}%`;
}

function channelBadge(ch: string): { bg: string; color: string; short: string } {
  const c = (ch || "").toLowerCase();
  if (c === "tiktok")               return { bg: "#18181B", color: "#fff",     short: "TK" };
  if (c === "facebook_post" || c === "facebook post") return { bg: "#DBEAFE", color: "#1D4ED8", short: "FB" };
  if (c === "facebook_ad"  || c === "facebook ad")   return { bg: "#EDE9FE", color: "#4338CA", short: "FB-Ad" };
  return { bg: A.line2, color: A.muted, short: ch.slice(0, 5) };
}

function getFirstStringValue(obj: JsonObj): string {
  for (const v of Object.values(obj)) {
    if (typeof v === "string" && v.trim()) return v;
  }
  return JSON.stringify(obj);
}

function getContentPreview(row: SocialPost): string {
  const ch = (row.channel || "").toLowerCase();
  let obj: JsonObj | null | undefined = null;
  if (ch === "tiktok")                                  obj = row.tiktok;
  else if (ch === "facebook_post" || ch === "facebook post") obj = row.facebook_post;
  else if (ch === "facebook_ad"   || ch === "facebook ad")   obj = row.facebook_ad;

  if (!obj || typeof obj !== "object") return "(No content)";

  // Try common field names in priority order
  const caption  = obj.caption;
  const hook     = obj.hook;
  const headline = obj.headline;
  const text     = obj.text;
  const body     = obj.body;

  for (const v of [caption, hook, headline, text, body]) {
    if (typeof v === "string" && v.trim()) return v.slice(0, 200);
  }
  return getFirstStringValue(obj).slice(0, 200);
}

function getHitlStatus(post: SocialPost): string | null {
  return post.hitl_status || post.status || null;
}

function hitlStatusStyle(s: string | null): { label: string; bg: string; color: string } {
  switch (s) {
    case "approved": return { label: "Approved", bg: "#D1FAE5", color: "#065F46" };
    case "rejected": return { label: "Rejected", bg: "#FEE2E2", color: "#991B1B" };
    case "pending":  return { label: "Pending",  bg: A.line2,   color: A.muted   };
    default:         return { label: s || "—",   bg: A.line2,   color: A.muted2  };
  }
}

function normalizeChannelName(ch: string): string {
  const c = (ch || "").toLowerCase();
  if (c === "tiktok") return "TikTok";
  if (c === "facebook_post" || c === "facebook post") return "Facebook Post";
  if (c === "facebook_ad" || c === "facebook ad") return "Facebook Ad";
  return ch;
}

function exportApprovedCSV(posts: SocialPost[]) {
  const approved = posts.filter(p => getHitlStatus(p) === "approved");
  const headers  = ["social_id", "channel", "formula_used", "mode", "tiktok", "facebook_post", "facebook_ad"];
  const rows     = approved.map(p => [
    getPostId(p),
    p.channel,
    p.formula_used || p.formula || "",
    p.mode || "",
    JSON.stringify(p.tiktok || ""),
    JSON.stringify(p.facebook_post || ""),
    JSON.stringify(p.facebook_ad || ""),
  ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(","));
  const blob = new Blob([[headers.join(","), ...rows].join("\n")], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = "approved-social.csv"; a.click();
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

// ── Social Card ───────────────────────────────────────────────────────────────

function SocialCard({ post, selected, onToggle }: {
  post: SocialPost;
  selected: boolean;
  onToggle: (id: string) => void;
}) {
  const cb      = channelBadge(post.channel);
  const preview = getContentPreview(post);
  const qsVal   = getQualityOverall(post.quality_score);
  const hs      = hitlStatusStyle(getHitlStatus(post));
  const formula = post.formula_used || post.formula;
  const postId  = getPostId(post);

  return (
    <div
      onClick={() => onToggle(postId)}
      style={{
        padding: "14px", borderRadius: 12, cursor: "pointer",
        border: `2px solid ${selected ? A.gold : A.line}`,
        background: selected ? A.goldTint : "#fff",
        transition: "border-color .15s, background .15s",
        display: "flex", flexDirection: "column", gap: 10,
        position: "relative",
      }}
    >
      {/* Checkbox (top-left) */}
      <div style={{ position: "absolute", top: 12, left: 12, color: selected ? A.gold : A.muted2 }}>
        {selected ? <CheckSquare size={16} /> : <Square size={16} />}
      </div>

      {/* Channel badge + formula + mode (top row) */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", paddingLeft: 26, paddingRight: 8, flexWrap: "wrap" }}>
        <span style={{
          padding: "3px 9px", borderRadius: 999, fontSize: 11, fontWeight: 700,
          background: cb.bg, color: cb.color, flexShrink: 0,
          border: cb.bg === "#18181B" ? "none" : `1px solid ${A.line}`,
        }}>{cb.short}</span>

        {formula && (
          <span style={{ fontSize: 10.5, color: A.muted2, fontFamily: mono }}>
            {formula}
          </span>
        )}

        {post.mode && (
          <span style={{
            padding: "2px 7px", borderRadius: 4, fontSize: 10.5, fontWeight: 600,
            background: post.mode === "Auto" ? A.line2 : A.amberSoft,
            color: post.mode === "Auto" ? A.muted : "#92400E",
          }}>{post.mode}</span>
        )}
      </div>

      {/* Content preview */}
      <div style={{
        fontSize: 13, color: A.body, lineHeight: 1.6, paddingLeft: 4,
        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
        overflow: "hidden",
      }}>
        {preview}
      </div>

      {/* Bottom row: quality score + hitl status */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{
          padding: "2px 8px", borderRadius: 6, fontSize: 11, fontWeight: 700,
          fontFamily: mono, background: qualityBg(qsVal), color: qualityColor(qsVal),
        }}>
          {qualityLabel(qsVal)}
        </div>
        <span style={{
          padding: "2px 8px", borderRadius: 999, fontSize: 10.5, fontWeight: 600,
          background: hs.bg, color: hs.color,
        }}>
          {hs.label}
        </span>
      </div>
    </div>
  );
}

// ── Channel Filter Chips ──────────────────────────────────────────────────────

function ChannelFilterChips({ channels, active, onChange, counts }: {
  channels: string[];
  active: string;
  onChange: (ch: string) => void;
  counts: Record<string, number>;
}) {
  const totalCount = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 16, overflowX: "auto" }}>
      {["All", ...channels].map(ch => {
        const isActive = active === ch;
        const count    = ch === "All" ? totalCount : (counts[ch] ?? 0);
        return (
          <button
            key={ch}
            onClick={() => onChange(ch)}
            style={{
              padding: "6px 14px", borderRadius: 999, fontSize: 12, fontWeight: 600,
              border: `1.5px solid ${isActive ? A.gold : A.line}`,
              background: isActive ? A.gold : "#fff",
              color: isActive ? "#fff" : A.muted,
              cursor: "pointer", transition: "all .15s", whiteSpace: "nowrap" as const,
            }}
          >
            {normalizeChannelName(ch)}{" "}
            <span style={{ opacity: 0.75 }}>({count})</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Reject Reason Modal ───────────────────────────────────────────────────────

function RejectModal({ count, onConfirm, onCancel }: {
  count: number;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300,
    }}>
      <div style={{
        background: "#fff", borderRadius: 14, padding: "24px 28px",
        maxWidth: 420, width: "90%", boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: A.ink, marginBottom: 6 }}>
          Reject {count} post{count !== 1 ? "s" : ""}
        </div>
        <div style={{ fontSize: 13, color: A.muted, marginBottom: 14 }}>
          Provide a reason for rejection (required).
        </div>
        <textarea
          autoFocus
          value={reason}
          onChange={e => setReason(e.target.value)}
          rows={4}
          placeholder="Rejection reason…"
          style={{
            width: "100%", padding: "9px 12px", borderRadius: 8,
            border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans,
            resize: "vertical", outline: "none", boxSizing: "border-box", marginBottom: 14,
          }}
        />
        <div style={{ display: "flex", gap: 8 }}>
          <Btn variant="danger" size="md" disabled={!reason.trim()} onClick={() => onConfirm(reason.trim())}>
            <XCircle size={14} /> Confirm Reject
          </Btn>
          <Btn variant="ghost" size="md" onClick={onCancel}>Cancel</Btn>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function S4SocialPage() {
  const [runs, setRuns]                   = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [posts, setPosts]                 = useState<SocialPost[]>([]);
  const [selectedIds, setSelectedIds]     = useState<Set<string>>(new Set());
  const [channelFilter, setChannelFilter] = useState("All");
  const [loadingRuns, setLoadingRuns]     = useState(true);
  const [loadingPosts, setLoadingPosts]   = useState(false);
  const [submitting, setSubmitting]       = useState(false);
  const [submitResult, setSubmitResult]   = useState<string | null>(null);
  const [error, setError]                 = useState<string | null>(null);
  const [showRejectModal, setShowRejectModal] = useState(false);

  useEffect(() => {
    fetch(`/api/admin/acp/runs`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setRuns(Array.isArray(d) ? d : (d.data || d.runs || [])))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingRuns(false));
  }, []);

  const loadPosts = useCallback((runId: string) => {
    if (!runId) return;
    setLoadingPosts(true);
    setPosts([]);
    setSelectedIds(new Set());
    setChannelFilter("All");
    setSubmitResult(null);
    setError(null);
    fetch(`/api/admin/acp/s4/social?run_id=${runId}`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setPosts(Array.isArray(d) ? d : (d.data || d.posts || [])))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingPosts(false));
  }, []);

  function onRunChange(runId: string) {
    setSelectedRunId(runId);
    loadPosts(runId);
  }

  function togglePost(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const channels = [...new Set(posts.map(p => p.channel))].sort();
  const channelCounts = channels.reduce<Record<string, number>>((acc, ch) => {
    acc[ch] = posts.filter(p => p.channel === ch).length;
    return acc;
  }, {});

  const visiblePosts      = channelFilter === "All" ? posts : posts.filter(p => p.channel === channelFilter);
  const allVisibleSelected = visiblePosts.length > 0 && visiblePosts.every(p => selectedIds.has(getPostId(p)));

  function selectAll()  { setSelectedIds(new Set(visiblePosts.map(p => getPostId(p)))); }
  function selectNone() { setSelectedIds(new Set()); }

  async function submitBatch(action: "approve" | "reject", reason?: string) {
    if (selectedIds.size === 0 || !selectedRunId) return;
    setSubmitting(true);
    setSubmitResult(null);
    setError(null);

    const ids = Array.from(selectedIds);
    const body = action === "approve"
      ? { run_id: selectedRunId, approved_ids: ids, rejected_ids: [] }
      : { run_id: selectedRunId, approved_ids: [], rejected_ids: ids };

    try {
      const res = await fetch(`/api/admin/acp/s4/social/batch-review`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const newStatus = action === "approve" ? "approved" : "rejected";
      setPosts(prev => prev.map(p => selectedIds.has(getPostId(p)) ? { ...p, status: newStatus, hitl_status: newStatus } : p));
      setSubmitResult(`${ids.length} post${ids.length !== 1 ? "s" : ""} ${newStatus}.`);
      setSelectedIds(new Set());
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  const approvedCount = posts.filter(p => getHitlStatus(p) === "approved").length;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>

        {/* Header + run selector */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
              S4 — Social Review Grid
            </h1>
            <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
              Batch-review social content · approve or reject selected posts
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
              <Btn variant="ghost" size="sm" onClick={() => loadPosts(selectedRunId)}>
                <RefreshCw size={13} />
              </Btn>
            )}
            {posts.length > 0 && (
              <Btn variant="ghost" size="sm" onClick={() => exportApprovedCSV(posts)}>
                <Download size={13} /> CSV ({approvedCount})
              </Btn>
            )}
          </div>
        </div>

        {error && !loadingPosts && (
          <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "#FEE2E2", color: "#dc2626", fontSize: 13 }}>
            {error}
          </div>
        )}

        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <div style={{ fontSize: 44, marginBottom: 12 }}>📲</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: A.ink, marginBottom: 6 }}>Select a run to review social content</div>
            <div style={{ fontSize: 13, color: A.muted2 }}>Choose a run above to see generated social posts.</div>
          </div>
        )}

        {loadingPosts && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
            {[1, 2, 3, 4, 5, 6].map(i => (
              <div key={i} style={{ borderRadius: 12, overflow: "hidden", border: `1px solid ${A.line}`, background: "#fff", padding: 14 }}>
                <Skeleton height={160} />
              </div>
            ))}
          </div>
        )}

        {!loadingPosts && selectedRunId && posts.length === 0 && !error && (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <div style={{ fontSize: 44, marginBottom: 12 }}>📲</div>
            <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 500, color: A.ink, marginBottom: 8 }}>
              No social content generated for this run yet.
            </div>
            <div style={{ fontSize: 13, color: A.muted, maxWidth: 440, margin: "0 auto", lineHeight: 1.7 }}>
              Run the S4.2 Social pipeline to populate this view.
            </div>
          </div>
        )}

        {!loadingPosts && posts.length > 0 && (
          <>
            {/* Select All header + result feedback */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <button
                  onClick={allVisibleSelected ? selectNone : selectAll}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    fontSize: 12, color: A.muted, background: "none",
                    border: `1px solid ${A.line}`, borderRadius: 6, padding: "5px 10px",
                    cursor: "pointer",
                  }}
                >
                  {allVisibleSelected ? <CheckSquare size={13} /> : <Square size={13} />}
                  {allVisibleSelected ? "Deselect all" : "Select all"}
                </button>
                <span style={{ fontSize: 13, color: A.muted }}>
                  <span style={{ fontWeight: 600, color: selectedIds.size > 0 ? A.gold : A.muted }}>
                    {selectedIds.size}
                  </span>{" "}selected
                </span>
                {approvedCount > 0 && (
                  <span style={{ fontSize: 13, color: "#16a34a", fontWeight: 600 }}>
                    ✓ {approvedCount} approved
                  </span>
                )}
              </div>
              {submitResult && (
                <span style={{ fontSize: 13, color: "#16a34a", fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
                  <CheckCircle size={14} /> {submitResult}
                </span>
              )}
            </div>

            {/* Channel filter chips */}
            {channels.length > 1 && (
              <ChannelFilterChips
                channels={channels}
                active={channelFilter}
                onChange={setChannelFilter}
                counts={channelCounts}
              />
            )}

            {/* Grid */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 14,
              marginBottom: selectedIds.size > 0 ? 100 : 0,
            }}>
              {visiblePosts.map(post => (
                <SocialCard
                  key={getPostId(post)}
                  post={post}
                  selected={selectedIds.has(getPostId(post))}
                  onToggle={togglePost}
                />
              ))}
            </div>

            {/* Sticky batch bar (appears when ≥1 selected) */}
            {selectedIds.size > 0 && (
              <div style={{
                position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
                background: A.ink, color: "#fff", borderRadius: 14, padding: "14px 22px",
                display: "flex", alignItems: "center", gap: 14,
                boxShadow: "0 6px 30px rgba(0,0,0,0.28)", zIndex: 100,
              }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>
                  {selectedIds.size} post{selectedIds.size !== 1 ? "s" : ""} selected
                </span>
                <Btn size="sm" variant="primary" disabled={submitting}
                  onClick={() => submitBatch("approve")}
                  style={{ background: "#16a34a", border: "1px solid #16a34a" }}>
                  <CheckCircle size={13} /> Approve All
                </Btn>
                <Btn size="sm" variant="danger" disabled={submitting}
                  onClick={() => setShowRejectModal(true)}
                  style={{ background: "#991B1B", border: "1px solid #991B1B", color: "#fff" }}>
                  <XCircle size={13} /> Reject All
                </Btn>
                <button onClick={selectNone} style={{
                  background: "none", border: "none", color: "rgba(255,255,255,0.55)",
                  cursor: "pointer", fontSize: 12, padding: 0,
                }}>Clear</button>
              </div>
            )}
          </>
        )}
      </main>

      {/* Reject reason modal */}
      {showRejectModal && (
        <RejectModal
          count={selectedIds.size}
          onConfirm={reason => { setShowRejectModal(false); submitBatch("reject", reason); }}
          onCancel={() => setShowRejectModal(false)}
        />
      )}

      <style>{`
        @keyframes shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}
