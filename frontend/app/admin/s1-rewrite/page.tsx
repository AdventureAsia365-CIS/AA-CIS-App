"use client";
// app/admin/s1-rewrite/page.tsx — Admin S1 Rewrite stage
// GET  /api/admin/tours-ready          → tours with pipeline_status='ingested'
// POST /api/admin/run-tour             → trigger rewrite for one tour
// PATCH /api/admin/tours/{id}/country  → manual country correction

import React, { useState, useEffect, useCallback } from "react";
import { Play, RefreshCw, ArrowRight, Search, CheckCircle, XCircle, Loader2 } from "lucide-react";
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

// ── Types ─────────────────────────────────────────────────────────────────────

interface ReadyTour {
  tour_id: string;
  src_name: string;
  country: string | null;
  ingest_at: string | null;
  source_id: string | null;
  batch_id: string | null;
  filename: string | null;
}

type TourRunStatus = "idle" | "running" | "done" | "failed";

interface RunResult {
  tour_id: string;
  status: string;
  quality_score: number | null;
  version_id: string | null;
  error?: string;
}

// ── Status badge ──────────────────────────────────────────────────────────────

function TourStatusBadge({ status, result }: { status: TourRunStatus; result?: RunResult }) {
  if (status === "running") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: A.amber }}>
        <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} /> Processing…
      </span>
    );
  }
  if (status === "done") {
    const score = result?.quality_score;
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: A.green }}>
        <CheckCircle size={12} /> Done{score != null ? ` · ${score.toFixed(1)}` : ""}
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: A.red }} title={result?.error}>
        <XCircle size={12} /> Failed
      </span>
    );
  }
  return <Badge color="gray">Ready</Badge>;
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function S1RewritePage() {
  const [tours, setTours]                 = useState<ReadyTour[]>([]);
  const [loading, setLoading]             = useState(true);
  const [selectedIds, setSelectedIds]     = useState<Set<string>>(new Set());
  const [filterCountry, setFilterCountry] = useState("");
  const [filterFile, setFilterFile]       = useState("");
  const [filterSearch, setFilterSearch]   = useState("");
  const [seoMode, setSeoMode]             = useState("dataforseo");
  const [modelTier, setModelTier]         = useState("haiku");
  const [subtitleFocus, setSubtitleFocus] = useState("standard");
  const [showConfirm, setShowConfirm]     = useState(false);
  const [running, setRunning]             = useState(false);
  const [tourStatuses, setTourStatuses]   = useState<Record<string, TourRunStatus>>({});
  const [runResults, setRunResults]       = useState<Record<string, RunResult>>({});
  const [runComplete, setRunComplete]     = useState(false);

  const loadTours = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/admin/tours-ready");
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setTours(data.tours || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadTours(); }, [loadTours]);

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

  function toggleTour(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function selectAll()   { setSelectedIds(new Set(filteredTours.map(t => t.tour_id))); }
  function deselectAll() { setSelectedIds(new Set()); }

  const selectedTours = tours.filter(t => selectedIds.has(t.tour_id));

  async function runSingleTour(tour: ReadyTour): Promise<void> {
    setTourStatuses(prev => ({ ...prev, [tour.tour_id]: "running" }));
    try {
      const res = await fetch("/api/admin/run-tour", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tour_id:       tour.tour_id,
          batch_id:      tour.batch_id || TENANT_ID,
          tenant_id:     TENANT_ID,
          seo_mode:      seoMode,
          model_tier:    modelTier,
          subtitle_focus: subtitleFocus,
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

  if (loading) {
    return (
      <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
        <AdminSidebar />
        <main style={{ flex: 1, padding: "32px 36px" }}>
          <LoadingScreen msg="Loading tours ready for rewrite…" />
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
              Select tours to rewrite with AI — {tours.length} ready
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
            <div style={{ fontSize: 15, color: A.muted, marginBottom: 14 }}>
              No tours ready for rewrite.
            </div>
            <div style={{ fontSize: 13, color: A.muted2, marginBottom: 20 }}>
              Upload Excel files in Upload (S0) first.
            </div>
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
                  <th style={TH}>Ingested</th>
                  <th style={TH}>Status</th>
                </tr>
              </thead>
              <tbody>
                {filteredTours.map((t, i) => {
                  const status = tourStatuses[t.tour_id] || "idle";
                  const result = runResults[t.tour_id];
                  const isSelected = selectedIds.has(t.tour_id);
                  return (
                    <tr
                      key={t.tour_id}
                      onClick={() => !running && toggleTour(t.tour_id)}
                      style={{
                        borderTop: i > 0 ? `1px solid ${A.line}` : undefined,
                        background: isSelected ? `${A.gold}12` : "transparent",
                        cursor: running ? "default" : "pointer",
                        transition: "background .12s",
                      }}
                    >
                      <td style={{ ...TD, paddingLeft: 16 }}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => !running && toggleTour(t.tour_id)}
                          onClick={e => e.stopPropagation()}
                          style={{ accentColor: A.gold }}
                        />
                      </td>
                      <td style={{ ...TD, fontWeight: 500, color: A.ink }}>{t.src_name}</td>
                      <td style={TD}>
                        <span style={{ color: t.country ? A.body : A.muted2 }}>{t.country || "—"}</span>
                      </td>
                      <td style={TD}>
                        <span style={{ fontFamily: mono, fontSize: 12, color: A.muted }}>
                          {stripUuidPrefix(t.filename)}
                        </span>
                      </td>
                      <td style={{ ...TD, color: A.muted2 }}>{relativeTime(t.ingest_at)}</td>
                      <td style={TD}><TourStatusBadge status={status} result={result} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        )}

        {/* Config + Run panel — shown when tours are selected */}
        {selectedIds.size > 0 && (
          <Card style={{ marginBottom: 20 }}>
            <SLabel>Rewrite Config</SLabel>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 12, alignItems: "flex-end" }}>
              <div>
                <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>SEO Mode</label>
                <select
                  value={seoMode}
                  onChange={e => setSeoMode(e.target.value)}
                  disabled={running}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }}
                >
                  <option value="dataforseo">Standard (DataForSEO)</option>
                  <option value="informational">Informational (mock)</option>
                  <option value="disabled">Disabled</option>
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
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>Subtitle Focus</label>
                <select
                  value={subtitleFocus}
                  onChange={e => setSubtitleFocus(e.target.value)}
                  disabled={running}
                  style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }}
                >
                  <option value="standard">Standard</option>
                  <option value="experience">Experience</option>
                  <option value="destination">Destination</option>
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
            <Card style={{ maxWidth: 400, width: "90%", padding: 28 }}>
              <div style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink, marginBottom: 12 }}>
                Confirm Rewrite
              </div>
              <div style={{ fontSize: 14, color: A.body, marginBottom: 20, lineHeight: 1.6 }}>
                This will rewrite{" "}
                <strong>{selectedIds.size} tour{selectedIds.size !== 1 ? "s" : ""}</strong>{" "}
                using <strong>{seoMode === "dataforseo" ? "Standard SEO" : seoMode}</strong> mode
                with <strong>{modelTier === "haiku" ? "Haiku 4.5" : "Sonnet 4.5"}</strong>. Continue?
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
  );
}
