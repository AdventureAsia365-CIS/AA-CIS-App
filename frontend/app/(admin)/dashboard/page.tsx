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

const MOCK_RUNS = [
  { date: "Apr 11", tours: 45, passed: 38, hitl: 5, failed: 2, cost: 1.24 },
  { date: "Apr 12", tours: 62, passed: 55, hitl: 4, failed: 3, cost: 1.87 },
  { date: "Apr 13", tours: 38, passed: 34, hitl: 3, failed: 1, cost: 1.12 },
  { date: "Apr 14", tours: 71, passed: 63, hitl: 6, failed: 2, cost: 2.15 },
  { date: "Apr 15", tours: 55, passed: 49, hitl: 4, failed: 2, cost: 1.68 },
  { date: "Apr 16", tours: 83, passed: 74, hitl: 7, failed: 2, cost: 2.51 },
  { date: "Apr 17", tours: 29, passed: 26, hitl: 2, failed: 1, cost: 0.87 },
];

const MOCK_MODELS = [
  { model: "claude-sonnet-4-6",      calls: 312, cost: 8.42, avg_score: 8.7 },
  { model: "claude-haiku-4-5",       calls: 48,  cost: 0.31, avg_score: 7.9 },
  { model: "gpt-4.1",               calls: 12,  cost: 0.89, avg_score: 7.4 },
];

const SPOT_WORKERS = [
  { id: "spot-1a", status: "running",     tours: 12, progress: 78, instance: "c5.xlarge" },
  { id: "spot-1b", status: "running",     tours: 8,  progress: 45, instance: "c5.xlarge" },
  { id: "spot-2a", status: "interrupted", tours: 5,  progress: 62, instance: "c5.2xlarge" },
  { id: "spot-2b", status: "idle",        tours: 0,  progress: 0,  instance: "c5.xlarge" },
];

const PIPELINE_HEALTH = [
  { name: "Ingestion Lambda",    status: "healthy",  latency: "1.2s",  errors: 0 },
  { name: "SEO Intelligence",    status: "healthy",  latency: "3.8s",  errors: 0 },
  { name: "Content Generation",  status: "degraded", latency: "48.2s", errors: 2 },
  { name: "Validation Lambda",   status: "healthy",  latency: "0.8s",  errors: 0 },
  { name: "Export Lambda",       status: "healthy",  latency: "0.5s",  errors: 0 },
  { name: "DLQ Classifier",      status: "healthy",  latency: "0.3s",  errors: 0 },
];

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

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<"metrics" | "health" | "spot" | "langfuse">("metrics");
  const [totalTours,  setTotalTours]  = useState(0);
  const [totalHITL,   setTotalHITL]   = useState(0);
  const [totalPassed, setTotalPassed] = useState(0);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    const h = { Authorization: `Bearer ${token}` };
    fetch(`${API_URL}/v1/tours?page=1&page_size=1`, { headers: h })
      .then(r => r.json())
      .then(d => { const t = d.pagination?.total || 0; setTotalTours(t); setTotalPassed(t); })
      .catch(() => {});
    fetch(`${API_URL}/v1/pipeline/review-queue?page_size=1`, { headers: h })
      .then(r => r.json())
      .then(d => setTotalHITL(d.pagination?.total || 0))
      .catch(() => {});
  }, []);

  const totalCost = (totalTours * 0.006).toFixed(2);
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
      {activeTab === "metrics" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <ChartCard title="Daily Pipeline Volume">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={MOCK_RUNS} barGap={2}>
                  <XAxis dataKey="date" tick={{ fill: "#8B9BB4", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#8B9BB4", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Bar dataKey="passed" name="Auto-Approved" fill="#22c55e" radius={[4,4,0,0]} />
                  <Bar dataKey="hitl"   name="HITL"          fill="#DB9628" radius={[4,4,0,0]} />
                  <Bar dataKey="failed" name="Failed"        fill="#ef4444" radius={[4,4,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
            <ChartCard title="Daily LLM Cost (USD)">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={MOCK_RUNS}>
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
                {MOCK_MODELS.map(m => (
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
            {PIPELINE_HEALTH.map(s => (
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
            {SPOT_WORKERS.map(w => (
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
            <a href="http://localhost:3001" target="_blank" rel="noreferrer"
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 14px", background: "var(--brand-gold)", borderRadius: 8, color: "white", fontSize: 12, fontWeight: 600, textDecoration: "none" }}>
              <ExternalLink size={12} /> Open Langfuse
            </a>
          </div>

          {/* Iframe embed with fallback */}
          <div style={{ position: "relative", borderRadius: 10, overflow: "hidden", border: "1px solid var(--border)", background: "var(--bg-primary)", height: 480 }}>
            <iframe
              src={process.env.NEXT_PUBLIC_LANGFUSE_URL || "http://localhost:3001"}
              style={{ width: "100%", height: "100%", border: "none" }}
              title="Langfuse Dashboard"
              onError={() => {}}
            />
            {/* Fallback overlay — shown when Langfuse not yet deployed */}
            <div style={{
              position: "absolute", inset: 0,
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              background: "var(--bg-primary)",
              gap: 16,
            }}>
              <div style={{ fontSize: 32 }}>🔍</div>
              <div style={{ fontWeight: 600, color: "var(--text-primary)", fontSize: 16 }}>
                Langfuse Not Yet Connected
              </div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", textAlign: "center", maxWidth: 360, lineHeight: 1.6 }}>
                Langfuse will be available after <code style={{ color: "var(--brand-gold)", background: "rgba(219,150,40,0.1)", padding: "1px 6px", borderRadius: 4 }}>terraform apply</code> deploys the ECS service.
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%", maxWidth: 360 }}>
                {[
                  { label: "LLM Traces", desc: "Every prompt + completion logged" },
                  { label: "Cost Breakdown", desc: "Per tour, per model, per batch" },
                  { label: "Quality Trends", desc: "Score history + retry patterns" },
                  { label: "Prompt Versions", desc: "A/B test prompt iterations" },
                ].map(f => (
                  <div key={f.label} style={{ display: "flex", gap: 12, padding: "10px 14px", background: "var(--bg-card)", borderRadius: 8, border: "1px solid var(--border)" }}>
                    <CheckCircle size={15} style={{ color: "#22c55e", flexShrink: 0, marginTop: 1 }} />
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{f.label}</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{f.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </ChartCard>
      )}
    </div>
  );
}
