"use client";
// app/admin/s1-rewrite/page.tsx — Admin S1 Rewrite v2
// GET  /api/admin/tours                   → all tours with rewrite_count
// GET  /api/admin/tours/{id}/history      → rewrite history
// GET  /api/admin/tours/{id}/detail       → raw + generated + published
// POST /api/admin/run-tour                → trigger rewrite

import React, { useState, useEffect, useCallback } from "react";
import { Play, RefreshCw, ArrowRight, Search, CheckCircle, XCircle, Loader2, ChevronRight } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Badge, Btn, LoadingScreen,
  TH, TD,
} from "../_components/adminUi";
import { TourDetailPanelV2 } from "../_components/TourDetailPanelV2";
import { CompareModal } from "../_components/CompareModal";
import { Pagination } from "../_components/Pagination";

const TENANT_ID = "00000000-0000-0000-0000-000000000001";
const PAGE_SIZE = 20;

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

interface BrandSummary {
  brand_name: string;
  brand_type: string | null;
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


// ── Pipeline status badge ─────────────────────────────────────────────────────

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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function S1RewritePage() {
  const [tours, setTours]                   = useState<Tour[]>([]);
  const [loading, setLoading]               = useState(true);
  const [selectedIds, setSelectedIds]       = useState<Set<string>>(new Set());
  const [filterCountry, setFilterCountry]   = useState("");
  const [filterFile, setFilterFile]         = useState("");
  const [filterStatus, setFilterStatus]     = useState("");
  const [filterSearch, setFilterSearch]     = useState("");
  const [page, setPage]                     = useState(1);
  const [seoMode, setSeoMode]               = useState("standard");
  const [modelTier, setModelTier]           = useState("haiku");
  const [brandList, setBrandList]           = useState<BrandSummary[]>([]);
  const [brandName, setBrandName]           = useState<string | null>(null);
  const [showConfirm, setShowConfirm]       = useState(false);
  const [running, setRunning]               = useState(false);
  const [tourStatuses, setTourStatuses]     = useState<Record<string, TourRunStatus>>({});
  const [runResults, setRunResults]         = useState<Record<string, RunResult>>({});
  const [runComplete, setRunComplete]       = useState(false);
  const [detailTour, setDetailTour]         = useState<Tour | null>(null);
  const [compareOpen, setCompareOpen]       = useState(false);

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

  const loadBrandList = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/brands");
      if (!res.ok) return;
      const data = await res.json();
      const list: BrandSummary[] = data.brands || [];
      setBrandList(list);
      const active = list.find(b => b.is_active) ?? list[0];
      if (active) setBrandName(active.brand_name);
    } catch {}
  }, []);

  useEffect(() => { loadTours(); loadBrandList(); }, [loadTours, loadBrandList]);

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
    if (filterStatus === "published" && t.pipeline_status !== "published") return false;
    if (filterStatus === "ready"     && t.pipeline_status === "published") return false;
    return true;
  });

  const paginatedTours = filteredTours.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  function handleFilterChange(setter: (v: string) => void, v: string) {
    setter(v);
    setPage(1);
  }

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
          brand_rules_version:  brandList.find(b => b.brand_name === brandName)?.version ?? null,
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

      {/* Right column: sticky config + scrollable main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        {/* ── Sticky Config Panel ─────────────────────────────────────────── */}
        <div style={{
          position: "sticky", top: 0, zIndex: 20,
          background: "#fff", borderBottom: `1px solid ${A.line}`,
          padding: "12px 36px",
        }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 12, alignItems: "flex-end" }}>
            <div>
              <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>Brand Identity</label>
              <select
                value={brandName ?? ""}
                onChange={e => setBrandName(e.target.value || null)}
                disabled={running}
                style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }}
              >
                {brandList.length === 0 && <option value="">No brand configured</option>}
                {brandList.map(b => (
                  <option key={b.brand_name} value={b.brand_name}>
                    {b.brand_name} · v{b.version}{b.is_active ? " (active)" : ""}
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
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
              {selectedIds.size >= 2 && selectedIds.size <= 4 && (
                <Btn
                  variant="secondary"
                  size="lg"
                  onClick={() => setCompareOpen(true)}
                  disabled={running}
                  style={{ whiteSpace: "nowrap" as const }}
                >
                  Compare ({selectedIds.size})
                </Btn>
              )}
              <Btn
                variant="primary"
                size="lg"
                disabled={running || selectedIds.size === 0}
                onClick={() => setShowConfirm(true)}
                style={{
                  background: (running || selectedIds.size === 0) ? A.muted : A.gold,
                  border: `1px solid ${(running || selectedIds.size === 0) ? A.muted : A.gold}`,
                  display: "flex", alignItems: "center", gap: 8,
                  whiteSpace: "nowrap" as const,
                  opacity: selectedIds.size === 0 ? 0.5 : 1,
                }}
              >
                <Play size={14} />
                {running ? "Running…" : `Run Rewrite${selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}`}
              </Btn>
            </div>
          </div>
        </div>

        {/* ── Scrollable Content ──────────────────────────────────────────── */}
        <main style={{ flex: 1, padding: "24px 36px 56px", overflowY: "auto" }}>

          {/* Header */}
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20 }}>
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
                onChange={e => handleFilterChange(setFilterCountry, e.target.value)}
                style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff", minWidth: 140 }}
              >
                <option value="">All Countries</option>
                {uniqueCountries.map(c => <option key={c} value={c}>{c}</option>)}
              </select>

              <select
                value={filterFile}
                onChange={e => handleFilterChange(setFilterFile, e.target.value)}
                style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff", minWidth: 180 }}
              >
                <option value="">All Files</option>
                {uniqueFiles.map(f => <option key={f} value={f}>{stripUuidPrefix(f)}</option>)}
              </select>

              <select
                value={filterStatus}
                onChange={e => handleFilterChange(setFilterStatus, e.target.value)}
                style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff", minWidth: 130 }}
              >
                <option value="">All Status</option>
                <option value="published">Published</option>
                <option value="ready">Ready</option>
              </select>

              <div style={{ display: "flex", alignItems: "center", gap: 6, border: `1px solid ${A.line}`, borderRadius: 6, padding: "6px 10px", background: "#fff", flex: 1, minWidth: 200 }}>
                <Search size={13} style={{ color: A.muted2, flexShrink: 0 }} />
                <input
                  placeholder="Search by tour name…"
                  value={filterSearch}
                  onChange={e => handleFilterChange(setFilterSearch, e.target.value)}
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
                <thead style={{ position: "sticky", top: 0, zIndex: 2 }}>
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
                  {paginatedTours.map((t, i) => {
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
              {filteredTours.length > PAGE_SIZE && (
                <div style={{ padding: "12px 20px", borderTop: `1px solid ${A.line}`, display: "flex", justifyContent: "flex-end" }}>
                  <Pagination page={page} total={filteredTours.length} pageSize={PAGE_SIZE} onPage={setPage} />
                </div>
              )}
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
                  {brandName ? ` (Brand: ${brandName})` : ""}. Continue?
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
      </div>

      {/* Detail panel v2 (handles its own backdrop) */}
      {detailTour && (
        <TourDetailPanelV2
          tourId={detailTour.tour_id}
          tourName={detailTour.src_name}
          rewriteCount={detailTour.rewrite_count}
          onClose={() => setDetailTour(null)}
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
