"use client";
// app/admin/pipeline/s4-social/page.tsx — S4 Social Batch Review
// GET  /v1/acp/runs                           → runs list
// GET  /acp/social/batch-review?run_id={id}   → social_content rows
// POST /acp/social/batch-review               → {run_id, approved_ids, rejected_ids}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckSquare, Square, CheckCircle, XCircle, Share2 } from "lucide-react";
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

interface SocialPost {
  id: string;
  channel: string;
  formula?: string | null;
  mode?: string | null;
  goal?: string | null;
  content?: string | null;
  caption?: string | null;
  quality_score?: number | null;
  validation_status?: string | null;
  status?: string | null;
  hashtags?: string[] | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRunLabel(r: AcpRun): string {
  const date = r.started_at ? new Date(r.started_at).toLocaleString() : "";
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${r.status}${date ? " · " + date : ""}`;
}

function channelStyle(ch: string): { bg: string; color: string } {
  const c = ch.toLowerCase();
  if (c.includes("instagram"))   return { bg: "#FCE7F3", color: "#9D174D" };
  if (c.includes("facebook"))    return { bg: "#DBEAFE", color: "#1E40AF" };
  if (c.includes("linkedin"))    return { bg: "#EFF6FF", color: "#1E3A5F" };
  if (c.includes("tiktok"))      return { bg: "#FDF4FF", color: "#6B21A8" };
  if (c.includes("email"))       return { bg: "#F0FDF4", color: "#166534" };
  if (c.includes("newsletter"))  return { bg: "#ECFDF5", color: "#065F46" };
  if (c.includes("landing"))     return { bg: "#FEF9C3", color: "#854D0E" };
  if (c.includes("ads"))         return { bg: "#FEE2E2", color: "#991B1B" };
  if (c.includes("twitter") || c.includes("x")) return { bg: "#F0F9FF", color: "#0369A1" };
  return { bg: A.line2, color: A.muted };
}

function qualityColor(s: number | null): string {
  if (s == null) return A.muted2;
  if (s >= 8) return "#16a34a";
  if (s >= 6) return A.amber;
  return "#dc2626";
}

function qualityBg(s: number | null): string {
  if (s == null) return A.line2;
  if (s >= 8) return A.greenSoft;
  if (s >= 6) return A.amberSoft;
  return "#FEE2E2";
}

function validationBadge(v: string | null | undefined): { label: string; color: "green" | "amber" | "red" | "gray" } {
  if (!v) return { label: "—", color: "gray" };
  if (v === "pass" || v === "valid")   return { label: "Valid",   color: "green" };
  if (v === "warn" || v === "warning") return { label: "Warning", color: "amber" };
  if (v === "fail" || v === "invalid") return { label: "Invalid", color: "red"   };
  return { label: v, color: "gray" };
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
  const cs      = channelStyle(post.channel);
  const content = post.content || post.caption || "(No content)";
  const vb      = validationBadge(post.validation_status);

  return (
    <div
      onClick={() => onToggle(post.id)}
      style={{
        padding: "14px", borderRadius: 12, cursor: "pointer",
        border: `2px solid ${selected ? A.gold : A.line}`,
        background: selected ? A.goldTint : "#fff",
        transition: "border-color .15s, background .15s",
        display: "flex", flexDirection: "column", gap: 10,
        position: "relative",
      }}
    >
      {/* Checkbox */}
      <div style={{ position: "absolute", top: 12, right: 12, color: selected ? A.gold : A.muted2 }}>
        {selected ? <CheckSquare size={18} /> : <Square size={18} />}
      </div>

      {/* Channel + badges */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", paddingRight: 28, flexWrap: "wrap" }}>
        <span style={{
          padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700,
          background: cs.bg, color: cs.color, flexShrink: 0,
        }}>{post.channel}</span>

        {post.formula && (
          <span style={{
            padding: "2px 7px", borderRadius: 4, fontSize: 10.5, fontWeight: 600,
            background: "#EDE9FE", color: "#5B21B6",
          }}>{post.formula}</span>
        )}

        {post.mode && (
          <span style={{
            padding: "2px 7px", borderRadius: 4, fontSize: 10.5, fontWeight: 600,
            background: post.mode === "Auto" ? A.line2 : A.amberSoft,
            color: post.mode === "Auto" ? A.muted : "#92400E",
          }}>{post.mode}</span>
        )}

        {post.status && post.status !== "pending" && (
          <Badge color={post.status === "approved" ? "green" : post.status === "rejected" ? "red" : "gray"}>
            {post.status}
          </Badge>
        )}
      </div>

      {/* Quality + validation */}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {post.quality_score != null && (
          <div style={{
            padding: "2px 8px", borderRadius: 6, fontSize: 12, fontWeight: 700,
            fontFamily: mono, background: qualityBg(post.quality_score), color: qualityColor(post.quality_score),
          }}>
            {post.quality_score.toFixed(1)}
          </div>
        )}
        {post.validation_status && (
          <Badge color={vb.color}>{vb.label}</Badge>
        )}
        {post.goal && (
          <span style={{ fontSize: 11, color: A.muted2 }}>{post.goal}</span>
        )}
      </div>

      {/* Content preview */}
      <div style={{
        fontSize: 13, color: A.body, lineHeight: 1.6,
        display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
        overflow: "hidden",
      }}>
        {content}
      </div>

      {/* Hashtags */}
      {post.hashtags && post.hashtags.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {post.hashtags.slice(0, 4).map((tag, i) => (
            <span key={i} style={{
              fontSize: 10.5, color: "#1D4ED8", background: "#DBEAFE",
              padding: "1px 6px", borderRadius: 4,
            }}>#{tag.replace(/^#/, "")}</span>
          ))}
          {post.hashtags.length > 4 && (
            <span style={{ fontSize: 10.5, color: A.muted2 }}>+{post.hashtags.length - 4}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Channel Filter ────────────────────────────────────────────────────────────

function ChannelFilterChips({ channels, active, onChange, counts }: {
  channels: string[];
  active: string;
  onChange: (ch: string) => void;
  counts: Record<string, number>;
}) {
  return (
    <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 16 }}>
      {["All", ...channels].map(ch => {
        const isActive = active === ch;
        const cs = ch === "All" ? { bg: A.ink, color: "#fff" } : channelStyle(ch);
        const count = ch === "All" ? Object.values(counts).reduce((a, b) => a + b, 0) : counts[ch] ?? 0;
        return (
          <button
            key={ch}
            onClick={() => onChange(ch)}
            style={{
              padding: "5px 12px", borderRadius: 999, fontSize: 12, fontWeight: 600,
              border: `1.5px solid ${isActive ? cs.color : A.line}`,
              background: isActive ? cs.bg : "#fff",
              color: isActive ? (ch === "All" ? "#fff" : cs.color) : A.muted,
              cursor: "pointer", transition: "all .15s",
            }}
          >
            {ch} <span style={{ opacity: 0.7 }}>({count})</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function S4SocialPage() {
  const [runs, setRuns]                     = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId]   = useState("");
  const [posts, setPosts]                   = useState<SocialPost[]>([]);
  const [selectedIds, setSelectedIds]       = useState<Set<string>>(new Set());
  const [channelFilter, setChannelFilter]   = useState("All");
  const [loadingRuns, setLoadingRuns]       = useState(true);
  const [loadingPosts, setLoadingPosts]     = useState(false);
  const [submitting, setSubmitting]         = useState(false);
  const [submitResult, setSubmitResult]     = useState<string | null>(null);
  const [error, setError]                   = useState<string | null>(null);

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
    setChannelFilter("All");
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

  const channels = [...new Set(posts.map(p => p.channel))].sort();
  const channelCounts = channels.reduce<Record<string, number>>((acc, ch) => {
    acc[ch] = posts.filter(p => p.channel === ch).length;
    return acc;
  }, {});

  const visiblePosts = channelFilter === "All" ? posts : posts.filter(p => p.channel === channelFilter);
  const allVisibleSelected = visiblePosts.length > 0 && visiblePosts.every(p => selectedIds.has(p.id));

  function selectAll()  { setSelectedIds(new Set(visiblePosts.map(p => p.id))); }
  function selectNone() { setSelectedIds(new Set()); }

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

  const approvedCount = posts.filter(p => p.status === "approved").length;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>

        {/* Header + run selector */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
              S4 — Social Review
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
          </div>
        </div>

        {error && !loadingPosts && (
          <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "#FEE2E2", color: "#dc2626", fontSize: 13 }}>{error}</div>
        )}

        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "80px 0", color: A.muted2, fontSize: 14 }}>
            Select a run above to review social content posts.
          </div>
        )}

        {loadingPosts && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
            {[1, 2, 3, 4, 5, 6].map(i => (
              <div key={i} style={{ borderRadius: 12, overflow: "hidden", border: `1px solid ${A.line}`, background: "#fff", padding: 14 }}>
                <Skeleton height={140} />
              </div>
            ))}
          </div>
        )}

        {!loadingPosts && selectedRunId && posts.length === 0 && !error && (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <Share2 size={44} style={{ color: A.muted2, display: "block", margin: "0 auto 16px" }} />
            <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 500, color: A.ink, marginBottom: 8 }}>
              No social content yet
            </div>
            <div style={{ fontSize: 13, color: A.muted, maxWidth: 440, margin: "0 auto", lineHeight: 1.7 }}>
              Social content is generated in parallel with blog drafts after Gate 2 approval.
              Run S4.2 Social Engine to see posts here.
            </div>
          </div>
        )}

        {!loadingPosts && posts.length > 0 && (
          <>
            {/* Toolbar */}
            <Card style={{ marginBottom: 16, padding: "14px 18px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
                <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                  <div style={{ fontSize: 14, color: A.body }}>
                    <span style={{ fontWeight: 700, color: A.ink }}>{posts.length}</span>
                    <span style={{ color: A.muted }}> posts</span>
                    {approvedCount > 0 && (
                      <span style={{ color: "#16a34a", marginLeft: 10, fontWeight: 600 }}>✓ {approvedCount} approved</span>
                    )}
                  </div>
                  <span style={{ fontSize: 13, color: A.muted }}>
                    <span style={{ fontWeight: 600, color: A.gold }}>{selectedIds.size}</span> selected
                  </span>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button
                    onClick={allVisibleSelected ? selectNone : selectAll}
                    style={{
                      fontSize: 12, color: A.muted, background: "none",
                      border: `1px solid ${A.line}`, borderRadius: 6, padding: "5px 10px",
                      cursor: "pointer", display: "flex", alignItems: "center", gap: 5,
                    }}
                  >
                    {allVisibleSelected ? <CheckSquare size={13} /> : <Square size={13} />}
                    {allVisibleSelected ? "Deselect all" : "Select all"}
                  </button>
                  <Btn size="md" variant="danger"
                    disabled={selectedIds.size === 0 || submitting}
                    onClick={() => submitBatch("reject")}>
                    <XCircle size={14} /> Reject ({selectedIds.size})
                  </Btn>
                  <Btn size="md" variant="primary"
                    disabled={selectedIds.size === 0 || submitting}
                    onClick={() => submitBatch("approve")}
                    style={{ background: "#16a34a", border: "1px solid #16a34a" }}>
                    <CheckCircle size={14} /> Approve ({selectedIds.size})
                  </Btn>
                </div>
              </div>
              {submitResult && (
                <div style={{ marginTop: 10, fontSize: 13, color: "#16a34a", fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
                  <CheckCircle size={14} /> {submitResult}
                </div>
              )}
            </Card>

            {/* Channel filter */}
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
            }}>
              {visiblePosts.map(post => (
                <SocialCard
                  key={post.id}
                  post={post}
                  selected={selectedIds.has(post.id)}
                  onToggle={togglePost}
                />
              ))}
            </div>

            {/* Sticky batch bar */}
            {selectedIds.size > 0 && (
              <div style={{
                position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
                background: A.ink, color: "#fff", borderRadius: 12, padding: "12px 20px",
                display: "flex", alignItems: "center", gap: 14,
                boxShadow: "0 4px 20px rgba(0,0,0,0.25)", zIndex: 100,
              }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedIds.size} posts selected</span>
                <Btn size="sm" variant="primary" disabled={submitting}
                  onClick={() => submitBatch("approve")}
                  style={{ background: "#16a34a", border: "1px solid #16a34a" }}>
                  <CheckCircle size={13} /> Approve
                </Btn>
                <Btn size="sm" variant="danger" disabled={submitting}
                  onClick={() => submitBatch("reject")}
                  style={{ background: "#991B1B", border: "1px solid #991B1B", color: "#fff" }}>
                  <XCircle size={13} /> Reject
                </Btn>
                <button onClick={selectNone} style={{
                  background: "none", border: "none", color: "rgba(255,255,255,0.6)",
                  cursor: "pointer", fontSize: 12, padding: 0,
                }}>Clear</button>
              </div>
            )}
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
