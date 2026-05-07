"use client";
// app/(admin)/dashboard/page.tsx
// Design: Fraunces serif + IBM Plex Sans, light theme, red accent
// API: same as before — /v1/pipeline/metrics, /v1/tours, /v1/pipeline/review-queue

import React, { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from "recharts";
import {
  FileText, CheckCircle, Clock, DollarSign, ExternalLink,
} from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, mono, sans,
  Card, SLabel, StatCard, TabBar, ChartCard, Badge,
  LoadingScreen, Btn, TH, TD, CHART_TOOLTIP,
} from "../_components/adminUi";

// ─── Helpers ──────────────────────────────────────────────────────────────────
const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/cis_api_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

const STATUS_COLOR: Record<string, string> = {
  healthy: "#22C55E", degraded: "#F59E0B", down: "#EF4444",
  running: "#22C55E", interrupted: "#EF4444", idle: "#9099A6",
};

const PIPELINE_HEALTH_DEFAULT = [
  { name: "Ingestion Lambda",   status: "idle", latency: "—", errors: 0 },
  { name: "SEO Intelligence",   status: "idle", latency: "—", errors: 0 },
  { name: "Content Generation", status: "idle", latency: "—", errors: 0 },
  { name: "Validation Lambda",  status: "idle", latency: "—", errors: 0 },
  { name: "Export Lambda",      status: "idle", latency: "—", errors: 0 },
];

const SPOT_WORKERS = [
  { id: "spot-1a", status: "idle", tours: 0, progress: 0, instance: "c5.xlarge" },
  { id: "spot-1b", status: "idle", tours: 0, progress: 0, instance: "c5.xlarge" },
  { id: "spot-2a", status: "idle", tours: 0, progress: 0, instance: "c5.2xlarge" },
  { id: "spot-2b", status: "idle", tours: 0, progress: 0, instance: "c5.xlarge" },
];

// ─── Sub-tab components (logic unchanged, design updated) ─────────────────────

function VolumeTab({ data }: { data: any }) {
  const daily       = data?.daily_runs ?? [];
  const totalTours  = daily.reduce((s: number, d: any) => s + (d.tours  ?? 0), 0);
  const totalPassed = daily.reduce((s: number, d: any) => s + (d.passed ?? 0), 0);
  const totalFailed = daily.reduce((s: number, d: any) => s + (d.failed ?? 0), 0);
  const passRate    = totalTours > 0 ? Math.round((totalPassed / totalTours) * 100) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
        {[
          { label: "Total Tours",  value: totalTours,  color: A.gold  },
          { label: "Auto-Passed",  value: totalPassed, color: "#22C55E" },
          { label: "Failed",       value: totalFailed, color: A.red   },
          { label: "Pass Rate",    value: `${passRate}%`, color: "#7C3AED" },
        ].map(c => (
          <Card key={c.label}>
            <SLabel>{c.label}</SLabel>
            <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: c.color, letterSpacing: "-0.02em" }}>
              {c.value}
            </div>
          </Card>
        ))}
      </div>
      <ChartCard title="Daily Volume Breakdown">
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={daily} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: A.muted }} tickFormatter={(v: string) => v?.slice(5) ?? v} />
            <YAxis tick={{ fontSize: 11, fill: A.muted }} />
            <Tooltip {...CHART_TOOLTIP} />
            <Bar dataKey="passed" name="Passed" fill="#22C55E" radius={[3,3,0,0]} />
            <Bar dataKey="hitl"   name="HITL"   fill={A.gold}  radius={[3,3,0,0]} />
            <Bar dataKey="failed" name="Failed"  fill={A.red}   radius={[3,3,0,0]} />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>
    </div>
  );
}

function QualityTab({ apiUrl, getToken }: { apiUrl: string; getToken: () => string | null }) {
  const [data, setData]     = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetch(`${apiUrl}/v1/pipeline/metrics?days=30`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null).then(setData).finally(() => setLoading(false));
  }, [apiUrl, getToken]);

  if (loading) return <LoadingScreen msg="Loading quality data…" />;
  const models = data?.model_usage ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card>
        <SLabel>Model Quality Scores (30d)</SLabel>
        {models.length === 0 ? (
          <div style={{ color: A.muted, fontSize: 13 }}>No model data yet</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>{["Model","Calls","Avg Score","Cost/Call"].map(h => <th key={h} style={TH}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {models.map((m: any) => {
                const score = parseFloat(m.avg_score ?? 0);
                const sc = score >= 9 ? "#22C55E" : score >= 7 ? A.gold : A.red;
                return (
                  <tr key={m.model}>
                    <td style={TD}><code style={{ fontSize: 12, color: A.gold, fontFamily: mono }}>{m.model}</code></td>
                    <td style={TD}>{m.calls}</td>
                    <td style={TD}><span style={{ color: sc, fontWeight: 700 }}>{score}</span></td>
                    <td style={TD}>{m.calls > 0 && m.total_cost ? `$${(m.total_cost / m.calls).toFixed(4)}` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      <ChartCard title="Quality Score Trend (7d)">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data?.daily_runs ?? []} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: A.muted }} tickFormatter={(v: string) => v?.slice(5) ?? v} />
            <YAxis domain={[0, 10]} tick={{ fontSize: 11, fill: A.muted }} />
            <CartesianGrid strokeDasharray="3 3" stroke={A.line} />
            <Tooltip {...CHART_TOOLTIP} />
            <Line type="monotone" dataKey="passed" name="Passed Tours" stroke="#22C55E" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>
    </div>
  );
}

function CostTab({ apiUrl, getToken }: { apiUrl: string; getToken: () => string | null }) {
  const [data, setData]     = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetch(`${apiUrl}/v1/pipeline/metrics?days=30`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null).then(setData).finally(() => setLoading(false));
  }, [apiUrl, getToken]);

  if (loading) return <LoadingScreen msg="Loading cost data…" />;

  const daily     = data?.daily_runs ?? [];
  const models    = data?.model_usage ?? [];
  const totalCost = daily.reduce((s: number, d: any) => s + parseFloat(d.cost ?? 0), 0);
  const totalTours = daily.reduce((s: number, d: any) => s + (d.tours ?? 0), 0);
  const cpt        = totalTours > 0 ? totalCost / totalTours : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
        {[
          { label: "Total LLM Cost (30d)", value: `$${totalCost.toFixed(2)}`, color: A.gold },
          { label: "Tours Processed",      value: String(totalTours),         color: "#7C3AED" },
          { label: "Cost / Tour",          value: `$${cpt.toFixed(4)}`,       color: "#22C55E" },
        ].map(c => (
          <Card key={c.label}>
            <SLabel>{c.label}</SLabel>
            <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: c.color, letterSpacing: "-0.02em" }}>{c.value}</div>
          </Card>
        ))}
      </div>
      <ChartCard title="Daily LLM Cost (30d)">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={daily} margin={{ top: 4, right: 4, left: -10, bottom: 0 }}>
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: A.muted }} tickFormatter={(v: string) => v?.slice(5) ?? v} />
            <YAxis tick={{ fontSize: 11, fill: A.muted }} tickFormatter={(v: number) => `$${v}`} />
            <CartesianGrid strokeDasharray="3 3" stroke={A.line} />
            <Tooltip {...CHART_TOOLTIP} formatter={(v: unknown) => [`$${Number(v).toFixed(4)}`, "Cost"]} />
            <Line type="monotone" dataKey="cost" stroke={A.gold} strokeWidth={2} dot={{ fill: A.gold, r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>
      <Card>
        <SLabel>Cost by Model</SLabel>
        {models.map((m: any) => (
          <div key={m.model} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", borderBottom: `1px solid ${A.line2}` }}>
            <code style={{ color: A.gold, fontSize: 12, fontFamily: mono }}>{m.model}</code>
            <div style={{ display: "flex", gap: 24 }}>
              <span style={{ color: A.muted, fontSize: 12 }}>{m.calls} calls</span>
              <span style={{ color: A.ink, fontWeight: 600, fontSize: 13 }}>${m.total_cost ? Number(m.total_cost).toFixed(4) : "0.0000"}</span>
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

function SeoTab({ apiUrl, getToken }: { apiUrl: string; getToken: () => string | null }) {
  const [data, setData]     = useState<any>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetch(`${apiUrl}/v1/pipeline/metrics/seo`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null).then(setData).finally(() => setLoading(false));
  }, [apiUrl, getToken]);
  if (loading) return <LoadingScreen msg="Loading SEO data…" />;
  if (!data) return <div style={{ padding: 40, textAlign: "center", color: A.red }}>Failed to load SEO data</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
        {[
          { label: "Tours in Pool",  value: data.total_tours ?? 0 },
          { label: "SEO Covered",    value: data.seo_covered ?? 0 },
          { label: "Coverage",       value: `${data.coverage_pct ?? 0}%` },
        ].map(c => (
          <Card key={c.label}>
            <SLabel>{c.label}</SLabel>
            <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, letterSpacing: "-0.02em" }}>{c.value}</div>
          </Card>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card>
          <SLabel>Top Keywords</SLabel>
          {(data.top_keywords || []).slice(0, 10).map((k: any) => (
            <div key={k.keyword} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 13 }}>
              <span style={{ color: A.ink }}>{k.keyword}</span>
              <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 20, background: A.goldTint, color: A.gold, fontWeight: 600 }}>{k.count}</span>
            </div>
          ))}
          {(!data.top_keywords || data.top_keywords.length === 0) && (
            <div style={{ color: A.muted, fontSize: 13 }}>No keyword data yet</div>
          )}
        </Card>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Card>
            <SLabel>Redis Cache</SLabel>
            {[["Hit Rate", data.cache?.hit_rate ?? "N/A"], ["Cached Keys", data.cache?.keys ?? 0], ["Hits", data.cache?.hits ?? 0], ["Misses", data.cache?.misses ?? 0]].map(([l, v]) => (
              <div key={l as string} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                <span style={{ color: A.muted }}>{l}</span>
                <span style={{ color: A.ink, fontWeight: 600 }}>{v as string}</span>
              </div>
            ))}
          </Card>
          <Card>
            <SLabel>Countries Covered</SLabel>
            {(data.countries || []).slice(0, 8).map((c: any) => (
              <div key={c.country} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                <span style={{ color: A.ink }}>{c.country || "Unknown"}</span>
                <span style={{ color: A.muted }}>{c.count} tours</span>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
}

function LibraryTab({ apiUrl, getToken }: { apiUrl: string; getToken: () => string | null }) {
  const [data, setData]     = useState<any>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetch(`${apiUrl}/v1/pipeline/metrics/library`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null).then(setData).finally(() => setLoading(false));
  }, [apiUrl, getToken]);
  if (loading) return <LoadingScreen msg="Loading library data…" />;
  if (!data) return <div style={{ padding: 40, textAlign: "center", color: A.red }}>Failed to load</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
        {[
          { label: "Total Tours",   value: data.total ?? 0,              color: A.gold },
          { label: "Avg Quality",   value: data.avg_score ?? 0,          color: "#22C55E" },
          { label: "Added (30d)",   value: data.published_last_30d ?? 0, color: "#7C3AED" },
          { label: "Stale (>180d)", value: data.stale_count ?? 0,        color: A.amber },
        ].map(c => (
          <Card key={c.label}>
            <SLabel>{c.label}</SLabel>
            <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: c.color, letterSpacing: "-0.02em" }}>{c.value}</div>
          </Card>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card>
          <SLabel>Coverage by Country</SLabel>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead><tr>{["Country","Tours","Avg Score"].map(h => <th key={h} style={TH}>{h}</th>)}</tr></thead>
            <tbody>
              {(data.by_country || []).slice(0, 12).map((r: any) => (
                <tr key={r.country}>
                  <td style={TD}>{r.country || "Unknown"}</td>
                  <td style={TD}>{r.total}</td>
                  <td style={TD}>
                    <span style={{ color: r.avg_score >= 9 ? "#22C55E" : r.avg_score >= 7 ? A.gold : A.red, fontWeight: 600 }}>{r.avg_score}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card>
          <SLabel>Score Distribution</SLabel>
          {(data.score_distribution || []).map((r: any) => {
            const pct   = Math.round((r.count / (data.total || 1)) * 100);
            const color = r.range === "9-10" ? "#22C55E" : r.range === "8-9" ? "#7C3AED" : r.range === "7-8" ? A.gold : A.red;
            return (
              <div key={r.range} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                  <span style={{ color: A.ink, fontWeight: 600 }}>{r.range}</span>
                  <span style={{ color: A.muted }}>{r.count} tours ({pct}%)</span>
                </div>
                <div style={{ height: 7, background: A.line2, borderRadius: 4, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 4, transition: "width 0.4s" }} />
                </div>
              </div>
            );
          })}
        </Card>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

const TABS = [
  { key: "metrics",  label: "📊 Metrics" },
  { key: "volume",   label: "📈 Volume" },
  { key: "quality",  label: "🎯 Quality" },
  { key: "billing",  label: "💰 Cost" },
  { key: "seo",      label: "🔎 SEO" },
  { key: "library",  label: "📚 Library" },
  { key: "health",   label: "🏥 Health" },
  { key: "spot",     label: "⚡ Spot Workers" },
  { key: "langfuse", label: "🔍 Langfuse" },
];

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState("metrics");
  const [totalTours,  setTotalTours]  = useState(0);
  const [totalHITL,   setTotalHITL]   = useState(0);
  const [totalPassed, setTotalPassed] = useState(0);
  const [metrics, setMetrics]         = useState<any>(null);
  const [loading, setLoading]         = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    const h = { Authorization: `Bearer ${token}` };
    fetch(`${API_URL}/v1/tours?page=1&page_size=1`, { headers: h })
      .then(r => r.json()).then(d => { const t = d.pagination?.total || 0; setTotalTours(t); setTotalPassed(t); }).catch(() => {});
    fetch(`${API_URL}/v1/pipeline/review-queue?page_size=1`, { headers: h })
      .then(r => r.json()).then(d => setTotalHITL(d.pagination?.total || 0)).catch(() => {});
    fetch(`${API_URL}/v1/pipeline/metrics?days=7`, { headers: h })
      .then(r => r.ok ? r.json() : null).then(d => { if (d) setMetrics(d); }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const totalCost = metrics?.model_usage
    ? metrics.model_usage.reduce((s: number, m: any) => s + (m.cost || 0), 0).toFixed(2)
    : (totalTours * 0.018).toFixed(2);
  const passRate = totalTours > 0 ? ((totalPassed / totalTours) * 100).toFixed(1) : "0.0";

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: sans, background: A.bg }}>
      <AdminSidebar />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* Topbar */}
        <header style={{ height: 56, background: "#fff", borderBottom: `1px solid ${A.line}`, display: "flex", alignItems: "center", padding: "0 32px", gap: 8, position: "sticky", top: 0, zIndex: 10 }}>
          <span style={{ fontSize: 12, color: A.muted2 }}>Admin /</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: A.body }}>Dashboard</span>
        </header>

        <main style={{ flex: 1, overflowY: "auto", padding: "28px 36px 56px" }}>
          {/* Page header */}
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24 }}>
            <div>
              <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink, margin: "0 0 6px", letterSpacing: "-0.01em" }}>
                Dev Dashboard
              </h1>
              <p style={{ fontSize: 13, color: A.muted, margin: 0 }}>Pipeline metrics · API v0.3.0</p>
            </div>
          </div>

          {/* Stat cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 24 }}>
            <StatCard icon={<FileText size={16} />}    label="Tours Processed" value={String(totalTours)}  sub="Last 7 days"           />
            <StatCard icon={<CheckCircle size={16} />} label="Auto-Approved"   value={`${passRate}%`}      sub={`${totalPassed} tours`} accent="#22C55E" />
            <StatCard icon={<Clock size={16} />}       label="HITL Queue"      value={String(totalHITL)}   sub="Awaiting review"        accent={A.amber} />
            <StatCard icon={<DollarSign size={16} />}  label="Total LLM Cost"  value={`$${totalCost}`}     sub="~$0.018 per tour avg"   />
          </div>

          {/* Tab bar */}
          <div style={{ marginBottom: 20, overflowX: "auto" }}>
            <TabBar tabs={TABS} active={activeTab} onChange={setActiveTab} />
          </div>

          {/* Tab content */}
          {activeTab === "metrics" && (
            loading ? <LoadingScreen msg="Loading metrics…" /> : (
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  <ChartCard title="Daily Pipeline Volume">
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={metrics?.daily_runs ?? []}>
                        <XAxis dataKey="date" tick={{ fill: A.muted, fontSize: 11 }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fill: A.muted, fontSize: 11 }} axisLine={false} tickLine={false} />
                        <Tooltip {...CHART_TOOLTIP} />
                        <Bar dataKey="tours"  name="Tours"  fill="#22C55E" radius={[4,4,0,0]} />
                        <Bar dataKey="hitl"   name="HITL"   fill={A.gold}  radius={[4,4,0,0]} />
                        <Bar dataKey="failed" name="Failed" fill={A.red}   radius={[4,4,0,0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartCard>
                  <ChartCard title="Daily LLM Cost (USD)">
                    <ResponsiveContainer width="100%" height={220}>
                      <LineChart data={metrics?.daily_runs ?? []}>
                        <CartesianGrid strokeDasharray="3 3" stroke={A.line} />
                        <XAxis dataKey="date" tick={{ fill: A.muted, fontSize: 11 }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fill: A.muted, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} />
                        <Tooltip {...CHART_TOOLTIP} formatter={(v: any) => [`$${v}`, "Cost"]} />
                        <Line type="monotone" dataKey="cost" stroke={A.gold} strokeWidth={2.5} dot={{ fill: A.gold, r: 4 }} activeDot={{ r: 6 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </ChartCard>
                </div>
                <ChartCard title="LLM Model Usage">
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr>{["Model","Calls","Total Cost","Avg Score","Cost/Call"].map((h,i) => (
                        <th key={h} style={{ ...TH, textAlign: i === 0 ? "left" : "right" }}>{h}</th>
                      ))}</tr>
                    </thead>
                    <tbody>
                      {(metrics?.model_usage ?? []).map((m: any) => (
                        <tr key={m.model}>
                          <td style={TD}><code style={{ fontFamily: mono, fontSize: 12, color: A.gold }}>{m.model}</code></td>
                          <td style={{ ...TD, textAlign: "right" }}>{m.calls}</td>
                          <td style={{ ...TD, textAlign: "right" }}>${m.cost.toFixed(2)}</td>
                          <td style={{ ...TD, textAlign: "right" }}>
                            <span style={{ fontWeight: 700, color: m.avg_score >= 8.5 ? "#22C55E" : m.avg_score >= 7.5 ? A.gold : A.amber }}>{m.avg_score}</span>
                          </td>
                          <td style={{ ...TD, textAlign: "right", color: A.muted }}>${(m.cost / m.calls).toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ChartCard>
              </div>
            )
          )}

          {activeTab === "volume"  && <VolumeTab data={metrics} />}
          {activeTab === "quality" && <QualityTab apiUrl={API_URL} getToken={getToken} />}
          {activeTab === "billing" && <CostTab apiUrl={API_URL} getToken={getToken} />}
          {activeTab === "seo"     && <SeoTab apiUrl={API_URL} getToken={getToken} />}
          {activeTab === "library" && <LibraryTab apiUrl={API_URL} getToken={getToken} />}

          {activeTab === "health" && (
            <ChartCard title="Pipeline Service Health">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {((metrics?.pipeline_health as any[]) ?? PIPELINE_HEALTH_DEFAULT).map((s: any) => (
                  <div key={s.name} style={{
                    display: "flex", alignItems: "center", gap: 16,
                    padding: "12px 16px", borderRadius: 10, background: A.bg, border: `1px solid ${A.line}`,
                  }}>
                    <div style={{ width: 10, height: 10, borderRadius: "50%", flexShrink: 0, background: STATUS_COLOR[s.status] || A.muted2, boxShadow: `0 0 6px ${STATUS_COLOR[s.status] || A.muted2}` }} />
                    <div style={{ flex: 1, fontWeight: 500, fontSize: 13, color: A.ink }}>{s.name}</div>
                    <div style={{ fontSize: 12, color: A.muted, width: 80, textAlign: "right", fontFamily: mono }}>{s.latency}</div>
                    <div style={{ width: 80, textAlign: "right" }}>
                      {s.errors > 0
                        ? <span style={{ fontSize: 12, color: A.red }}>⚠ {s.errors} err</span>
                        : <span style={{ fontSize: 12, color: "#22C55E" }}>✓ Clean</span>}
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 999, background: `${STATUS_COLOR[s.status]}18`, color: STATUS_COLOR[s.status], textTransform: "capitalize" }}>{s.status}</span>
                  </div>
                ))}
              </div>
            </ChartCard>
          )}

          {activeTab === "spot" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <ChartCard title="Batch Rewrite Spot Workers">
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  {SPOT_WORKERS.map(w => (
                    <div key={w.id} style={{ padding: 16, borderRadius: 10, background: A.bg, border: `1px solid ${STATUS_COLOR[w.status]}33` }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                        <div>
                          <div style={{ fontFamily: mono, fontSize: 13, color: A.ink, fontWeight: 600 }}>{w.id}</div>
                          <div style={{ fontSize: 11, color: A.muted, marginTop: 2 }}>{w.instance}</div>
                        </div>
                        <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 999, background: `${STATUS_COLOR[w.status]}18`, color: STATUS_COLOR[w.status], textTransform: "capitalize" }}>{w.status}</span>
                      </div>
                      <div style={{ fontSize: 12, color: A.muted }}>Waiting for batch job</div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 14, padding: 12, background: A.goldTint, borderRadius: 8, border: `1px solid ${A.gold}33`, fontSize: 12, color: A.muted }}>
                  💡 Spot Workers run ECS Fargate Spot for cost-efficient batch rewriting. On interruption, checkpoint is saved and work resumes.
                </div>
              </ChartCard>
            </div>
          )}

          {activeTab === "langfuse" && (
            <ChartCard title="Langfuse LLM Observability">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                <p style={{ fontSize: 13, color: A.muted, margin: 0 }}>
                  Langfuse traces all LLM calls — prompts, completions, costs, latency per tour.
                </p>
                <a href="https://langfuse.lumiguides.it.com" target="_blank" rel="noreferrer"
                  style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 16px", background: A.gold, borderRadius: 8, color: "#fff", fontSize: 12, fontWeight: 600, textDecoration: "none" }}>
                  <ExternalLink size={12} /> Open Langfuse
                </a>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 12 }}>
                {[
                  { label: "LLM Traces",      desc: "Every prompt + completion logged with latency",  icon: "🔍" },
                  { label: "Cost Breakdown",   desc: "Per tour, per model, per batch",                 icon: "💰" },
                  { label: "Quality Trends",   desc: "Score history + retry patterns over time",       icon: "📈" },
                  { label: "Prompt Versions",  desc: "A/B test prompt iterations",                    icon: "🧪" },
                ].map(f => (
                  <div key={f.label} style={{ display: "flex", gap: 12, padding: "14px 16px", background: A.bg, borderRadius: 10, border: `1px solid ${A.line}` }}>
                    <span style={{ fontSize: 20 }}>{f.icon}</span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: A.ink, marginBottom: 4 }}>{f.label}</div>
                      <div style={{ fontSize: 12, color: A.muted, lineHeight: 1.5 }}>{f.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 14, padding: "10px 14px", background: A.goldTint, borderRadius: 8, fontSize: 12, color: A.muted, textAlign: "center" }}>
                Live at <a href="https://langfuse.lumiguides.it.com" target="_blank" rel="noreferrer" style={{ color: A.gold, fontWeight: 600 }}>langfuse.lumiguides.it.com</a> — iframe blocked by browser security policy
              </div>
            </ChartCard>
          )}
        </main>
      </div>
    </div>
  );
}
