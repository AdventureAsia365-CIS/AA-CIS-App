"use client";
// app/admin/master-content/page.tsx
// GET /admin/tenants/AA_INTERNAL_ID/details → rewritten_tours, summary, pipeline_runs

import React, { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Badge, Btn, LoadingScreen, StatCard, TH, TD,
} from "../_components/adminUi";
import { BarChart2, Star, DollarSign, CalendarClock } from "lucide-react";

const AA_INTERNAL_ID = "00000000-0000-0000-0000-000000000001";

interface RewrittenTour {
  version_id: string;
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

function scoreColor(s: number): string {
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

export default function MasterContentPage() {
  const [data, setData]         = useState<DetailsResponse | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch]     = useState("");

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
    t.country.toLowerCase().includes(search.toLowerCase())
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
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((t, i) => (
                    <tr key={t.version_id} style={{ background: i % 2 === 0 ? "#fff" : A.bg }}>
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
                    </tr>
                  ))}
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
    </div>
  );
}
