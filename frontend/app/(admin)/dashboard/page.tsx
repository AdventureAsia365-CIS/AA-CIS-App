"use client";
import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from "recharts";
import {
  FileText, CheckCircle, Clock, DollarSign,
  Activity, Cpu, AlertTriangle, ExternalLink,
} from "lucide-react";

const TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: "#1A2230", border: "1px solid #2A3547",
    borderRadius: 8, fontSize: 12,
  },
  labelStyle: { color: "#F8F6F2" },
};

function StatCard({ icon: Icon, label, value, sub, accent = "#DB9628" }: {
  icon: any; label: string; value: string; sub?: string; accent?: string;
}) {
  return (
    <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <div style={{ padding: 8, borderRadius: 8, background: `${accent}18`, color: accent }}>
          <Icon size={16} />
        </div>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{label}</span>
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, color: "var(--text-primary)" }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 20 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

const STATUS_DOT: Record<string, string> = {
  healthy:     "#22c55e",
  degraded:    "#f59e0b",
  down:        "#ef4444",
  running:     "#22c55e",
  interrupted: "#ef4444",
  idle:        "#4A5568",
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/cis_api_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

const PIPELINE_HEALTH = [
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

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<"metrics" | "health" | "spot" | "langfuse">("metrics");
  const [totalTours,  setTotalTours]  = useState(0);
  const [totalHITL,   setTotalHITL]   = useState(0);
  const [totalPassed, setTotalPassed] = useState(0);
  const [metrics, setMetrics] = useState<{
    daily_runs: any[];
    model_usage: any[];
    last_run: any;
    pipeline_health?: any[];
  } | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    const h = { Authorization: `Bearer ${token}` };

    // Fetch stats
    fetch(`${API_URL}/v1/tours?page=1&page_size=1`, { headers: h })
      .then(r => r.json())
      .then(d => { const t = d.pagination?.total || 0; setTotalTours(t); setTotalPassed(t); })
      .catch(() => {});
    fetch(`${API_URL}/v1/pipeline/review-queue?page_size=1`, { headers: h })
      .then(r => r.json())
      .then(d => setTotalHITL(d.pagination?.total || 0))
      .catch(() => {});

    // Fetch real metrics
    fetch(`${API_URL}/v1/pipeline/metrics?days=7`, { headers: h })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setMetrics(d); })
      .catch(() => {})
      .finally(() => setMetricsLoading(false));
  }, []);

  const totalCost = metrics?.model_usage
    ? metrics.model_usage.reduce((s: number, m: any) => s + (m.cost || 0), 0).toFixed(2)
    : (totalTours * 0.006).toFixed(2);
  const passRate  = totalTours > 0 ? ((totalPassed / totalTours) * 100).toFixed(1) : "0.0";

  const tabStyle = (t: string): React.CSSProperties => ({
    padding: "8px 18px", borderRadius: 8, fontSize: 13, fontWeight: 500,
    cursor: "pointer", border: "none",
    background: activeTab === t ? "var(--brand-gold)" : "var(--bg-card)",
    color: activeTab === t ? "white" : "var(--text-secondary)",
    transition: "all 0.15s",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>Dev Dashboard</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 6 }}>
            Pipeline metrics · Live data
          </p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(["metrics", "health", "spot", "langfuse"] as const).map(t => (
            <button key={t} style={tabStyle(t)} onClick={() => setActiveTab(t)}>
              {t === "metrics" ? "📊 Metrics" :
               t === "health"  ? "🏥 Health" :
               t === "spot"    ? "⚡ Spot Workers" : "🔍 Langfuse"}
            </button>
          ))}
        </div>
      </div>

      {/* Stat cards — always visible */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16 }}>
        <StatCard icon={FileText}    label="Tours Processed" value={String(totalTours)}         sub="Last 7 days"           accent="#DB9628" />
        <StatCard icon={CheckCircle} label="Auto-Approved"   value={`${passRate}%`}             sub={`${totalPassed} tours`} accent="#22c55e" />
        <StatCard icon={Clock}       label="HITL Queue"      value={String(totalHITL)}           sub="Awaiting human review" accent="#f59e0b" />
        <StatCard icon={DollarSign}  label="Total LLM Cost"  value={`$${totalCost}`} sub="~$0.018 per tour avg"  accent="#ef4444" />
      </div>

      {/* TAB: Metrics */}
      {activeTab === "metrics" && metricsLoading ? (
        <div style={{ padding: 48, textAlign: "center", color: "var(--text-muted)" }}>Loading metrics…</div>
      ) : activeTab === "metrics" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <ChartCard title="Daily Pipeline Volume">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={metrics?.daily_runs ?? []} barGap={2}>
                  <XAxis dataKey="date" tick={{ fill: "#8B9BB4", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#8B9BB4", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Bar dataKey="tours" name="Tours" fill="#22c55e" radius={[4,4,0,0]} />
                  <Bar dataKey="hitl" name="HITL"          fill="#DB9628" radius={[4,4,0,0]} />
                  <Bar dataKey="failed" name="Failed"        fill="#ef4444" radius={[4,4,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
            <ChartCard title="Daily LLM Cost (USD)">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={metrics?.daily_runs ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2A3547" />
                  <XAxis dataKey="date" tick={{ fill: "#8B9BB4", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#8B9BB4", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} />
                  <Tooltip {...TOOLTIP_STYLE} formatter={(v: any) => [`$${v}`, "Cost"]} />
                  <Line type="monotone" dataKey="cost" stroke="#DB9628" strokeWidth={2.5}
                    dot={{ fill: "#DB9628", r: 4, strokeWidth: 0 }} activeDot={{ r: 6 }} />
                </LineChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          <ChartCard title="LLM Model Usage">
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Model", "Calls", "Total Cost", "Avg Score", "Cost / Call"].map((h, i) => (
                    <th key={h} style={{ padding: "6px 12px 10px", fontSize: 11, color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1, textAlign: i === 0 ? "left" : "right" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(metrics?.model_usage ?? []).map((m: any) => (
                  <tr key={m.model} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: 12, fontFamily: "monospace", fontSize: 13, color: "var(--brand-gold)" }}>{m.model}</td>
                    <td style={{ padding: 12, textAlign: "right", color: "var(--text-secondary)", fontSize: 13 }}>{m.calls}</td>
                    <td style={{ padding: 12, textAlign: "right", color: "var(--text-secondary)", fontSize: 13 }}>${m.cost.toFixed(2)}</td>
                    <td style={{ padding: 12, textAlign: "right" }}>
                      <span style={{ fontWeight: 700, fontSize: 13, color: m.avg_score >= 8.5 ? "#22c55e" : m.avg_score >= 7.5 ? "#DB9628" : "#f59e0b" }}>{m.avg_score}</span>
                    </td>
                    <td style={{ padding: 12, textAlign: "right", color: "var(--text-muted)", fontSize: 13 }}>${(m.cost / m.calls).toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ChartCard>
        </>
      )}

      {/* TAB: Pipeline Health */}
      {activeTab === "health" && (
        <ChartCard title="Pipeline Service Health">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {((metrics?.pipeline_health as any[]) ?? PIPELINE_HEALTH).map((s: any) => (
              <div key={s.name} style={{
                display: "flex", alignItems: "center", gap: 16,
                padding: "12px 16px", borderRadius: 10,
                background: "var(--bg-primary)", border: "1px solid var(--border)",
              }}>
                <div style={{
                  width: 10, height: 10, borderRadius: "50%", flexShrink: 0,
                  background: STATUS_DOT[s.status] || "#4A5568",
                  boxShadow: `0 0 6px ${STATUS_DOT[s.status] || "#4A5568"}`,
                }} />
                <div style={{ flex: 1, fontWeight: 500, fontSize: 13, color: "var(--text-primary)" }}>{s.name}</div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", width: 80, textAlign: "right" }}>
                  {s.latency}
                </div>
                <div style={{ width: 60, textAlign: "right" }}>
                  {s.errors > 0
                    ? <span style={{ fontSize: 12, color: "#ef4444" }}>⚠ {s.errors} err</span>
                    : <span style={{ fontSize: 12, color: "#22c55e" }}>✓ Clean</span>
                  }
                </div>
                <span style={{
                  fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20,
                  background: `${STATUS_DOT[s.status]}18`, color: STATUS_DOT[s.status],
                  border: `1px solid ${STATUS_DOT[s.status]}33`, textTransform: "capitalize",
                }}>{s.status}</span>
              </div>
            ))}
          </div>
        </ChartCard>
      )}

      {/* TAB: Spot Workers */}
      {activeTab === "spot" && (
        <ChartCard title="Batch Rewrite Spot Workers">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {SPOT_WORKERS.map((w) => (
              <div key={w.id} style={{
                padding: 16, borderRadius: 10,
                background: "var(--bg-primary)", border: `1px solid ${STATUS_DOT[w.status]}33`,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                  <div>
                    <div style={{ fontFamily: "monospace", fontSize: 13, color: "var(--text-primary)", fontWeight: 600 }}>{w.id}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{w.instance}</div>
                  </div>
                  <span style={{
                    fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 20, alignSelf: "flex-start",
                    background: `${STATUS_DOT[w.status]}18`, color: STATUS_DOT[w.status],
                    border: `1px solid ${STATUS_DOT[w.status]}33`, textTransform: "capitalize",
                  }}>{w.status}</span>
                </div>
                {w.status !== "idle" && (
                  <>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 12, color: "var(--text-secondary)" }}>
                      <span>{w.tours} tours</span>
                      <span>{w.progress}%</span>
                    </div>
                    <div style={{ height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{
                        height: "100%", width: `${w.progress}%`,
                        background: w.status === "interrupted"
                          ? "linear-gradient(90deg, #ef4444, #f87171)"
                          : "linear-gradient(90deg, var(--brand-gold), #f59e0b)",
                        borderRadius: 3, transition: "width 0.4s",
                      }} />
                    </div>
                    {w.status === "interrupted" && (
                      <div style={{ fontSize: 11, color: "#ef4444", marginTop: 6 }}>
                        ⚠ Spot interruption — work saved, will resume
                      </div>
                    )}
                  </>
                )}
                {w.status === "idle" && (
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Waiting for batch job</div>
                )}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16, padding: 12, background: "rgba(219,150,40,0.06)", borderRadius: 8, border: "1px solid rgba(219,150,40,0.2)", fontSize: 12, color: "var(--text-secondary)" }}>
            💡 Spot Workers run ECS Fargate Spot tasks for cost-efficient batch rewriting. On interruption, checkpoint is saved and work resumes on next available instance.
          </div>
        </ChartCard>
      )}

      {/* TAB: Langfuse */}
      {activeTab === "langfuse" && (
        <ChartCard title="Langfuse LLM Observability">
          <div style={{ marginBottom: 16, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: 0 }}>
              Langfuse traces all LLM calls — prompts, completions, costs, latency per tour.
            </p>
            <a href="https://langfuse.lumiguides.it.com" target="_blank" rel="noreferrer"
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 14px", background: "var(--brand-gold)", borderRadius: 8, color: "white", fontSize: 12, fontWeight: 600, textDecoration: "none" }}>
              <ExternalLink size={12} /> Open Langfuse
            </a>
          </div>

          {/* Langfuse feature cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, marginTop: 8 }}>
            {[
              { label: "LLM Traces", desc: "Every prompt + completion logged with latency", icon: "🔍" },
              { label: "Cost Breakdown", desc: "Per tour, per model, per batch", icon: "💰" },
              { label: "Quality Trends", desc: "Score history + retry patterns over time", icon: "📈" },
              { label: "Prompt Versions", desc: "A/B test prompt iterations", icon: "🧪" },
            ].map(f => (
              <div key={f.label} style={{ display: "flex", gap: 12, padding: "14px 16px", background: "var(--bg-primary)", borderRadius: 10, border: "1px solid var(--border)" }}>
                <span style={{ fontSize: 20 }}>{f.icon}</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 4 }}>{f.label}</div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>{f.desc}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16, padding: "12px 16px", background: "rgba(219,150,40,0.06)", borderRadius: 8, fontSize: 12, color: "var(--text-muted)", textAlign: "center" }}>
            Langfuse is live at{" "}
            <a href="https://langfuse.lumiguides.it.com" target="_blank" rel="noreferrer"
              style={{ color: "var(--brand-gold)", fontWeight: 600 }}>
              langfuse.lumiguides.it.com
            </a>
            {" "}— open in a new tab to view traces (iframe blocked by browser security policy)
          </div>
        </ChartCard>
      )}
    </div>
  );
}
