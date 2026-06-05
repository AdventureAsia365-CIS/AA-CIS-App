"use client";
// app/admin/pipeline/s3/page.tsx — S3 Calendar + Ads + Gate 2
// GET /api/admin/acp/runs                  → runs list
// GET /api/admin/acp/runs/{run_id}/context → s3_content_calendar, s3_ads_plan, s3_funnel_mix
// POST /api/admin/acp/gate/s3/approve      → {run_id}
// POST /api/admin/acp/gate/s3/reject       → {run_id, reason}

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, CheckCircle, XCircle, ChevronDown, ChevronUp, Copy } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, serif, sans, mono, Card, SLabel, Badge, Btn, TabBar } from "../../_components/adminUi";

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

interface CalendarPost {
  format?: string;
  word_count?: number;
  title_topic?: string;
  brief_outline?: string[];
  search_intent?: string;
  lead_magnet_cta?: string;
  primary_keyword?: string;
  secondary_keywords?: string[];
}

interface CalendarWeek {
  week: number;
  posts: CalendarPost[];
}

interface CalendarPlan {
  strategy?: string;
  calendar_weeks?: CalendarWeek[];
  funnel_mix?: { tofu?: number; mofu?: number; bofu?: number };
}

interface AdGroup {
  name?: string;
  keywords?: string[];
  headlines?: string[];
  descriptions?: string[];
}

interface AdCampaign {
  campaign_name?: string;
  objective?: string;
  ad_groups?: AdGroup[];
}

interface RunContext {
  run_id: string;
  s3_content_calendar: CalendarPlan | string | null;
  s3_ads_plan: AdCampaign[] | { campaigns?: AdCampaign[] } | string | null;
  s3_funnel_mix?: { tofu?: number; mofu?: number; bofu?: number } | null;
  gate2_status?: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseJson<T>(v: T | string | null | undefined): T | null {
  if (v == null) return null;
  if (typeof v === "string") { try { return JSON.parse(v) as T; } catch { return null; } }
  return v;
}

function fmtRunLabel(r: AcpRun): string {
  const date = r.started_at ? new Date(r.started_at).toLocaleString() : "";
  return `${r.run_id.slice(0, 8)} · ${r.country || "—"} · ${r.status}${date ? " · " + date : ""}`;
}

function gateStatusColor(s: string | null | undefined): "green" | "amber" | "red" | "gray" {
  if (s === "approved" || s === "auto_approved") return "green";
  if (s === "pending") return "amber";
  if (s === "rejected") return "red";
  return "gray";
}

function formatBadgeStyle(fmt: string | undefined): { bg: string; color: string } {
  switch ((fmt || "").toLowerCase()) {
    case "guide":       return { bg: "#DBEAFE", color: "#1E40AF" };
    case "how-to":
    case "howto":       return { bg: "#EDE9FE", color: "#5B21B6" };
    case "listicle":    return { bg: A.amberSoft, color: "#92400E" };
    case "comparison":  return { bg: "#CCFBF1", color: "#0F766E" };
    case "story":       return { bg: "#FCE7F3", color: "#9D174D" };
    default:            return { bg: A.line2, color: A.muted };
  }
}

function intentBadgeStyle(intent: string | undefined): { bg: string; color: string } {
  switch ((intent || "").toLowerCase()) {
    case "informational": return { bg: "#E0F2FE", color: "#0369A1" };
    case "commercial":    return { bg: "#EDE9FE", color: "#5B21B6" };
    case "transactional": return { bg: "#D1FAE5", color: "#065F46" };
    default:              return { bg: A.line2, color: A.muted };
  }
}

function objectiveBadgeStyle(obj: string | undefined): { bg: string; color: string } {
  switch ((obj || "").toLowerCase()) {
    case "awareness":      return { bg: "#DBEAFE", color: "#1E40AF" };
    case "consideration":  return { bg: A.amberSoft, color: "#92400E" };
    case "conversion":     return { bg: "#D1FAE5", color: "#065F46" };
    default:               return { bg: A.line2, color: A.muted };
  }
}

function extractCampaigns(raw: AdCampaign[] | { campaigns?: AdCampaign[] } | string | null): AdCampaign[] {
  const parsed = parseJson<AdCampaign[] | { campaigns?: AdCampaign[] }>(raw as AdCampaign[] | string | null);
  if (!parsed) return [];
  if (Array.isArray(parsed)) return parsed;
  if (parsed.campaigns) return parsed.campaigns;
  return [];
}

function exportCalendarCSV(weeks: CalendarWeek[]) {
  const rows: string[] = [["Week", "Format", "Title/Topic", "Primary Keyword", "Search Intent", "Word Count", "CTA"].join(",")];
  for (const w of weeks) {
    for (const p of w.posts || []) {
      rows.push([
        w.week,
        p.format || "",
        JSON.stringify(p.title_topic || ""),
        JSON.stringify(p.primary_keyword || ""),
        p.search_intent || "",
        p.word_count ?? "",
        JSON.stringify(p.lead_magnet_cta || ""),
      ].join(","));
    }
  }
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a"); a.href = url; a.download = "content-calendar.csv"; a.click();
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

// ── Funnel Mix ────────────────────────────────────────────────────────────────

function FunnelMix({ mix }: { mix: { tofu?: number; mofu?: number; bofu?: number } | undefined }) {
  if (!mix) return null;
  const parts = [
    { label: "TOFU", pct: mix.tofu ?? 0, color: "#3B82F6", bg: "#DBEAFE" },
    { label: "MOFU", pct: mix.mofu ?? 0, color: A.gold,   bg: A.amberSoft },
    { label: "BOFU", pct: mix.bofu ?? 0, color: "#16a34a", bg: A.greenSoft },
  ];
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
      {parts.map(p => (
        <div key={p.label} style={{
          padding: "6px 14px", borderRadius: 8, background: p.bg, textAlign: "center" as const,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: p.color, letterSpacing: "0.08em" }}>{p.label}</div>
          <div style={{ fontFamily: mono, fontSize: 18, fontWeight: 700, color: p.color }}>{p.pct}%</div>
        </div>
      ))}
    </div>
  );
}

// ── Calendar Tab ──────────────────────────────────────────────────────────────

function CalendarTab({ cal }: { cal: CalendarPlan }) {
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const weeks = cal.calendar_weeks || [];

  const allPosts = weeks.flatMap(w => w.posts.map(p => ({ ...p, week: w.week })));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {cal.strategy && (
        <Card style={{ background: A.bg }}>
          <SLabel>Strategy</SLabel>
          <div style={{ fontSize: 13, color: A.body, lineHeight: 1.8 }}>{cal.strategy}</div>
        </Card>
      )}

      <FunnelMix mix={cal.funnel_mix} />

      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "16px 20px 12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <SLabel style={{ marginBottom: 0 }}>Content Calendar ({allPosts.length} posts)</SLabel>
          {allPosts.length > 0 && (
            <Btn variant="ghost" size="sm" onClick={() => exportCalendarCSV(weeks)}>
              Export CSV
            </Btn>
          )}
        </div>
        {allPosts.length === 0 ? (
          <div style={{ padding: "24px 20px", fontSize: 13, color: A.muted2 }}>No calendar entries available.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: A.bg }}>
                  {["Week", "Format", "Primary Keyword", "Search Intent", "Words", "CTA", ""].map(h => (
                    <th key={h} style={{
                      padding: "9px 14px", textAlign: "left", fontSize: 10.5, fontWeight: 600,
                      letterSpacing: "0.1em", textTransform: "uppercase" as const,
                      color: A.muted, borderBottom: `1px solid ${A.line}`,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {allPosts.map((p, i) => {
                  const key = `${p.week}-${i}`;
                  const expanded = expandedRow === key;
                  const fs = formatBadgeStyle(p.format);
                  const is = intentBadgeStyle(p.search_intent);
                  return (
                    <React.Fragment key={key}>
                      <tr style={{ background: i % 2 === 0 ? "#fff" : A.bg }}>
                        <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, fontFamily: mono, fontWeight: 600, color: A.ink, whiteSpace: "nowrap" as const }}>
                          W{p.week}
                        </td>
                        <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}` }}>
                          {p.format ? (
                            <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600, background: fs.bg, color: fs.color }}>
                              {p.format}
                            </span>
                          ) : "—"}
                        </td>
                        <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, color: A.ink, maxWidth: 200 }}>
                          <div style={{ fontWeight: 500 }}>{p.primary_keyword || "—"}</div>
                          {p.title_topic && <div style={{ fontSize: 11, color: A.muted, marginTop: 2 }}>{p.title_topic}</div>}
                        </td>
                        <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}` }}>
                          {p.search_intent ? (
                            <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600, background: is.bg, color: is.color }}>
                              {p.search_intent}
                            </span>
                          ) : "—"}
                        </td>
                        <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, fontFamily: mono, color: A.muted }}>
                          {p.word_count ?? "—"}
                        </td>
                        <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, fontSize: 12, color: A.muted, maxWidth: 160 }}>
                          {p.lead_magnet_cta || "—"}
                        </td>
                        <td style={{ padding: "9px 14px", borderBottom: `1px solid ${A.line}`, textAlign: "center" as const }}>
                          {(p.brief_outline?.length || p.secondary_keywords?.length) ? (
                            <button onClick={() => setExpandedRow(expanded ? null : key)}
                              style={{ background: "none", border: "none", cursor: "pointer", color: A.muted, display: "flex", alignItems: "center" }}>
                              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                            </button>
                          ) : null}
                        </td>
                      </tr>
                      {expanded && (
                        <tr style={{ background: "#FAFAF8" }}>
                          <td colSpan={7} style={{ padding: "12px 20px", borderBottom: `1px solid ${A.line}` }}>
                            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                              {p.brief_outline && p.brief_outline.length > 0 && (
                                <div>
                                  <div style={{ fontSize: 10.5, fontWeight: 600, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em", marginBottom: 6 }}>Brief Outline</div>
                                  <ul style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 3 }}>
                                    {p.brief_outline.map((b, j) => (
                                      <li key={j} style={{ fontSize: 12, color: A.body }}>{b}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {p.secondary_keywords && p.secondary_keywords.length > 0 && (
                                <div>
                                  <div style={{ fontSize: 10.5, fontWeight: 600, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em", marginBottom: 6 }}>Secondary Keywords</div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                                    {p.secondary_keywords.map((kw, j) => (
                                      <span key={j} style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, background: A.bg, color: A.muted, border: `1px solid ${A.line}` }}>{kw}</span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ── Ads Tab ───────────────────────────────────────────────────────────────────

function AdsTab({ campaigns }: { campaigns: AdCampaign[] }) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  if (!campaigns.length) {
    return <div style={{ fontSize: 13, color: A.muted2, padding: "24px 0" }}>No ads campaigns available.</div>;
  }

  function toggleGroup(key: string) {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  function copyText(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {campaigns.map((campaign, ci) => {
        const os = objectiveBadgeStyle(campaign.objective);
        return (
          <Card key={ci} style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "14px 20px", display: "flex", alignItems: "center", gap: 10, borderBottom: `1px solid ${A.line}`, background: A.bg }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: A.ink }}>{campaign.campaign_name || `Campaign ${ci + 1}`}</div>
              </div>
              {campaign.objective && (
                <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600, background: os.bg, color: os.color, textTransform: "capitalize" as const }}>
                  {campaign.objective}
                </span>
              )}
            </div>
            <div style={{ padding: "12px 20px", display: "flex", flexDirection: "column", gap: 8 }}>
              {(campaign.ad_groups || []).map((group, gi) => {
                const gkey = `${ci}-${gi}`;
                const expanded = expandedGroups.has(gkey);
                return (
                  <div key={gi} style={{ border: `1px solid ${A.line}`, borderRadius: 8, overflow: "hidden" }}>
                    <button
                      onClick={() => toggleGroup(gkey)}
                      style={{
                        width: "100%", padding: "10px 14px", background: expanded ? A.bg : "#fff",
                        border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between",
                        fontFamily: sans, fontSize: 13, fontWeight: 600, color: A.ink,
                      }}
                    >
                      <span>{group.name || `Ad Group ${gi + 1}`}</span>
                      {expanded ? <ChevronUp size={13} color={A.muted} /> : <ChevronDown size={13} color={A.muted} />}
                    </button>
                    {expanded && (
                      <div style={{ padding: "12px 14px", borderTop: `1px solid ${A.line}`, display: "flex", flexDirection: "column", gap: 14 }}>
                        {group.keywords && group.keywords.length > 0 && (
                          <div>
                            <div style={{ fontSize: 10.5, fontWeight: 600, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em", marginBottom: 6 }}>Keywords</div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                              {group.keywords.map((kw, ki) => (
                                <span key={ki} style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, background: "#EFF6FF", color: "#1E40AF", border: "1px solid #BFDBFE" }}>{kw}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {group.headlines && group.headlines.length > 0 && (
                          <div>
                            <div style={{ fontSize: 10.5, fontWeight: 600, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em", marginBottom: 6 }}>Headlines</div>
                            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                              {group.headlines.map((hl, hi) => (
                                <div key={hi} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 10px", borderRadius: 6, background: "#F9FAFB", border: `1px solid ${A.line}` }}>
                                  <span style={{ fontSize: 13, color: A.ink }}>{hl}</span>
                                  <button onClick={() => copyText(hl)} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, display: "flex", flexShrink: 0 }}>
                                    <Copy size={12} />
                                  </button>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        {group.descriptions && group.descriptions.length > 0 && (
                          <div>
                            <div style={{ fontSize: 10.5, fontWeight: 600, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em", marginBottom: 6 }}>Descriptions</div>
                            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                              {group.descriptions.map((desc, di) => (
                                <div key={di} style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, padding: "6px 10px", borderRadius: 6, background: "#F9FAFB", border: `1px solid ${A.line}` }}>
                                  <span style={{ fontSize: 12, color: A.body, lineHeight: 1.6 }}>{desc}</span>
                                  <button onClick={() => copyText(desc)} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, display: "flex", flexShrink: 0, marginTop: 2 }}>
                                    <Copy size={12} />
                                  </button>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

// ── Gate 2 Tab ────────────────────────────────────────────────────────────────

function Gate2Tab({ runId, status, onAction }: {
  runId: string;
  status: string | null | undefined;
  onAction: () => void;
}) {
  const [showReject, setShowReject] = useState(false);
  const [reason, setReason]         = useState("");
  const [busy, setBusy]             = useState(false);
  const [err, setErr]               = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  async function approve() {
    setBusy(true); setErr(null);
    try {
      const res = await fetch(`/api/admin/acp/gate/s3/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onAction();
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); setShowConfirm(false); }
  }

  async function reject() {
    if (!reason.trim()) return;
    setBusy(true); setErr(null);
    try {
      const res = await fetch(`/api/admin/acp/gate/s3/reject`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, reason: reason.trim() }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onAction();
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  }

  const isPending  = status === "pending" || status === null || status === undefined;
  const isApproved = status === "approved" || status === "auto_approved";
  const isRejected = status === "rejected";

  return (
    <Card>
      <SLabel>Gate 2 — Content Strategy Approval</SLabel>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <Badge color={gateStatusColor(status)}>
          {status === "auto_approved" ? "Auto-approved" : status || "Pending"}
        </Badge>
        {isPending && (
          <span style={{ fontSize: 12, color: A.amber }}>⚠️ Awaiting Ms. Thu approval — SLA: 24h</span>
        )}
      </div>

      {isPending && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ fontSize: 13, color: A.muted }}>
            Review the calendar and ads plan, then approve or reject to proceed to S4.
          </div>

          {showConfirm ? (
            <div style={{
              padding: "14px 16px", borderRadius: 8, background: A.greenSoft,
              border: "1px solid #86EFAC", display: "flex", flexDirection: "column", gap: 10,
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#166534" }}>
                Confirm Gate 2 approval? This will unlock S4 content generation.
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <Btn variant="primary" size="md" disabled={busy} onClick={approve}
                  style={{ background: "#16a34a", border: "1px solid #16a34a" }}>
                  <CheckCircle size={14} /> Yes, Approve
                </Btn>
                <Btn variant="ghost" size="md" onClick={() => setShowConfirm(false)}>Cancel</Btn>
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", gap: 8 }}>
              <Btn variant="primary" size="md" disabled={busy} onClick={() => setShowConfirm(true)}
                style={{ background: "#16a34a", border: "1px solid #16a34a" }}>
                <CheckCircle size={14} /> Approve Gate 2
              </Btn>
              <Btn variant="danger" size="md" disabled={busy}
                onClick={() => setShowReject(v => !v)}>
                <XCircle size={14} /> Reject
              </Btn>
            </div>
          )}

          {showReject && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <textarea
                placeholder="Rejection reason (required)…"
                value={reason}
                onChange={e => setReason(e.target.value)}
                rows={3}
                style={{
                  width: "100%", padding: "9px 12px", borderRadius: 8,
                  border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans,
                  resize: "vertical", outline: "none", boxSizing: "border-box",
                }}
              />
              <Btn variant="danger" size="sm" disabled={busy || !reason.trim()} onClick={reject}>
                Confirm Rejection
              </Btn>
            </div>
          )}
          {err && <div style={{ color: "#dc2626", fontSize: 12 }}>{err}</div>}
        </div>
      )}

      {isApproved && (
        <div style={{ fontSize: 13, color: "#166534" }}>
          ✅ Gate 2 approved — S4 pipeline may proceed.
        </div>
      )}
      {isRejected && (
        <div style={{ fontSize: 13, color: "#991B1B" }}>
          ❌ Gate 2 rejected — run cannot proceed to S4.
        </div>
      )}
    </Card>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function S3Page() {
  const [runs, setRuns]                   = useState<AcpRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [context, setContext]             = useState<RunContext | null>(null);
  const [loadingRuns, setLoadingRuns]     = useState(true);
  const [loadingData, setLoadingData]     = useState(false);
  const [error, setError]                 = useState<string | null>(null);
  const [activeTab, setActiveTab]         = useState("calendar");

  useEffect(() => {
    fetch(`/api/admin/acp/runs`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setRuns(Array.isArray(d) ? d : (d.data || d.runs || [])))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingRuns(false));
  }, []);

  const loadData = useCallback((runId: string) => {
    if (!runId) return;
    setLoadingData(true);
    setContext(null);
    setError(null);
    fetch(`/api/admin/acp/runs/${runId}/context`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => setContext(d))
      .catch(e => setError(String(e)))
      .finally(() => setLoadingData(false));
  }, []);

  function onRunChange(runId: string) {
    setSelectedRunId(runId);
    loadData(runId);
  }

  const cal       = parseJson<CalendarPlan>(context?.s3_content_calendar ?? null);
  const campaigns = extractCampaigns(context?.s3_ads_plan ?? null);
  const gateStatus = context?.gate2_status;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>

        {/* Header + run selector */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0, letterSpacing: "-0.02em" }}>
              S3 — Content Strategy
            </h1>
            <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
              Content calendar · ads campaigns · Gate 2 review
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
              <Btn variant="ghost" size="sm" onClick={() => loadData(selectedRunId)}>
                <RefreshCw size={13} />
              </Btn>
            )}
          </div>
        </div>

        {error && (
          <div style={{ marginBottom: 16, padding: "10px 14px", borderRadius: 8, background: "#FEE2E2", color: "#dc2626", fontSize: 13 }}>{error}</div>
        )}

        {!selectedRunId && !loadingRuns && (
          <div style={{ textAlign: "center", padding: "80px 0", color: A.muted2, fontSize: 14 }}>
            Select a run above to view its S3 content strategy.
          </div>
        )}

        {loadingData && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Card><Skeleton height={60} /></Card>
            <Card><Skeleton height={300} /></Card>
          </div>
        )}

        {context && !loadingData && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <TabBar
              tabs={[
                { key: "calendar", label: "📅 Content Calendar" },
                { key: "ads",      label: "📢 Ads Campaigns" },
                { key: "gate2",    label: "🚦 Gate 2" },
              ]}
              active={activeTab}
              onChange={setActiveTab}
            />

            {activeTab === "calendar" && (
              cal ? <CalendarTab cal={cal} /> : (
                <div style={{ fontSize: 13, color: A.muted2, padding: "24px 0" }}>No content calendar data for this run.</div>
              )
            )}

            {activeTab === "ads" && (
              <AdsTab campaigns={campaigns} />
            )}

            {activeTab === "gate2" && (
              <Gate2Tab
                runId={context.run_id}
                status={gateStatus}
                onAction={() => loadData(context.run_id)}
              />
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
