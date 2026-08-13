"use client";
// app/admin/curation/preview/page.tsx — AA-300 preview screen.
// The first screen in the whole ACP v2 build (N0-N6) that shows anything
// visually — everything before this was verified through test code and
// direct DB queries only. Calls the real N4/N5/N6 chain
// (services/acp_planning/) via GET /admin/atoms/preview-slotgrid and
// renders the resulting SlotGrid.

import { Suspense, useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Grid3x3, RefreshCw, Info, Sparkles, X, ExternalLink } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, sans, serif, mono, Card, Btn, Badge, LoadingScreen } from "../../_components/adminUi";

interface Slot {
  slot_id: string;
  week: number;
  channel: string;
  kind: "evergreen" | "campaign" | "reactive_hold";
  trip_id: string | null;
  atom_ids: string[];
  funnel_stage: "TOFU" | "MOFU" | "BOFU" | "OFF";
  framework: string | null;
  cta_target: string | null;
  topic_hint: string | null;
  keyword_seed: string | null;
}

// AA-323 Gap 2 — one row per (destination, market, month) runway cell, now
// returned in full (previously only runway_cell_count, a bare integer).
interface RunwayCell {
  destination: string;
  market: string;
  month: number;
  stage: "TOFU" | "MOFU" | "BOFU" | "OFF";
}

interface PreviewResponse {
  runway_cell_count: number;
  runway_cells: RunwayCell[];
  quarter_plan: {
    tenant_id: string; year: number; quarter: number; trip_ids: string[];
    destination_shares: Record<string, number>; approved: boolean; approved_by: string | null;
    thin_trip_notes: string[]; capacity_note: string | null;
  };
  // AA-323 round 5 — Việc 2: null in demo mode (nothing persisted yet to have a
  // version number); the persisted version_no this screen is reading otherwise.
  quarter_plan_version_no: number | null;
  slot_grid: {
    tenant_id: string; year: number; month: number; slots: Slot[]; capacity_note: string | null;
  };
  demo_params: {
    markets: string[]; channels: string[]; capacity_posts_per_week: number;
    demo_mode: boolean; note: string;
  };
}

const STAGE_BADGE: Record<string, "green" | "amber" | "blue" | "gray"> = {
  BOFU: "green", MOFU: "amber", TOFU: "blue", OFF: "gray",
};

const STAGE_CELL_COLOR: Record<string, string> = {
  BOFU: A.green, MOFU: A.amber, TOFU: "#3B82F6", OFF: A.line2,
};

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// AA-323 Gap 2 — destination x month grid, one table per market (usually
// just one). Missing (destination, market, month) combinations default to
// OFF, matching RunwayMap.stage()'s own fallback (services/acp_planning/
// models.py) so an unlisted cell reads the same here as it would server-side.
function RunwayMapGrid({ cells }: { cells: RunwayCell[] }) {
  if (cells.length === 0) {
    return (
      <Card style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 13, color: A.muted, textAlign: "center", padding: "16px 0" }}>
          No runway cells computed for this tenant.
        </div>
      </Card>
    );
  }
  const markets = Array.from(new Set(cells.map(c => c.market))).sort();
  const destinations = Array.from(new Set(cells.map(c => c.destination))).sort();
  const lookup = new Map<string, string>();
  for (const c of cells) lookup.set(`${c.market}|${c.destination}|${c.month}`, c.stage);

  return (
    <Card style={{ marginBottom: 18, overflow: "auto" }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: A.muted, marginBottom: 10, textTransform: "uppercase" }}>
        Runway Map
      </div>
      {markets.map(market => (
        <div key={market} style={{ marginBottom: markets.length > 1 ? 16 : 0 }}>
          {markets.length > 1 && (
            <div style={{ fontSize: 11, fontWeight: 700, color: A.body, marginBottom: 6 }}>{market}</div>
          )}
          <table style={{ borderCollapse: "collapse", fontSize: 10 }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "3px 8px", color: A.muted2, fontWeight: 600 }}>Destination</th>
                {MONTH_LABELS.map(m => (
                  <th key={m} style={{ padding: "3px 4px", color: A.muted2, fontWeight: 600, minWidth: 28 }}>{m}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {destinations.map(dest => (
                <tr key={dest}>
                  <td style={{ padding: "3px 8px", color: A.body, whiteSpace: "nowrap" }}>{dest}</td>
                  {MONTH_LABELS.map((_, i) => {
                    const stage = lookup.get(`${market}|${dest}|${i + 1}`) ?? "OFF";
                    return (
                      <td key={i} title={stage} style={{ padding: 2 }}>
                        <div style={{
                          width: 22, height: 16, borderRadius: 3,
                          background: STAGE_CELL_COLOR[stage],
                        }} />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <div style={{ display: "flex", gap: 14, marginTop: 10, fontSize: 10.5, color: A.muted }}>
        {(["BOFU", "MOFU", "TOFU", "OFF"] as const).map(s => (
          <span key={s} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: STAGE_CELL_COLOR[s] }} />
            {s}
          </span>
        ))}
      </div>
    </Card>
  );
}

// AA-323 Gap 4 — slot detail: fetches the slot's real atoms (text,
// distinctiveness) via GET /admin/atoms?atom_ids=..., plus a deep link back
// to Curation for the slot's source tour. Route/param already exist and are
// exercised via useSearchParams() on the receiving page (curation/page.tsx,
// fixed AA-345 round 5) — this only adds the outbound link.
interface AtomDetail {
  atom_id: string;
  tour_id: string;
  tour_name: string;
  text: string;
  distinctiveness: "HIGH" | "MED" | "LOW";
  activity_type: string | null;
}

const DIST_BADGE: Record<string, "green" | "amber" | "gray"> = {
  HIGH: "green", MED: "amber", LOW: "gray",
};

function SlotDetailModal({ slot, onClose }: { slot: Slot; onClose: () => void }) {
  const router = useRouter();
  const [atoms, setAtoms] = useState<AtomDetail[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (slot.atom_ids.length === 0) { setAtoms([]); return; }
    fetch(`/api/admin/atoms?atom_ids=${slot.atom_ids.join(",")}`)
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(d => setAtoms(d.atoms ?? []))
      .catch(() => setError("Failed to load atom detail"));
  }, [slot.atom_ids]);

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex",
      alignItems: "center", justifyContent: "center", zIndex: 100,
    }} onClick={onClose}>
      <div
        style={{ background: A.card, border: `1px solid ${A.line}`, borderRadius: 16, padding: 28, width: 560, maxHeight: "80vh", overflowY: "auto" }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink }}>Slot Detail</div>
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <Badge color="gray">{slot.channel}</Badge>
              <Badge color={STAGE_BADGE[slot.funnel_stage]}>{slot.funnel_stage}</Badge>
              {slot.framework && <span style={{ fontSize: 12, color: A.muted, alignSelf: "center" }}>{slot.framework}</span>}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted }}><X size={16} /></button>
        </div>

        {slot.keyword_seed && (
          <div style={{ fontSize: 12, color: A.muted, marginBottom: 12 }}>keyword: {slot.keyword_seed}</div>
        )}

        {slot.trip_id && (
          <Btn size="sm" variant="secondary" onClick={() => router.push(`/admin/curation?tour_id=${slot.trip_id}`)} style={{ marginBottom: 16 }}>
            <ExternalLink size={12} /> View source tour in Curation
          </Btn>
        )}

        {error && <div style={{ fontSize: 12, color: A.red, marginBottom: 10 }}>{error}</div>}

        <div style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase", marginBottom: 8 }}>
          Atoms ({slot.atom_ids.length})
        </div>
        {atoms === null ? (
          <div style={{ fontSize: 12, color: A.muted }}>Loading…</div>
        ) : atoms.length === 0 ? (
          <div style={{ fontSize: 12, color: A.muted }}>No atoms in this slot.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {atoms.map(a => (
              <div key={a.atom_id} style={{ padding: "10px 12px", background: A.bg, borderRadius: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                  <Badge color={DIST_BADGE[a.distinctiveness]}>{a.distinctiveness}</Badge>
                  {a.activity_type && <span style={{ fontSize: 10.5, color: A.muted2 }}>{a.activity_type}</span>}
                  <span style={{ fontSize: 10, color: A.muted2, marginLeft: "auto", fontFamily: mono }}>{a.atom_id}</span>
                </div>
                <div style={{ fontSize: 13, color: A.body, lineHeight: 1.5 }}>{a.text}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function CurationPreviewPageInner() {
  const router = useRouter();
  // AA-323 round 6, Phần A — the History tab's "Slot Grid Preview" link
  // navigates here with ?version_id=<uuid> to view one specific historical
  // (always-approved) version instead of the tenant's current one.
  // useSearchParams(), not a lazy window.location read — same reasoning as
  // AA-345 round 5 (a client-side router.push() navigation can otherwise
  // race the URL actually updating).
  const searchParams = useSearchParams();
  const versionId = searchParams.get("version_id");
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedSlot, setSelectedSlot] = useState<Slot | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const url = versionId
        ? `/api/admin/atoms/preview-slotgrid?version_id=${encodeURIComponent(versionId)}`
        : "/api/admin/atoms/preview-slotgrid";
      const res = await fetch(url);
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Failed to load preview (${res.status})`);
      }
      setData(await res.json());
    } catch (err: any) {
      setError(err.message || "Failed to load preview.");
    } finally {
      setLoading(false);
    }
  }, [versionId]);

  useEffect(() => { load(); }, [load]);

  const weeks = data ? [1, 2, 3, 4] : [];

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "28px 32px", maxWidth: 1400 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <Grid3x3 size={18} color={A.gold} />
          <h1 style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: A.ink, margin: 0 }}>
            N6 Slot Grid Preview
          </h1>
          <div style={{ flex: 1 }} />
          <Btn size="sm" variant="ghost" onClick={() => router.push("/admin/curation")}>
            <Sparkles size={12} /> Back to curation
          </Btn>
          <Btn size="sm" variant="secondary" onClick={load} disabled={loading}>
            <RefreshCw size={12} /> Recompute
          </Btn>
        </div>
        <p style={{ fontSize: 13, color: A.muted, marginTop: 4, marginBottom: 18 }}>
          Runs the real N4 (Runway Map) → N5 (Quarter Plan) → N6 (Slot Allocator) chain against
          the currently curated atom pool, reading the tenant's Gate-B-approved quarter plan from
          the database when one exists (falling back to an unpersisted preview otherwise — see the
          note below). Computing this slot grid never writes anything back to the database.
        </p>

        {error && (
          <div style={{
            fontSize: 12, padding: "8px 12px", borderRadius: 6, marginBottom: 14,
            background: A.redSoft, color: A.red,
          }}>{error}</div>
        )}

        {loading ? (
          <LoadingScreen msg="Running N4 → N5 → N6…" />
        ) : data && (
          <>
            <div style={{
              display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 8,
              fontSize: 11, color: A.muted,
              background: data.demo_params.demo_mode ? A.line2 : A.greenSoft,
              borderRadius: 8, padding: "8px 12px",
            }}>
              <Info size={13} style={{ marginTop: 1, flexShrink: 0 }} />
              <span>{data.demo_params.note} — markets={data.demo_params.markets.join(",")},
                channels={data.demo_params.channels.join(",")},
                capacity={data.demo_params.capacity_posts_per_week}/wk</span>
            </div>

            <div style={{ display: "flex", gap: 12, marginBottom: 18, flexWrap: "wrap" }}>
              <Card style={{ padding: "12px 16px" }}>
                <div style={{ fontSize: 10, color: A.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Runway cells
                </div>
                <div style={{ fontFamily: serif, fontSize: 20, color: A.ink }}>{data.runway_cell_count}</div>
              </Card>
              <Card style={{ padding: "12px 16px" }}>
                <div style={{ fontSize: 10, color: A.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Quarter plan
                </div>
                <div style={{ fontFamily: serif, fontSize: 20, color: A.ink }}>
                  Q{data.quarter_plan.quarter} {data.quarter_plan.year}
                  {data.quarter_plan_version_no !== null && ` · v${data.quarter_plan_version_no}`}
                  {" "}— {data.quarter_plan.trip_ids.length} trips
                  {/* AA-323 round 6, Phần A — distinguishes a historical version
                      (reached via ?version_id=) from the tenant's current one, so a
                      reviewer can't mistake an old version for what's live today. */}
                  {versionId && <span style={{ color: A.muted, fontWeight: 400 }}> (historical)</span>}
                </div>
                <Badge color={data.quarter_plan.approved ? "green" : "red"}>
                  {data.quarter_plan.approved ? `Approved (${data.quarter_plan.approved_by})` : "Not approved (Gate B)"}
                </Badge>
              </Card>
              <Card style={{ padding: "12px 16px" }}>
                <div style={{ fontSize: 10, color: A.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                  Slot grid
                </div>
                <div style={{ fontFamily: serif, fontSize: 20, color: A.ink }}>
                  {data.slot_grid.year}-{String(data.slot_grid.month).padStart(2, "0")} —
                  {" "}{data.slot_grid.slots.length} slots
                </div>
              </Card>
            </div>

            {data.slot_grid.capacity_note && (
              <div style={{
                fontSize: 11, padding: "8px 12px", borderRadius: 6, marginBottom: 14,
                background: A.amberSoft, color: "#92400E",
              }}>
                {data.slot_grid.capacity_note}
              </div>
            )}

            <RunwayMapGrid cells={data.runway_cells} />

            {Object.keys(data.quarter_plan.destination_shares).length > 0 && (
              <Card style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: A.muted, marginBottom: 8, textTransform: "uppercase" }}>
                  Destination shares
                </div>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                  {Object.entries(data.quarter_plan.destination_shares).map(([dest, share]) => (
                    <div key={dest} style={{ fontSize: 12, color: A.body }}>
                      <b>{dest}</b>: {(share * 100).toFixed(0)}%
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {weeks.map(week => {
              const weekSlots = data.slot_grid.slots.filter(s => s.week === week);
              if (weekSlots.length === 0) return null;
              return (
                <div key={week} style={{ marginBottom: 18 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: A.muted, marginBottom: 8 }}>
                    Week {week}
                  </div>
                  <div style={{
                    display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10,
                  }}>
                    {weekSlots.map(slot => {
                      const clickable = slot.kind !== "reactive_hold";
                      return (
                        <Card
                          key={slot.slot_id}
                          style={{ padding: 12, cursor: clickable ? "pointer" : "default" }}
                        >
                          <div
                            onClick={clickable ? () => setSelectedSlot(slot) : undefined}
                            style={{ cursor: clickable ? "pointer" : "default" }}
                          >
                            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, flexWrap: "wrap" }}>
                              <Badge color="gray">{slot.channel}</Badge>
                              <Badge color={STAGE_BADGE[slot.funnel_stage]}>{slot.funnel_stage}</Badge>
                              {slot.kind === "reactive_hold" && <Badge color="amber">reactive hold</Badge>}
                              {slot.kind === "campaign" && <Badge color="gold">campaign</Badge>}
                            </div>
                            {slot.kind === "reactive_hold" ? (
                              <div style={{ fontSize: 12, color: A.muted, fontStyle: "italic" }}>
                                {slot.topic_hint}
                              </div>
                            ) : (
                              <>
                                <div style={{ fontSize: 12, color: A.body, marginBottom: 4 }}>
                                  {slot.framework && <span style={{ fontFamily: sans, fontWeight: 600 }}>{slot.framework}</span>}
                                </div>
                                {slot.keyword_seed && (
                                  <div style={{ fontSize: 11, color: A.muted, marginBottom: 4 }}>
                                    keyword: {slot.keyword_seed.slice(0, 60)}
                                  </div>
                                )}
                                <div style={{ fontSize: 10, color: A.muted2 }}>
                                  {slot.atom_ids.length} atom{slot.atom_ids.length === 1 ? "" : "s"} — click for detail
                                </div>
                              </>
                            )}
                          </div>
                        </Card>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </>
        )}
      </main>
      {selectedSlot && <SlotDetailModal slot={selectedSlot} onClose={() => setSelectedSlot(null)} />}
    </div>
  );
}

// AA-323 round 6, Phần A — useSearchParams() (used in CurationPreviewPageInner
// above) requires a Suspense boundary around any component that calls it, per
// Next.js App Router — same pattern as curation/page.tsx (AA-345 round 5).
export default function CurationPreviewPage() {
  return (
    <Suspense fallback={<LoadingScreen msg="Loading…" />}>
      <CurationPreviewPageInner />
    </Suspense>
  );
}
