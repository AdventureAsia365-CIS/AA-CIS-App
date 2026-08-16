"use client";
// app/admin/produce/HistoryTab.tsx — AA-412 Phần B: N7 run history + gate_ledger drill-down.
//
// GET /api/admin/produce/runs lists every past run with a per-gate final-state pass/fail
// summary (F1/F3/F4/F5/F8/F9…) — the same shape docs/claude_audit/AA-404-n7-run6-results.md
// built by hand querying the DB directly; this tab is that report turned into a live view.
// Drill-down reuses the existing GET /api/admin/produce/run/{id} (extended by AA-412 to also
// return gate_ledger/brand_seo_audit/review_status per piece).
//
// AA-412 follow-up (readability): the original table (Tenant/Week/Status/Triggered/Pieces +
// 7 gate columns, all at TH/TD's normal 13px) overflowed 1920px and needed horizontal scroll to
// see the gate columns, which then hid the row underneath as it scrolled. Fix here is column
// budgeting, not hiding data: `table-layout: fixed` with a <colgroup> of PERCENTAGES that always
// sum to exactly 100% (identity columns get a fixed share; the remainder splits evenly across
// however many gate columns the data has) guarantees the table renders at true 100% width with
// no overflow at standard viewports — no per-column px guess to get wrong. Identity columns also
// shrink a bit (e.g. "Triggered" drops to date-only, full timestamp still in a title tooltip) and
// gate headers use short labels (full gate name in a title tooltip) so nothing gets truncated.
// Horizontal scroll is kept as a local, table-only fallback (never a page-level scroll) for
// windows narrower than what real content needs to stay readable.

import { useState, useEffect, useCallback, Fragment } from "react";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { A, mono, Card, SLabel, Btn, Badge, Spinner } from "../_components/adminUi";

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

// Short labels keep the gate columns narrow without dropping any gate or truncating its count —
// full gate name still shown as a title tooltip on the header cell.
const GATE_SHORT_LABEL: Record<string, string> = {
  F1_grounding: "F1",
  F3_structural_variance: "F3",
  F4_brief_compliance: "F4",
  F5_atom_density: "F5",
  F8_framework: "F8",
  F9_brand_seo_audit: "F9 brand",
  F9_brand_seo_audit_social: "F9 social",
};

// Column widths are set entirely by each table's own <colgroup> (percentages, always summing to
// 100%) — these two style objects are just the shared cell chrome (padding/font/border), no
// `width` here, so they can't fight the colgroup for column sizing under table-layout: fixed.
const gateTh: React.CSSProperties = {
  padding: "10px 6px", fontSize: 10.5, fontWeight: 600,
  textTransform: "uppercase", letterSpacing: "0.04em",
  color: A.muted, textAlign: "center", background: A.bg,
  borderBottom: `1px solid ${A.line}`,
};

const gateTd: React.CSSProperties = {
  padding: "11px 6px", fontSize: 11.5, color: A.body, textAlign: "center",
  borderBottom: `1px solid ${A.line2}`,
};

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
    <span style={{ fontSize: 11.5, fontFamily: mono, color, fontWeight: 600 }}>
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
        // Local scroll fallback ONLY — this div, not the page, scrolls if the viewport is too
        // narrow to fit every column. At 1440px+ the fixed layout below fits without scrolling.
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
            <colgroup>
              <col style={{ width: "16%" }} />
              <col style={{ width: "10%" }} />
              <col style={{ width: "10%" }} />
              <col style={{ width: "10%" }} />
              <col style={{ width: "24%" }} />
              <col style={{ width: "30%" }} />
            </colgroup>
            <thead>
              <tr>
                <th style={gateTh}>Piece</th><th style={gateTh}>Channel</th><th style={gateTh}>Status</th>
                <th style={gateTh}>Review</th><th style={gateTh}>Held Reason</th><th style={gateTh}>Gate Detail</th>
              </tr>
            </thead>
            <tbody>
              {detail.pieces.map(p => (
                <tr key={p.piece_id}>
                  <td style={{ ...gateTd, fontFamily: mono, fontSize: 11, textAlign: "left" }} title={p.piece_id}>
                    {p.piece_id.split(":").slice(1).join(":")}
                  </td>
                  <td style={{ ...gateTd, textAlign: "left" }}><Badge color="blue">{p.channel}</Badge></td>
                  <td style={{ ...gateTd, textAlign: "left" }}>
                    {p.status === "passed" ? <Badge color="green">Passed</Badge> : <Badge color="amber">Held</Badge>}
                  </td>
                  <td style={{ ...gateTd, textAlign: "left" }}>
                    <Badge color={p.review_status === "approved" ? "green" : p.review_status === "rejected" ? "red" : "gray"}>
                      {p.review_status}
                    </Badge>
                  </td>
                  <td style={{ ...gateTd, fontSize: 11, color: A.muted, textAlign: "left", whiteSpace: "normal" }}>
                    {p.held_reason ?? "—"}
                  </td>
                  <td style={{ ...gateTd, fontSize: 11, color: A.muted, textAlign: "left", whiteSpace: "normal" }}>
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

  // All-percentage column budget (identity + gates always sum to exactly 100%) — this is what
  // keeps the table at true 100% viewport width with no page-level horizontal scroll, regardless
  // of how many gate columns a given dataset has (7 today, more if a new gate is added later).
  const identityColPercents = [2, 14, 8, 9, 12, 15]; // chevron, tenant, week, status, triggered, pieces
  const identityPercentSum = identityColPercents.reduce((a, b) => a + b, 0);
  const gatePercentEach = gateColumns.length > 0
    ? (100 - identityPercentSum) / gateColumns.length
    : 0;

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
        // Local scroll fallback ONLY (never the page) — the colgroup below always sums to 100%
        // of the table, so at 1440x900/1920x1080 this fits with zero scrolling; overflow-x only
        // engages if the browser window itself is narrower than each cell's readable minimum.
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
            <colgroup>
              {identityColPercents.map((p, i) => <col key={i} style={{ width: `${p}%` }} />)}
              {gateColumns.map(g => <col key={g} style={{ width: `${gatePercentEach}%` }} />)}
            </colgroup>
            <thead>
              <tr>
                <th style={gateTh}></th>
                <th style={{ ...gateTh, textAlign: "left" }}>Tenant</th>
                <th style={{ ...gateTh, textAlign: "left" }}>Week</th>
                <th style={{ ...gateTh, textAlign: "left" }}>Status</th>
                <th style={{ ...gateTh, textAlign: "left" }}>Triggered</th>
                <th style={{ ...gateTh, textAlign: "left" }}>Pieces</th>
                {gateColumns.map(g => (
                  <th key={g} style={gateTh} title={g.replace(/_/g, " ")}>
                    {GATE_SHORT_LABEL[g] ?? g.replace(/_/g, " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map(run => (
                <Fragment key={run.run_id}>
                  <tr style={{ cursor: "pointer" }}
                    onClick={() => setExpandedRunId(id => id === run.run_id ? null : run.run_id)}>
                    <td style={gateTd}>
                      {expandedRunId === run.run_id ? <ChevronDown size={14} color={A.muted} /> : <ChevronRight size={14} color={A.muted} />}
                    </td>
                    <td style={{ ...gateTd, textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      title={tenantNameById[run.tenant_id] ?? run.tenant_id}>
                      {tenantNameById[run.tenant_id] ?? `${run.tenant_id.slice(0, 8)}…`}
                    </td>
                    <td style={{ ...gateTd, textAlign: "left" }}>{run.year}-{String(run.month).padStart(2, "0")} W{run.week}</td>
                    <td style={{ ...gateTd, textAlign: "left" }}>
                      <Badge color={run.status === "completed" ? "green" : run.status === "failed" ? "red" : "amber"}>
                        {run.status}
                      </Badge>
                    </td>
                    <td style={{ ...gateTd, fontSize: 11, color: A.muted, textAlign: "left" }}
                      title={run.triggered_at ? new Date(run.triggered_at).toLocaleString() : undefined}>
                      {run.triggered_at ? new Date(run.triggered_at).toLocaleDateString() : "—"}
                    </td>
                    <td style={{ ...gateTd, fontSize: 11, textAlign: "left" }}>
                      {run.passed_count}/{run.held_count}/{run.piece_count}
                      <span style={{ color: A.muted2 }}> pass/held/total</span>
                    </td>
                    {gateColumns.map(g => (
                      <td key={g} style={gateTd}><GateCell entry={run.gate_summary[g]} /></td>
                    ))}
                  </tr>
                  {expandedRunId === run.run_id && (
                    <tr key={`${run.run_id}-detail`}>
                      <td colSpan={6 + gateColumns.length} style={{ padding: 0, borderBottom: `1px solid ${A.line2}` }}>
                        <RunDrillDown run={run} tenantName={tenantNameById[run.tenant_id] ?? run.tenant_id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
