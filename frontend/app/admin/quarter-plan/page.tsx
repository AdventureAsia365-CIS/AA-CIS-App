"use client";
// app/admin/quarter-plan/page.tsx — AA-388: Gate B approval UI (N5 Quarter Plan).
// Gate B is REQUIRED, NEVER auto (D6) — this page only ever calls the real
// POST /admin/quarter-plan/{version_id}/approve endpoint on an explicit click.
// No auto-approve, no default value, no bypass anywhere in this file.
//
// No Reject button: the backend has no reject endpoint (confirmed AA-388 STEP 0,
// grepped api/routers/admin.py + services/acp_planning/quarter.py) — adding one
// was explicitly out of scope for this issue.

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { CalendarCheck, CheckCircle2, ChevronLeft, ExternalLink, Loader2, Plus } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, sans, Card, SLabel, Btn, Badge, LoadingScreen, TabBar, TH, TD } from "../_components/adminUi";

interface PendingItem {
  version_id: string;
  plan_id: string;
  version_no: number;
  source: string;
  created_at: string;
  tenant_id: string;
  tenant_name: string;
  year: number;
  quarter: number;
}

interface Tenant {
  tenant_id: string;
  name: string;
  is_active: boolean;
}

// AA-323 round 4 — Việc 1: one row per persisted version (not just the newest),
// returned by GET /admin/quarter-plan/{tenant}/{year}/{quarter}/history. Carries
// the full plan payload so the History tab can build a VersionDetail directly on
// click, no second fetch per row.
interface HistoryVersion {
  version_id: string;
  plan_id: string;
  version_no: number;
  source: string;
  approval_status: "pending" | "approved" | "rejected";
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  trip_count: number;
  plan: QuarterPlanPayload;
}

interface BigRock {
  rock_id: string;
  trip_id: string;
  title: string;
  atom_ids: string[];
  atomization_contract: Record<string, number>;
}

// AA-323 Gap 1 — per-trip N5 scoring, added to QuarterPlan so this card can
// resolve real tour names instead of raw UUIDs. Absent on quarter plan
// versions persisted before this change (payload is JSONB, old rows just
// have no trip_scores key) — DetailView falls back to the UUID for those.
interface TripScore {
  trip_id: string;
  name: string;
  destination: string | null;
  score: number;
  forced: boolean;
  selected: boolean;
  reason: string;
}

interface QuarterPlanPayload {
  tenant_id: string;
  year: number;
  quarter: number;
  trip_ids: string[];
  forced_specials: string[];
  big_rocks: BigRock[];
  destination_shares: Record<string, number>;
  thin_trip_notes: string[];
  capacity_note: string | null;
  trip_scores?: TripScore[];
}

interface VersionDetail {
  version_id: string;
  version_no: number;
  source: string;
  approval_status: "pending" | "approved" | "rejected";
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  plan: QuarterPlanPayload;
}

function getCookie(name: string): string {
  return document.cookie.split(";").find(c => c.trim().startsWith(`${name}=`))?.split("=")[1] ?? "";
}

export default function QuarterPlanPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"pending" | "history">("pending");
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [pending, setPending] = useState<PendingItem[] | null>(null);
  const [selected, setSelected] = useState<PendingItem | null>(null);
  const [detail, setDetail] = useState<VersionDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState("");

  const loadPending = useCallback(() => {
    setPending(null);
    fetch("/api/admin/quarter-plan/pending")
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(d => setPending(d.items))
      .catch(() => setError("Failed to load pending quarter plans"));
  }, []);

  useEffect(() => { loadPending(); }, [loadPending]);

  useEffect(() => {
    fetch("/api/admin/tenants")
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(d => setTenants((d.tenants ?? []).filter((t: Tenant) => t.is_active)))
      .catch(() => setError("Failed to load tenants"));
  }, []);

  function openDetail(item: PendingItem) {
    setSelected(item);
    setDetail(null);
    setLoadingDetail(true);
    setError("");
    fetch(`/api/admin/quarter-plan/${item.tenant_id}/${item.year}/${item.quarter}`)
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(d => setDetail(d))
      .catch(() => setError("Failed to load plan detail"))
      .finally(() => setLoadingDetail(false));
  }

  // AA-323 round 4 — History tab already has the full plan payload from
  // GET .../history (see HistoryVersion), so this builds VersionDetail/PendingItem
  // in place and reuses the same DetailView as the Pending tab, no extra fetch.
  function openHistoryDetail(v: HistoryVersion, tenantId: string, tenantName: string, year: number, quarter: number) {
    setError("");
    setSelected({
      version_id: v.version_id, plan_id: v.plan_id, version_no: v.version_no,
      source: v.source, created_at: v.created_at,
      tenant_id: tenantId, tenant_name: tenantName, year, quarter,
    });
    setDetail({
      version_id: v.version_id, version_no: v.version_no, source: v.source,
      approval_status: v.approval_status, approved_by: v.approved_by,
      approved_at: v.approved_at, created_at: v.created_at, plan: v.plan,
    });
    setLoadingDetail(false);
  }

  async function approve() {
    if (!detail) return;
    const approvedBy = getCookie("cis_user") ? decodeURIComponent(getCookie("cis_user")) : "";
    if (!approvedBy) {
      setError("No admin identity found — cannot approve without approved_by.");
      return;
    }
    setApproving(true);
    setError("");
    try {
      const res = await fetch(`/api/admin/quarter-plan/${detail.version_id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved_by: approvedBy }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Approve failed (${res.status})`);
      }
      const updated = await res.json();
      setDetail(d => d ? {
        ...d,
        approval_status: updated.approval_status,
        approved_by: updated.approved_by,
        approved_at: updated.approved_at,
      } : d);
      setPending(list => list ? list.filter(p => p.version_id !== detail.version_id) : list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setApproving(false);
    }
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "28px 32px", maxWidth: 1100 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          {selected && (
            <button onClick={() => { setSelected(null); setDetail(null); setError(""); }} style={{
              background: "none", border: "none", cursor: "pointer", color: A.muted,
              display: "flex", alignItems: "center", padding: 4,
            }}>
              <ChevronLeft size={18} />
            </button>
          )}
          <CalendarCheck size={20} color={A.red} />
          <h1 style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: A.ink, margin: 0 }}>
            Quarter Plan Approval (Gate B)
          </h1>
          <div style={{ flex: 1 }} />
          {!selected && (
            <Btn size="sm" variant="primary" onClick={() => router.push("/admin/quarter-plan/create")}>
              <Plus size={12} /> Create Plan
            </Btn>
          )}
        </div>
        <p style={{ fontSize: 13, color: A.muted, marginBottom: 24, fontFamily: sans }}>
          Every quarter plan must be reviewed and approved by a human before N6 can allocate
          content from it. This gate is required and never runs automatically.
        </p>

        {error && (
          <div style={{
            background: "#FEE2E2", border: "1px solid #FECACA", color: "#991B1B",
            borderRadius: 8, padding: "10px 14px", fontSize: 13, marginBottom: 18,
          }}>{error}</div>
        )}

        {!selected && (
          <div style={{ marginBottom: 16 }}>
            <TabBar
              tabs={[{ key: "pending", label: "Pending" }, { key: "history", label: "History" }]}
              active={tab}
              onChange={k => setTab(k as "pending" | "history")}
            />
          </div>
        )}

        {!selected && tab === "pending" && <PendingList items={pending} onSelect={openDetail} />}
        {!selected && tab === "history" && (
          <HistoryPanel tenants={tenants} onSelect={openHistoryDetail} setError={setError} />
        )}

        {selected && (
          <DetailView
            selected={selected}
            detail={detail}
            loading={loadingDetail}
            approving={approving}
            onApprove={approve}
            router={router}
          />
        )}
      </main>
    </div>
  );
}

function PendingList({ items, onSelect }: { items: PendingItem[] | null; onSelect: (i: PendingItem) => void }) {
  if (items === null) return <LoadingScreen msg="Loading pending quarter plans..." />;
  if (items.length === 0) {
    return (
      <Card>
        <div style={{ textAlign: "center", padding: "24px 0", color: A.muted, fontSize: 13 }}>
          No quarter plans are pending approval.
        </div>
      </Card>
    );
  }
  return (
    <Card style={{ padding: 0 }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={TH}>Tenant</th>
            <th style={TH}>Quarter</th>
            <th style={TH}>Version</th>
            <th style={TH}>Source</th>
            <th style={TH}>Created</th>
            <th style={TH}></th>
          </tr>
        </thead>
        <tbody>
          {items.map(item => (
            <tr key={item.version_id}>
              <td style={TD}>{item.tenant_name}</td>
              <td style={TD}>Q{item.quarter} {item.year}</td>
              <td style={TD}>v{item.version_no}</td>
              <td style={TD}><Badge color={item.source === "override" ? "amber" : "gray"}>{item.source}</Badge></td>
              <td style={TD}>{new Date(item.created_at).toLocaleString()}</td>
              <td style={{ ...TD, textAlign: "right" }}>
                <Btn size="sm" onClick={() => onSelect(item)}>Review</Btn>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function currentQuarter(): { year: number; quarter: number } {
  const now = new Date();
  return { year: now.getFullYear(), quarter: Math.floor(now.getMonth() / 3) + 1 };
}

// AA-323 round 4 — Việc 1: History tab. There's no existing "browse all versions
// across tenants" listing (unlike Pending, which already spans tenants) — the
// backend endpoint is scoped to one tenant/year/quarter, so this needs its own
// selector before it can list anything, same shape as the Create Plan page's
// tenant/year/quarter picker.
function HistoryPanel({ tenants, onSelect, setError }: {
  tenants: Tenant[];
  onSelect: (v: HistoryVersion, tenantId: string, tenantName: string, year: number, quarter: number) => void;
  setError: (msg: string) => void;
}) {
  const { year: defaultYear, quarter: defaultQuarter } = currentQuarter();
  const [tenantId, setTenantId] = useState("");
  const [year, setYear] = useState(defaultYear);
  const [quarter, setQuarter] = useState(defaultQuarter);
  const [versions, setVersions] = useState<HistoryVersion[] | null>(null);
  const [loading, setLoading] = useState(false);

  function loadHistory() {
    if (!tenantId) return;
    setLoading(true);
    setError("");
    fetch(`/api/admin/quarter-plan/${tenantId}/${year}/${quarter}/history`)
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(d => setVersions(d.versions))
      .catch(() => setError("Failed to load quarter plan history"))
      .finally(() => setLoading(false));
  }

  const tenantName = tenants.find(t => t.tenant_id === tenantId)?.name ?? "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div>
            <SLabel>Tenant</SLabel>
            <select value={tenantId} onChange={e => { setTenantId(e.target.value); setVersions(null); }} style={{
              padding: "9px 12px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8,
              color: A.body, fontSize: 13, fontFamily: sans, minWidth: 220, outline: "none",
            }}>
              <option value="">Select a tenant…</option>
              {tenants.map(t => <option key={t.tenant_id} value={t.tenant_id}>{t.name}</option>)}
            </select>
          </div>
          <div>
            <SLabel>Year</SLabel>
            <input type="number" value={year} onChange={e => setYear(Number(e.target.value))} style={{
              width: 90, padding: "9px 12px", background: A.bg, border: `1px solid ${A.line}`,
              borderRadius: 8, color: A.body, fontSize: 13, fontFamily: sans, outline: "none",
            }} />
          </div>
          <div>
            <SLabel>Quarter</SLabel>
            <select value={quarter} onChange={e => setQuarter(Number(e.target.value))} style={{
              padding: "9px 12px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8,
              color: A.body, fontSize: 13, fontFamily: sans, outline: "none",
            }}>
              {[1, 2, 3, 4].map(q => <option key={q} value={q}>Q{q}</option>)}
            </select>
          </div>
          <Btn size="sm" variant="primary" disabled={!tenantId || loading} onClick={loadHistory}>
            {loading ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : "Load History"}
          </Btn>
        </div>
      </Card>

      {versions === null ? (
        <Card>
          <div style={{ textAlign: "center", padding: "24px 0", color: A.muted, fontSize: 13 }}>
            Select a tenant, year, and quarter, then load its version history.
          </div>
        </Card>
      ) : versions.length === 0 ? (
        <Card>
          <div style={{ textAlign: "center", padding: "24px 0", color: A.muted, fontSize: 13 }}>
            No quarter plan versions exist for this tenant/year/quarter yet.
          </div>
        </Card>
      ) : (
        <Card style={{ padding: 0 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={TH}>Version</th>
                <th style={TH}>Status</th>
                <th style={TH}>Trips</th>
                <th style={TH}>Approved By</th>
                <th style={TH}>Approved At</th>
                <th style={TH}>Created</th>
                <th style={TH}></th>
              </tr>
            </thead>
            <tbody>
              {versions.map(v => {
                const statusColor = v.approval_status === "approved" ? "green"
                  : v.approval_status === "rejected" ? "red" : "amber";
                return (
                  <tr key={v.version_id}>
                    <td style={TD}>v{v.version_no}</td>
                    <td style={TD}><Badge color={statusColor}>{v.approval_status}</Badge></td>
                    <td style={TD}>{v.trip_count}</td>
                    <td style={TD}>{v.approved_by ?? "—"}</td>
                    <td style={TD}>{v.approved_at ? new Date(v.approved_at).toLocaleString() : "—"}</td>
                    <td style={TD}>{new Date(v.created_at).toLocaleString()}</td>
                    <td style={{ ...TD, textAlign: "right" }}>
                      <Btn size="sm" onClick={() => onSelect(v, tenantId, tenantName, year, quarter)}>View</Btn>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function DetailView({ selected, detail, loading, approving, onApprove, router }: {
  selected: PendingItem; detail: VersionDetail | null; loading: boolean;
  approving: boolean; onApprove: () => void; router: ReturnType<typeof useRouter>;
}) {
  if (loading || !detail) return <LoadingScreen msg="Loading plan detail..." />;
  const plan = detail.plan;
  const statusColor = detail.approval_status === "approved" ? "green"
    : detail.approval_status === "rejected" ? "red" : "amber";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
          <div>
            <div style={{ fontFamily: serif, fontSize: 18, color: A.ink, fontWeight: 500 }}>
              {selected.tenant_name} — Q{plan.quarter} {plan.year}
            </div>
            <div style={{ fontSize: 12, color: A.muted, marginTop: 2 }}>
              Version {detail.version_no} · {detail.source} · created {new Date(detail.created_at).toLocaleString()}
            </div>
          </div>
          <Badge color={statusColor}>{detail.approval_status}</Badge>
        </div>

        {detail.approval_status === "approved" && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 12, color: A.muted, display: "flex", alignItems: "center", gap: 6 }}>
              <CheckCircle2 size={14} color={A.green} />
              Approved by {detail.approved_by} at {detail.approved_at ? new Date(detail.approved_at).toLocaleString() : "—"}
            </div>
            {/* AA-323 round 4 — Việc 3: the Approved screen had no path onward to N6's
                Preview; a human had to already know the URL. */}
            <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end" }}>
              <Btn size="sm" variant="primary" onClick={() => router.push("/admin/curation/preview")}>
                <ExternalLink size={12} /> View in Slot Grid Preview
              </Btn>
            </div>
          </div>
        )}

        {detail.approval_status === "pending" && (
          <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
            <Btn variant="primary" onClick={onApprove} disabled={approving}>
              {approving ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <CheckCircle2 size={14} />}
              {approving ? "Approving..." : "Approve Quarter Plan"}
            </Btn>
          </div>
        )}
      </Card>

      <Card>
        <SLabel>Selected Trips ({plan.trip_ids.length})</SLabel>
        {plan.capacity_note && (
          <div style={{
            fontSize: 12, color: "#92400E", background: A.amberSoft,
            border: "1px solid #FDE68A", borderRadius: 6, padding: "8px 10px", marginBottom: 12,
          }}>{plan.capacity_note}</div>
        )}
        {plan.trip_ids.length === 0 ? (
          <div style={{ fontSize: 12, color: A.muted }}>—</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {plan.trip_ids.map(id => {
              const score = plan.trip_scores?.find(s => s.trip_id === id);
              return (
                <div key={id} style={{
                  display: "flex", alignItems: "baseline", gap: 8, fontSize: 12,
                  padding: "4px 0", borderBottom: `1px solid ${A.line2}`,
                }}>
                  <span style={{ color: A.body, fontWeight: 600 }}>
                    {score ? score.name : id}
                  </span>
                  {score?.destination && (
                    <span style={{ color: A.muted2 }}>{score.destination}</span>
                  )}
                  {score && (
                    <span style={{ color: A.muted2, marginLeft: "auto", fontStyle: "italic" }}>
                      {score.reason}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {plan.forced_specials.length > 0 && (
          <div style={{ fontSize: 12, color: A.muted, marginTop: 8 }}>
            Forced specials: {plan.forced_specials.length} trip(s)
          </div>
        )}
      </Card>

      <Card>
        <SLabel>Destination Content Shares</SLabel>
        {Object.keys(plan.destination_shares).length === 0 ? (
          <div style={{ fontSize: 13, color: A.muted }}>No destination shares computed.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {Object.entries(plan.destination_shares)
              .sort((a, b) => b[1] - a[1])
              .map(([dest, share]) => (
                <div key={dest} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ width: 160, fontSize: 12, color: A.body, flexShrink: 0 }}>{dest}</div>
                  <div style={{ flex: 1, height: 8, background: A.line2, borderRadius: 4, overflow: "hidden" }}>
                    <div style={{ width: `${Math.min(share * 100, 100)}%`, height: "100%", background: A.red }} />
                  </div>
                  <div style={{ width: 46, fontSize: 12, color: A.muted, textAlign: "right" }}>
                    {(share * 100).toFixed(0)}%
                  </div>
                </div>
              ))}
          </div>
        )}
        {plan.thin_trip_notes.length > 0 && (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 4 }}>
            {plan.thin_trip_notes.map((note, i) => (
              <div key={i} style={{ fontSize: 11, color: A.muted2 }}>· {note}</div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <SLabel>Big Rocks ({plan.big_rocks.length})</SLabel>
        {plan.big_rocks.length === 0 ? (
          <div style={{ fontSize: 13, color: A.muted }}>No big rocks selected for this quarter.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {plan.big_rocks.map(rock => (
              <div key={rock.rock_id} style={{ padding: "10px 12px", background: A.bg, borderRadius: 8 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: A.ink }}>{rock.title}</div>
                <div style={{ fontSize: 11, color: A.muted, marginTop: 3 }}>
                  {rock.atom_ids.length} atoms · contract: {Object.entries(rock.atomization_contract)
                    .map(([k, v]) => `${k}=${v}`).join(", ") || "—"}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
