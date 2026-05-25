"use client";
// app/admin/master-content/page.tsx
// GET /api/tenant/admin/tenants/AA_INTERNAL_ID/details → rewritten_tours, summary, pipeline_runs
// GET /api/admin/tours/{tour_id}/detail → slide-in panel

import React, { useState, useEffect } from "react";
import { RefreshCw, X, ChevronRight } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Badge, Btn, LoadingScreen, StatCard, TH, TD,
} from "../_components/adminUi";
import { BarChart2, Star, DollarSign, CalendarClock } from "lucide-react";

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

interface TourDetail {
  raw: {
    src_name: string;
    src_subtitle: string | null;
    src_summary: string | null;
    src_highlights: string[] | null;
    src_itineraries: string | null;
    country: string | null;
    duration: string | null;
    price_raw: string | null;
    group_size: string | null;
    pipeline_status: string;
  };
  generated: {
    id: string;
    version_num: number;
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

// ── Tour detail panel ─────────────────────────────────────────────────────────

function TourDetailPanel({ tourId, tourName, onClose }: {
  tourId: string;
  tourName: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<TourDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/admin/tours/${tourId}/detail`)
      .then(r => r.json())
      .then(setDetail)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tourId]);

  const highlights = (arr: string[] | null | undefined): string[] => arr ?? [];
  const keywords = (arr: string[] | null | undefined): string[] => arr ?? [];

  const ScoreBar = ({ label, score }: { label: string; score: number | null }) => (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: A.muted }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 700, fontFamily: mono, color: scoreColor(score) }}>
          {score != null ? score.toFixed(1) : "—"}
        </span>
      </div>
      <div style={{ height: 5, background: A.line, borderRadius: 3 }}>
        <div style={{
          height: "100%", borderRadius: 3,
          width: score != null ? `${Math.min(score / 10 * 100, 100)}%` : "0%",
          background: scoreColor(score),
          transition: "width .3s",
        }} />
      </div>
    </div>
  );

  return (
    <div style={{
      position: "fixed", top: 0, right: 0, bottom: 0,
      width: 650, background: "#fff",
      boxShadow: "-4px 0 32px rgba(0,0,0,0.12)",
      zIndex: 200, display: "flex", flexDirection: "column",
      fontFamily: sans,
    }}>
      {/* Header */}
      <div style={{ padding: "20px 24px", borderBottom: `1px solid ${A.line}`, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ flex: 1, paddingRight: 12 }}>
          <div style={{ fontFamily: serif, fontSize: 17, fontWeight: 600, color: A.ink, lineHeight: 1.3 }}>
            {detail?.generated?.aa_name || tourName}
          </div>
          <div style={{ fontSize: 12, color: A.muted, marginTop: 3, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {detail?.raw?.country && <Badge color="blue">{detail.raw.country}</Badge>}
            {detail?.generated?.score_overall != null && (
              <span style={{ fontWeight: 700, color: scoreColor(detail.generated.score_overall) }}>
                ★ {detail.generated.score_overall.toFixed(1)}
              </span>
            )}
            {detail?.published?.published_at && (
              <span>Published {relDate(detail.published.published_at)}</span>
            )}
          </div>
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted, padding: 4 }}>
          <X size={18} />
        </button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
        {loading ? (
          <div style={{ textAlign: "center", padding: 40, color: A.muted }}>Loading…</div>
        ) : !detail ? (
          <div style={{ textAlign: "center", padding: 40, color: A.red }}>Failed to load detail</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>

            {/* Published Content */}
            {detail.generated && (
              <div>
                <SLabel>Published Content</SLabel>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  {detail.generated.aa_subtitle && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 4 }}>Subtitle</div>
                      <div style={{ fontSize: 14, fontStyle: "italic", color: A.body }}>{detail.generated.aa_subtitle}</div>
                    </div>
                  )}
                  {detail.generated.aa_summary && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 4 }}>Summary</div>
                      <div style={{ fontSize: 13, color: A.body, lineHeight: 1.6 }}>{detail.generated.aa_summary}</div>
                    </div>
                  )}
                  {highlights(detail.generated.aa_highlights).length > 0 && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 6 }}>Highlights</div>
                      <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
                        {highlights(detail.generated.aa_highlights).map((h, i) => (
                          <li key={i} style={{ fontSize: 13, color: A.body }}>{h}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {detail.generated.aa_itineraries && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 6 }}>Itineraries</div>
                      <div style={{ fontSize: 12, color: A.body, lineHeight: 1.7, whiteSpace: "pre-wrap", background: A.bg, padding: 12, borderRadius: 8, maxHeight: 220, overflowY: "auto" }}>
                        {detail.generated.aa_itineraries}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* SEO */}
            {detail.generated && (detail.generated.seo_title || detail.generated.seo_meta) && (
              <div style={{ borderTop: `1px solid ${A.line}`, paddingTop: 20 }}>
                <SLabel>SEO</SLabel>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {detail.generated.seo_title && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 3 }}>
                        Title <span style={{ color: detail.generated.seo_title.length > 60 ? A.amber : A.muted2 }}>({detail.generated.seo_title.length}/70)</span>
                      </div>
                      <div style={{ fontSize: 13, color: A.ink }}>{detail.generated.seo_title}</div>
                    </div>
                  )}
                  {detail.generated.seo_meta && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 3 }}>
                        Meta <span style={{ color: detail.generated.seo_meta.length > 155 ? A.amber : A.muted2 }}>({detail.generated.seo_meta.length}/170)</span>
                      </div>
                      <div style={{ fontSize: 13, color: A.body }}>{detail.generated.seo_meta}</div>
                    </div>
                  )}
                  {keywords(detail.generated.seo_keywords_used).length > 0 && (
                    <div>
                      <div style={{ fontSize: 11, color: A.muted, marginBottom: 6 }}>Keywords</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {keywords(detail.generated.seo_keywords_used).map((kw, i) => (
                          <span key={i} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 12, background: A.goldTint, color: A.gold, border: `1px solid ${A.line}` }}>{kw}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Quality Scores */}
            {detail.generated && (
              <div style={{ borderTop: `1px solid ${A.line}`, paddingTop: 20 }}>
                <SLabel>Quality Scores</SLabel>
                <ScoreBar label="Overall" score={detail.generated.score_overall} />
                <ScoreBar label="Brand" score={detail.generated.score_brand} />
                <ScoreBar label="SEO" score={detail.generated.score_seo} />
                <ScoreBar label="Structure" score={detail.generated.score_structure} />
              </div>
            )}

            {/* Footer actions */}
            <div style={{ borderTop: `1px solid ${A.line}`, paddingTop: 16, display: "flex", gap: 10, alignItems: "center" }}>
              <Btn
                size="sm"
                variant="primary"
                onClick={() => window.location.href = `/admin/s1-rewrite?tour_id=${tourId}`}
                style={{ background: A.gold, border: `1px solid ${A.gold}`, display: "flex", alignItems: "center", gap: 6 }}
              >
                Re-run Rewrite <ChevronRight size={13} />
              </Btn>
              {detail.generated?.aa_name && (
                <button
                  onClick={() => navigator.clipboard.writeText(detail.generated!.aa_name)}
                  style={{ background: "none", border: `1px solid ${A.line}`, borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontSize: 12, color: A.muted, fontFamily: sans }}
                >
                  Copy Name
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MasterContentPage() {
  const [data, setData]         = useState<DetailsResponse | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch]     = useState("");
  const [detailTourId, setDetailTourId] = useState<string | null>(null);
  const [detailTourName, setDetailTourName] = useState("");

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

  function refresh() {
    setRefreshing(true);
    load();
  }

  const tours = data?.rewritten_tours ?? [];
  const summary = data?.summary;
  const runs = data?.pipeline_runs ?? [];

  const avgScore = tours.length
    ? tours.reduce((s, t) => s + (t.quality_score ?? 0), 0) / tours.length
    : 0;

  const filtered = tours.filter(t =>
    !search ||
    t.tour_name.toLowerCase().includes(search.toLowerCase()) ||
    (t.country || "").toLowerCase().includes(search.toLowerCase())
  );

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
          <StatCard icon={<BarChart2 size={16} />}   label="Total Tours"    value={String(tours.length)}       sub={`↳ rewritten_tours · ${summary?.tours_view ?? tours.length} visible`} />
          <StatCard icon={<Star size={16} />}         label="Avg Quality"   value={avgScore.toFixed(1)}        sub="↳ quality_score avg" accent={scoreColor(avgScore)} />
          <StatCard icon={<DollarSign size={16} />}  label="Total LLM Cost" value={`$${(summary?.total_llm_cost_usd ?? 0).toFixed(4)}`} sub="↳ summary.total_llm_cost_usd" />
          <StatCard icon={<CalendarClock size={16} />} label="Pipeline Runs" value={String(runs.length)}       sub={`↳ ${summary?.pipeline_note ?? "pipeline_runs"}`} />
        </div>

        {/* Search */}
        <div style={{ marginBottom: 16 }}>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by tour name or country…"
            style={{
              width: 300, padding: "8px 12px", borderRadius: 8,
              border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans,
              background: "#fff", color: A.ink, outline: "none",
            }}
          />
          {search && (
            <span style={{ fontSize: 12, color: A.muted, marginLeft: 12 }}>
              {filtered.length} of {tours.length} tours
            </span>
          )}
        </div>

        {/* Tours table */}
        <Card style={{ padding: 0, marginBottom: 28 }}>
          <div style={{ padding: "14px 20px 10px", borderBottom: `1px solid ${A.line}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <SLabel>Rewritten Tours — aa_internal</SLabel>
            <span style={{ fontSize: 12, color: A.muted2 }}>{tours.length} total</span>
          </div>
          {filtered.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center" as const, color: A.muted, fontSize: 13 }}>
              {search ? "No tours match your search" : "No rewritten tours found"}
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={TH}>#</th>
                    <th style={TH}>Tour Name</th>
                    <th style={TH}>Country</th>
                    <th style={TH}>Quality</th>
                    <th style={TH}>Version</th>
                    <th style={TH}>Status</th>
                    <th style={TH}>Date</th>
                    <th style={{ ...TH, width: 28 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((t, i) => {
                    const isDetail = detailTourId === t.tour_id;
                    return (
                      <tr
                        key={t.version_id}
                        onClick={() => {
                          if (!t.tour_id) return;
                          if (isDetail) { setDetailTourId(null); return; }
                          setDetailTourId(t.tour_id);
                          setDetailTourName(t.tour_name);
                        }}
                        style={{
                          background: isDetail ? `${A.gold}18` : i % 2 === 0 ? "#fff" : A.bg,
                          cursor: t.tour_id ? "pointer" : "default",
                          transition: "background .12s",
                        }}
                      >
                        <td style={{ ...TD, color: A.muted2 }}>{i + 1}</td>
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
                        <td style={{ ...TD, color: A.muted2, fontSize: 12 }}>{relDate(t.created_at)}</td>
                        <td style={{ ...TD, color: A.muted2 }}>
                          {t.tour_id && <ChevronRight size={14} />}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
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

      {/* Detail panel overlay */}
      {detailTourId && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 199 }}
          onClick={() => setDetailTourId(null)}
        />
      )}

      {detailTourId && (
        <TourDetailPanel
          tourId={detailTourId}
          tourName={detailTourName}
          onClose={() => setDetailTourId(null)}
        />
      )}
    </div>
  );
}
