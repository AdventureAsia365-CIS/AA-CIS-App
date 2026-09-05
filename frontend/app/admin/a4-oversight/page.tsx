"use client";
// app/admin/a4-oversight/page.tsx — AA-437 [A4] Cross-Tenant Oversight v1 + AA-455 bước 1 +
// AA-469 Việc 5
//
// Four sections, all read-only except Publish Log's one mutating action, per Nghiep's decisions
// (Linear AA-437, 23/08/2026):
//   1. Review Log — silver_aa_internal.review_queue rows, T3 (QA-gate escalate) AND (since
//      AA-469 Việc 5) T5 (atomize failure) rows, same table/join key, distinguished only by
//      check_id prefix (structural:/grounding: for T3, t5_atomize: for T5) — no BE/FE branching
//      needed, the existing per-check_id grouping already separates them. Raw rows from the
//      backend; grouped by check_id client-side (BE deliberately does no aggregation — STEP0's
//      own recommendation, less logic server-side, same flat-list-first approach AtomsTab.tsx
//      already uses).
//   2. Trust Ramp — every acp_deliver.packets row with its own publish_mode. No per-tenant
//      rollup: ramp state lives per-PACKET (STEP0 finding), so a tenant with multiple packets
//      shows one row per packet, grouped visually by tenant, never collapsed to one number.
//   3. Publish Log — AA-455 bước 1's one mutating addition: acp_shared.publish_log rows +
//      a "Force unpublish" action on status='published' rows. Per STEP0
//      (docs/claude_audit/AA-455-01-step0-a4-force-unpublish.md §4/§7), this stays a section on
//      THIS SAME page rather than a new route — /admin/a4-oversight is already allowlisted in
//      middleware.ts (since AA-437), and a new route would repeat the exact 307-redirect bug
//      AA-384/388/405/437 each independently hit (a page with no PROTECTED_ROUTES entry
//      silently redirects to /login even with a valid admin session).
//   4. Content Log (AA-469 Việc 5) — acp_shared.content_piece rows with status IN ('held',
//      'failed'). T9/T10 had the best structured error data of any LLM-using stage
//      (gate_ledger/held_reason) but zero A4 path before this — STEP0's own "easiest gap to
//      patch" ranking (data already existed, only the read route was missing).
//
// Style/component pattern follows /admin/run-health (AA-259's own confirmed reference UI for
// this kind of admin monitoring page) — Card/SLabel/Badge/TH/TD from adminUi.tsx, no new
// design pattern introduced.

import { useState, useEffect, useCallback, useMemo } from "react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, mono, sans, Card, Badge } from "../_components/adminUi";

// ── Types ─────────────────────────────────────────────────────────────────────

interface EscalateDetailItem {
  check_id: string;
  field: string | null;
  description: string | null;
  source_span: string | null;
  suggested_fix: string | null;
}

interface ReviewLogRow {
  id: string;
  tour_id: string;
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  tenant_tour_version_id: string;
  failure_summary: string | null;
  escalate_detail: EscalateDetailItem[];
  review_status: string;
  created_at: string | null;
}

interface PublishLogRow {
  publish_id: string;
  piece_id: string;
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  channel: string;
  status: string;
  external_id: string | null;
  external_url: string | null;
  published_at: string | null;
  unpublished_at: string | null;
  unpublished_by: string | null;
  last_error: string | null;
  created_at: string | null;
}

interface GateLedgerEntry {
  gate: string;
  passed: boolean;
  violations: string[];
}

interface ContentLogAngle {
  name: string | null; why_it_works: string | null;
  formula_fit: string | null; best_final_style: string | null;
}

interface ContentLogAtom {
  text: string | null; activity_type: string | null;
  emotional_hook: string | null; season_note: string | null;
}

interface ContentLogTour { name: string | null; destination: string | null }

interface DfsPaaSnapshot { relevance: string; people_also_ask: string[]; related_keywords: string[] }

interface ContentLogRow {
  piece_id: string;
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  angle_gate_request_id: string;
  atom_id: string;
  goal: string | null;
  channel: string | null;
  status: string;
  held_reason: string | null;
  gate_ledger: GateLedgerEntry[];
  gate_pass_count: number;
  gate_total_count: number;
  repair_log: unknown[];
  attempt_number: number;
  content_preview: string | null;
  cta: string | null;
  angle: ContentLogAngle | null;
  atom: ContentLogAtom | null;
  tour: ContentLogTour | null;
  dfs_paa_snapshot: DfsPaaSnapshot | null;
  publish_status: string;
  created_at: string | null;
}

interface TrustRampRow {
  packet_id: string;
  tenant_id: string;
  tenant_name: string | null;
  tenant_slug: string | null;
  year: number;
  month: number;
  week: number;
  status: string;
  publish_mode: string;
  created_at: string | null;
  delivered_at: string | null;
  // AA-464 — on-demand suggestion fields, computed fresh server-side on every fetch.
  engagement_ok: boolean;
  weeks_active: number;
  suggested_mode: string;
  eligible: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(s: string | null): string {
  return s ? new Date(s).toLocaleString() : "—";
}

const RAMP_LABEL: Record<string, string> = {
  propose_only: "Propose Only",
  approve_to_publish: "Approve to Publish",
  veto_window_auto: "Veto Window Auto",
};

function rampBadgeColor(mode: string): "gray" | "amber" | "green" {
  if (mode === "veto_window_auto") return "green";
  if (mode === "approve_to_publish") return "amber";
  return "gray";
}

function publishStatusColor(status: string): "gray" | "amber" | "green" | "red" {
  if (status === "published") return "green";
  if (status === "failed") return "red";
  return "gray"; // unpublished
}

function contentStatusColor(status: string): "amber" | "red" | "green" | "blue" | "gray" {
  // AA-501 — widened from held/failed-only to every status, since content-log now lists every
  // content_piece row, not just failures.
  if (status === "failed") return "red";
  if (status === "held") return "amber";
  if (status === "approved") return "green";
  if (status === "processing") return "blue";
  return "gray";
}

function contentPublishStatusColor(status: string): "green" | "amber" | "gray" {
  // AA-501 — distinct from publishStatusColor() above: this reads content-log's own
  // publish_status ("published"/"pending_publish"/"n/a"), not publish_log.status
  // ("published"/"failed"/"unpublished") the Publish Log section reads.
  if (status === "published") return "green";
  if (status === "pending_publish") return "amber";
  return "gray";
}

// ── Review Log section ───────────────────────────────────────────────────────

function ReviewLogSection() {
  const [rows, setRows] = useState<ReviewLogRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tenantFilter, setTenantFilter] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: "200" });
    if (tenantFilter.trim()) params.set("tenant_id", tenantFilter.trim());
    fetch(`/api/admin/a4/review-log?${params}`)
      .then(r => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then(d => { setRows(d.data || []); setError(null); })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [tenantFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Client-side check_id pattern rollup — deliberately not computed server-side (see file
  // header). Counts how many rows each check_id fired in, across the currently loaded set.
  const checkIdCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const row of rows) {
      for (const item of row.escalate_detail || []) {
        counts[item.check_id] = (counts[item.check_id] || 0) + 1;
      }
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [rows]);

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <h2 style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink, margin: "0 0 4px" }}>
            Review Log — T3/T5 Escalations
          </h2>
          <div style={{ fontSize: 12, color: A.muted }}>
            silver_aa_internal.review_queue rows: T3 QA-gate failures (auto-passed to the tenant,
            logged here for pattern review) and, since AA-469 Việc 5, T5 atomize failures
            (check_id prefixed t5_atomize: — filterable via the Checks badges below) — neither is
            a queue to action, both are post-hoc pattern review.
          </div>
        </div>
        <input
          value={tenantFilter}
          onChange={e => setTenantFilter(e.target.value)}
          placeholder="Filter by tenant_id…"
          style={{
            padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`,
            fontSize: 12, fontFamily: mono, width: 280, outline: "none",
          }}
        />
      </div>

      {checkIdCounts.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
          {checkIdCounts.map(([checkId, count]) => (
            <Badge key={checkId} color={count > 1 ? "amber" : "gray"}>
              {checkId} × {count}
            </Badge>
          ))}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 24, textAlign: "center", color: A.muted }}>Loading…</div>
      ) : error ? (
        <div style={{ padding: 24, textAlign: "center", color: A.red }}>{error}</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: A.muted2 }}>No escalations found.</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: A.bg }}>
                {["Tenant", "Failure Summary", "Checks", "Status", "Created", ""].map(h => (
                  <th key={h} style={{
                    padding: "8px 12px", textAlign: "left", fontSize: 10.5, fontWeight: 600,
                    letterSpacing: "0.08em", textTransform: "uppercase", color: A.muted,
                    borderBottom: `1px solid ${A.line}`,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <RowLine key={row.id} row={row}
                  expanded={expanded === row.id}
                  onToggle={() => setExpanded(expanded === row.id ? null : row.id)} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function RowLine({ row, expanded, onToggle }: {
  row: ReviewLogRow; expanded: boolean; onToggle: () => void;
}) {
  const td: React.CSSProperties = { padding: "10px 12px", borderBottom: `1px solid ${A.line}`, fontSize: 12.5, color: A.body, verticalAlign: "top" };
  return (
    <>
      <tr onClick={onToggle} style={{ cursor: "pointer" }}>
        <td style={td}>
          <div style={{ fontWeight: 600 }}>{row.tenant_name || "—"}</div>
          <div style={{ fontFamily: mono, fontSize: 10.5, color: A.muted2 }}>{row.tenant_slug || row.tenant_id.slice(0, 8)}</div>
        </td>
        <td style={td}>{row.failure_summary || "—"}</td>
        <td style={td}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {(row.escalate_detail || []).map((item, i) => (
              <Badge key={i} color="gray">{item.check_id}</Badge>
            ))}
          </div>
        </td>
        <td style={td}><Badge color={row.review_status === "pending" ? "amber" : "gray"}>{row.review_status}</Badge></td>
        <td style={{ ...td, fontFamily: mono, fontSize: 11, color: A.muted }}>{fmtDate(row.created_at)}</td>
        <td style={{ ...td, textAlign: "center" }}>{expanded ? "▲" : "▼"}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} style={{ padding: "0 12px 14px", borderBottom: `1px solid ${A.line}` }}>
            <div style={{ background: A.bg, borderRadius: 8, padding: 12, fontFamily: mono, fontSize: 11, color: A.body }}>
              <div style={{ marginBottom: 6, color: A.muted2 }}>
                tour_id: {row.tour_id} · version_id: {row.tenant_tour_version_id}
              </div>
              {(row.escalate_detail || []).map((item, i) => (
                <div key={i} style={{ marginBottom: 4 }}>
                  <strong>{item.check_id}</strong>
                  {item.field && <> · field: {item.field}</>}
                  {item.description && <> — {item.description}</>}
                  {item.source_span && <div style={{ color: A.muted2, marginTop: 2 }}>“{item.source_span}”</div>}
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Publish Log section (AA-455 bước 1) ──────────────────────────────────────

function PublishLogSection() {
  const [rows, setRows] = useState<PublishLogRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tenantFilter, setTenantFilter] = useState("");
  const [actioningId, setActioningId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: "200" });
    if (tenantFilter.trim()) params.set("tenant_id", tenantFilter.trim());
    fetch(`/api/admin/a4/publish-log?${params}`)
      .then(r => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then(d => { setRows(d.data || []); setError(null); })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [tenantFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleForceUnpublish = useCallback(async (publishId: string) => {
    if (!window.confirm("Force-unpublish this piece? This cannot be undone from here.")) return;
    setActioningId(publishId);
    setActionError(null);
    try {
      const res = await fetch(`/api/admin/a4/publish-log/${publishId}/unpublish`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchData();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setActioningId(null);
    }
  }, [fetchData]);

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <h2 style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink, margin: "0 0 4px" }}>
            Publish Log — T11 Delivery State
          </h2>
          <div style={{ fontSize: 12, color: A.muted }}>
            acp_shared.publish_log — force-unpublish a live piece if something's wrong (grounding
            miss, brand-rule violation T10 didn't catch). Tenants can also unpublish their own
            content; this table doesn&apos;t distinguish who acted beyond unpublished_by.
          </div>
        </div>
        <input
          value={tenantFilter}
          onChange={e => setTenantFilter(e.target.value)}
          placeholder="Filter by tenant_id…"
          style={{
            padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`,
            fontSize: 12, fontFamily: mono, width: 280, outline: "none",
          }}
        />
      </div>

      {actionError && (
        <div style={{ padding: "8px 12px", marginBottom: 12, borderRadius: 6, background: "#fef2f2", color: A.red, fontSize: 12 }}>
          {actionError}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 24, textAlign: "center", color: A.muted }}>Loading…</div>
      ) : error ? (
        <div style={{ padding: 24, textAlign: "center", color: A.red }}>{error}</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: A.muted2 }}>
          No publish_log rows yet — T11&apos;s own write path isn&apos;t built yet (bước 2).
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: A.bg }}>
                {["Tenant", "Channel", "Status", "External", "Unpublished By", "Created", ""].map(h => (
                  <th key={h} style={{
                    padding: "8px 12px", textAlign: "left", fontSize: 10.5, fontWeight: 600,
                    letterSpacing: "0.08em", textTransform: "uppercase", color: A.muted,
                    borderBottom: `1px solid ${A.line}`,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => {
                const td: React.CSSProperties = { padding: "10px 12px", borderBottom: `1px solid ${A.line}`, fontSize: 12.5, color: A.body, verticalAlign: "top" };
                return (
                  <tr key={row.publish_id}>
                    <td style={td}>
                      <div style={{ fontWeight: 600 }}>{row.tenant_name || "—"}</div>
                      <div style={{ fontFamily: mono, fontSize: 10.5, color: A.muted2 }}>{row.tenant_slug || row.tenant_id.slice(0, 8)}</div>
                    </td>
                    <td style={td}>{row.channel}</td>
                    <td style={td}><Badge color={publishStatusColor(row.status)}>{row.status}</Badge></td>
                    <td style={{ ...td, fontFamily: mono, fontSize: 11 }}>
                      {row.external_url ? (
                        <a href={row.external_url} target="_blank" rel="noreferrer" style={{ color: A.ink }}>{row.external_id || row.external_url}</a>
                      ) : (row.external_id || "—")}
                      {row.last_error && <div style={{ color: A.red, marginTop: 2 }}>{row.last_error}</div>}
                    </td>
                    <td style={{ ...td, fontFamily: mono, fontSize: 11, color: A.muted }}>{row.unpublished_by || "—"}</td>
                    <td style={{ ...td, fontFamily: mono, fontSize: 11, color: A.muted }}>{fmtDate(row.created_at)}</td>
                    <td style={td}>
                      {row.status === "published" && (
                        <button
                          onClick={() => handleForceUnpublish(row.publish_id)}
                          disabled={actioningId === row.publish_id}
                          style={{
                            padding: "5px 10px", borderRadius: 6, border: `1px solid ${A.red}`,
                            background: "transparent", color: A.red, fontSize: 11.5, cursor: "pointer",
                            opacity: actioningId === row.publish_id ? 0.5 : 1,
                          }}
                        >
                          {actioningId === row.publish_id ? "Unpublishing…" : "Force unpublish"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ── Content Log section (AA-469 Việc 5) ──────────────────────────────────────

function ContentLogSection() {
  const [rows, setRows] = useState<ContentLogRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tenantFilter, setTenantFilter] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: "200" });
    if (tenantFilter.trim()) params.set("tenant_id", tenantFilter.trim());
    fetch(`/api/admin/a4/content-log?${params}`)
      .then(r => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then(d => { setRows(d.data || []); setError(null); })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [tenantFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Same client-side rollup pattern as Review Log above — counts how many rows each FAILED gate
  // fired in, across the currently loaded set (passed gates don't count, only violations matter
  // for pattern review).
  const gateCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const row of rows) {
      for (const g of row.gate_ledger || []) {
        if (!g.passed) counts[g.gate] = (counts[g.gate] || 0) + 1;
      }
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [rows]);

  return (
    <Card style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <h2 style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink, margin: "0 0 4px" }}>
            Content Log — T9/T10 Every Piece + Full Context
          </h2>
          <div style={{ fontSize: 12, color: A.muted }}>
            Every acp_shared.content_piece row (AA-501 — widened from held/failed-only: this is
            the widest of the two AA-501 views, everything the tenant sees plus full gate/retry/
            error/publish detail) — full write context (atom/tour/goal/angle/DFS-PAA) and, for
            held/failed rows, per-gate pass/fail + the retry-feedback trail. Post-hoc pattern
            review + lesson log, not a queue to action — AA does not gate tenant content.
          </div>
        </div>
        <input
          value={tenantFilter}
          onChange={e => setTenantFilter(e.target.value)}
          placeholder="Filter by tenant_id…"
          style={{
            padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`,
            fontSize: 12, fontFamily: mono, width: 280, outline: "none",
          }}
        />
      </div>

      {gateCounts.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
          {gateCounts.map(([gate, count]) => (
            <Badge key={gate} color={count > 1 ? "amber" : "gray"}>
              {gate} × {count}
            </Badge>
          ))}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 24, textAlign: "center", color: A.muted }}>Loading…</div>
      ) : error ? (
        <div style={{ padding: 24, textAlign: "center", color: A.red }}>{error}</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: A.muted2 }}>No content pieces found.</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: A.bg }}>
                {["Tenant", "Goal / Channel", "Status", "Gates", "Publish", "Attempt", "Created", ""].map(h => (
                  <th key={h} style={{
                    padding: "8px 12px", textAlign: "left", fontSize: 10.5, fontWeight: 600,
                    letterSpacing: "0.08em", textTransform: "uppercase", color: A.muted,
                    borderBottom: `1px solid ${A.line}`,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <ContentLogRowLine key={row.piece_id} row={row}
                  expanded={expanded === row.piece_id}
                  onToggle={() => setExpanded(expanded === row.piece_id ? null : row.piece_id)} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ContentLogRowLine({ row, expanded, onToggle }: {
  row: ContentLogRow; expanded: boolean; onToggle: () => void;
}) {
  const td: React.CSSProperties = { padding: "10px 12px", borderBottom: `1px solid ${A.line}`, fontSize: 12.5, color: A.body, verticalAlign: "top" };
  return (
    <>
      <tr onClick={onToggle} style={{ cursor: "pointer" }}>
        <td style={td}>
          <div style={{ fontWeight: 600 }}>{row.tenant_name || "—"}</div>
          <div style={{ fontFamily: mono, fontSize: 10.5, color: A.muted2 }}>{row.tenant_slug || row.tenant_id.slice(0, 8)}</div>
        </td>
        <td style={td}>
          <div>{row.goal || "—"}</div>
          <div style={{ fontFamily: mono, fontSize: 10.5, color: A.muted2 }}>{row.channel || "—"}</div>
        </td>
        <td style={td}><Badge color={contentStatusColor(row.status)}>{row.status}</Badge></td>
        <td style={{ ...td, fontFamily: mono, fontSize: 11 }}>
          {row.gate_total_count > 0 ? `${row.gate_pass_count}/${row.gate_total_count}` : "—"}
        </td>
        <td style={td}><Badge color={contentPublishStatusColor(row.publish_status)}>{row.publish_status}</Badge></td>
        <td style={td}>{row.attempt_number}</td>
        <td style={{ ...td, fontFamily: mono, fontSize: 11, color: A.muted }}>{fmtDate(row.created_at)}</td>
        <td style={{ ...td, textAlign: "center" }}>{expanded ? "▲" : "▼"}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={8} style={{ padding: "0 12px 14px", borderBottom: `1px solid ${A.line}` }}>
            <div style={{ background: A.bg, borderRadius: 8, padding: 12, fontFamily: mono, fontSize: 11, color: A.body }}>
              <div style={{ marginBottom: 6, color: A.muted2 }}>
                piece_id: {row.piece_id} · atom_id: {row.atom_id} · request_id: {row.angle_gate_request_id}
              </div>

              {/* Full write context — same fields the tenant's own /portal/t10-review shows,
                  plus (below) the technical detail the tenant never sees. */}
              {row.angle && (
                <div style={{ marginBottom: 6 }}>
                  <strong>angle:</strong> {row.angle.name} — {row.angle.why_it_works} ({row.angle.formula_fit} · {row.angle.best_final_style})
                </div>
              )}
              {row.atom && (
                <div style={{ marginBottom: 6 }}>
                  <strong>atom:</strong> {row.atom.text}
                  {(row.atom.activity_type || row.atom.emotional_hook || row.atom.season_note) &&
                    ` (${[row.atom.activity_type, row.atom.emotional_hook, row.atom.season_note].filter(Boolean).join(" · ")})`}
                </div>
              )}
              {row.tour && (
                <div style={{ marginBottom: 6 }}><strong>tour:</strong> {row.tour.name} ({row.tour.destination})</div>
              )}
              {row.dfs_paa_snapshot && (row.dfs_paa_snapshot.people_also_ask.length > 0 || row.dfs_paa_snapshot.related_keywords.length > 0) && (
                <div style={{ marginBottom: 6 }}>
                  <strong>dfs/paa ({row.dfs_paa_snapshot.relevance}):</strong>{" "}
                  {row.dfs_paa_snapshot.people_also_ask.join("; ")}
                  {row.dfs_paa_snapshot.related_keywords.length > 0 && ` — ${row.dfs_paa_snapshot.related_keywords.join(", ")}`}
                </div>
              )}
              {row.cta && <div style={{ marginBottom: 6 }}><strong>cta:</strong> {row.cta}</div>}

              {/* Technical detail — held_reason/gate_ledger/repair_log, deliberately NEVER shown
                  on the tenant's own /portal/t10-review. */}
              {row.held_reason && (
                <div style={{ marginBottom: 6 }}><strong>held_reason:</strong> {row.held_reason}</div>
              )}
              {(row.gate_ledger || []).map((g, i) => (
                <div key={i} style={{ marginBottom: 4, color: g.passed ? A.muted2 : A.red }}>
                  <strong>{g.gate}</strong> — {g.passed ? "passed" : `FAILED: ${(g.violations || []).join("; ")}`}
                </div>
              ))}
              {row.repair_log && row.repair_log.length > 0 && (
                <div style={{ marginTop: 8, marginBottom: 6 }}>
                  <strong>repair_log:</strong>
                  <pre style={{ margin: "4px 0 0", whiteSpace: "pre-wrap", fontSize: 10.5 }}>
                    {JSON.stringify(row.repair_log, null, 2)}
                  </pre>
                </div>
              )}
              {row.content_preview && (
                <div style={{ marginTop: 8, color: A.muted2, whiteSpace: "pre-wrap" }}>
                  {row.content_preview}…
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Trust Ramp section ───────────────────────────────────────────────────────

function TrustRampSection() {
  const [rows, setRows] = useState<TrustRampRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioningId, setActioningId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    fetch("/api/admin/a4/trust-ramp")
      .then(r => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then(d => { setRows(d.data || []); setError(null); })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // AA-464 — approve/skip a suggested transition. Both re-compute server-side (never trust the
  // client's own suggested_mode), so this just needs the packet_id; fetchData() re-pulls fresh
  // state (including whatever the packet's NEW suggestion is, if any) after either action.
  const handleRampAction = useCallback(async (packetId: string, action: "approve" | "skip") => {
    setActioningId(packetId);
    setActionError(null);
    try {
      const res = await fetch(`/api/admin/a4/trust-ramp/${packetId}/${action}`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      await fetchData();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setActioningId(null);
    }
  }, [fetchData]);

  // Group by tenant for readability — every packet still shown with its own level, never
  // collapsed into one tenant-level number (Nghiep's decision #3).
  const byTenant = useMemo(() => {
    const groups: Record<string, TrustRampRow[]> = {};
    for (const row of rows) {
      const key = row.tenant_id;
      (groups[key] ||= []).push(row);
    }
    return Object.values(groups);
  }, [rows]);

  return (
    <Card>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink, margin: "0 0 4px" }}>
          Trust Ramp — Current State
        </h2>
        <div style={{ fontSize: 12, color: A.muted }}>
          acp_deliver.packets.publish_mode per packet. AA-464 — suggest_ramp_transition() is now
          wired: eligible packets (engagement_ok AND weeks_active ≥ 2) show a suggested next
          level below with Approve/Skip. Approving is the only way a ramp state actually
          changes — nothing here auto-transitions on its own (ADR-2026-038 §0.2).
        </div>
      </div>

      {actionError && (
        <div style={{ padding: "8px 12px", marginBottom: 12, borderRadius: 6, background: "#fef2f2", color: A.red, fontSize: 12 }}>
          {actionError}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 24, textAlign: "center", color: A.muted }}>Loading…</div>
      ) : error ? (
        <div style={{ padding: 24, textAlign: "center", color: A.red }}>{error}</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: A.muted2 }}>No packets found.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {byTenant.map(group => (
            <div key={group[0].tenant_id}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: A.ink, marginBottom: 8 }}>
                {group[0].tenant_name || group[0].tenant_id}
                <span style={{ fontFamily: mono, fontSize: 10.5, color: A.muted2, marginLeft: 8, fontWeight: 400 }}>
                  {group[0].tenant_slug} · {group.length} packet{group.length !== 1 ? "s" : ""}
                </span>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ background: A.bg }}>
                      {["Period", "Status", "Ramp Level", "Suggestion", "Created", "Delivered"].map(h => (
                        <th key={h} style={{
                          padding: "6px 12px", textAlign: "left", fontSize: 10, fontWeight: 600,
                          letterSpacing: "0.08em", textTransform: "uppercase", color: A.muted,
                          borderBottom: `1px solid ${A.line}`,
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {group.map(p => (
                      <tr key={p.packet_id}>
                        <td style={{ padding: "8px 12px", fontSize: 12, fontFamily: mono, borderBottom: `1px solid ${A.line}` }}>
                          {p.year}-{String(p.month).padStart(2, "0")} W{p.week}
                        </td>
                        <td style={{ padding: "8px 12px", fontSize: 12, borderBottom: `1px solid ${A.line}` }}>
                          <Badge color="gray">{p.status}</Badge>
                        </td>
                        <td style={{ padding: "8px 12px", fontSize: 12, borderBottom: `1px solid ${A.line}` }}>
                          <Badge color={rampBadgeColor(p.publish_mode)}>{RAMP_LABEL[p.publish_mode] || p.publish_mode}</Badge>
                        </td>
                        <td style={{ padding: "8px 12px", fontSize: 12, borderBottom: `1px solid ${A.line}` }}>
                          {p.eligible ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                              <Badge color={rampBadgeColor(p.suggested_mode)}>
                                → {RAMP_LABEL[p.suggested_mode] || p.suggested_mode}
                              </Badge>
                              <button
                                onClick={() => handleRampAction(p.packet_id, "approve")}
                                disabled={actioningId === p.packet_id}
                                style={{
                                  padding: "4px 8px", borderRadius: 6, border: `1px solid ${A.ink}`,
                                  background: A.ink, color: "#fff", fontSize: 11, cursor: "pointer",
                                  opacity: actioningId === p.packet_id ? 0.5 : 1,
                                }}
                              >
                                {actioningId === p.packet_id ? "…" : "Approve"}
                              </button>
                              <button
                                onClick={() => handleRampAction(p.packet_id, "skip")}
                                disabled={actioningId === p.packet_id}
                                style={{
                                  padding: "4px 8px", borderRadius: 6, border: `1px solid ${A.line}`,
                                  background: "transparent", color: A.muted, fontSize: 11, cursor: "pointer",
                                  opacity: actioningId === p.packet_id ? 0.5 : 1,
                                }}
                              >
                                Skip
                              </button>
                            </div>
                          ) : (
                            <span style={{ fontSize: 11, color: A.muted2 }}>—</span>
                          )}
                        </td>
                        <td style={{ padding: "8px 12px", fontSize: 11, fontFamily: mono, color: A.muted, borderBottom: `1px solid ${A.line}` }}>
                          {fmtDate(p.created_at)}
                        </td>
                        <td style={{ padding: "8px 12px", fontSize: 11, fontFamily: mono, color: A.muted, borderBottom: `1px solid ${A.line}` }}>
                          {fmtDate(p.delivered_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function A4OversightPage() {
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <div style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0 }}>
            Cross-Tenant Oversight
          </h1>
          <div style={{ fontSize: 12, color: A.muted, marginTop: 4 }}>
            Post-hoc monitoring — AA does not gate tenant content at any T0-T11 step. Review Log,
            Content Log, and Trust Ramp are read-only; Publish Log below is the one exception, per
            AA-455 — force-unpublish is a safety-net intervention, not a content-approval gate.
          </div>
        </div>
        <ReviewLogSection />
        <ContentLogSection />
        <PublishLogSection />
        <TrustRampSection />
      </div>
    </div>
  );
}
