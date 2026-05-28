"use client";
// app/admin/master-content/page.tsx

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, ChevronDown, ChevronRight, Download, X } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Badge, Btn, LoadingScreen, StatCard, TH, TD,
} from "../_components/adminUi";
import { BarChart2, Star, DollarSign, CalendarClock } from "lucide-react";
import { TourDetailPanelV2 } from "../_components/TourDetailPanelV2";
import { CompareModal } from "../_components/CompareModal";
import { FilterBar } from "../_components/FilterBar";
import { Pagination } from "../_components/Pagination";

const AA_INTERNAL_ID = "00000000-0000-0000-0000-000000000001";
const PAGE_SIZE = 20;
const RUNS_PAGE_SIZE = 10;

interface RewrittenTour {
  version_id: string;
  tour_id: string | null;
  tour_name: string;
  country: string;
  quality_score: number;
  version_number: number | null;
  status: string;
  created_at: string;
}

interface Summary {
  total_rewrites: number;
  total_llm_cost_usd: number;
  api_calls_this_month: number;
  quota_pct: number;
  plan_name: string;
  member_since: string;
  tours_view: number;
  pipeline_note: string;
}

interface PipelineRun {
  run_id: string;
  started_at: string;
  tours_processed: number;
  tours_passed: number;
  llm_model: string;
  llm_cost_usd: number;
  status: string;
}

interface DetailsResponse {
  summary: Summary;
  rewritten_tours: RewrittenTour[];
  pipeline_runs: PipelineRun[];
}

interface TourVersion {
  id: string;
  version_num: number;
  model_id: string | null;
  quality_score: number | null;
  created_at: string | null;
  is_current: boolean;
}

interface VersionDetail {
  id: string;
  version_num: number;
  model_id: string | null;
  quality_score: number | null;
  score_brand: number | null;
  score_seo: number | null;
  score_structure: number | null;
  created_at: string | null;
  aa_name: string | null;
  aa_subtitle: string | null;
  aa_summary: string | null;
  aa_description: string | null;
  aa_highlights: string[];
  aa_itineraries: string | null;
  seo_title: string | null;
  seo_meta: string | null;
  brand_name: string | null;
  seo_mode: string | null;
  dataforseo_used: boolean;
  llm_cost_usd: number | null;
  top_keywords: string[];
}

function scoreColor(s: number | null | undefined): string {
  if (s == null) return A.muted2;
  if (s >= 9) return A.green;
  if (s >= 7) return A.amber;
  return A.red;
}

function relDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function statusBadge(status: string) {
  const color = status === "published" ? "green" : status === "active" ? "blue" : "gray";
  return <Badge color={color}>{status}</Badge>;
}

// ── Score Bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ label, value }: { label: string; value: number | null }) {
  const pct = value != null ? Math.min(100, (value / 10) * 100) : 0;
  const color = scoreColor(value);
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
        <span style={{ fontSize: 11, color: A.muted }}>{label}</span>
        <span style={{ fontSize: 11, fontWeight: 700, color, fontFamily: mono }}>
          {value != null ? value.toFixed(1) : "—"}
        </span>
      </div>
      <div style={{ height: 4, background: A.line, borderRadius: 2 }}>
        <div style={{ height: 4, width: `${pct}%`, background: color, borderRadius: 2, transition: "width .3s" }} />
      </div>
    </div>
  );
}

// ── Version Compare Modal (full-screen, 2-4 panels) ───────────────────────────

interface PanelState {
  versionNum: number;
  data: VersionDetail | null;
  loading: boolean;
}

const PANEL_COLORS = [A.gold, "#3B82F6", "#16A34A", "#7C3AED"];
const PANEL_BG     = ["#FAFAF8", "#F8FAFF", "#F0FDF4", "#F5F3FF"];

const CONTENT_FIELDS: [keyof VersionDetail, string][] = [
  ["aa_name",        "Tour Name"],
  ["aa_subtitle",    "Subtitle"],
  ["aa_summary",     "Summary"],
  ["aa_itineraries", "Itineraries"],
  ["seo_title",      "SEO Title"],
  ["seo_meta",       "SEO Meta"],
  ["aa_description", "Description"],
];

function VersionCompareModal({ tourId, tourName, versionNums, onClose }: {
  tourId: string;
  tourName: string;
  versionNums: [number, number];
  onClose: () => void;
}) {
  const [panels, setPanels] = useState<PanelState[]>(
    versionNums.map(n => ({ versionNum: n, data: null, loading: true }))
  );
  const [allVersions, setAllVersions]   = useState<TourVersion[]>([]);
  const [error, setError]               = useState("");

  useEffect(() => {
    fetch(`/api/admin/tours/${tourId}/versions`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setAllVersions(d.versions ?? []); })
      .catch(() => {});
  }, [tourId]);

  // Fetch data for any panel that is still loading (loading: true means data needed)
  useEffect(() => {
    panels.forEach((panel, idx) => {
      if (!panel.loading) return;
      const vnum = Number(panel.versionNum);
      const fetchUrl = vnum === -1
        ? `/api/admin/tours/${tourId}/source`
        : `/api/admin/tours/${tourId}/versions/${vnum}`;
      fetch(fetchUrl)
        .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
        .then(data => {
          setPanels(prev => prev.map((p, i) =>
            i === idx && p.versionNum === panel.versionNum ? { ...p, data, loading: false } : p
          ));
        })
        .catch(e => {
          setError(String(e));
          setPanels(prev => prev.map((p, i) =>
            i === idx && p.versionNum === panel.versionNum ? { ...p, data: null, loading: false } : p
          ));
        });
    });
  }, [panels.map(p => `${p.versionNum}:${p.loading}`).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  function changePanel(idx: number, vNum: number) {
    setPanels(prev => prev.map((p, i) =>
      i === idx ? { versionNum: vNum, data: null, loading: true } : p
    ));
  }

  function addPanel() {
    if (panels.length >= 4 || allVersions.length === 0) return;
    const used = new Set(panels.map(p => p.versionNum));
    const nextVNum = allVersions.find(v => !used.has(v.version_num))?.version_num ?? allVersions[0].version_num;
    setPanels(prev => [...prev, { versionNum: nextVNum, data: null, loading: true }]);
  }

  function removePanel(idx: number) {
    if (panels.length <= 2) return;
    setPanels(prev => prev.filter((_, i) => i !== idx));
  }

  function modelLabel(m: string | null) {
    return m?.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? "—";
  }

  function fieldSerial(v: VersionDetail | null, key: keyof VersionDetail): string {
    if (!v) return "\x00";
    const raw = v[key];
    if (raw == null) return "";
    if (Array.isArray(raw)) return JSON.stringify(raw);
    return String(raw);
  }

  function isFieldDiff(idx: number, key: keyof VersionDetail): boolean {
    if (idx === 0 || panels.length < 2) return false;
    if (!panels[0].data || !panels[idx].data) return false;
    return fieldSerial(panels[0].data, key) !== fieldSerial(panels[idx].data, key);
  }

  function cellVal(panel: PanelState, key: keyof VersionDetail): React.ReactNode {
    if (panel.loading) return <div style={{ padding: "10px 20px", fontSize: 12, color: A.muted2 }}>Loading…</div>;
    const v = panel.data;
    if (!v) return <div style={{ padding: "10px 20px", fontSize: 12, color: A.muted2 }}>—</div>;
    const raw: unknown = v[key];
    let display: React.ReactNode;

    if (key === "aa_highlights" && Array.isArray(raw)) {
      display = (
        <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
          {(raw as string[]).map((h, i) => <li key={i}>{h}</li>)}
        </ul>
      );
    } else if (key === "seo_title") {
      const len = typeof raw === "string" ? raw.length : 0;
      display = <><span>{(raw as string) || "—"}</span>{typeof raw === "string" && <span style={{ marginLeft: 6, fontSize: 10, color: A.muted2 }}>{len} chars</span>}</>;
    } else if (key === "seo_meta") {
      const len = typeof raw === "string" ? raw.length : 0;
      const over = len > 170;
      display = <><span style={{ color: over ? A.red : "inherit" }}>{(raw as string) || "—"}</span>{typeof raw === "string" && <span style={{ marginLeft: 6, fontSize: 10, color: over ? A.red : A.muted2 }}>{len} chars{over ? " (>170)" : ""}</span>}</>;
    } else {
      display = <span>{typeof raw === "string" ? raw : raw == null ? "—" : String(raw)}</span>;
    }

    return (
      <div style={{ padding: "10px 20px", fontSize: 13, color: raw ? A.body : A.muted2, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
        {display}
      </div>
    );
  }

  const n = panels.length;

  return (
    <div style={{
      position: "fixed", top: 0, left: 240, width: "calc(100vw - 240px)", height: "100vh",
      background: "#fff", zIndex: 300, display: "flex", flexDirection: "column",
      boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
    }}>
      {/* Modal header */}
      <div style={{
        padding: "14px 24px", borderBottom: `1px solid ${A.line}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexShrink: 0, background: "#fff", zIndex: 10,
      }}>
        <div>
          <div style={{ fontFamily: serif, fontSize: 16, fontWeight: 500, color: A.ink }}>
            Version Compare — {tourName}
          </div>
          <div style={{ fontSize: 12, color: A.muted, marginTop: 2 }}>
            {n} panel{n > 1 ? "s" : ""} · Use version dropdowns to switch · Highlighted cells differ from panel 1
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {n < 4 && (
            <button
              onClick={addPanel}
              disabled={allVersions.length === 0}
              style={{
                padding: "6px 12px", fontSize: 12, fontWeight: 600,
                border: `1px solid ${A.gold}`, borderRadius: 6,
                background: A.goldTint, color: A.gold,
                cursor: allVersions.length === 0 ? "not-allowed" : "pointer",
                opacity: allVersions.length === 0 ? 0.5 : 1,
              }}
            >
              + Add Panel
            </button>
          )}
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, padding: 6 }}>
            <X size={20} />
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: "8px 24px", background: A.redSoft, color: A.red, fontSize: 12, flexShrink: 0 }}>
          {error}
        </div>
      )}

      {/* Panels grid — each panel scrolls independently */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: `repeat(${n}, 1fr)`, overflow: "hidden" }}>
        {panels.map((panel, idx) => {
          const v         = panel.data;
          const color     = PANEL_COLORS[idx] ?? PANEL_COLORS[0];
          const panelBg   = PANEL_BG[idx] ?? PANEL_BG[0];
          return (
            <div key={idx} style={{
              display: "flex", flexDirection: "column", overflow: "hidden",
              borderRight: idx < n - 1 ? `1px solid ${A.line}` : undefined,
            }}>
              <div style={{ overflowY: "auto", flex: 1 }}>
                {/* Sticky column header */}
                <div style={{ padding: "12px 20px", background: panelBg, position: "sticky", top: 0, zIndex: 5, borderBottom: `1px solid ${A.line}` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <select
                      value={panel.versionNum}
                      onChange={e => changePanel(idx, parseInt(e.target.value))}
                      style={{
                        padding: "3px 8px", fontSize: 12, fontWeight: 700,
                        background: color, color: "#fff",
                        border: "none", borderRadius: 10, cursor: "pointer",
                      }}
                    >
                      {idx === 0 && <option value={-1}>Original (source)</option>}
                      {allVersions.map(av => (
                        <option key={av.version_num} value={av.version_num}>v{av.version_num}</option>
                      ))}
                    </select>
                    {v && (
                      <span style={{ fontSize: 12, color: A.muted }}>{modelLabel(v.model_id)}</span>
                    )}
                    {v?.created_at && (
                      <span style={{ fontSize: 11, color: A.muted2, marginLeft: "auto" }}>{relDate(v.created_at)}</span>
                    )}
                    {n > 2 && (
                      <button
                        onClick={() => removePanel(idx)}
                        title="Remove panel"
                        style={{
                          marginLeft: v?.created_at ? 0 : "auto",
                          background: "none", border: "none", cursor: "pointer",
                          color: A.muted, padding: "0 4px", fontSize: 16, lineHeight: 1,
                        }}
                      >×</button>
                    )}
                  </div>

                  {/* Score bars */}
                  {v ? (
                    <div style={{ padding: "8px 0", borderTop: `1px solid ${A.line}`, marginTop: 4 }}>
                      <ScoreBar label="Overall"   value={v.quality_score} />
                      <ScoreBar label="Brand"     value={v.score_brand} />
                      <ScoreBar label="SEO"       value={v.score_seo} />
                      <ScoreBar label="Structure" value={v.score_structure} />
                    </div>
                  ) : (
                    <div style={{ fontSize: 12, color: A.muted2, padding: "8px 0" }}>
                      {panel.loading ? "Loading…" : "No data"}
                    </div>
                  )}

                  {/* Rewrite config */}
                  {v && (
                    <div style={{ padding: "8px 0", borderTop: `1px solid ${A.line}`, marginTop: 4, fontSize: 11 }}>
                      <div style={{ fontWeight: 600, color: A.muted, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Rewrite Config</div>
                      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 8px", color: A.body }}>
                        <span style={{ color: A.muted }}>Model</span>
                        <span style={{ fontFamily: mono }}>{modelLabel(v.model_id)}</span>
                        <span style={{ color: A.muted }}>Brand</span>
                        <span>{v.brand_name || "default"}</span>
                        <span style={{ color: A.muted }}>SEO Mode</span>
                        <span>{v.seo_mode || "standard"}</span>
                        <span style={{ color: A.muted }}>DataForSEO</span>
                        <span style={{ color: v.dataforseo_used ? A.green : A.muted2 }}>{v.dataforseo_used ? "Live" : "Mock"}</span>
                        <span style={{ color: A.muted }}>Cost</span>
                        <span style={{ fontFamily: mono }}>{v.llm_cost_usd != null ? `$${v.llm_cost_usd.toFixed(4)}` : "—"}</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Keywords */}
                {v && v.top_keywords.length > 0 && (
                  <div style={{ borderBottom: `1px solid ${A.line}` }}>
                    <div style={{ padding: "5px 20px", background: A.line2, fontSize: 10, fontWeight: 700, textTransform: "uppercase" as const, letterSpacing: "0.12em", color: A.muted }}>
                      Keywords
                    </div>
                    <div style={{ padding: "8px 20px", fontSize: 12, color: A.body }}>
                      {v.top_keywords.slice(0, 15).join(", ")}
                    </div>
                  </div>
                )}

                {/* Content fields with diff highlight */}
                {CONTENT_FIELDS.map(([key, label]) => {
                  const diff = isFieldDiff(idx, key);
                  return (
                    <div key={key} style={{ borderBottom: `1px solid ${A.line}`, background: diff ? "#FFF9E6" : "transparent" }}>
                      <div style={{
                        padding: "5px 20px",
                        background: diff ? "#FFF0C4" : A.line2,
                        fontSize: 10, fontWeight: 700,
                        textTransform: "uppercase" as const, letterSpacing: "0.12em", color: A.muted,
                        display: "flex", alignItems: "center", gap: 6,
                      }}>
                        {label}
                        {diff && <span style={{ color: "#C2410C", fontSize: 9 }}>↕ diff</span>}
                      </div>
                      {cellVal(panel, key)}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MasterContentPage() {
  const [data, setData]                 = useState<DetailsResponse | null>(null);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState("");
  const [refreshing, setRefreshing]     = useState(false);
  const [search, setSearch]             = useState("");
  const [detailTourId, setDetailTourId] = useState<string | null>(null);
  const [detailTourName, setDetailTourName] = useState("");
  const [selectedIds, setSelectedIds]   = useState<Set<string>>(new Set());
  const [compareOpen, setCompareOpen]   = useState(false);
  const [expandedTours, setExpandedTours] = useState<Set<string>>(new Set());
  const [tourVersions, setTourVersions] = useState<Record<string, TourVersion[]>>({});
  const [versionLoading, setVersionLoading] = useState<Record<string, boolean>>({});
  const [promoting, setPromoting]       = useState<string | null>(null);
  const [page, setPage]                 = useState(1);
  const [runsPage, setRunsPage]         = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  const [scoreFilter, setScoreFilter]   = useState("");
  const [versionFilter, setVersionFilter] = useState("");
  const [exporting, setExporting]       = useState(false);

  const [compareVersionSel, setCompareVersionSel] = useState<Record<string, Set<number>>>({});
  const [compareVersionOpen, setCompareVersionOpen] = useState<{ tourId: string; tourName: string; vNums: [number, number] } | null>(null);

  async function load() {
    try {
      const res = await fetch(`/api/tenant/admin/tenants/${AA_INTERNAL_ID}/details`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setData(await res.json());
      setError("");
    } catch (e: any) {
      setError(e.message || "Failed to load");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => { load(); }, []);

  function refresh() { setRefreshing(true); load(); }

  const tours = data?.rewritten_tours ?? [];
  const summary = data?.summary;
  const runs = data?.pipeline_runs ?? [];

  const avgScore = tours.length
    ? tours.reduce((s, t) => s + (t.quality_score ?? 0), 0) / tours.length
    : 0;

  const uniqueCountries = Array.from(new Set(tours.map(t => t.country).filter(Boolean))).sort() as string[];

  const filtered = tours.filter(t => {
    if (search && !t.tour_name.toLowerCase().includes(search.toLowerCase()) &&
        !(t.country || "").toLowerCase().includes(search.toLowerCase())) return false;
    if (statusFilter && t.status !== statusFilter) return false;
    if (countryFilter && t.country !== countryFilter) return false;
    if (scoreFilter) {
      const s = t.quality_score ?? 0;
      if (scoreFilter === "9.5+" && s < 9.5) return false;
      if (scoreFilter === "9.0+" && s < 9.0) return false;
      if (scoreFilter === "8.0+" && s < 8.0) return false;
      if (scoreFilter === "below8" && s >= 8.0) return false;
    }
    if (versionFilter) {
      const v = t.version_number ?? 0;
      if (versionFilter === "v1" && v !== 1) return false;
      if (versionFilter === "v2+" && v < 2) return false;
      if (versionFilter === "v3+" && v < 3) return false;
    }
    return true;
  });

  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const paginatedRuns = runs.slice((runsPage - 1) * RUNS_PAGE_SIZE, runsPage * RUNS_PAGE_SIZE);

  function handleSearch(v: string) { setSearch(v); setPage(1); }
  function handleStatusFilter(v: string) { setStatusFilter(v); setPage(1); }

  async function exportTours(format: "csv" | "xlsx") {
    setExporting(true);
    try {
      const r = await fetch(`/api/admin/tours/export?format=${format}`);
      if (!r.ok) return;
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `master_content_export.${format}`; a.click();
      URL.revokeObjectURL(url);
    } finally { setExporting(false); }
  }

  const statusOptions = ["published", "active", "pending", "failed"].map(s => ({ label: s, value: s }));
  const countryOptions = uniqueCountries.map(c => ({ label: c, value: c }));
  const scoreOptions = [
    { label: "9.5+", value: "9.5+" },
    { label: "9.0+", value: "9.0+" },
    { label: "8.0+", value: "8.0+" },
    { label: "Below 8.0", value: "below8" },
  ];
  const versionOptions = [
    { label: "v1 only", value: "v1" },
    { label: "v2+",     value: "v2+" },
    { label: "v3+",     value: "v3+" },
  ];

  const toggleExpand = useCallback(async (tourId: string) => {
    setExpandedTours(prev => {
      const next = new Set(prev);
      next.has(tourId) ? next.delete(tourId) : next.add(tourId);
      return next;
    });
    if (!tourVersions[tourId]) {
      setVersionLoading(prev => ({ ...prev, [tourId]: true }));
      try {
        const r = await fetch(`/api/admin/tours/${tourId}/versions`);
        if (r.ok) {
          const d = await r.json();
          setTourVersions(prev => ({ ...prev, [tourId]: d.versions ?? [] }));
        }
      } finally {
        setVersionLoading(prev => ({ ...prev, [tourId]: false }));
      }
    }
  }, [tourVersions]);

  async function promoteVersion(tourId: string, tourName: string, versionNum: number) {
    if (!confirm(`Make v${versionNum} the current published version for "${tourName}"?`)) return;
    setPromoting(`${tourId}-${versionNum}`);
    try {
      const r = await fetch(`/api/admin/tours/${tourId}/versions/${versionNum}/promote`, { method: "POST" });
      if (r.ok) {
        setTourVersions(prev => ({
          ...prev,
          [tourId]: (prev[tourId] ?? []).map(v => ({ ...v, is_current: v.version_num === versionNum })),
        }));
      }
    } finally { setPromoting(null); }
  }

  function toggleSelect(tourId: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(tourId) ? next.delete(tourId) : next.add(tourId);
      return next;
    });
  }

  function toggleVersionSel(tourId: string, vNum: number) {
    setCompareVersionSel(prev => {
      const cur = new Set(prev[tourId] ?? []);
      cur.has(vNum) ? cur.delete(vNum) : cur.add(vNum);
      return { ...prev, [tourId]: cur };
    });
  }

  if (loading) {
    return (
      <div style={{ display: "flex", height: "100vh", background: A.bg, fontFamily: sans }}>
        <AdminSidebar />
        <main style={{ flex: 1, padding: "32px 36px" }}>
          <LoadingScreen msg="Loading master content…" />
        </main>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "100vh", background: A.bg, fontFamily: sans, overflow: "hidden" }}>
      <AdminSidebar />

      {/* Main area: flex column, fills height */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        {/* ── Section 1: Page header + Stats (fixed) ──────────────────────── */}
        <div style={{ flexShrink: 0, padding: "20px 32px 16px", background: A.bg, borderBottom: `1px solid ${A.line}` }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 16 }}>
            <div>
              <div style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: A.ink, letterSpacing: "-0.02em" }}>
                Master Content
              </div>
              <div style={{ fontSize: 12, color: A.muted, marginTop: 2 }}>
                aa_internal tenant · {AA_INTERNAL_ID.slice(0, 8)}…
              </div>
            </div>
            <Btn variant="secondary" size="sm" onClick={refresh} disabled={refreshing}>
              <RefreshCw size={13} style={{ animation: refreshing ? "spin 1s linear infinite" : "none" }} />
              {refreshing ? "Refreshing…" : "Refresh"}
            </Btn>
          </div>

          {error && (
            <div style={{ padding: "10px 14px", background: A.redSoft, color: A.red, borderRadius: 7, fontSize: 13, marginBottom: 12 }}>
              {error}
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
            <StatCard icon={<BarChart2 size={16} />}    label="Total Tours"    value={String(tours.length)}       sub={`↳ ${summary?.tours_view ?? tours.length} visible`} />
            <StatCard icon={<Star size={16} />}          label="Avg Quality"   value={avgScore.toFixed(1)}        sub="↳ quality_score avg" accent={scoreColor(avgScore)} />
            <StatCard icon={<DollarSign size={16} />}   label="Total LLM Cost" value={`$${(summary?.total_llm_cost_usd ?? 0).toFixed(4)}`} sub="↳ all pipeline runs" />
            <StatCard icon={<CalendarClock size={16} />} label="Pipeline Runs" value={String(runs.length)}        sub={`↳ ${summary?.pipeline_note ?? "pipeline_runs"}`} />
          </div>
        </div>

        {/* ── Section 2: Rewritten Tours (flex, scrollable) ───────────────── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", borderBottom: `2px solid ${A.line}` }}>
          {/* Sticky inner header */}
          <div style={{
            position: "sticky", top: 0, zIndex: 5, background: "#fff",
            padding: "10px 32px 8px", borderBottom: `1px solid ${A.line}`,
            display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexShrink: 0,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <SLabel style={{ margin: 0 }}>Rewritten Tours</SLabel>
              <span style={{ fontSize: 12, color: A.muted2 }}>
                {filtered.length < tours.length ? `${filtered.length} of ${tours.length}` : `${tours.length}`} tours
              </span>
            </div>

            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {/* Inline filters */}
              <input
                value={search}
                onChange={e => handleSearch(e.target.value)}
                placeholder="Search name or country…"
                style={{ padding: "5px 10px", border: `1px solid ${A.line}`, borderRadius: 6, fontSize: 12, fontFamily: sans, width: 180, background: "#fff", color: A.ink, outline: "none" }}
              />
              <select value={statusFilter} onChange={e => handleStatusFilter(e.target.value)}
                style={{ padding: "5px 8px", border: `1px solid ${A.line}`, borderRadius: 6, fontSize: 12, fontFamily: sans, background: "#fff", color: A.ink }}>
                <option value="">All Status</option>
                {statusOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <select value={countryFilter} onChange={e => { setCountryFilter(e.target.value); setPage(1); }}
                style={{ padding: "5px 8px", border: `1px solid ${A.line}`, borderRadius: 6, fontSize: 12, fontFamily: sans, background: "#fff", color: A.ink }}>
                <option value="">All Countries</option>
                {countryOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <select value={scoreFilter} onChange={e => { setScoreFilter(e.target.value); setPage(1); }}
                style={{ padding: "5px 8px", border: `1px solid ${A.line}`, borderRadius: 6, fontSize: 12, fontFamily: sans, background: "#fff", color: A.ink }}>
                <option value="">All Scores</option>
                {scoreOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <select value={versionFilter} onChange={e => { setVersionFilter(e.target.value); setPage(1); }}
                style={{ padding: "5px 8px", border: `1px solid ${A.line}`, borderRadius: 6, fontSize: 12, fontFamily: sans, background: "#fff", color: A.ink }}>
                <option value="">All Versions</option>
                {versionOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>

              {/* Compare + export */}
              {selectedIds.size >= 2 && selectedIds.size <= 4 && (
                <Btn variant="secondary" size="sm" onClick={() => setCompareOpen(true)}>
                  Compare ({selectedIds.size})
                </Btn>
              )}
              {selectedIds.size > 0 && (
                <button onClick={() => setSelectedIds(new Set())}
                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: A.muted, padding: "4px 8px" }}>
                  Clear ({selectedIds.size})
                </button>
              )}
              <div style={{ display: "inline-flex" }}>
                <Btn variant="secondary" size="sm" disabled={exporting} onClick={() => exportTours("csv")}
                  style={{ borderRadius: "6px 0 0 6px", borderRight: "none" }}>
                  <Download size={12} /> {exporting ? "…" : "CSV"}
                </Btn>
                <Btn variant="secondary" size="sm" disabled={exporting} onClick={() => exportTours("xlsx")}
                  style={{ borderRadius: "0 6px 6px 0" }}>
                  XLSX
                </Btn>
              </div>
            </div>
          </div>

          {/* Scrollable table area */}
          <div style={{ flex: 1, overflowY: "auto" }}>
            {filtered.length === 0 ? (
              <div style={{ padding: 40, textAlign: "center" as const, color: A.muted, fontSize: 13 }}>
                {search || statusFilter || countryFilter || scoreFilter || versionFilter
                  ? "No tours match your filters"
                  : "No rewritten tours found"}
              </div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead style={{ position: "sticky", top: 0, zIndex: 2, background: A.bg }}>
                  <tr>
                    <th style={{ ...TH, width: 36, paddingLeft: 16 }}>
                      <input
                        type="checkbox"
                        checked={paginated.length > 0 && paginated.filter(t => t.tour_id).every(t => selectedIds.has(t.tour_id!))}
                        onChange={e => {
                          if (e.target.checked) {
                            setSelectedIds(new Set([...selectedIds, ...paginated.filter(t => t.tour_id).map(t => t.tour_id!)]));
                          } else {
                            setSelectedIds(new Set([...selectedIds].filter(id => !paginated.some(t => t.tour_id === id))));
                          }
                        }}
                        style={{ accentColor: A.gold }}
                      />
                    </th>
                    <th style={TH}>#</th>
                    <th style={TH}>Tour Name</th>
                    <th style={TH}>Country</th>
                    <th style={TH}>Score</th>
                    <th style={TH}>Versions</th>
                    <th style={TH}>Status</th>
                    <th style={TH}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {paginated.map((t, i) => {
                    const absIdx = (page - 1) * PAGE_SIZE + i;
                    const isExpanded = t.tour_id ? expandedTours.has(t.tour_id) : false;
                    const isSelected = t.tour_id ? selectedIds.has(t.tour_id) : false;
                    const versions   = t.tour_id ? (tourVersions[t.tour_id] ?? []) : [];
                    const vLoading   = t.tour_id ? (versionLoading[t.tour_id] ?? false) : false;
                    const vSel       = t.tour_id ? (compareVersionSel[t.tour_id] ?? new Set<number>()) : new Set<number>();
                    return (
                      <React.Fragment key={t.version_id}>
                        <tr style={{
                          background: isExpanded ? `${A.gold}14` : isSelected ? `${A.gold}10` : absIdx % 2 === 0 ? "#fff" : A.bg,
                          borderBottom: isExpanded ? "none" : undefined,
                        }}>
                          <td style={{ ...TD, paddingLeft: 16 }} onClick={e => e.stopPropagation()}>
                            {t.tour_id && (
                              <input type="checkbox" checked={isSelected} onChange={() => toggleSelect(t.tour_id!)} style={{ accentColor: A.gold }} />
                            )}
                          </td>
                          <td style={{ ...TD, color: A.muted2 }}>{absIdx + 1}</td>
                          <td style={{ ...TD, fontWeight: 600, color: A.ink, fontFamily: serif }}>{t.tour_name}</td>
                          <td style={TD}>{t.country || "—"}</td>
                          <td style={TD}>
                            <span style={{ fontFamily: mono, fontWeight: 700, fontSize: 15, color: scoreColor(t.quality_score) }}>
                              {t.quality_score != null ? t.quality_score.toFixed(1) : "—"}
                            </span>
                          </td>
                          <td style={TD}>
                            {t.version_number != null
                              ? <Badge color="blue">v{t.version_number}</Badge>
                              : <span style={{ color: A.muted2, fontSize: 12 }}>—</span>}
                          </td>
                          <td style={TD}>{statusBadge(t.status)}</td>
                          <td style={TD}>
                            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                              <button
                                onClick={() => { if (t.tour_id) { setDetailTourId(t.tour_id); setDetailTourName(t.tour_name); } }}
                                style={{ padding: "3px 8px", fontSize: 11, border: `1px solid ${A.line}`, borderRadius: 5, background: "#fff", cursor: "pointer", color: A.body }}
                              >View</button>
                              {t.tour_id && (
                                <button
                                  onClick={() => toggleExpand(t.tour_id!)}
                                  style={{ padding: "3px 8px", fontSize: 11, border: `1px solid ${A.line}`, borderRadius: 5, background: isExpanded ? `${A.gold}22` : "#fff", cursor: "pointer", color: A.gold, display: "flex", alignItems: "center", gap: 3 }}
                                >
                                  {isExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />} Versions
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr style={{ background: `${A.gold}08` }}>
                            <td colSpan={8} style={{ padding: "0 0 0 48px", borderBottom: `1px solid ${A.line}` }}>
                              {vLoading ? (
                                <div style={{ padding: "12px 16px", fontSize: 12, color: A.muted }}>Loading versions…</div>
                              ) : versions.length === 0 ? (
                                <div style={{ padding: "12px 16px", fontSize: 12, color: A.muted }}>No versions found</div>
                              ) : (
                                <>
                                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                                    <thead>
                                      <tr style={{ background: A.line2 }}>
                                        {["", "Version", "Model", "Score", "Date", ""].map((h, hi) => (
                                          <th key={hi} style={{ padding: "6px 10px", textAlign: "left" as const, fontSize: 10, fontWeight: 600, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.08em" }}>{h}</th>
                                        ))}
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {versions.map(v => (
                                        <tr key={v.id} style={{ borderTop: `1px solid ${A.line}`, background: v.is_current ? "#FEFCE8" : "transparent" }}>
                                          <td style={{ padding: "6px 10px", width: 32 }}>
                                            <input
                                              type="checkbox"
                                              checked={vSel.has(v.version_num)}
                                              onChange={() => t.tour_id && toggleVersionSel(t.tour_id, v.version_num)}
                                              disabled={!vSel.has(v.version_num) && vSel.size >= 2}
                                              style={{ accentColor: A.gold }}
                                            />
                                          </td>
                                          <td style={{ padding: "6px 10px" }}>
                                            <span style={{ padding: "2px 7px", borderRadius: 10, background: v.is_current ? A.gold : A.goldTint, color: v.is_current ? "#fff" : A.gold, fontSize: 11, fontWeight: 600 }}>
                                              v{v.version_num}
                                            </span>
                                            {v.is_current && <span style={{ marginLeft: 6, fontSize: 10, color: A.gold }}>current</span>}
                                          </td>
                                          <td style={{ padding: "6px 10px", fontFamily: mono, fontSize: 11, color: A.muted2 }}>
                                            {v.model_id?.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? "—"}
                                          </td>
                                          <td style={{ padding: "6px 10px", fontWeight: 700, color: scoreColor(v.quality_score) }}>
                                            {v.quality_score != null ? v.quality_score.toFixed(1) : "—"}
                                          </td>
                                          <td style={{ padding: "6px 10px", color: A.muted2 }}>
                                            {v.created_at ? relDate(v.created_at) : "—"}
                                          </td>
                                          <td style={{ padding: "6px 10px" }}>
                                            <div style={{ display: "flex", gap: 5 }}>
                                              <button
                                                onClick={() => { if (t.tour_id) { setDetailTourId(t.tour_id); setDetailTourName(t.tour_name); } }}
                                                style={{ padding: "2px 7px", fontSize: 11, border: `1px solid ${A.line}`, borderRadius: 4, background: "#fff", cursor: "pointer", color: A.body }}
                                              >View</button>
                                              {!v.is_current && (
                                                <button
                                                  onClick={() => t.tour_id && promoteVersion(t.tour_id, t.tour_name, v.version_num)}
                                                  disabled={promoting === `${t.tour_id}-${v.version_num}`}
                                                  style={{ padding: "2px 7px", fontSize: 11, border: `1px solid ${A.gold}`, borderRadius: 4, background: A.goldTint, cursor: "pointer", color: A.gold, fontWeight: 600 }}
                                                >
                                                  {promoting === `${t.tour_id}-${v.version_num}` ? "…" : "Promote"}
                                                </button>
                                              )}
                                            </div>
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                  {vSel.size === 2 && t.tour_id && (
                                    <div style={{ padding: "8px 12px", borderTop: `1px solid ${A.line}`, display: "flex", alignItems: "center", gap: 10 }}>
                                      <span style={{ fontSize: 12, color: A.muted }}>
                                        v{[...vSel].sort((a,b)=>a-b).join(" vs v")} selected
                                      </span>
                                      <button
                                        onClick={() => {
                                          const nums = [...vSel].sort((a,b)=>a-b) as [number, number];
                                          setCompareVersionOpen({ tourId: t.tour_id!, tourName: t.tour_name, vNums: nums });
                                        }}
                                        style={{ padding: "4px 12px", fontSize: 12, fontWeight: 600, border: `1px solid ${A.gold}`, borderRadius: 6, background: A.goldTint, cursor: "pointer", color: A.gold }}
                                      >
                                        Compare Versions
                                      </button>
                                      <button
                                        onClick={() => t.tour_id && setCompareVersionSel(p => ({ ...p, [t.tour_id!]: new Set() }))}
                                        style={{ fontSize: 11, color: A.muted2, background: "none", border: "none", cursor: "pointer" }}
                                      >Clear</button>
                                    </div>
                                  )}
                                </>
                              )}
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            )}
            {filtered.length > PAGE_SIZE && (
              <div style={{ padding: "12px 20px", borderTop: `1px solid ${A.line}`, display: "flex", justifyContent: "flex-end" }}>
                <Pagination page={page} total={filtered.length} pageSize={PAGE_SIZE} onPage={setPage} />
              </div>
            )}
          </div>
        </div>

        {/* ── Section 3: Pipeline Runs (fixed height) ──────────────────────── */}
        <div style={{ height: 280, display: "flex", flexDirection: "column", flexShrink: 0 }}>
          {/* Sticky section header */}
          <div style={{ padding: "8px 32px 6px", borderBottom: `1px solid ${A.line}`, flexShrink: 0, background: "#fff" }}>
            <SLabel style={{ margin: 0 }}>Recent Pipeline Runs</SLabel>
          </div>
          {runs.length === 0 ? (
            <div style={{ padding: "16px 32px", fontSize: 12, color: A.muted }}>No pipeline runs found.</div>
          ) : (
            <div style={{ flex: 1, overflowY: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead style={{ position: "sticky", top: 0, background: A.bg, zIndex: 2 }}>
                  <tr>
                    <th style={TH}>Run ID</th>
                    <th style={TH}>Date</th>
                    <th style={TH}>Processed</th>
                    <th style={TH}>Passed</th>
                    <th style={TH}>Model</th>
                    <th style={TH}>Cost</th>
                    <th style={TH}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedRuns.map((r, i) => (
                    <tr key={r.run_id} style={{ background: i % 2 === 0 ? "#fff" : A.bg }}>
                      <td style={{ ...TD, fontFamily: mono, fontSize: 11, color: A.muted2 }}>{r.run_id.slice(0, 8)}…</td>
                      <td style={{ ...TD, fontSize: 11, color: A.muted2 }}>{relDate(r.started_at)}</td>
                      <td style={TD}>{r.tours_processed}</td>
                      <td style={{ ...TD, color: A.green, fontWeight: 600 }}>{r.tours_passed}</td>
                      <td style={{ ...TD, fontFamily: mono, fontSize: 11 }}>{r.llm_model?.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? "—"}</td>
                      <td style={{ ...TD, color: A.gold, fontWeight: 600 }}>${(r.llm_cost_usd ?? 0).toFixed(4)}</td>
                      <td style={TD}>
                        <Badge color={r.status === "completed" ? "green" : r.status === "failed" ? "red" : "amber"}>{r.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {runs.length > RUNS_PAGE_SIZE && (
                <div style={{ padding: "8px 20px", borderTop: `1px solid ${A.line}`, display: "flex", justifyContent: "flex-end" }}>
                  <Pagination page={runsPage} total={runs.length} pageSize={RUNS_PAGE_SIZE} onPage={setRunsPage} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Detail panel v2 */}
      {detailTourId && (
        <TourDetailPanelV2
          tourId={detailTourId}
          tourName={detailTourName}
          onClose={() => setDetailTourId(null)}
        />
      )}

      {/* Cross-tour compare modal */}
      {compareOpen && (
        <CompareModal
          tourIds={[...selectedIds]}
          onClose={() => setCompareOpen(false)}
        />
      )}

      {/* Version compare modal (full-screen) */}
      {compareVersionOpen && (
        <VersionCompareModal
          tourId={compareVersionOpen.tourId}
          tourName={compareVersionOpen.tourName}
          versionNums={compareVersionOpen.vNums}
          onClose={() => setCompareVersionOpen(null)}
        />
      )}
    </div>
  );
}
