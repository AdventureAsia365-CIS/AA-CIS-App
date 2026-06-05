"use client";
// app/admin/pipeline/s4-social/page.tsx — S4 Social Batch Review
// GET  /v1/acp/runs                             → runs list
// GET  /acp/social/batch-review?run_id={id}     → social_content rows
// POST /acp/social/batch-review                  → {run_id, approved_ids, rejected_ids}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckSquare, Square, CheckCircle, XCircle } from "lucide-react";
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

interface SocialPost {
  id: string;
  channel: string;
  goal: string | null;
  content: string | null;
  quality_score: number | null;
  status: string | null;
  caption?: string | null;
  hashtags?: string[] | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRunLabel(r: AcpRun): string {
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${new Date(r.created_at).toLocaleString()}`;
}

function channelStyle(channel: string): { bg: string; color: string } {
  const c = channel.toLowerCase();
  if (c.includes("instagram")) return { bg: "#FCE7F3", color: "#9D174D" };
  if (c.includes("facebook"))  return { bg: "#DBEAFE", color: "#1E40AF" };
  if (c.includes("linkedin"))  return { bg: "#EFF6FF", color: "#1E3A5F" };
  if (c.includes("twitter") || c.includes("x")) return { bg: "#F0F9FF", color: "#0369A1" };
  if (c.includes("tiktok"))    return { bg: "#FDF4FF", color: "#6B21A8" };
  if (c.includes("youtube"))   return { bg: "#FEE2E2", color: "#991B1B" };
  return { bg: A.line2, color: A.muted };
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

// ── Social Card ───────────────────────────────────────────────────────────────

function SocialCard({ post, selected, onToggle }: {
  post: SocialPost;
  selected: boolean;
  onToggle: (id: string) => void;
}) {
  const ch = channelStyle(post.channel);
  const displayContent = post.content || post.caption || "(No content)";

  return (
    <div
      onClick={() => onToggle(post.id)}
      style={{
        padding: "16px", borderRadius: 12,
        border: `2px solid ${selected ? A.gold : A.line}`,
        background: selected ? A.goldTint : "#fff",
        cursor: "pointer", transition: "all .15s",
        display: "flex", flexDirection: "column", gap: 10,
        position: "relative",
      }}
    >
      {/* Select indicator */}
      <div style={{ position: "absolute", top: 12, right: 12, color: selected ? A.gold : A.muted2 }}>
        {selected ? <CheckSquare size={18} /> : <Square size={18} />}
      </div>

      {/* Header */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", paddingRight: 28 }}>
        <span style={{
          padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700,
          background: ch.bg, color: ch.color, flexShrink: 0,
        }}>{post.channel}</span>
        {post.goal && (
          <span style={{
            padding: "2px 8px", borderRadius: 4, fontSize: 10.5, fontWeight: 600,
            background: A.amberSoft, color: A.amber,
          }}>{post.goal}</span>
        )}
        {post.status && post.status !== "pending" && (
          <Badge color={post.status === "approved" ? "green" : post.status === "rejected" ? "red" : "gray"}>
            {post.status}
          </Badge>
        )}
      </div>

      {/* Quality score */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          padding: "2px 8px", borderRadius: 6, fontSize: 12, fontWeight: 700,
          fontFamily: mono, background: qualityBg(post.quality_score),
          color: qualityColor(post.quality_score),
        }}>
          {post.quality_score != null ? post.quality_score.toFixed(1) : "—"}
        </div>
        <span style={{ fontSize: 11, color: A.muted2 }}>quality score</span>
      </div>

      {/* Content preview */}
      <div style={{
        fontSize: 13, color: A.body, lineHeight: 1.6,
        display: "-webkit-box", WebkitLineClamp: 4, WebkitBoxOrient: "vertical",
        overflow: "hidden",
      }}>
        {displayContent}
      </div>

      {/* Hashtags */}
      {post.hashtags && post.hashtags.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {post.hashtags.slice(0, 5).map((tag, i) => (
            <span key={i} style={{
              fontSize: 10.5, color: "#1D4ED8", background: "#DBEAFE",
              padding: "1px 6px", borderRadius: 4,
            }}>#{tag.replace(/^#/, "")}</span>
          ))}
          {post.hashtags.length > 5 && (
            <span style={{ fontSize: 10.5, color: A.muted2 }}>+{post.hashtags.length - 5}</span>
          )}
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

export default function S4SocialPage() {
  const [runs, setRuns]               = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [posts, setPosts]             = useState<SocialPost[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingPosts, setLoadingPosts] = useState(false);
  const [submitting, setSubmitting]   = useState(false);
  const [submitResult, setSubmitResult] = useState<string | null>(null);
  const [error, setError]             = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/v1/acp/runs`, { headers: authHeaders() })
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
    setSubmitResult(null);
    setError(null);
    fetch(`${API_URL}/acp/social/batch-review?run_id=${runId}`, { headers: authHeaders() })
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

  function selectAll()   { setSelectedIds(new Set(posts.map(p => p.id))); }
  function selectNone()  { setSelectedIds(new Set()); }

  async function submitBatch(action: "approve" | "reject") {
    if (selectedIds.size === 0 || !selectedRunId) return;
    setSubmitting(true);
    setSubmitResult(null);
    setError(null);

    const ids = Array.from(selectedIds);
    const body = action === "approve"
      ? { run_id: selectedRunId, approved_ids: ids, rejected_ids: [] }
      : { run_id: selectedRunId, approved_ids: [], rejected_ids: ids };

    try {
      const res = await fetch(`${API_URL}/acp/social/batch-review`, {
        method: "POST", headers: authHeaders(), body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const newStatus = action === "approve" ? "approved" : "rejected";
      setPosts(prev => prev.map(p => selectedIds.has(p.id) ? { ...p, status: newStatus } : p));
      setSubmitResult(`${ids.length} post${ids.length !== 1 ? "s" : ""} ${newStatus}.`);
      setSelectedIds(new Set());
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  const pendingPosts = posts.filter(p => !p.status || p.status === "pending");
  const approvedCount = posts.filter(p => p.status === "approved").length;
  const allSelected = posts.length > 0 && selectedIds.size === posts.length;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
            S4 Social Review
          </h1>
          <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
            Batch-review social content · approve or reject selected posts
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
                <option value="">— Select a run to review social posts —</option>
                {runs.map(r => (
                  <option key={r.run_id} value={r.run_id}>{fmtRunLabel(r)}</option>
                ))}
              </select>
              {selectedRunId && (
                <Btn variant="ghost" size="sm" onClick={() => loadPosts(selectedRunId)}>
                  <RefreshCw size={13} /> Refresh
                </Btn>
              )}
            </div>
          )}
          {error && !loadingPosts && !submitting && (
            <div style={{ marginTop: 10, color: A.red, fontSize: 13 }}>{error}</div>
          )}
        </Card>

        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "60px 0", color: A.muted2, fontSize: 14 }}>
            Select a run above to review social content posts.
          </div>
        )}

        {loadingPosts && <LoadingScreen msg="Loading social content…" />}

        {!loadingPosts && selectedRunId && posts.length === 0 && !error && (
          <div style={{ textAlign: "center", padding: "60px 0", color: A.muted2, fontSize: 14 }}>
            No social posts found for this run.
          </div>
        )}

        {!loadingPosts && posts.length > 0 && (
          <>
            {/* Toolbar */}
            <Card style={{ marginBottom: 20, padding: "14px 18px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
                {/* Stats */}
                <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                  <div style={{ fontSize: 14, color: A.body }}>
                    <span style={{ fontWeight: 700, color: A.ink }}>{posts.length}</span>
                    <span style={{ color: A.muted }}> posts</span>
                    {approvedCount > 0 && (
                      <span style={{ color: A.green, marginLeft: 10, fontWeight: 600 }}>✓ {approvedCount} approved</span>
                    )}
                  </div>
                  <div style={{ fontSize: 13, color: A.muted }}>
                    <span style={{ fontWeight: 600, color: A.gold }}>{selectedIds.size}</span> selected
                  </div>
                </div>

                {/* Actions */}
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button
                    onClick={allSelected ? selectNone : selectAll}
                    style={{
                      fontSize: 12, color: A.muted, background: "none",
                      border: `1px solid ${A.line}`, borderRadius: 6, padding: "5px 10px",
                      cursor: "pointer", display: "flex", alignItems: "center", gap: 5,
                    }}
                  >
                    {allSelected ? <CheckSquare size={13} /> : <Square size={13} />}
                    {allSelected ? "Deselect all" : "Select all"}
                  </button>
                  <Btn
                    size="md" variant="danger"
                    disabled={selectedIds.size === 0 || submitting}
                    onClick={() => submitBatch("reject")}
                  >
                    <XCircle size={14} />
                    Reject Selected ({selectedIds.size})
                  </Btn>
                  <Btn
                    size="md" variant="primary"
                    disabled={selectedIds.size === 0 || submitting}
                    onClick={() => submitBatch("approve")}
                    style={{ background: "#16A34A", border: "1px solid #16A34A" }}
                  >
                    <CheckCircle size={14} />
                    Approve Selected ({selectedIds.size})
                  </Btn>
                </div>
              </div>

              {submitResult && (
                <div style={{ marginTop: 10, fontSize: 13, color: A.green, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
                  <CheckCircle size={14} /> {submitResult}
                </div>
              )}
              {error && submitting === false && submitResult === null && (
                <div style={{ marginTop: 10, fontSize: 13, color: A.red }}>{error}</div>
              )}
            </Card>

            {/* Channel filter strip */}
            <ChannelFilter posts={posts} selectedIds={selectedIds} />

            {/* Grid */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 14, marginTop: 16,
            }}>
              {posts.map(post => (
                <SocialCard
                  key={post.id}
                  post={post}
                  selected={selectedIds.has(post.id)}
                  onToggle={togglePost}
                />
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

// ── Channel filter ────────────────────────────────────────────────────────────

function ChannelFilter({ posts, selectedIds }: { posts: SocialPost[]; selectedIds: Set<string> }) {
  const channels = [...new Set(posts.map(p => p.channel))];
  if (channels.length <= 1) return null;

  const counts = channels.reduce<Record<string, number>>((acc, ch) => {
    acc[ch] = posts.filter(p => p.channel === ch).length;
    return acc;
  }, {});

  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {channels.map(ch => {
        const style = channelStyle(ch);
        return (
          <span key={ch} style={{
            padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 600,
            background: style.bg, color: style.color, cursor: "default",
          }}>
            {ch} <span style={{ opacity: 0.7 }}>({counts[ch]})</span>
          </span>
        );
      })}
    </div>
  );

  function channelStyle(channel: string): { bg: string; color: string } {
    const c = channel.toLowerCase();
    if (c.includes("instagram")) return { bg: "#FCE7F3", color: "#9D174D" };
    if (c.includes("facebook"))  return { bg: "#DBEAFE", color: "#1E40AF" };
    if (c.includes("linkedin"))  return { bg: "#EFF6FF", color: "#1E3A5F" };
    if (c.includes("twitter") || c.includes("x")) return { bg: "#F0F9FF", color: "#0369A1" };
    if (c.includes("tiktok"))    return { bg: "#FDF4FF", color: "#6B21A8" };
    return { bg: A.line2, color: A.muted };
  }
}
