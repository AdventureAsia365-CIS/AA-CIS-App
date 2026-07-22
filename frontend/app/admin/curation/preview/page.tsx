"use client";
// app/admin/curation/preview/page.tsx — AA-300 preview screen.
// The first screen in the whole ACP v2 build (N0-N6) that shows anything
// visually — everything before this was verified through test code and
// direct DB queries only. Calls the real N4/N5/N6 chain
// (services/acp_planning/) via GET /admin/atoms/preview-slotgrid and
// renders the resulting SlotGrid.

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Grid3x3, RefreshCw, Info, Sparkles } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import { A, sans, serif, Card, Btn, Badge, LoadingScreen } from "../../_components/adminUi";

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

interface PreviewResponse {
  runway_cell_count: number;
  quarter_plan: {
    tenant_id: string; year: number; quarter: number; trip_ids: string[];
    destination_shares: Record<string, number>; approved: boolean; approved_by: string | null;
    thin_trip_notes: string[]; capacity_note: string | null;
  };
  slot_grid: {
    tenant_id: string; year: number; month: number; slots: Slot[]; capacity_note: string | null;
  };
  demo_params: {
    markets: string[]; channels: string[]; capacity_posts_per_week: number; note: string;
  };
}

const STAGE_BADGE: Record<string, "green" | "amber" | "blue" | "gray"> = {
  BOFU: "green", MOFU: "amber", TOFU: "blue", OFF: "gray",
};

export default function CurationPreviewPage() {
  const router = useRouter();
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/admin/atoms/preview-slotgrid");
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
  }, []);

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
          the currently curated atom pool. Read-only — nothing here is written to the database.
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
              fontSize: 11, color: A.muted, background: A.line2, borderRadius: 8, padding: "8px 12px",
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
                  Q{data.quarter_plan.quarter} {data.quarter_plan.year} — {data.quarter_plan.trip_ids.length} trips
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
                    {weekSlots.map(slot => (
                      <Card key={slot.slot_id} style={{ padding: 12 }}>
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
                              {slot.atom_ids.length} atom{slot.atom_ids.length === 1 ? "" : "s"}
                            </div>
                          </>
                        )}
                      </Card>
                    ))}
                  </div>
                </div>
              );
            })}
          </>
        )}
      </main>
    </div>
  );
}
