"use client";
// app/admin/s1-rewrite/page.tsx — Admin S1 Rewrite v2
// GET  /api/admin/tours                   → all tours with rewrite_count
// GET  /api/admin/tours/{id}/history      → rewrite history
// GET  /api/admin/tours/{id}/detail       → raw + generated + published
// POST /api/admin/run-tour                → trigger rewrite

import React, { useState, useEffect, useCallback, useRef } from "react";
import { Play, RefreshCw, ArrowRight, Search, CheckCircle, XCircle, Loader2, X, ChevronRight } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Badge, Btn, LoadingScreen,
  TH, TD,
} from "../_components/adminUi";

const TENANT_ID = "00000000-0000-0000-0000-000000000001";

function stripUuidPrefix(filename: string | null | undefined): string {
  if (!filename) return "—";
  return filename.replace(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_/i, "");
}

function relativeTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "—";
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60) return "Just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(isoStr).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function scoreColor(s: number | null | undefined): string {
  if (s == null) return A.muted2;
  if (s >= 9) return A.green;
  if (s >= 7) return A.amber;
  return A.red;
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface Tour {
  tour_id: string;
  src_name: string;
  country: string | null;
  pipeline_status: string;
  ingest_at: string | null;
  source_id: string | null;
  batch_id: string | null;
  filename: string | null;
  rewrite_count: number;
  last_rewritten_at: string | null;
}

interface BrandVersion {
  version: number;
  is_active: boolean;
  updated_at: string | null;
}

type TourRunStatus = "idle" | "running" | "done" | "failed";

interface RunResult {
  tour_id: string;
  status: string;
  quality_score: number | null;
  version_id: string | null;
  error?: string;
}

interface HistoryRow {
  id: string;
  version_num: number;
  created_at: string | null;
  status: string;
  model_editorial: string | null;
  score_overall: number | null;
  score_brand: number | null;
  score_seo: number | null;
  score_structure: number | null;
  llm_model: string | null;
  cost_usd: number | null;
}

interface TourDetail {
  raw: {
    tour_id: string;
    src_name: string;
    src_subtitle: string | null;
    src_summary: string | null;
    src_highlights: string[] | string | null;
    src_itineraries: string | null;
    country: string | null;
    duration: string | null;
    price_raw: string | null;
    group_size: string | null;
    pipeline_status: string;
    ingest_at: string | null;
  };
  generated: {
    id: string;
    version_num: number;
    status: string;
    aa_name: string;
    aa_subtitle: string | null;
    aa_summary: string | null;
    aa_highlights: string[] | null;
    aa_itineraries: string | null;
    seo_title: string | null;
    seo_meta: string | null;
    seo_keywords_used: string[] | null;
    score_overall: number | null;
    score_brand: number | null;
    score_seo: number | null;
    score_structure: number | null;
    model_editorial: string | null;
  } | null;
  published: {
    aa_name: string;
    quality_score: number | null;
    published_at: string | null;
  } | null;
}

// ── Status badge ──────────────────────────────────────────────────────────────

function PipelineStatusBadge({ tour, runStatus, result }: {
  tour: Tour;
  runStatus: TourRunStatus;
  result?: RunResult;
}) {
  if (runStatus === "running") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: A.amber }}>
        <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} /> Processing…
      </span>
    );
  }
  if (runStatus === "done") {
    const score = result?.quality_score;
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: A.green }}>
        <CheckCircle size={12} /> Done{score != null ? ` · ${score.toFixed(1)}` : ""}
      </span>
    );
  }
  if (runStatus === "failed") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: A.red }} title={result?.error}>
        <XCircle size={12} /> Failed
      </span>
    );
  }

  const { pipeline_status, rewrite_count } = tour;
  if (pipeline_status === "processing") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: A.amber }}>
        <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} /> Processing
      </span>
    );
  }
  if (pipeline_status === "published") {
    return <Badge color="green">Published</Badge>;
  }
  if (pipeline_status === "ingested" && rewrite_count > 0) {
    return <Badge color="green">Ready (rewritten {rewrite_count}×)</Badge>;
  }
  return <Badge color="gray">Ready</Badge>;
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({ tour, onClose }: { tour: Tour; onClose: () => void }) {
  const [tab, setTab]           = useState<"original" | "rewrite" | "history">("original");
  const [detail, setDetail]     = useState<TourDetail | null>(null);
  const [history, setHistory]   = useState<HistoryRow[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(false);

  useEffect(() => {
    setLoadingDetail(true);
    fetch(`/api/admin/tours/${tour.tour_id}/detail`)
      .then(r => r.json())
      .then(setDetail)
      .catch(() => {})
      .finally(() => setLoadingDetail(false));
  }, [tour.tour_id]);

  useEffect(() => {
    if (tab !== "history") return;
    setLoadingHistory(true);
    fetch(`/api/admin/tours/${tour.tour_id}/history`)
      .then(r => r.json())
      .then(d => setHistory(d.history || []))
      .catch(() => {})
      .finally(() => setLoadingHistory(false));
  }, [tab, tour.tour_id]);

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: "8px 16px",
    fontSize: 13,
    fontWeight: active ? 600 : 400,
    color: active ? A.ink : A.muted,
    cursor: "pointer",
    background: "none",
    border: "none",
    borderBottom: active ? `2px solid ${A.gold}` : "2px solid transparent",
    fontFamily: sans,
  });

  const highlights = (arr: string[] | string | null | undefined): string[] => {
    if (!arr) return [];
    if (typeof arr === "string") {
      try { return JSON.parse(arr); } catch { return [arr]; }
    }
    return arr;
  };

  const keywords = (arr: string[] | null | undefined): string[] => {
    if (!arr) return [];
    return arr;
  };

  return (
    <div style={{
      position: "fixed", top: 0, right: 0, bottom: 0,
      width: 620, background: "#fff",
      boxShadow: "-4px 0 32px rgba(0,0,0,0.12)",
      zIndex: 200, display: "flex", flexDirection: "column",
      fontFamily: sans,
    }}>
      {/* Header */}
      <div style={{ padding: "20px 24px 0", borderBottom: `1px solid ${A.line}` }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
          <div style={{ flex: 1, paddingRight: 12 }}>
            <div style={{ fontFamily: serif, fontSize: 17, fontWeight: 600, color: A.ink, lineHeight: 1.3 }}>
              {tour.src_name}
            </div>
            <div style={{ fontSize: 12, color: A.muted, marginTop: 3 }}>
              {tour.country || "—"} · {tour.rewrite_count > 0 ? `Rewritten ${tour.rewrite_count}×` : "Not yet rewritten"}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted, padding: 4 }}>
            <X size={18} />
          </button>
        </div>
        {/* Tabs */}
        <div style={{ display: "flex", gap: 0 }}>
          <button style={tabStyle(tab === "original")} onClick={() => setTab("original")}>Original Content</button>
          <button style={{ ...tabStyle(tab === "rewrite"), opacity: tour.rewrite_count === 0 ? 0.4 : 1 }} onClick={() => tour.rewrite_count > 0 && setTab("rewrite")}>Latest Rewrite</button>
          <button style={tabStyle(tab === "history")} onClick={() => setTab("history")}>Rewrite History</button>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        {loadingDetail ? (
          <div style={{ textAlign: "center", padding: 40, color: A.muted }}>Loading…</div>
        ) : !detail ? (
          <div style={{ textAlign: "center", padding: 40, color: A.red }}>Failed to load detail</div>
        ) : tab === "original" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {[
                ["Tour Name", detail.raw.src_name],
                ["Country", detail.raw.country || "—"],
                ["Duration", detail.raw.duration || "—"],
                ["Price", detail.raw.price_raw || "—"],
                ["Group Size", detail.raw.group_size || "—"],
                ["Status", detail.raw.pipeline_status],
              ].map(([label, val]) => (
                <div key={label}>
                  <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>{label}</div>
                  <div style={{ fontSize: 13, color: A.ink }}>{val}</div>
                </div>
              ))}
            </div>

            {detail.raw.src_summary && (
              <div>
                <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Summary</div>
                <div style={{ fontSize: 13, color: A.body, lineHeight: 1.6 }}>{detail.raw.src_summary}</div>
              </div>
            )}

            {highlights(detail.raw.src_highlights).length > 0 && (
              <div>
                <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Highlights</div>
                <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
                  {highlights(detail.raw.src_highlights).map((h, i) => (
                    <li key={i} style={{ fontSize: 13, color: A.body }}>{h}</li>
                  ))}
                </ul>
              </div>
            )}

            {detail.raw.src_itineraries && (
              <div>
                <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Itineraries</div>
                <div style={{ fontSize: 12, color: A.body, lineHeight: 1.7, whiteSpace: "pre-wrap", background: A.bg, padding: 12, borderRadius: 8, maxHeight: 280, overflowY: "auto" }}>
                  {detail.raw.src_itineraries}
                </div>
              </div>
            )}
          </div>
        ) : tab === "rewrite" ? (
          detail.generated ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {[
                  ["Version", `v${detail.generated.version_num}`],
                  ["Status", detail.generated.status],
                  ["Model", detail.generated.model_editorial?.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? "—"],
                ].map(([label, val]) => (
                  <div key={label}>
                    <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>{label}</div>
                    <div style={{ fontSize: 13, color: A.ink }}>{val}</div>
                  </div>
                ))}
              </div>

              <div>
                <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>AA Name</div>
                <div style={{ fontSize: 15, fontFamily: serif, fontWeight: 600, color: A.ink }}>{detail.generated.aa_name}</div>
              </div>

              {detail.generated.aa_subtitle && (
                <div>
                  <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>Subtitle</div>
                  <div style={{ fontSize: 13, color: A.body, fontStyle: "italic" }}>{detail.generated.aa_subtitle}</div>
                </div>
              )}

              {detail.generated.aa_summary && (
                <div>
                  <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Summary</div>
                  <div style={{ fontSize: 13, color: A.body, lineHeight: 1.6 }}>{detail.generated.aa_summary}</div>
                </div>
              )}

              {detail.generated.aa_highlights && detail.generated.aa_highlights.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Highlights</div>
                  <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
                    {detail.generated.aa_highlights.map((h, i) => (
                      <li key={i} style={{ fontSize: 13, color: A.body }}>{h}</li>
                    ))}
                  </ul>
                </div>
              )}

              {detail.generated.aa_itineraries && (
                <div>
                  <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Itineraries</div>
                  <div style={{ fontSize: 12, color: A.body, lineHeight: 1.7, whiteSpace: "pre-wrap", background: A.bg, padding: 12, borderRadius: 8, maxHeight: 220, overflowY: "auto" }}>
                    {detail.generated.aa_itineraries}
                  </div>
                </div>
              )}

              {/* SEO */}
              <div style={{ borderTop: `1px solid ${A.line}`, paddingTop: 16 }}>
                <SLabel>SEO</SLabel>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {detail.generated.seo_title && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 3 }}>Title ({detail.generated.seo_title.length}/70)</div>
                      <div style={{ fontSize: 13, color: A.ink }}>{detail.generated.seo_title}</div>
                    </div>
                  )}
                  {detail.generated.seo_meta && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 3 }}>Meta ({detail.generated.seo_meta.length}/170)</div>
                      <div style={{ fontSize: 13, color: A.body }}>{detail.generated.seo_meta}</div>
                    </div>
                  )}
                  {keywords(detail.generated.seo_keywords_used).length > 0 && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 6 }}>Keywords used</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {keywords(detail.generated.seo_keywords_used).map((kw, i) => (
                          <span key={i} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 12, background: A.goldTint, color: A.gold, border: `1px solid ${A.line}` }}>{kw}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Quality scores */}
              <div style={{ borderTop: `1px solid ${A.line}`, paddingTop: 16 }}>
                <SLabel>Quality Scores</SLabel>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  {[
                    ["Overall", detail.generated.score_overall],
                    ["Brand", detail.generated.score_brand],
                    ["SEO", detail.generated.score_seo],
                    ["Structure", detail.generated.score_structure],
                  ].map(([label, score]) => (
                    <div key={label as string} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: A.bg, borderRadius: 8 }}>
                      <span style={{ fontSize: 12, color: A.muted }}>{label}</span>
                      <span style={{ fontSize: 15, fontWeight: 700, fontFamily: mono, color: scoreColor(score as number | null) }}>
                        {score != null ? (score as number).toFixed(1) : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: 40, color: A.muted }}>No rewrite data available</div>
          )
        ) : (
          /* History tab */
          loadingHistory ? (
            <div style={{ textAlign: "center", padding: 40, color: A.muted }}>Loading history…</div>
          ) : history.length === 0 ? (
            <div style={{ textAlign: "center", padding: 40, color: A.muted, fontSize: 13 }}>No rewrites yet</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: A.line2 }}>
                  {["Version", "Model", "Score", "Cost", "Date"].map(h => (
                    <th key={h} style={{ ...TH, padding: "8px 10px", textAlign: "left" as const }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr key={h.id} style={{ borderTop: i > 0 ? `1px solid ${A.line}` : undefined }}>
                    <td style={{ ...TD, padding: "8px 10px" }}><Badge color="blue">v{h.version_num}</Badge></td>
                    <td style={{ ...TD, padding: "8px 10px", fontFamily: mono, fontSize: 11, color: A.muted }}>
                      {h.model_editorial?.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? "—"}
                    </td>
                    <td style={{ ...TD, padding: "8px 10px", fontWeight: 700, color: scoreColor(h.score_overall) }}>
                      {h.score_overall != null ? h.score_overall.toFixed(1) : "—"}
                    </td>
                    <td style={{ ...TD, padding: "8px 10px", color: A.gold }}>
                      {h.cost_usd != null ? `$${h.cost_usd.toFixed(4)}` : "—"}
                    </td>
                    <td style={{ ...TD, padding: "8px 10px", color: A.muted2, fontSize: 12 }}>
                      {relativeTime(h.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function S1RewritePage() {
  const [tours, setTours]                   = useState<Tour[]>([]);
  const [loading, setLoading]               = useState(true);
  const [selectedIds, setSelectedIds]       = useState<Set<string>>(new Set());
  const [filterCountry, setFilterCountry]   = useState("");
  const [filterFile, setFilterFile]         = useState("");
  const [filterSearch, setFilterSearch]     = useState("");
  const [seoMode, setSeoMode]               = useState("standard");
  const [modelTier, setModelTier]           = useState("haiku");
  const [brandVersions, setBrandVersions]   = useState<BrandVersion[]>([]);
  const [brandVersion, setBrandVersion]     = useState<number | null>(null);
  const [showConfirm, setShowConfirm]       = useState(false);
  const [running, setRunning]               = useState(false);
  const [tourStatuses, setTourStatuses]     = useState<Record<string, TourRunStatus>>({});
  const [runResults, setRunResults]         = useState<Record<string, RunResult>>({});
  const [runComplete, setRunComplete]       = useState(false);
  const [detailTour, setDetailTour]         = useState<Tour | null>(null);

  const loadTours = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/admin/tours");
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setTours(data.tours || []);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadBrandVersions = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/brand-identity");
      if (!res.ok) return;
      const data = await res.json();
      const history: BrandVersion[] = data.history || [];
      setBrandVersions(history);
      const active = history.find(h => h.is_active);
      if (active) setBrandVersion(active.version);
    } catch {}
  }, []);

  useEffect(() => { loadTours(); loadBrandVersions(); }, [loadTours, loadBrandVersions]);

  const uniqueCountries = Array.from(new Set(
    tours.map(t => t.country).filter((c): c is string => Boolean(c))
  )).sort();
  const uniqueFiles = Array.from(new Set(
    tours.map(t => t.filename).filter((f): f is string => Boolean(f))
  )).sort();

  const filteredTours = tours.filter(t => {
    if (filterCountry && t.country !== filterCountry) return false;
    if (filterFile && t.filename !== filterFile) return false;
    if (filterSearch && !t.src_name.toLowerCase().includes(filterSearch.toLowerCase())) return false;
    return true;
  });

  function toggleTour(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function selectAll()   { setSelectedIds(new Set(filteredTours.map(t => t.tour_id))); }
  function deselectAll() { setSelectedIds(new Set()); }

  const selectedTours = tours.filter(t => selectedIds.has(t.tour_id));

  async function runSingleTour(tour: Tour): Promise<void> {
    setTourStatuses(prev => ({ ...prev, [tour.tour_id]: "running" }));
    try {
      const res = await fetch("/api/admin/run-tour", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tour_id:              tour.tour_id,
          batch_id:             tour.batch_id || TENANT_ID,
          tenant_id:            TENANT_ID,
          seo_mode:             seoMode,
          model_tier:           modelTier,
          brand_rules_version:  brandVersion,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Run failed");
      }
      const data: RunResult = await res.json();
      setRunResults(prev => ({ ...prev, [tour.tour_id]: data }));
      setTourStatuses(prev => ({ ...prev, [tour.tour_id]: "done" }));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setRunResults(prev => ({
        ...prev,
        [tour.tour_id]: { tour_id: tour.tour_id, status: "failed", quality_score: null, version_id: null, error: msg },
      }));
      setTourStatuses(prev => ({ ...prev, [tour.tour_id]: "failed" }));
    }
  }

  async function startRun() {
    setShowConfirm(false);
    setRunning(true);
    setRunComplete(false);
    setTourStatuses({});
    setRunResults({});

    const toRun = [...selectedTours];
    for (let i = 0; i < toRun.length; i += 3) {
      const chunk = toRun.slice(i, i + 3);
      await Promise.all(chunk.map(t => runSingleTour(t)));
    }
    setRunning(false);
    setRunComplete(true);
  }

  const statusCounts = Object.values(tourStatuses).reduce(
    (acc, s) => { acc[s] = (acc[s] || 0) + 1; return acc; },
    {} as Record<TourRunStatus, number>
  );

  const seoModeLabel = (m: string) => ({
    standard:   "Standard",
    aggressive: "Aggressive",
    minimal:    "Minimal",
  }[m] ?? m);

  const modelLabel = (m: string) => ({
    haiku:  "Haiku 4.5",
    sonnet: "Sonnet 4.5",
    gpt4:   "GPT-4.1",
  }[m] ?? m);

  if (loading) {
    return (
      <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
        <AdminSidebar />
        <main style={{ flex: 1, padding: "32px 36px" }}>
          <LoadingScreen msg="Loading tours…" />
        </main>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, letterSpacing: "-0.02em" }}>
              S1 Rewrite
            </div>
            <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
              {tours.length} tours total — select to rewrite with AI
            </div>
          </div>
          <Btn size="sm" variant="ghost" onClick={loadTours} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <RefreshCw size={13} /> Refresh
          </Btn>
        </div>

        {/* Filter bar */}
        <Card style={{ marginBottom: 16, padding: "12px 16px" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <select
              value={filterCountry}
              onChange={e => setFilterCountry(e.target.value)}
              style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff", minWidth: 140 }}
            >
              <option value="">All Countries</option>
              {uniqueCountries.map(c => <option key={c} value={c}>{c}</option>)}
            </select>

            <select
              value={filterFile}
              onChange={e => setFilterFile(e.target.value)}
              style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff", minWidth: 180 }}
            >
              <option value="">All Files</option>
              {uniqueFiles.map(f => <option key={f} value={f}>{stripUuidPrefix(f)}</option>)}
            </select>

            <div style={{ display: "flex", alignItems: "center", gap: 6, border: `1px solid ${A.line}`, borderRadius: 6, padding: "6px 10px", background: "#fff", flex: 1, minWidth: 200 }}>
              <Search size={13} style={{ color: A.muted2, flexShrink: 0 }} />
              <input
                placeholder="Search by tour name…"
                value={filterSearch}
                onChange={e => setFilterSearch(e.target.value)}
                style={{ border: "none", outline: "none", fontSize: 13, fontFamily: sans, width: "100%", background: "transparent" }}
              />
            </div>

            <Btn size="sm" variant="ghost" onClick={selectAll}>Select All ({filteredTours.length})</Btn>
            <Btn size="sm" variant="ghost" onClick={deselectAll} disabled={selectedIds.size === 0}>Deselect All</Btn>
          </div>
        </Card>

        {/* Tours table */}
        {tours.length === 0 ? (
          <Card style={{ textAlign: "center", padding: "48px 24px" }}>
            <div style={{ fontSize: 15, color: A.muted, marginBottom: 14 }}>No tours found.</div>
            <div style={{ fontSize: 13, color: A.muted2, marginBottom: 20 }}>Upload Excel files in Upload (S0) first.</div>
            <Btn size="sm" variant="secondary" onClick={() => window.location.href = "/admin/upload"}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              Go to Upload <ArrowRight size={12} />
            </Btn>
          </Card>
        ) : (
          <Card style={{ marginBottom: 20, padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: A.line2 }}>
                  <th style={{ ...TH, width: 36, paddingLeft: 16 }}>
                    <input
                      type="checkbox"
                      checked={filteredTours.length > 0 && filteredTours.every(t => selectedIds.has(t.tour_id))}
                      onChange={e => e.target.checked ? selectAll() : deselectAll()}
                      style={{ accentColor: A.gold }}
                    />
                  </th>
                  <th style={TH}>Tour Name</th>
                  <th style={TH}>Country</th>
                  <th style={TH}>Source File</th>
                  <th style={TH}>Rewrites</th>
                  <th style={TH}>Last Rewritten</th>
                  <th style={TH}>Ingested</th>
                  <th style={TH}>Status</th>
                  <th style={{ ...TH, width: 28 }}></th>
                </tr>
              </thead>
              <tbody>
                {filteredTours.map((t, i) => {
                  const runStatus = tourStatuses[t.tour_id] || "idle";
                  const result = runResults[t.tour_id];
                  const isSelected = selectedIds.has(t.tour_id);
                  const isDetail = detailTour?.tour_id === t.tour_id;
                  return (
                    <tr
                      key={t.tour_id}
                      onClick={() => setDetailTour(isDetail ? null : t)}
                      style={{
                        borderTop: i > 0 ? `1px solid ${A.line}` : undefined,
                        background: isDetail ? `${A.gold}18` : isSelected ? `${A.gold}10` : "transparent",
                        cursor: "pointer",
                        transition: "background .12s",
                      }}
                    >
                      <td style={{ ...TD, paddingLeft: 16 }} onClick={e => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {}}
                          onClick={e => { e.stopPropagation(); setSelectedIds(prev => { const next = new Set(prev); next.has(t.tour_id) ? next.delete(t.tour_id) : next.add(t.tour_id); return next; }); }}
                          disabled={running}
                          style={{ accentColor: A.gold }}
                        />
                      </td>
                      <td style={{ ...TD, fontWeight: 500, color: A.ink }}>{t.src_name}</td>
                      <td style={TD}>
                        <span style={{ color: t.country ? A.body : A.muted2 }}>{t.country || "—"}</span>
                      </td>
                      <td style={TD}>
                        <span style={{ fontFamily: mono, fontSize: 11, color: A.muted }}>
                          {stripUuidPrefix(t.filename)}
                        </span>
                      </td>
                      <td style={{ ...TD, textAlign: "center" as const }}>
                        {t.rewrite_count > 0
                          ? <span style={{ fontFamily: mono, fontSize: 13, fontWeight: 600, color: A.ink }}>{t.rewrite_count}</span>
                          : <span style={{ color: A.muted2 }}>—</span>}
                      </td>
                      <td style={{ ...TD, color: A.muted2, fontSize: 12 }}>{relativeTime(t.last_rewritten_at)}</td>
                      <td style={{ ...TD, color: A.muted2, fontSize: 12 }}>{relativeTime(t.ingest_at)}</td>
                      <td style={TD}><PipelineStatusBadge tour={t} runStatus={runStatus} result={result} /></td>
                      <td style={{ ...TD, color: A.muted2 }}><ChevronRight size={14} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        )}

        {/* Config + Run panel */}
        {selectedIds.size > 0 && (
          <Card style={{ marginBottom: 20 }}>
            <SLabel>Rewrite Config</SLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 12, alignItems: "flex-end" }}>
              <div>
                <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>Brand Identity</label>
                <select
                  value={brandVersion ?? ""}
                  onChange={e => setBrandVersion(e.target.value ? Number(e.target.value) : null)}
                  disabled={running}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }}
                >
                  {brandVersions.length === 0 && <option value="">No brand configured</option>}
                  {brandVersions.map(bv => (
                    <option key={bv.version} value={bv.version}>
                      v{bv.version}{bv.is_active ? " (active)" : ""}
                      {bv.updated_at ? ` · ${new Date(bv.updated_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}` : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>SEO Mode</label>
                <select
                  value={seoMode}
                  onChange={e => setSeoMode(e.target.value)}
                  disabled={running}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }}
                >
                  <option value="standard">Standard — DataForSEO keywords, balanced</option>
                  <option value="aggressive">Aggressive — keyword-heavy, SEO-first</option>
                  <option value="minimal">Minimal — brand-only, no SEO enrichment</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>Model</label>
                <select
                  value={modelTier}
                  onChange={e => setModelTier(e.target.value)}
                  disabled={running}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }}
                >
                  <option value="haiku">Haiku 4.5 (~$0.002/tour)</option>
                  <option value="sonnet">Sonnet 4.5 (~$0.02/tour)</option>
                  <option value="gpt4">GPT-4.1 (~$0.01/tour)</option>
                </select>
              </div>
              <Btn
                variant="primary"
                size="lg"
                disabled={running}
                onClick={() => setShowConfirm(true)}
                style={{
                  background: running ? A.muted : A.gold,
                  border: `1px solid ${running ? A.muted : A.gold}`,
                  display: "flex", alignItems: "center", gap: 8,
                  whiteSpace: "nowrap" as const,
                }}
              >
                <Play size={14} />
                {running ? "Running…" : `Run Rewrite (${selectedIds.size})`}
              </Btn>
            </div>
          </Card>
        )}

        {/* Confirm dialog */}
        {showConfirm && (
          <div style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
          }}>
            <Card style={{ maxWidth: 420, width: "90%", padding: 28 }}>
              <div style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink, marginBottom: 12 }}>
                Confirm Rewrite
              </div>
              <div style={{ fontSize: 14, color: A.body, marginBottom: 20, lineHeight: 1.6 }}>
                This will rewrite{" "}
                <strong>{selectedIds.size} tour{selectedIds.size !== 1 ? "s" : ""}</strong>{" "}
                using <strong>{seoModeLabel(seoMode)} SEO</strong> mode
                with <strong>{modelLabel(modelTier)}</strong>
                {brandVersion ? ` (Brand v${brandVersion})` : ""}. Continue?
              </div>
              <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                <Btn size="sm" variant="ghost" onClick={() => setShowConfirm(false)}>Cancel</Btn>
                <Btn
                  size="sm"
                  variant="primary"
                  onClick={startRun}
                  style={{ background: A.gold, border: `1px solid ${A.gold}` }}
                >
                  Yes, Run Rewrite
                </Btn>
              </div>
            </Card>
          </div>
        )}

        {/* Progress summary */}
        {(running || runComplete) && Object.keys(tourStatuses).length > 0 && (
          <Card style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
              <div style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.14em", color: A.muted }}>
                Rewrite Progress
              </div>
              <span style={{ fontSize: 13, color: A.muted }}>
                {(statusCounts.done || 0) + (statusCounts.failed || 0)} / {Object.keys(tourStatuses).length} complete
              </span>
              {(statusCounts.done || 0) > 0 && (
                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, color: A.green }}>
                  <CheckCircle size={13} /> {statusCounts.done} done
                </span>
              )}
              {(statusCounts.failed || 0) > 0 && (
                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, color: A.red }}>
                  <XCircle size={13} /> {statusCounts.failed} failed
                </span>
              )}
              {running && <span style={{ fontSize: 13, color: A.amber }}>Processing…</span>}
              {runComplete && (
                <Btn
                  size="sm"
                  variant="primary"
                  onClick={() => window.location.href = "/admin/master-content"}
                  style={{
                    background: A.gold, border: `1px solid ${A.gold}`,
                    display: "flex", alignItems: "center", gap: 6, marginLeft: "auto",
                  }}
                >
                  View in Master Content <ArrowRight size={12} />
                </Btn>
              )}
            </div>
          </Card>
        )}
      </main>

      {/* Detail panel overlay backdrop */}
      {detailTour && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 199 }}
          onClick={() => setDetailTour(null)}
        />
      )}

      {/* Detail slide-in panel */}
      {detailTour && (
        <DetailPanel tour={detailTour} onClose={() => setDetailTour(null)} />
      )}
    </div>
  );
}
