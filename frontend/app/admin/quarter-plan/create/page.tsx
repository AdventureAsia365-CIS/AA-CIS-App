"use client";
// app/admin/quarter-plan/create/page.tsx — AA-323 Gap 1: N5 create-plan UI.
//
// Lets a human see which trips N5 auto-selected (with a short reason per
// trip, services/acp_planning/quarter.py's TripScore), manually add/remove
// trips before committing, then create a pending quarter plan version for
// Gate B review (/admin/quarter-plan). Never changes the algorithm's
// scoring weights (runway_fit 0.4 / richness 0.3 / distinctiveness 0.3) —
// only which trips are eligible for selection (AA-323 decision #3).
//
// markets/channels/capacity come read-only from the tenant's Planning
// config (Gap 3, GET /admin/tenants/{id}/config) — this screen is about
// trip selection, not campaign parameters; change those from Tenants >
// Planning instead.

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ListChecks, ChevronLeft, Loader2, CheckCircle2, Info } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, serif, sans, mono, Card, SLabel, Btn, Badge, LoadingScreen } from "../../_components/adminUi";

interface Tenant {
  tenant_id: string;
  name: string;
  is_active: boolean;
}

interface TripScore {
  trip_id: string;
  name: string;
  destination: string | null;
  score: number;
  forced: boolean;
  selected: boolean;
  reason: string;
}

interface PreviewPlan {
  trip_ids: string[];
  capacity_note: string | null;
  trip_scores: TripScore[];
}

interface TenantConfig {
  markets: string[];
  channels: string[];
  posts_per_week: number;
}

function currentQuarter(): { year: number; quarter: number } {
  const now = new Date();
  return { year: now.getFullYear(), quarter: Math.floor(now.getMonth() / 3) + 1 };
}

export default function CreateQuarterPlanPage() {
  const router = useRouter();
  const { year: defaultYear, quarter: defaultQuarter } = currentQuarter();

  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [year, setYear] = useState(defaultYear);
  const [quarter, setQuarter] = useState(defaultQuarter);

  const [config, setConfig] = useState<TenantConfig | null>(null);
  const [configLoading, setConfigLoading] = useState(false);

  const [plan, setPlan] = useState<PreviewPlan | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState<Set<string>>(new Set());

  const [creating, setCreating] = useState(false);
  const [createdVersionId, setCreatedVersionId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/admin/tenants")
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(d => setTenants((d.tenants ?? []).filter((t: Tenant) => t.is_active)))
      .catch(() => setError("Failed to load tenants"));
  }, []);

  useEffect(() => {
    if (!tenantId) { setConfig(null); return; }
    setConfigLoading(true);
    setError("");
    fetch(`/api/admin/tenants/${tenantId}/config`)
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(d => setConfig({ markets: d.markets, channels: d.channels, posts_per_week: d.posts_per_week }))
      .catch(() => setError("Failed to load tenant config"))
      .finally(() => setConfigLoading(false));
  }, [tenantId]);

  const runPreview = useCallback(
    async (cfg: TenantConfig, specials: string[], excludeIds: string[]) => {
      if (!tenantId) return;
      setPreviewLoading(true);
      setError("");
      try {
        const res = await fetch("/api/admin/quarter-plan/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tenant_id: tenantId, year, quarter,
            markets: cfg.markets, capacity_posts_per_week: cfg.posts_per_week,
            specials, excluded_trip_ids: excludeIds,
          }),
        });
        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          throw new Error(e.detail || "Failed to preview quarter plan");
        }
        setPlan((await res.json()).plan);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to preview quarter plan");
      } finally {
        setPreviewLoading(false);
      }
    },
    [tenantId, year, quarter]
  );

  useEffect(() => {
    if (!config) { setPlan(null); return; }
    setExcluded(new Set());
    setAdded(new Set());
    setCreatedVersionId(null);
    runPreview(config, [], []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, year, quarter]);

  function toggleTrip(t: TripScore) {
    if (!config) return;
    const nextExcluded = new Set(excluded);
    const nextAdded = new Set(added);
    if (t.selected) {
      nextExcluded.add(t.trip_id);
      nextAdded.delete(t.trip_id);
    } else {
      nextAdded.add(t.trip_id);
      nextExcluded.delete(t.trip_id);
    }
    setExcluded(nextExcluded);
    setAdded(nextAdded);
    const specials = (plan?.trip_scores ?? [])
      .filter(s => nextAdded.has(s.trip_id))
      .map(s => s.name);
    runPreview(config, specials, Array.from(nextExcluded));
  }

  async function createPlan() {
    if (!tenantId || !config || !plan) return;
    setCreating(true);
    setError("");
    try {
      const specials = plan.trip_scores.filter(s => added.has(s.trip_id)).map(s => s.name);
      const res = await fetch("/api/admin/quarter-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId, year, quarter,
          markets: config.markets, capacity_posts_per_week: config.posts_per_week,
          specials, excluded_trip_ids: Array.from(excluded),
        }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail ?? "Failed to create quarter plan"); return; }
      setCreatedVersionId(data.version_id);
    } catch {
      setError("Connection error");
    } finally {
      setCreating(false);
    }
  }

  const selectedCount = plan?.trip_scores.filter(s => s.selected).length ?? 0;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "28px 32px", paddingBottom: 0, maxWidth: 900 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <button onClick={() => router.push("/admin/quarter-plan")} style={{
            background: "none", border: "none", cursor: "pointer", color: A.muted,
            display: "flex", alignItems: "center", padding: 4,
          }}>
            <ChevronLeft size={18} />
          </button>
          <ListChecks size={20} color={A.red} />
          <h1 style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: A.ink, margin: 0 }}>
            Create Quarter Plan
          </h1>
        </div>
        <p style={{ fontSize: 13, color: A.muted, marginBottom: 24, fontFamily: sans }}>
          N5 auto-selects trips by score. Review the selection below, add or remove trips
          manually if needed, then create a pending plan for Gate B review.
        </p>

        {error && (
          <div style={{
            background: "#FEE2E2", border: "1px solid #FECACA", color: "#991B1B",
            borderRadius: 8, padding: "10px 14px", fontSize: 13, marginBottom: 18,
          }}>{error}</div>
        )}

        <Card style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <div>
              <SLabel>Tenant</SLabel>
              <select value={tenantId} onChange={e => setTenantId(e.target.value)} style={{
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
          </div>

          {tenantId && (
            <div style={{ marginTop: 14, fontSize: 12, color: A.muted, display: "flex", alignItems: "flex-start", gap: 6 }}>
              <Info size={13} style={{ marginTop: 1, flexShrink: 0 }} />
              {configLoading ? "Loading tenant config…" : config ? (
                <span>
                  markets={config.markets.join(",")}, channels={config.channels.join(",")},
                  {" "}capacity={config.posts_per_week}/wk — edit in Tenants &gt; Planning.
                </span>
              ) : "No config loaded."}
            </div>
          )}
        </Card>

        {!tenantId ? (
          <Card>
            <div style={{ textAlign: "center", padding: "24px 0", color: A.muted, fontSize: 13 }}>
              Select a tenant to preview its N5 selection.
            </div>
          </Card>
        ) : previewLoading && !plan ? (
          <LoadingScreen msg="Computing N5 preview…" />
        ) : plan && (
          <>
            <Card style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <SLabel>Trips ({selectedCount} selected)</SLabel>
                {previewLoading && <Loader2 size={13} style={{ animation: "spin 1s linear infinite", color: A.muted }} />}
              </div>
              {plan.capacity_note && (
                <div style={{
                  fontSize: 12, color: "#92400E", background: A.amberSoft,
                  border: "1px solid #FDE68A", borderRadius: 6, padding: "8px 10px", marginBottom: 12,
                }}>{plan.capacity_note}</div>
              )}
              {plan.trip_scores.length === 0 ? (
                <div style={{ fontSize: 13, color: A.muted, textAlign: "center", padding: "16px 0" }}>
                  No eligible trips found for this tenant.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {plan.trip_scores.map(t => (
                    <label key={t.trip_id} style={{
                      display: "flex", alignItems: "center", gap: 10, padding: "8px 6px",
                      borderRadius: 6, cursor: "pointer",
                      background: t.selected ? A.redTint : "transparent",
                    }}>
                      <input type="checkbox" checked={t.selected} onChange={() => toggleTrip(t)}
                        style={{ flexShrink: 0, cursor: "pointer" }} />
                      <span style={{ fontSize: 13, fontWeight: 600, color: A.ink, minWidth: 180 }}>{t.name}</span>
                      <span style={{ fontSize: 12, color: A.muted2, minWidth: 100 }}>{t.destination ?? "—"}</span>
                      <span style={{ fontSize: 11, fontFamily: mono, color: A.muted2, minWidth: 48 }}>
                        {t.score.toFixed(2)}
                      </span>
                      <span style={{ fontSize: 12, color: A.muted, flex: 1 }}>{t.reason}</span>
                      {t.forced && <Badge color="amber">forced</Badge>}
                    </label>
                  ))}
                </div>
              )}
            </Card>

            {createdVersionId ? (
              <Card>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <CheckCircle2 size={16} color="#22C55E" />
                  <span style={{ fontSize: 13, color: A.body }}>
                    Quarter plan created — pending Gate B review.
                  </span>
                </div>
                <Btn variant="primary" onClick={() => router.push("/admin/quarter-plan")}>
                  Go to Quarter Plan Approval
                </Btn>
              </Card>
            ) : (
              // Sticky action bar — a tenant with hundreds of eligible trips (e.g. aa_internal,
              // 763) makes the checklist above scroll very long; without this the submit button
              // was only reachable after scrolling past all of it. Sticks to the viewport bottom
              // instead (main's own scroll container is the document, so `sticky` needs no manual
              // left-offset math against the sidebar — unlike `fixed`, it inherits its horizontal
              // position from normal flow).
              <div style={{
                position: "sticky", bottom: 0, background: A.bg,
                borderTop: `1px solid ${A.line}`, padding: "14px 0",
                display: "flex", justifyContent: "flex-end",
              }}>
                <Btn variant="primary" disabled={creating || previewLoading} onClick={createPlan}>
                  {creating
                    ? <><Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> Creating…</>
                    : "Create Quarter Plan for Review"}
                </Btn>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
