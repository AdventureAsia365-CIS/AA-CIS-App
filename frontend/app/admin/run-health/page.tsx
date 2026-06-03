"use client";
// app/admin/run-health/page.tsx — AA-141 Run-Health Dashboard

import React, { useState, useEffect, useCallback } from "react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, mono, sans, Card, SLabel } from "../_components/adminUi";

// ── Types ─────────────────────────────────────────────────────────────────────

interface StageRecord {
  stage: string;
  status: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error_msg: string | null;
  slo_breached: boolean;
}

interface GateStatus {
  status: string;
  elapsed_hours: number | null;
  sla_hours: number;
  breached: boolean;
  auto_approved: boolean;
} | null

interface RunHealth {
  run_id: string;
  tenant_id: string;
  country: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  stages: StageRecord[];
  total_cost_usd: number;
  cost_cap_breached: boolean;
  gate_statuses: Record<string, GateStatus>;
  evaluator_score: number | null;
  evaluator_warning: boolean;
  retry_count: number;
  stuck: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  completed:  A.green,
  running:    A.amber,
  pending:    A.amber,
  failed:     A.red,
  stuck:      A.red,
  approved:   A.green,
  rejected:   A.red,
};

function statusColor(s: string | null, stuck = false): string {
  if (stuck) return A.red;
  return STATUS_COLOR[(s ?? "").toLowerCase()] ?? A.muted;
}

function fmtDuration(secs: number | null): string {
  if (secs === null) return "—";
  if (secs < 60) return `${Math.round(secs)}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m`;
  return `${(secs / 3600).toFixed(1)}h`;
}

function fmtCost(usd: number): string {
  return usd === 0 ? "$0" : `$${usd.toFixed(3)}`;
}

function shortId(id: string): string {
  return id.slice(0, 8) + "…";
}

// ── SLO Badge ─────────────────────────────────────────────────────────────────

function SLOBadge({ ok, label }: { ok: boolean; label: string }) {
  const color = ok ? A.green : A.red;
  const bg    = ok ? A.greenSoft : "#FEE2E2";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 7px", borderRadius: 999, fontSize: 10.5, fontWeight: 600,
      background: bg, color, fontFamily: mono,
    }}>
      <span style={{ fontSize: 8 }}>{ok ? "●" : "●"}</span>
      {label}
    </span>
  );
}

// ── Stage Timeline ─────────────────────────────────────────────────────────────

function StageTimeline({ stages }: { stages: StageRecord[] }) {
  if (!stages.length) {
    return <div style={{ padding: "8px 0", color: A.muted2, fontSize: 12 }}>No stage data</div>;
  }

  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", padding: "10px 0 4px" }}>
      {stages.map((s, i) => {
        const color = s.slo_breached ? A.red : statusColor(s.status);
        const bg    = s.slo_breached ? "#FEE2E2" : s.status === "completed" ? A.greenSoft : A.amberSoft;
        return (
          <div key={i} style={{
            border: `1px solid ${color}40`, borderRadius: 8,
            padding: "7px 11px", background: bg, minWidth: 90,
          }}>
            <div style={{ fontFamily: mono, fontSize: 10, fontWeight: 700, color, marginBottom: 3 }}>
              {s.stage.toUpperCase()}
            </div>
            <div style={{ fontSize: 10, color: A.muted, marginBottom: 2 }}>
              {fmtDuration(s.duration_seconds)}
            </div>
            {s.slo_breached && (
              <div style={{ fontSize: 9, color: A.red, fontWeight: 600 }}>SLO breached</div>
            )}
            {s.error_msg && (
              <div style={{ fontSize: 9, color: A.red, marginTop: 3, wordBreak: "break-all" }}>
                {s.error_msg.slice(0, 60)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Gate Summary ──────────────────────────────────────────────────────────────

function GateSummary({ gates }: { gates: Record<string, GateStatus> }) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
      {[0, 1, 2, 3].map(gn => {
        const key = `gate_${gn}`;
        const g = gates[key];
        if (!g) {
          return (
            <span key={gn} style={{
              padding: "2px 8px", borderRadius: 999, fontSize: 10.5,
              background: A.line, color: A.muted2, fontFamily: mono,
            }}>G{gn} —</span>
          );
        }
        const breached = g.breached;
        const color = breached ? A.red : g.status === "approved" ? A.green : A.amber;
        return (
          <span key={gn} style={{
            padding: "2px 8px", borderRadius: 999, fontSize: 10.5, fontWeight: 600,
            background: breached ? "#FEE2E2" : g.status === "approved" ? A.greenSoft : A.amberSoft,
            color, fontFamily: mono,
          }} title={`Gate ${gn}: SLA ${g.sla_hours}h${g.elapsed_hours ? ` | elapsed ${g.elapsed_hours.toFixed(1)}h` : ""}`}>
            G{gn} {g.status}{breached ? " ⚠" : ""}
          </span>
        );
      })}
    </div>
  );
}

// ── Filter Bar ────────────────────────────────────────────────────────────────

interface Filters {
  country: string;
  status: string;
  date_from: string;
  date_to: string;
}

function FilterBar({ filters, onChange }: {
  filters: Filters;
  onChange: (f: Filters) => void;
}) {
  const inp: React.CSSProperties = {
    padding: "5px 10px", borderRadius: 6, border: `1px solid ${A.line}`,
    background: "#fff", fontSize: 12, fontFamily: sans, color: A.ink,
    outline: "none", width: 130,
  };

  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 16 }}>
      <input
        style={inp} placeholder="Country"
        value={filters.country}
        onChange={e => onChange({ ...filters, country: e.target.value })}
      />
      <select
        style={{ ...inp, width: 120, cursor: "pointer" }}
        value={filters.status}
        onChange={e => onChange({ ...filters, status: e.target.value })}
      >
        <option value="">All status</option>
        <option value="running">Running</option>
        <option value="completed">Completed</option>
        <option value="failed">Failed</option>
        <option value="pending">Pending</option>
      </select>
      <input
        style={inp} type="date" placeholder="From"
        value={filters.date_from}
        onChange={e => onChange({ ...filters, date_from: e.target.value })}
      />
      <input
        style={inp} type="date" placeholder="To"
        value={filters.date_to}
        onChange={e => onChange({ ...filters, date_to: e.target.value })}
      />
      <button
        style={{
          padding: "5px 12px", borderRadius: 6, border: `1px solid ${A.line}`,
          background: "#fff", fontSize: 12, cursor: "pointer", color: A.muted,
        }}
        onClick={() => onChange({ country: "", status: "", date_from: "", date_to: "" })}
      >Clear</button>
    </div>
  );
}

// ── Run Row ───────────────────────────────────────────────────────────────────

function RunRow({ run }: { run: RunHealth }) {
  const [expanded, setExpanded] = useState(false);
  const rowBg = run.stuck ? "#FFF1F1" : run.cost_cap_breached ? "#FFFBEB" : "#fff";

  return (
    <>
      <tr
        onClick={() => setExpanded(v => !v)}
        style={{ background: rowBg, cursor: "pointer" }}
      >
        <td style={tdStyle}>
          <span style={{ fontFamily: mono, fontSize: 11, color: A.muted }}>{shortId(run.run_id)}</span>
        </td>
        <td style={tdStyle}>
          <span style={{ fontSize: 12 }}>{run.country || "—"}</span>
        </td>
        <td style={tdStyle}>
          <span style={{
            display: "inline-block", padding: "2px 8px", borderRadius: 999,
            fontSize: 10.5, fontWeight: 600, fontFamily: mono,
            background: run.stuck ? "#FEE2E2" : statusColor(run.status) + "22",
            color: statusColor(run.status, run.stuck),
          }}>
            {run.stuck ? "STUCK" : (run.status ?? "—").toUpperCase()}
          </span>
        </td>
        <td style={tdStyle}>
          <span style={{ fontFamily: mono, fontSize: 12, color: run.cost_cap_breached ? A.red : A.ink }}>
            {fmtCost(run.total_cost_usd)}
          </span>
          {run.cost_cap_breached && (
            <span style={{ marginLeft: 5, fontSize: 10, color: A.red, fontWeight: 700 }}>⚠ cap</span>
          )}
        </td>
        <td style={tdStyle}>
          {run.evaluator_score !== null ? (
            <SLOBadge ok={!run.evaluator_warning} label={`${run.evaluator_score.toFixed(1)}/10`} />
          ) : <span style={{ color: A.muted2, fontSize: 11 }}>—</span>}
        </td>
        <td style={tdStyle}>
          <GateSummary gates={run.gate_statuses} />
        </td>
        <td style={tdStyle}>
          <span style={{ fontSize: 11, color: A.muted2 }}>
            {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
          </span>
        </td>
        <td style={{ ...tdStyle, textAlign: "center" }}>
          <span style={{ fontSize: 11, color: A.muted2 }}>{expanded ? "▲" : "▼"}</span>
        </td>
      </tr>
      {expanded && (
        <tr style={{ background: rowBg }}>
          <td colSpan={8} style={{ padding: "0 16px 12px 16px", borderBottom: `1px solid ${A.line}` }}>
            <StageTimeline stages={run.stages} />
          </td>
        </tr>
      )}
    </>
  );
}

const tdStyle: React.CSSProperties = {
  padding: "10px 14px", borderBottom: `1px solid ${A.line}`,
  fontSize: 12, color: A.body, verticalAlign: "middle",
};

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function RunHealthPage() {
  const [runs, setRuns]     = useState<RunHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);
  const [filters, setFilters] = useState<Filters>({
    country: "", status: "", date_from: "", date_to: "",
  });

  const fetchData = useCallback(() => {
    const params = new URLSearchParams({ limit: "50" });
    if (filters.country)   params.set("country", filters.country);
    if (filters.status)    params.set("status", filters.status);
    if (filters.date_from) params.set("date_from", filters.date_from);
    if (filters.date_to)   params.set("date_to", filters.date_to);

    fetch(`/api/admin/acp/run-health?${params}`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(data => {
        setRuns(data);
        setError(null);
        setLastFetch(new Date());
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [filters]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
  }, [fetchData]);

  const stuckCount    = runs.filter(r => r.stuck).length;
  const capCount      = runs.filter(r => r.cost_cap_breached).length;
  const gateBreaches  = runs.reduce((n, r) =>
    n + Object.values(r.gate_statuses).filter(g => g?.breached).length, 0);

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />

      <div style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0 }}>
              Run Health
            </h1>
            <div style={{ fontSize: 12, color: A.muted, marginTop: 4 }}>
              Live ACP pipeline state — refreshes every 30s
              {lastFetch && ` · Last update ${lastFetch.toLocaleTimeString()}`}
            </div>
          </div>
          <button
            onClick={fetchData}
            style={{
              padding: "7px 14px", borderRadius: 7,
              border: `1px solid ${A.line}`, background: "#fff",
              fontSize: 12, cursor: "pointer", color: A.muted,
            }}
          >Refresh</button>
        </div>

        {/* Summary strip */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 24 }}>
          <Card>
            <SLabel>Total Runs</SLabel>
            <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: A.ink }}>{runs.length}</div>
          </Card>
          <Card>
            <SLabel>Stuck</SLabel>
            <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: stuckCount > 0 ? A.red : A.ink }}>
              {stuckCount}
            </div>
          </Card>
          <Card>
            <SLabel>Cost Cap Breached</SLabel>
            <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: capCount > 0 ? A.amber : A.ink }}>
              {capCount}
            </div>
          </Card>
          <Card>
            <SLabel>Gate SLA Breaches</SLabel>
            <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: gateBreaches > 0 ? A.red : A.ink }}>
              {gateBreaches}
            </div>
          </Card>
        </div>

        {/* Filters */}
        <FilterBar filters={filters} onChange={setFilters} />

        {/* Table */}
        <Card style={{ padding: 0, overflow: "hidden" }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: "center", color: A.muted }}>Loading…</div>
          ) : error ? (
            <div style={{ padding: 40, textAlign: "center", color: A.red }}>{error}</div>
          ) : runs.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: A.muted2 }}>No runs found</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: A.bg }}>
                  {["Run ID", "Country", "Status", "Cost", "Eval Score", "Gates", "Started", ""].map(h => (
                    <th key={h} style={{
                      padding: "10px 14px", textAlign: "left",
                      fontSize: 10.5, fontWeight: 600, letterSpacing: "0.1em",
                      textTransform: "uppercase", color: A.muted,
                      borderBottom: `1px solid ${A.line}`,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map(run => <RunRow key={run.run_id} run={run} />)}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
