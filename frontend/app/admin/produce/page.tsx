"use client";
// app/admin/produce/page.tsx — AA-405: manual N7 Produce -> N8 Deliver/Learn trigger + Gate C review.
//
// Triggers POST /admin/produce/run (allocate -> create-run -> persist-slots synchronously, then
// the slow per-slot production loop runs as a backend BackgroundTask) and polls
// GET /admin/produce/run/{run_id} for progress/results. The Gate C section lists packets with
// status='ready' and approves them via the existing trust_ramp.confirm_ramp_transition()
// (AA-365) through POST /admin/produce/packets/{id}/gate-c/approve — no gate logic here, this
// page only calls what already exists.
//
// Each slot involves several real AI generation calls and typically takes 2-4 minutes; a full
// week (up to 4 slots) can take 10+ minutes — the polling UI below is built around that being
// expected, not a sign anything is broken.

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { PlayCircle, RefreshCw } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, sans, mono, Card, SLabel, Btn, Badge, Spinner, TabBar, TH, TD } from "../_components/adminUi";
import PieceReviewModal from "./PieceReviewModal";
import HistoryTab from "./HistoryTab";

interface Tenant {
  tenant_id: string;
  name: string;
  is_active: boolean;
}

interface SlotRow {
  slot_id: string;
  channel: string;
  kind: string;
  status: string;
}

interface PieceRow {
  piece_id: string;
  channel: string;
  status: string;
  held_reason: string | null;
  repair_count: number;
}

interface PacketInfo {
  packet_id: string;
  status: string;
  publish_mode: string;
}

// AA-412 follow-up — Phần 2a: `month` was missing entirely from this shape until migration 106 +
// the backend fix added it (acp_deliver.packets had no `month` column at all — two different
// months' Week-N runs for the same tenant were silently merged into ONE packet; see
// docs/implementation-notes/AA-412-produce-page-usability.md D1). Always render year/month/week
// together below — never year+week alone — so two different months never look identical again.
interface GateLedgerEntry { gate: string; passed: boolean; violations: string[]; }

// AA-412 follow-up — Phần 2: one row per piece, not per packet. Fetched via the existing
// GET /packets/{id}/pieces (no new endpoint — see D4) once per ready packet, then flattened here
// with the parent packet's identity attached so the table can group visually by packet while the
// row unit stays the piece.
interface PacketPieceRow {
  packet_id: string;
  piece_id: string;
  channel: string;
  status: string; // gate outcome: in_progress | passed | held
  gate_ledger: GateLedgerEntry[];
  review_status: string; // pending | approved | rejected
  reviewed_by: string | null;
}

interface RunDetail {
  run_id: string;
  tenant_id: string;
  year: number;
  month: number;
  week: number;
  status: string; // allocated | producing | completed | failed
  created_at: string | null;
  completed_at: string | null;
  slots: SlotRow[];
  pieces: PieceRow[];
  packet: PacketInfo | null;
}

interface PendingPacket {
  packet_id: string;
  tenant_id: string;
  year: number;
  month: number; // AA-412 follow-up — added by migration 106, see PacketPieceRow comment above
  week: number;
  status: string;
  publish_mode: string;
  piece_count: number;
  approved_count: number;
}

// Shared year/month/week label — always all three together, never year+week alone (Phần 2a).
function slotLabel(year: number, month: number, week: number): string {
  return `${year}-${String(month).padStart(2, "0")} W${week}`;
}

const POLL_INTERVAL_MS = 8000;

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const labelStyle: React.CSSProperties = {
  display: "block", fontSize: 11, fontWeight: 600, color: A.muted,
  textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 5,
};

const inputStyle: React.CSSProperties = {
  padding: "8px 10px", borderRadius: 7, border: `1px solid ${A.line}`,
  background: A.card, color: A.ink, fontSize: 13, fontFamily: sans, minWidth: 200,
};

function RunStatusBadge({ status }: { status: string }) {
  const map: Record<string, { color: "green" | "amber" | "red" | "gray"; label: string }> = {
    allocated: { color: "gray", label: "Allocated" },
    producing: { color: "amber", label: "Producing" },
    completed: { color: "green", label: "Completed" },
    failed: { color: "red", label: "Failed" },
  };
  const s = map[status] ?? { color: "gray" as const, label: status };
  return <Badge color={s.color}>{s.label}</Badge>;
}

function SlotStatusBadge({ status }: { status: string }) {
  const map: Record<string, { color: "green" | "amber" | "gray"; label: string }> = {
    due: { color: "gray", label: "Due" },
    produced: { color: "green", label: "Produced" },
    skipped: { color: "amber", label: "Skipped" },
  };
  const s = map[status] ?? { color: "gray" as const, label: status };
  return <Badge color={s.color}>{s.label}</Badge>;
}

function PieceGateBadge({ ledger }: { ledger: GateLedgerEntry[] }) {
  if (ledger.length === 0) return <span style={{ color: A.muted2, fontSize: 11.5 }}>—</span>;
  const failed = ledger.filter(g => !g.passed).length;
  return failed === 0
    ? <Badge color="green">All pass</Badge>
    : <Badge color="red">{failed} fail</Badge>;
}

function PieceReviewBadge({ status }: { status: string }) {
  const map: Record<string, { color: "green" | "red" | "gray"; label: string }> = {
    approved: { color: "green", label: "Approved" },
    rejected: { color: "red", label: "Rejected" },
    pending: { color: "gray", label: "Pending" },
  };
  const s = map[status] ?? { color: "gray" as const, label: status };
  return <Badge color={s.color}>{s.label}</Badge>;
}

// AA-412 follow-up — Phần 2: a packet-level header row (id/tenant/week/reviewed-count — the "one
// point into the packet overview" the task asked to keep) followed by one row per piece. The
// header row is the only place packet-level identity is shown; piece rows below it are the real
// review unit and open PieceReviewModal focused on exactly that piece.
function PacketPieceGroup({ packet, pieces, groupBg, tenantName, onOpenPacket, onOpenPiece }: {
  packet: PendingPacket;
  pieces: PacketPieceRow[];
  groupBg: string;
  tenantName: string;
  onOpenPacket: () => void;
  onOpenPiece: (pieceId: string) => void;
}) {
  return (
    <>
      <tr style={{ background: A.line2 }}>
        <td colSpan={8} style={{ padding: "10px 14px", borderBottom: `1px solid ${A.line}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span style={{ fontFamily: mono, fontSize: 11, color: A.muted }}>{packet.packet_id.slice(0, 8)}…</span>
            <strong style={{ fontSize: 12.5, color: A.ink }}>{tenantName}</strong>
            <span style={{ fontSize: 12, color: A.muted }}>{slotLabel(packet.year, packet.month, packet.week)}</span>
            <Badge color={packet.approved_count === packet.piece_count ? "green" : "gray"}>
              {packet.approved_count}/{packet.piece_count} approved
            </Badge>
            <span style={{ fontSize: 11.5, color: A.muted2 }}>{packet.publish_mode}</span>
            <div style={{ flex: 1 }} />
            <Btn size="sm" variant="ghost" onClick={onOpenPacket}>Open Packet</Btn>
          </div>
        </td>
      </tr>
      {pieces.length === 0 ? (
        <tr style={{ background: groupBg }}>
          <td colSpan={8} style={{ ...TD, color: A.muted, fontSize: 12 }}>No pieces loaded for this packet.</td>
        </tr>
      ) : pieces.map(piece => (
        <tr
          key={piece.piece_id} style={{ background: groupBg, cursor: "pointer" }}
          onClick={() => onOpenPiece(piece.piece_id)}
        >
          <td style={TD}></td>
          <td style={TD}>{tenantName}</td>
          <td style={TD}>{slotLabel(packet.year, packet.month, packet.week)}</td>
          <td style={TD}><Badge color="blue">{piece.channel}</Badge></td>
          <td style={TD}>{piece.status === "passed" ? <Badge color="green">Passed</Badge> : <Badge color="amber">Held</Badge>}</td>
          <td style={TD}><PieceGateBadge ledger={piece.gate_ledger} /></td>
          <td style={TD}><PieceReviewBadge status={piece.review_status} /></td>
          <td style={{ ...TD, textAlign: "right" }}>
            <Btn size="sm" variant="primary" onClick={() => onOpenPiece(piece.piece_id)}>
              Review
            </Btn>
          </td>
        </tr>
      ))}
    </>
  );
}

export default function ProducePage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth() + 1); // AA-410 — backend default is the same date.today().month
  const [week, setWeek] = useState(1);

  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState("");

  const [run, setRun] = useState<RunDetail | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [packets, setPackets] = useState<PendingPacket[]>([]);
  const [packetPieces, setPacketPieces] = useState<Record<string, PacketPieceRow[]>>({});
  const [piecesLoading, setPiecesLoading] = useState(false);
  const [packetsError, setPacketsError] = useState("");
  const [reviewTarget, setReviewTarget] = useState<{ packetId: string; pieceId: string | null } | null>(null);

  const [activeTab, setActiveTab] = useState<"live" | "history">("live");

  useEffect(() => {
    // Loaded unfiltered (not just is_active) so History's tenant name lookup also resolves
    // packets/runs belonging to a since-deactivated tenant, not just live ones.
    fetch("/api/admin/tenants")
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(d => setTenants(d.tenants ?? []))
      .catch(() => setTriggerError("Failed to load tenants."));
  }, []);

  const tenantNameById = useMemo(
    () => Object.fromEntries(tenants.map(t => [t.tenant_id, t.name])),
    [tenants],
  );
  const activeTenants = useMemo(() => tenants.filter(t => t.is_active), [tenants]);

  // AA-412 follow-up — Phần 2: after loading the packet-level overview, also fetch each ready
  // packet's pieces (existing GET /packets/{id}/pieces, no new endpoint — D4) so the table below
  // can render one row per piece. Packet count is small (Gate C review queue, not the full piece
  // history), so N+1 fetches here is the same shape PieceReviewModal already uses per-packet.
  const loadPendingPackets = useCallback(() => {
    fetch("/api/admin/produce/packets")
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(async (d: PendingPacket[]) => {
        setPackets(d);
        setPacketsError("");
        setPiecesLoading(true);
        const entries = await Promise.all(d.map(async (p): Promise<[string, PacketPieceRow[]]> => {
          try {
            const res = await fetch(`/api/admin/produce/packets/${p.packet_id}/pieces`);
            if (!res.ok) return [p.packet_id, []];
            const pieces = await res.json();
            return [p.packet_id, pieces.map((pc: PacketPieceRow) => ({ ...pc, packet_id: p.packet_id }))];
          } catch {
            return [p.packet_id, []];
          }
        }));
        setPacketPieces(Object.fromEntries(entries));
        setPiecesLoading(false);
      })
      .catch(() => setPacketsError("Failed to load pending packets."));
  }, []);

  useEffect(() => { loadPendingPackets(); }, [loadPendingPackets]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
  }, []);

  const pollRun = useCallback((runId: string) => {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/admin/produce/run/${runId}`);
        if (!res.ok) return;
        const data: RunDetail = await res.json();
        setRun(data);
        if (data.status === "completed" || data.status === "failed") {
          stopPolling();
          loadPendingPackets();
        }
      } catch {
        // Transient network hiccup — keep polling, the next tick may succeed.
      }
    }, POLL_INTERVAL_MS);
  }, [stopPolling, loadPendingPackets]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  async function handleTrigger() {
    if (!tenantId) { setTriggerError("Select a tenant first."); return; }
    setTriggering(true);
    setTriggerError("");
    setRun(null);
    try {
      const res = await fetch("/api/admin/produce/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenantId, year, month, week }),
      });
      const data = await res.json();
      if (!res.ok) {
        setTriggerError(data.detail || "Failed to start the run.");
        return;
      }
      setRun({
        run_id: data.run_id, tenant_id: data.tenant_id, year: data.year, month: data.month, week: data.week,
        status: data.status, created_at: null, completed_at: null, slots: [], pieces: [], packet: null,
      });
      pollRun(data.run_id);
    } catch {
      setTriggerError("Could not reach the server. Please try again.");
    } finally {
      setTriggering(false);
    }
  }

  function handlePacketAdvanced() {
    setReviewTarget(null);
    loadPendingPackets();
  }

  const isRunning = run !== null && (run.status === "producing" || run.status === "allocated");
  const passedCount = run?.pieces.filter(p => p.status === "passed").length ?? 0;
  const heldCount = run?.pieces.filter(p => p.status === "held").length ?? 0;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      {/* AA-412 follow-up (layout fixes round) — `maxWidth: 1100` used to cap this content area
          well short of the real available width next to the sidebar, leaving dead whitespace on
          any screen wider than ~1320px total. Removed to match the full-width pattern every other
          `/admin/*` page already uses (dashboard/tenants: flex-1 content column, no page-level
          max-width). `minWidth: 0` is the actual fix for the Run History table's overlap bug
          reported in the same session — a flex item's default `min-width: auto` refuses to shrink
          below its content's intrinsic width, so a wide `table-layout: fixed` table inside an
          unconstrained flex child can force this whole column wider than the viewport instead of
          respecting it, which is what produced the column-overlap symptom at narrower viewports. */}
      <div style={{ flex: 1, minWidth: 0, padding: "28px 36px" }}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink, margin: 0 }}>
            Produce &amp; Deliver (N7 / N8)
          </h1>
          <p style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
            Manually trigger a weekly production run (N7), review packet pieces before approving
            them (N8 Gate C), and look back at past runs.
          </p>
        </div>

        <div style={{ marginBottom: 24 }}>
          <TabBar
            tabs={[{ key: "live", label: "Trigger & Gate C" }, { key: "history", label: "Run History" }]}
            active={activeTab}
            onChange={k => setActiveTab(k as "live" | "history")}
          />
        </div>

        {activeTab === "history" && <HistoryTab tenantNameById={tenantNameById} />}

        {activeTab === "live" && <>
        {/* Trigger form */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>Trigger a Production Run</SLabel>
          <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <label style={labelStyle}>Tenant</label>
              <select value={tenantId} onChange={e => setTenantId(e.target.value)} style={inputStyle}>
                <option value="">Select a tenant…</option>
                {activeTenants.map(t => (
                  <option key={t.tenant_id} value={t.tenant_id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Year</label>
              <input type="number" value={year} onChange={e => setYear(Number(e.target.value))}
                style={{ ...inputStyle, width: 90, minWidth: 90 }} />
            </div>
            <div>
              <label style={labelStyle}>Month</label>
              <select value={month} onChange={e => setMonth(Number(e.target.value))}
                style={{ ...inputStyle, width: 150, minWidth: 150 }}>
                {MONTH_NAMES.map((name, i) => (
                  <option key={i + 1} value={i + 1}>{String(i + 1).padStart(2, "0")} — {name}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Week (1-4)</label>
              <select value={week} onChange={e => setWeek(Number(e.target.value))}
                style={{ ...inputStyle, width: 90, minWidth: 90 }}>
                {[1, 2, 3, 4].map(w => <option key={w} value={w}>{w}</option>)}
              </select>
            </div>
            <Btn variant="primary" onClick={handleTrigger} disabled={triggering || isRunning}>
              <PlayCircle size={14} /> {triggering ? "Starting…" : "Run Production"}
            </Btn>
          </div>
          <div style={{ fontSize: 11.5, color: A.muted2, marginTop: 10 }}>
            Requires an approved Quarter Plan (Gate B) for the tenant. Week = 1st–4th week of
            the selected month, not an ISO week.
          </div>
          {triggerError && (
            <div style={{
              marginTop: 10, fontSize: 12.5, color: A.red, background: A.redTint,
              padding: "8px 12px", borderRadius: 8,
            }}>
              {triggerError}
            </div>
          )}
        </Card>

        {/* Results view */}
        {run && (
          <Card style={{ marginBottom: 24 }}>
            <SLabel>Run Result</SLabel>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
              <RunStatusBadge status={run.status} />
              <span style={{ fontSize: 12, color: A.muted }}>
                Run {run.run_id.slice(0, 8)}… — tenant {run.tenant_id.slice(0, 8)}… —
                {" "}{run.year}-{String(run.month).padStart(2, "0")} week {run.week}
              </span>
            </div>

            {isRunning && (
              <div style={{
                display: "flex", alignItems: "center", gap: 10, padding: "12px 14px",
                background: A.line2, borderRadius: 8, marginBottom: 14,
              }}>
                <Spinner />
                <div style={{ fontSize: 12.5, color: A.body }}>
                  Production in progress — each slot involves several real AI generation calls and
                  typically takes 2-4 minutes. A full week (up to 4 slots) can take 10+ minutes.
                  This page updates automatically every {POLL_INTERVAL_MS / 1000}s; you can leave
                  it and come back later.
                </div>
              </div>
            )}

            {run.slots.length > 0 && (
              <>
                <div style={{ fontSize: 12, fontWeight: 600, color: A.ink, margin: "14px 0 8px" }}>Slots</div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 18 }}>
                    <thead>
                      <tr>
                        <th style={TH}>Slot</th><th style={TH}>Channel</th><th style={TH}>Kind</th><th style={TH}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.slots.map(s => (
                        <tr key={s.slot_id}>
                          <td style={TD}>{s.slot_id}</td>
                          <td style={TD}>{s.channel}</td>
                          <td style={TD}>{s.kind}</td>
                          <td style={TD}><SlotStatusBadge status={s.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {run.pieces.length > 0 && (
              <>
                <div style={{ fontSize: 12, fontWeight: 600, color: A.ink, margin: "0 0 8px" }}>
                  Pieces — {passedCount} passed, {heldCount} held
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 18 }}>
                    <thead>
                      <tr>
                        <th style={TH}>Piece</th><th style={TH}>Channel</th><th style={TH}>Status</th>
                        <th style={TH}>Repairs</th><th style={TH}>Held Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.pieces.map(p => (
                        <tr key={p.piece_id}>
                          <td style={TD}>{p.piece_id.split(":").slice(1).join(":")}</td>
                          <td style={TD}>{p.channel}</td>
                          <td style={TD}>
                            {p.status === "passed" ? <Badge color="green">Passed</Badge> : <Badge color="amber">Held</Badge>}
                          </td>
                          <td style={TD}>{p.repair_count}</td>
                          <td style={{ ...TD, fontSize: 11.5, color: A.muted, maxWidth: 360 }}>{p.held_reason ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {!isRunning && run.status === "completed" && (
              <div style={{ fontSize: 12.5, color: A.body }}>
                {run.packet ? (
                  <>
                    Packet created — status <Badge color={run.packet.status === "ready" ? "green" : "gray"}>{run.packet.status}</Badge>.
                    Review it in the Gate C section below.
                  </>
                ) : (
                  "No pieces passed their gates, so no packet was assembled for this run."
                )}
              </div>
            )}
            {run.status === "failed" && (
              <div style={{ fontSize: 12.5, color: A.red }}>
                This run failed before completing. Check server logs for details, or try triggering
                it again — slots already produced will not be re-run.
              </div>
            )}
          </Card>
        )}

        {/* Gate C section — AA-412 follow-up (Phần 2): one row per PIECE, not per packet, so
            channel/status/gate result are visible without opening the modal first. Rows are
            grouped visually under a sticky-ish packet header (id/tenant/week/reviewed count) —
            the review unit is still the piece; clicking a piece row opens PieceReviewModal
            already scrolled/focused to that exact piece. Packet identity travels with each piece
            row via PacketPieceRow.packet_id, same convention as HistoryTab's run grouping. */}
        <Card>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
            <SLabel style={{ marginBottom: 0 }}>Gate C — Packets Ready for Review</SLabel>
            <Btn variant="ghost" size="sm" onClick={loadPendingPackets}>
              <RefreshCw size={12} /> Refresh
            </Btn>
          </div>
          {packetsError && (
            <div style={{ fontSize: 12.5, color: A.red, margin: "10px 0" }}>{packetsError}</div>
          )}
          {packets.length === 0 ? (
            <div style={{ fontSize: 13, color: A.muted, padding: "16px 0" }}>
              No packets ready for review.
            </div>
          ) : piecesLoading ? (
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "16px 0" }}>
              <Spinner size={16} /> <span style={{ fontSize: 12.5, color: A.muted }}>Loading pieces…</span>
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={TH}>Packet</th><th style={TH}>Tenant</th><th style={TH}>Week</th>
                    <th style={TH}>Channel</th><th style={TH}>Status</th><th style={TH}>Gate</th>
                    <th style={TH}>Review</th><th style={TH}></th>
                  </tr>
                </thead>
                <tbody>
                  {packets.map((p, packetIdx) => {
                    const pieces = packetPieces[p.packet_id] ?? [];
                    const groupBg = packetIdx % 2 === 1 ? A.bg : "transparent";
                    return (
                      <PacketPieceGroup
                        key={p.packet_id}
                        packet={p}
                        pieces={pieces}
                        groupBg={groupBg}
                        tenantName={tenantNameById[p.tenant_id] ?? `${p.tenant_id.slice(0, 8)}…`}
                        onOpenPacket={() => setReviewTarget({ packetId: p.packet_id, pieceId: null })}
                        onOpenPiece={pieceId => setReviewTarget({ packetId: p.packet_id, pieceId })}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        </>}

        {reviewTarget && (
          <PieceReviewModal
            packetId={reviewTarget.packetId}
            focusPieceId={reviewTarget.pieceId}
            onClose={() => setReviewTarget(null)}
            onPacketAdvanced={handlePacketAdvanced}
          />
        )}
      </div>
    </div>
  );
}
