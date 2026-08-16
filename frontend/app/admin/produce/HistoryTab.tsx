"use client";
// app/admin/produce/HistoryTab.tsx — AA-412 Phần B: N7 run history + gate_ledger drill-down.
//
// GET /api/admin/produce/runs lists every past run with a per-gate final-state pass/fail
// summary (F1/F3/F4/F5/F8/F9…) — the same shape docs/claude_audit/AA-404-n7-run6-results.md
// built by hand querying the DB directly; this tab is that report turned into a live view.
// Drill-down reuses the existing GET /api/admin/produce/run/{id} (extended by AA-412 to also
// return gate_ledger/brand_seo_audit/review_status per piece).

import { useState, useEffect, useCallback } from "react";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { A, mono, Card, SLabel, Btn, Badge, Spinner, TH, TD } from "../_components/adminUi";

interface GateSummaryEntry { passed: number; failed: number; }

interface RunSummary {
  run_id: string;
  tenant_id: string;
  year: number;
  month: number;
  week: number;
  status: string;
  triggered_at: string | null;
  completed_at: string | null;
  piece_count: number;
  passed_count: number;
  held_count: number;
  gate_summary: Record<string, GateSummaryEntry>;
}

interface PieceDrillDown {
  piece_id: string;
  channel: string;
  status: string;
  held_reason: string | null;
  repair_count: number;
  gate_ledger: { gate: string; passed: boolean; violations: string[] }[];
  brand_seo_audit: Record<string, unknown> | null;
  review_status: string;
}

interface RunDetailResponse {
  pieces: PieceDrillDown[];
}

// Canonical gate display order — matches docs/claude_audit/AA-404-n7-run6-results.md's own table.
const GATE_ORDER = [
  "F1_grounding", "F3_structural_variance", "F4_brief_compliance",
  "F5_atom_density", "F8_framework", "F9_brand_seo_audit", "F9_brand_seo_audit_social",
];

function orderedGates(summary: Record<string, GateSummaryEntry>): string[] {
  const known = GATE_ORDER.filter(g => g in summary);
  const rest = Object.keys(summary).filter(g => !GATE_ORDER.includes(g)).sort();
  return [...known, ...rest];
}

function GateCell({ entry }: { entry: GateSummaryEntry | undefined }) {
  if (!entry) return <span style={{ color: A.muted2 }}>—</span>;
  const total = entry.passed + entry.failed;
  const color = entry.failed === 0 ? A.green : (entry.failed === total ? A.red : A.amber);
  return (
    <span style={{ fontSize: 12, fontFamily: mono, color }}>
      {entry.passed}/{total}
    </span>
  );
}

function RunDrillDown({ run, tenantName }: { run: RunSummary; tenantName: string }) {
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    // No synchronous setLoading(true) here — `loading` already starts true (mount-once effect,
    // this component only exists while its row is expanded) and react-hooks/set-state-in-effect
    // flags a setState call made synchronously in an effect body.
    fetch(`/api/admin/produce/run/${run.run_id}`)
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then((d: RunDetailResponse) => { setDetail(d); setError(""); })
      .catch(() => setError("Failed to load run detail."))
      .finally(() => setLoading(false));
  }, [run.run_id]);

  return (
    <div style={{ padding: "14px 20px 20px", background: A.bg }}>
      <div style={{ fontSize: 12, color: A.muted, marginBottom: 10 }}>
        {tenantName} — {run.year}-{String(run.month).padStart(2, "0")} week {run.week} —
        run <span style={{ fontFamily: mono }}>{run.run_id}</span>
      </div>
      {loading && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Spinner size={16} /> <span style={{ fontSize: 12.5, color: A.muted }}>Loading gate ledger…</span>
        </div>
      )}
      {error && <div style={{ fontSize: 12.5, color: A.red }}>{error}</div>}
      {detail && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={TH}>Piece</th><th style={TH}>Channel</th><th style={TH}>Status</th>
                <th style={TH}>Review</th><th style={TH}>Held Reason</th><th style={TH}>Gate Detail</th>
              </tr>
            </thead>
            <tbody>
              {detail.pieces.map(p => (
                <tr key={p.piece_id}>
                  <td style={{ ...TD, fontFamily: mono, fontSize: 11.5 }}>{p.piece_id.split(":").slice(1).join(":")}</td>
                  <td style={TD}><Badge color="blue">{p.channel}</Badge></td>
                  <td style={TD}>{p.status === "passed" ? <Badge color="green">Passed</Badge> : <Badge color="amber">Held</Badge>}</td>
                  <td style={TD}>
                    <Badge color={p.review_status === "approved" ? "green" : p.review_status === "rejected" ? "red" : "gray"}>
                      {p.review_status}
                    </Badge>
                  </td>
                  <td style={{ ...TD, fontSize: 11.5, color: A.muted, maxWidth: 300 }}>{p.held_reason ?? "—"}</td>
                  <td style={{ ...TD, fontSize: 11, color: A.muted }}>
                    {p.gate_ledger.filter(g => !g.passed).map(g => g.gate).join(", ") || "all pass"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function HistoryTab({ tenantNameById }: { tenantNameById: Record<string, string> }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  const loadRuns = useCallback(() => {
    // No synchronous setLoading(true) here — called from useEffect below too, and
    // react-hooks/set-state-in-effect flags setState invoked synchronously from an effect.
    // `loading` already starts true for the initial mount; the Refresh button's onClick sets it
    // back to true itself (a click handler, not an effect) before calling this.
    fetch("/api/admin/produce/runs")
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then((d: RunSummary[]) => { setRuns(d); setError(""); })
      .catch(() => setError("Failed to load run history."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const gateColumns = orderedGates(
    runs.reduce((acc, r) => ({ ...acc, ...r.gate_summary }), {} as Record<string, GateSummaryEntry>)
  );

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <SLabel style={{ marginBottom: 0 }}>Run History — N7 Produce</SLabel>
        <Btn variant="ghost" size="sm" onClick={() => { setLoading(true); loadRuns(); }}>
          <RefreshCw size={12} /> Refresh
        </Btn>
      </div>
      <div style={{ fontSize: 11.5, color: A.muted2, marginBottom: 14 }}>
        Every N7 run triggered for any tenant, most recent first. Click a row to see the full
        gate ledger per piece — same shape as a by-hand DB pull, now live.
      </div>
      {error && <div style={{ fontSize: 12.5, color: A.red, marginBottom: 10 }}>{error}</div>}
      {loading && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "16px 0" }}>
          <Spinner size={18} /> <span style={{ fontSize: 13, color: A.muted }}>Loading run history…</span>
        </div>
      )}
      {!loading && runs.length === 0 && !error && (
        <div style={{ fontSize: 13, color: A.muted, padding: "16px 0" }}>No runs triggered yet.</div>
      )}
      {!loading && runs.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={TH}></th>
                <th style={TH}>Tenant</th><th style={TH}>Week</th><th style={TH}>Status</th>
                <th style={TH}>Triggered</th><th style={TH}>Pieces</th>
                {gateColumns.map(g => <th key={g} style={TH}>{g.replace(/_/g, " ")}</th>)}
              </tr>
            </thead>
            <tbody>
              {runs.map(run => (
                <>
                  <tr key={run.run_id} style={{ cursor: "pointer" }}
                    onClick={() => setExpandedRunId(id => id === run.run_id ? null : run.run_id)}>
                    <td style={TD}>
                      {expandedRunId === run.run_id ? <ChevronDown size={14} color={A.muted} /> : <ChevronRight size={14} color={A.muted} />}
                    </td>
                    <td style={TD}>{tenantNameById[run.tenant_id] ?? `${run.tenant_id.slice(0, 8)}…`}</td>
                    <td style={TD}>{run.year}-{String(run.month).padStart(2, "0")} W{run.week}</td>
                    <td style={TD}>
                      <Badge color={run.status === "completed" ? "green" : run.status === "failed" ? "red" : "amber"}>
                        {run.status}
                      </Badge>
                    </td>
                    <td style={{ ...TD, fontSize: 11.5, color: A.muted }}>
                      {run.triggered_at ? new Date(run.triggered_at).toLocaleString() : "—"}
                    </td>
                    <td style={TD}>{run.passed_count} passed / {run.held_count} held / {run.piece_count} total</td>
                    {gateColumns.map(g => (
                      <td key={g} style={TD}><GateCell entry={run.gate_summary[g]} /></td>
                    ))}
                  </tr>
                  {expandedRunId === run.run_id && (
                    <tr key={`${run.run_id}-detail`}>
                      <td colSpan={6 + gateColumns.length} style={{ padding: 0, borderBottom: `1px solid ${A.line2}` }}>
                        <RunDrillDown run={run} tenantName={tenantNameById[run.tenant_id] ?? run.tenant_id} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
