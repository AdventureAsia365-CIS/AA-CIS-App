"use client";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from "recharts";
import { FileText, CheckCircle, Clock, DollarSign } from "lucide-react";

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

const TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: "#1A2230",
    border: "1px solid #2A3547",
    borderRadius: 8, fontSize: 12,
  },
  labelStyle: { color: "#F8F6F2" },
};

function StatCard({ icon: Icon, label, value, sub, accent = "#DB9628" }: {
  icon: any; label: string; value: string; sub?: string; accent?: string;
}) {
  return (
    <div style={{
      background: "var(--bg-card)", border: "1px solid var(--border)",
      borderRadius: 12, padding: "20px 24px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <div style={{
          padding: 8, borderRadius: 8,
          background: `${accent}18`, color: accent,
        }}>
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
    <div style={{
      background: "var(--bg-card)", border: "1px solid var(--border)",
      borderRadius: 12, padding: "20px 24px",
    }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)",
        textTransform: "uppercase", letterSpacing: 1, marginBottom: 20 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

export default function DashboardPage() {
  const totalTours  = MOCK_RUNS.reduce((s, r) => s + r.tours,  0);
  const totalPassed = MOCK_RUNS.reduce((s, r) => s + r.passed, 0);
  const totalHITL   = MOCK_RUNS.reduce((s, r) => s + r.hitl,   0);
  const totalCost   = MOCK_RUNS.reduce((s, r) => s + r.cost,   0);
  const passRate    = ((totalPassed / totalTours) * 100).toFixed(1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
          Dev Dashboard
        </h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 6 }}>
          Pipeline metrics · Last 7 days · Mock data (live after Terraform apply)
        </p>
      </div>

      {/* Stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16 }}>
        <StatCard icon={FileText}    label="Tours Processed" value={String(totalTours)}         sub="Last 7 days"             accent="#DB9628" />
        <StatCard icon={CheckCircle} label="Auto-Approved"   value={`${passRate}%`}             sub={`${totalPassed} tours`}  accent="#22c55e" />
        <StatCard icon={Clock}       label="HITL Queue"      value={String(totalHITL)}           sub="Awaiting human review"   accent="#f59e0b" />
        <StatCard icon={DollarSign}  label="Total LLM Cost"  value={`$${totalCost.toFixed(2)}`} sub="~$0.018 per tour avg"    accent="#ef4444" />
      </div>

      {/* Charts */}
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
              <YAxis tick={{ fill: "#8B9BB4", fontSize: 11 }} axisLine={false} tickLine={false}
                tickFormatter={v => `$${v}`} />
              <Tooltip {...TOOLTIP_STYLE} formatter={(v: any) => [`$${v}`, "Cost"]} />
              <Line type="monotone" dataKey="cost"
                stroke="#DB9628" strokeWidth={2.5}
                dot={{ fill: "#DB9628", r: 4, strokeWidth: 0 }}
                activeDot={{ r: 6, fill: "#DB9628" }} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* LLM Model table */}
      <ChartCard title="LLM Model Usage">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Model", "Calls", "Total Cost", "Avg Score", "Cost / Call"].map(h => (
                <th key={h} style={{
                  textAlign: h === "Model" ? "left" : "right",
                  padding: "6px 12px 10px", fontSize: 11,
                  color: "var(--text-muted)", fontWeight: 600,
                  textTransform: "uppercase", letterSpacing: 1,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {MOCK_MODELS.map(m => (
              <tr key={m.model} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "12px", fontFamily: "monospace",
                  fontSize: 13, color: "var(--brand-gold)" }}
                  onMouseEnter={e => (e.currentTarget.style.color = "#f59e0b")}
                  onMouseLeave={e => (e.currentTarget.style.color = "var(--brand-gold)")}>
                  {m.model}
                </td>
                <td style={{ padding: 12, textAlign: "right", color: "var(--text-secondary)", fontSize: 13 }}>
                  {m.calls}
                </td>
                <td style={{ padding: 12, textAlign: "right", color: "var(--text-secondary)", fontSize: 13 }}>
                  ${m.cost.toFixed(2)}
                </td>
                <td style={{ padding: 12, textAlign: "right" }}>
                  <span style={{
                    fontWeight: 700, fontSize: 13,
                    color: m.avg_score >= 8.5 ? "#22c55e" :
                           m.avg_score >= 7.5 ? "#DB9628" : "#f59e0b",
                  }}>{m.avg_score}</span>
                </td>
                <td style={{ padding: 12, textAlign: "right", color: "var(--text-muted)", fontSize: 13 }}>
                  ${(m.cost / m.calls).toFixed(4)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ChartCard>
    </div>
  );
}
