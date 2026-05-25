"use client";

import React, { useState, useEffect } from "react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, mono, sans,
  Card, SLabel, TabBar, LoadingScreen, TH, TD,
} from "../_components/adminUi";

const STATUS_COLOR: Record<string, string> = {
  healthy: "#22C55E", degraded: "#F59E0B", down: "#EF4444",
  running: "#22C55E", interrupted: "#EF4444", idle: "#9099A6",
};

function MetricCard({ label, value, sub, color = A.ink }: {
  label: string; value: string | number; sub?: string; color?: string;
}) {
  return (
    <Card>
      <SLabel>{label}</SLabel>
      <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color, letterSpacing: "-0.02em" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: A.muted2, marginTop: 4 }}>{sub}</div>}
    </Card>
  );
}

// ─── Tab 1: Overview ──────────────────────────────────────────────────────────
function OverviewTab({ data }: { data: any }) {
  if (!data) return (
    <div style={{ padding: 40, textAlign: "center", color: A.red }}>Failed to load metrics</div>
  );

  const cs        = data.content_summary ?? {};
  const total     = cs.total_content_all_tenants ?? 0;
  const published = data.published_count ?? 0;
  const rewrites  = data.tenant_rewrite_count ?? 0;
  const breakdown = (cs.tenant_breakdown ?? []).filter((r: any) => r.rewrite_count > 0);
  const daily     = (data.daily_runs ?? []).filter((r: any) => r.runs > 0);
  const models    = data.model_usage ?? [];
  const health    = data.pipeline_health ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Row 1 — 4 metric cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
        <MetricCard
          label="Total Content"
          value={total}
          sub={`${published} master + ${rewrites} tenant rewrites`}
          color={A.ink}
        />
        <MetricCard
          label="Master Tours"
          value={published}
          sub="aa_internal published"
          color={A.gold}
        />
        <MetricCard
          label="Tenant Rewrites"
          value={rewrites}
          sub={`${breakdown.length} active tenants`}
          color="#7C3AED"
        />
        <MetricCard
          label="LLM Calls"
          value={data.llm_calls ?? 0}
          sub={`avg $${Number(data.avg_cost_per_run ?? 0).toFixed(4)}/run`}
          color="#22C55E"
        />
      </div>

      {/* Row 2 — Tenant Breakdown */}
      {breakdown.length > 0 && (
        <Card>
          <SLabel>Tenant Breakdown</SLabel>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Tenant Slug", "Plan Tier", "Rewrites"].map((h, i) => (
                  <th key={h} style={{ ...TH, textAlign: i > 0 ? "right" : "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {breakdown.map((r: any, idx: number) => (
                <tr key={r.slug} style={{ background: idx % 2 === 1 ? A.bg : "transparent" }}>
                  <td style={TD}><code style={{ fontFamily: mono, fontSize: 12, color: A.gold }}>{r.slug}</code></td>
                  <td style={{ ...TD, textAlign: "right" }}>{r.plan_tier ?? "—"}</td>
                  <td style={{ ...TD, textAlign: "right", fontWeight: 600 }}>{r.rewrite_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Row 3 — Pipeline Activity */}
      <Card>
        <SLabel>Pipeline Activity (7d)</SLabel>
        {daily.length === 0 ? (
          <div style={{ color: A.muted, fontSize: 13 }}>No pipeline activity in the last 7 days</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Date", "Runs", "Tours", "Passed", "Failed", "Cost ($)"].map((h, i) => (
                  <th key={h} style={{ ...TH, textAlign: i > 0 ? "right" : "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {daily.map((r: any, idx: number) => (
                <tr key={r.date} style={{ background: idx % 2 === 1 ? A.bg : "transparent" }}>
                  <td style={TD}>{r.date}</td>
                  <td style={{ ...TD, textAlign: "right" }}>{r.runs}</td>
                  <td style={{ ...TD, textAlign: "right" }}>{r.tours}</td>
                  <td style={{ ...TD, textAlign: "right", color: "#22C55E", fontWeight: 600 }}>{r.passed}</td>
                  <td style={{ ...TD, textAlign: "right", color: r.failed > 0 ? A.red : A.muted }}>{r.failed}</td>
                  <td style={{ ...TD, textAlign: "right", fontFamily: mono, fontSize: 12 }}>
                    ${Number(r.cost ?? 0).toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Row 4 — Model Usage */}
      {models.length > 0 && (
        <Card>
          <SLabel>Model Usage</SLabel>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Model", "Calls", "Avg Score", "Total Cost", "Cost/Call"].map((h, i) => (
                  <th key={h} style={{ ...TH, textAlign: i > 0 ? "right" : "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map((m: any, idx: number) => {
                const score = m.avg_score != null ? parseFloat(m.avg_score) : null;
                const sc    = score == null ? A.muted2 : score >= 9 ? "#22C55E" : score >= 7 ? A.gold : A.red;
                return (
                  <tr key={m.model} style={{ background: idx % 2 === 1 ? A.bg : "transparent" }}>
                    <td style={TD}><code style={{ fontFamily: mono, fontSize: 12, color: A.gold }}>{m.model}</code></td>
                    <td style={{ ...TD, textAlign: "right" }}>{m.calls}</td>
                    <td style={{ ...TD, textAlign: "right" }}>
                      <span style={{ color: sc, fontWeight: 700 }}>{score != null ? score.toFixed(1) : "—"}</span>
                    </td>
                    <td style={{ ...TD, textAlign: "right" }}>${Number(m.total_cost ?? 0).toFixed(4)}</td>
                    <td style={{ ...TD, textAlign: "right", color: A.muted }}>${Number(m.cost_per_call ?? 0).toFixed(4)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {/* Row 5 — Pipeline Health */}
      {health.length > 0 && (
        <Card>
          <SLabel>Pipeline Health</SLabel>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {health.map((s: any) => (
              <div key={s.name} style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 14px", borderRadius: 8,
                background: A.bg, border: `1px solid ${A.line}`,
              }}>
                <div style={{
                  width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                  background: STATUS_COLOR[s.status] || A.muted2,
                  boxShadow: `0 0 5px ${STATUS_COLOR[s.status] || A.muted2}`,
                }} />
                <span style={{ fontSize: 12, fontWeight: 500, color: A.ink }}>{s.name}</span>
                <span style={{
                  fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
                  background: `${STATUS_COLOR[s.status] || A.muted2}18`,
                  color: STATUS_COLOR[s.status] || A.muted2,
                  textTransform: "capitalize",
                }}>{s.status}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

// ─── Tab 2: SEO Intelligence ──────────────────────────────────────────────────
function SeoTab() {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(false);

  useEffect(() => {
    fetch("/api/admin/metrics/seo")
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingScreen msg="Loading SEO data…" />;
  if (error || !data) return (
    <div style={{ padding: 40, textAlign: "center", color: A.red }}>Failed to load SEO data</div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Row 1 — 3 metric cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
        <MetricCard
          label="SEO Coverage"
          value={`${data.coverage_pct ?? 0}%`}
          sub={`${data.seo_covered ?? 0}/${data.total_tours ?? 0} tours`}
          color={A.gold}
        />
        <MetricCard
          label="Cache Hit Rate"
          value={data.cache?.hit_rate ?? "N/A"}
          sub={`${data.cache?.hits ?? 0} hits / ${data.cache?.misses ?? 0} misses`}
          color="#22C55E"
        />
        <MetricCard
          label="Countries"
          value={(data.countries ?? []).length}
          sub="with SEO data"
          color="#7C3AED"
        />
      </div>

      {/* Row 2 — Countries table */}
      <Card>
        <SLabel>Countries</SLabel>
        {(data.countries ?? []).length === 0 ? (
          <div style={{ color: A.muted, fontSize: 13 }}>No country data yet</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Country", "Tours with SEO"].map((h, i) => (
                  <th key={h} style={{ ...TH, textAlign: i > 0 ? "right" : "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data.countries ?? []).map((c: any, idx: number) => (
                <tr key={c.country} style={{ background: idx % 2 === 1 ? A.bg : "transparent" }}>
                  <td style={TD}>{c.country || "Unknown"}</td>
                  <td style={{ ...TD, textAlign: "right" }}>{c.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Row 3 — Top Keywords */}
      <Card>
        <SLabel>Top Keywords</SLabel>
        {(data.top_keywords ?? []).length === 0 ? (
          <div style={{ color: A.muted, fontSize: 13 }}>No keyword data yet</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {(data.top_keywords ?? []).map((k: any, idx: number) => (
              <div key={k.keyword} style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                fontSize: 13, padding: "8px 0",
                borderBottom: idx < (data.top_keywords ?? []).length - 1 ? `1px solid ${A.line2}` : "none",
              }}>
                <span style={{ color: A.ink }}>{k.keyword}</span>
                <span style={{
                  fontSize: 11, padding: "2px 8px", borderRadius: 20,
                  background: A.goldTint, color: A.gold, fontWeight: 600,
                }}>{k.count}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ─── Tab 3: Content Library ───────────────────────────────────────────────────
function LibraryTab() {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(false);

  useEffect(() => {
    fetch("/api/admin/metrics/library")
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingScreen msg="Loading library data…" />;
  if (error || !data) return (
    <div style={{ padding: 40, textAlign: "center", color: A.red }}>Failed to load library data</div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Row 1 — 3 metric cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
        <MetricCard
          label="Total Published"
          value={data.total ?? 0}
          color={A.gold}
        />
        <MetricCard
          label="Avg Quality Score"
          value={data.avg_score != null ? Number(data.avg_score).toFixed(1) : "—"}
          color="#22C55E"
        />
        <MetricCard
          label="Published (30d)"
          value={data.published_last_30d ?? 0}
          color="#7C3AED"
        />
      </div>

      {/* Row 2 — By Country table */}
      <Card>
        <SLabel>By Country</SLabel>
        {(data.by_country ?? []).length === 0 ? (
          <div style={{ color: A.muted, fontSize: 13 }}>No country data yet</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Country", "Tours", "Avg Score", "Last Published"].map((h, i) => (
                  <th key={h} style={{ ...TH, textAlign: i > 0 ? "right" : "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data.by_country ?? []).map((r: any, idx: number) => (
                <tr key={r.country ?? "unknown"} style={{ background: idx % 2 === 1 ? A.bg : "transparent" }}>
                  <td style={TD}>{r.country || "Unknown"}</td>
                  <td style={{ ...TD, textAlign: "right" }}>{r.total}</td>
                  <td style={{ ...TD, textAlign: "right" }}>
                    <span style={{
                      fontWeight: 700,
                      color: Number(r.avg_score) >= 9 ? "#22C55E" : Number(r.avg_score) >= 7 ? A.gold : A.red,
                    }}>{Number(r.avg_score).toFixed(1)}</span>
                  </td>
                  <td style={{ ...TD, textAlign: "right", color: A.muted, fontSize: 12 }}>
                    {r.last_published ? String(r.last_published).slice(0, 10) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Row 3 — Score Distribution */}
      <Card>
        <SLabel>Score Distribution</SLabel>
        {(data.score_distribution ?? []).length === 0 ? (
          <div style={{ color: A.muted, fontSize: 13 }}>No distribution data yet</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Range", "Count"].map((h, i) => (
                  <th key={h} style={{ ...TH, textAlign: i > 0 ? "right" : "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data.score_distribution ?? []).map((r: any, idx: number) => (
                <tr key={r.range} style={{ background: idx % 2 === 1 ? A.bg : "transparent" }}>
                  <td style={TD}>{r.range}</td>
                  <td style={{ ...TD, textAlign: "right", fontWeight: 600 }}>{r.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
const TABS = [
  { key: "overview", label: "Overview" },
  { key: "seo",      label: "SEO Intelligence" },
  { key: "library",  label: "Content Library" },
];

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState("overview");
  const [metrics, setMetrics]     = useState<any>(null);
  const [loading, setLoading]     = useState(true);

  useEffect(() => {
    fetch("/api/admin/metrics?days=7")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setMetrics(d); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: sans, background: A.bg }}>
      <AdminSidebar />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <header style={{
          height: 56, background: "#fff", borderBottom: `1px solid ${A.line}`,
          display: "flex", alignItems: "center", padding: "0 32px", gap: 8,
          position: "sticky", top: 0, zIndex: 10,
        }}>
          <span style={{ fontSize: 12, color: A.muted2 }}>Admin /</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: A.body }}>Dashboard</span>
        </header>

        <main style={{ flex: 1, overflowY: "auto", padding: "28px 36px 56px" }}>
          <div style={{ marginBottom: 24 }}>
            <h1 style={{
              fontFamily: serif, fontSize: 24, fontWeight: 500,
              color: A.ink, margin: "0 0 6px", letterSpacing: "-0.01em",
            }}>Dashboard</h1>
            <p style={{ fontSize: 13, color: A.muted, margin: 0 }}>
              All-tenant metrics · API v0.3.0
            </p>
          </div>

          <div style={{ marginBottom: 24 }}>
            <TabBar tabs={TABS} active={activeTab} onChange={setActiveTab} />
          </div>

          {activeTab === "overview" && (
            loading
              ? <LoadingScreen msg="Loading metrics…" />
              : <OverviewTab data={metrics} />
          )}
          {activeTab === "seo"     && <SeoTab />}
          {activeTab === "library" && <LibraryTab />}
        </main>
      </div>
    </div>
  );
}
