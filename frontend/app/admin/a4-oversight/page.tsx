"use client";
// app/admin/a4-oversight/page.tsx — AA-437 [A4] Cross-Tenant Oversight v1
//
// Read-only, per Nghiep's decisions (Linear AA-437, 23/08/2026): no flag/suspend/
// force-unpublish action here — that's explicitly deferred to the Command Center backlog
// (AA-255->259) if/when it gets built. Two sections:
//   1. Review Log — silver_aa_internal.review_queue T3 (QA-gate escalate) rows, the log AA-436
//      redirected here once T3 stopped blocking tenants. Raw rows from the backend; grouped by
//      check_id client-side (BE deliberately does no aggregation — STEP0's own recommendation,
//      less logic server-side, same flat-list-first approach AtomsTab.tsx already uses).
//   2. Trust Ramp — every acp_deliver.packets row with its own publish_mode. No per-tenant
//      rollup: ramp state lives per-PACKET (STEP0 finding), so a tenant with multiple packets
//      shows one row per packet, grouped visually by tenant, never collapsed to one number.
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
            Review Log — T3 QA-Gate Escalations
          </h2>
          <div style={{ fontSize: 12, color: A.muted }}>
            silver_aa_internal.review_queue rows written when a tenant rewrite fails QA twice
            (auto-passed to the tenant, logged here for pattern review — not a queue to action).
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

// ── Trust Ramp section ───────────────────────────────────────────────────────

function TrustRampSection() {
  const [rows, setRows] = useState<TrustRampRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/admin/a4/trust-ramp")
      .then(r => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then(d => { setRows(d.data || []); setError(null); })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

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
          acp_deliver.packets.publish_mode per packet — current state only, no auto-suggested
          next level (suggest_ramp_transition() is not wired into any live process yet).
        </div>
      </div>

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
                      {["Period", "Status", "Ramp Level", "Created", "Delivered"].map(h => (
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
            Read-only monitoring — AA does not gate tenant content at any T0-T11 step; this is
            post-hoc visibility only. No action on this page (flag/suspend/force-unpublish is a
            separate, future scope).
          </div>
        </div>
        <ReviewLogSection />
        <TrustRampSection />
      </div>
    </div>
  );
}
