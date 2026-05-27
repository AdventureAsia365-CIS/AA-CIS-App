"use client";
// app/admin/master-content/page.tsx
// GET /api/tenant/admin/tenants/AA_INTERNAL_ID/details → rewritten_tours, summary, pipeline_runs
// GET /api/admin/tours/{tour_id}/detail → detail panel

import React, { useState, useEffect, useCallback } from "react";
import { RefreshCw, ChevronDown, ChevronRight, Download } from "lucide-react";
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
  const [statusFilter, setStatusFilter] = useState("");
  const [exporting, setExporting]       = useState(false);
  const PAGE_SIZE = 25;

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

  const filtered = tours.filter(t =>
    (!search ||
      t.tour_name.toLowerCase().includes(search.toLowerCase()) ||
      (t.country || "").toLowerCase().includes(search.toLowerCase())) &&
    (!statusFilter || t.status === statusFilter)
  );
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

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

  if (loading) {
    return (
      <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
        <AdminSidebar />
        <main style={{ flex: 1, padding: "32px 36px" }}>
          <LoadingScreen msg="Loading master content…" />
        </main>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 28 }}>
          <div>
            <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, letterSpacing: "-0.02em" }}>
              Master Content
            </div>
            <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
              aa_internal tenant · {AA_INTERNAL_ID.slice(0, 8)}…
            </div>
          </div>
          <Btn variant="secondary" size="sm" onClick={refresh} disabled={refreshing}>
            <RefreshCw size={13} style={{ animation: refreshing ? "spin 1s linear infinite" : "none" }} />
            {refreshing ? "Refreshing…" : "Refresh"}
          </Btn>
        </div>

        {error && (
          <div style={{ padding: "12px 16px", background: A.redSoft, color: A.red, borderRadius: 8, fontSize: 13, marginBottom: 20 }}>
            {error}
          </div>
        )}

        {/* Summary cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 24 }}>
          <StatCard icon={<BarChart2 size={16} />}    label="Total Tours"    value={String(tours.length)}       sub={`↳ rewritten_tours · ${summary?.tours_view ?? tours.length} visible`} />
          <StatCard icon={<Star size={16} />}          label="Avg Quality"   value={avgScore.toFixed(1)}        sub="↳ quality_score avg" accent={scoreColor(avgScore)} />
          <StatCard icon={<DollarSign size={16} />}   label="Total LLM Cost" value={`$${(summary?.total_llm_cost_usd ?? 0).toFixed(4)}`} sub="↳ summary.total_llm_cost_usd" />
          <StatCard icon={<CalendarClock size={16} />} label="Pipeline Runs" value={String(runs.length)}        sub={`↳ ${summary?.pipeline_note ?? "pipeline_runs"}`} />
        </div>

        {/* Toolbar: filter + compare + export */}
        <FilterBar
          search={search}
          onSearch={handleSearch}
          placeholder="Search by tour name or country…"
          filters={[{
            label: "Status", value: "status", current: statusFilter,
            options: statusOptions, onChange: handleStatusFilter,
          }]}
          extra={
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {selectedIds.size >= 2 && selectedIds.size <= 4 && (
                <Btn variant="secondary" size="sm" onClick={() => setCompareOpen(true)}>
                  Compare ({selectedIds.size})
                </Btn>
              )}
              {selectedIds.size > 0 && (
                <button
                  onClick={() => setSelectedIds(new Set())}
                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: A.muted, padding: "4px 8px" }}
                >
                  Clear ({selectedIds.size})
                </button>
              )}
              <div style={{ position: "relative", display: "inline-flex" }}>
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
          }
        />

        {/* Tours table */}
        <Card style={{ padding: 0, marginBottom: 28 }}>
          <div style={{ padding: "14px 20px 10px", borderBottom: `1px solid ${A.line}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <SLabel>Rewritten Tours — aa_internal</SLabel>
            <span style={{ fontSize: 12, color: A.muted2 }}>{tours.length} total</span>
          </div>
          {filtered.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center" as const, color: A.muted, fontSize: 13 }}>
              {search || statusFilter ? "No tours match your filters" : "No rewritten tours found"}
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
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
                    return (
                      <React.Fragment key={t.version_id}>
                        <tr style={{
                          background: isExpanded ? `${A.gold}14` : isSelected ? `${A.gold}10` : absIdx % 2 === 0 ? "#fff" : A.bg,
                          borderBottom: isExpanded ? "none" : undefined,
                        }}>
                          <td style={{ ...TD, paddingLeft: 16 }} onClick={e => e.stopPropagation()}>
                            {t.tour_id && (
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => toggleSelect(t.tour_id!)}
                                style={{ accentColor: A.gold }}
                              />
                            )}
                          </td>
                          <td style={{ ...TD, color: A.muted2 }}>{absIdx + 1}</td>
                          <td style={{ ...TD, fontWeight: 600, color: A.ink, fontFamily: serif }}>
                            {t.tour_name}
                          </td>
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
                          <td style={{ ...TD }}>
                            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                              <button
                                onClick={() => { if (t.tour_id) { setDetailTourId(t.tour_id); setDetailTourName(t.tour_name); } }}
                                style={{ padding: "3px 8px", fontSize: 11, border: `1px solid ${A.line}`, borderRadius: 5, background: "#fff", cursor: "pointer", color: A.body }}
                              >
                                View
                              </button>
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
                                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                                  <thead>
                                    <tr style={{ background: A.line2 }}>
                                      {["Version", "Model", "Score", "Date", ""].map(h => (
                                        <th key={h} style={{ padding: "6px 10px", textAlign: "left" as const, fontSize: 10, fontWeight: 600, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.08em" }}>{h}</th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {versions.map(v => (
                                      <tr key={v.id} style={{ borderTop: `1px solid ${A.line}`, background: v.is_current ? "#FEFCE8" : "transparent" }}>
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
                              )}
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
          {filtered.length > PAGE_SIZE && (
            <div style={{ padding: "14px 20px", borderTop: `1px solid ${A.line}`, display: "flex", justifyContent: "flex-end" }}>
              <Pagination page={page} total={filtered.length} pageSize={PAGE_SIZE} onPage={setPage} />
            </div>
          )}
        </Card>

        {/* Recent pipeline runs */}
        {runs.length > 0 && (
          <Card style={{ padding: 0 }}>
            <div style={{ padding: "14px 20px 10px", borderBottom: `1px solid ${A.line}` }}>
              <SLabel>Recent Pipeline Runs</SLabel>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
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
                  {runs.slice(0, 10).map((r, i) => (
                    <tr key={r.run_id} style={{ background: i % 2 === 0 ? "#fff" : A.bg }}>
                      <td style={{ ...TD, fontFamily: mono, fontSize: 11, color: A.muted2 }}>
                        {r.run_id.slice(0, 8)}…
                      </td>
                      <td style={{ ...TD, fontSize: 12, color: A.muted2 }}>{relDate(r.started_at)}</td>
                      <td style={TD}>{r.tours_processed}</td>
                      <td style={{ ...TD, color: A.green, fontWeight: 600 }}>{r.tours_passed}</td>
                      <td style={{ ...TD, fontFamily: mono, fontSize: 11 }}>
                        {r.llm_model?.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? "—"}
                      </td>
                      <td style={{ ...TD, color: A.gold, fontWeight: 600 }}>${(r.llm_cost_usd ?? 0).toFixed(4)}</td>
                      <td style={TD}>
                        <Badge color={r.status === "completed" ? "green" : r.status === "failed" ? "red" : "amber"}>
                          {r.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </main>

      {/* Detail panel v2 (handles its own backdrop) */}
      {detailTourId && (
        <TourDetailPanelV2
          tourId={detailTourId}
          tourName={detailTourName}
          onClose={() => setDetailTourId(null)}
        />
      )}

      {/* Compare modal */}
      {compareOpen && (
        <CompareModal
          tourIds={[...selectedIds]}
          onClose={() => setCompareOpen(false)}
        />
      )}
    </div>
  );
}
