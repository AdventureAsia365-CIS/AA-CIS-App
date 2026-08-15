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

import { useState, useEffect, useCallback, useRef } from "react";
import { PlayCircle, RefreshCw } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, sans, Card, SLabel, Btn, Badge, Spinner, TH, TD } from "../_components/adminUi";

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
  week: number;
  status: string;
  publish_mode: string;
  piece_count: number;
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

function getCookieUser(): string {
  if (typeof document === "undefined") return "admin";
  const n = document.cookie.split(";").find(c => c.trim().startsWith("cis_user="))?.split("=")[1];
  return n ? decodeURIComponent(n) : "admin";
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
  const [packetsError, setPacketsError] = useState("");
  const [approvingId, setApprovingId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/admin/tenants")
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(d => setTenants((d.tenants ?? []).filter((t: Tenant) => t.is_active)))
      .catch(() => setTriggerError("Failed to load tenants."));
  }, []);

  const loadPendingPackets = useCallback(() => {
    fetch("/api/admin/produce/packets")
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then((d: PendingPacket[]) => { setPackets(d); setPacketsError(""); })
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

  async function handleApprove(packetId: string) {
    setApprovingId(packetId);
    setPacketsError("");
    try {
      const res = await fetch(`/api/admin/produce/packets/${packetId}/gate-c/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "approve_to_publish", actor: getCookieUser() }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setPacketsError(data.detail || "Approval failed.");
        return;
      }
      loadPendingPackets();
    } catch {
      setPacketsError("Could not reach the server. Please try again.");
    } finally {
      setApprovingId(null);
    }
  }

  const isRunning = run !== null && (run.status === "producing" || run.status === "allocated");
  const passedCount = run?.pieces.filter(p => p.status === "passed").length ?? 0;
  const heldCount = run?.pieces.filter(p => p.status === "held").length ?? 0;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      <div style={{ flex: 1, padding: "28px 36px", maxWidth: 1100 }}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink, margin: 0 }}>
            Produce &amp; Deliver (N7 / N8)
          </h1>
          <p style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
            Manually trigger a weekly production run (N7) and review packets ready for delivery (N8 Gate C).
          </p>
        </div>

        {/* Trigger form */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>Trigger a Production Run</SLabel>
          <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <label style={labelStyle}>Tenant</label>
              <select value={tenantId} onChange={e => setTenantId(e.target.value)} style={inputStyle}>
                <option value="">Select a tenant…</option>
                {tenants.map(t => (
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
            Only tenants with an approved Quarter Plan (Gate B) can be produced for. If a tenant
            has no approved plan yet, the run will fail with a clear message below — approve one
            first via Quarter Plan (Gate B). &ldquo;Week&rdquo; is the 1-4 week-of-month slot
            numbering used by the production schedule, not an ISO week — Month + Week together
            identify one specific production slot (AA-410).
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

        {/* Gate C section */}
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
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={TH}>Packet</th><th style={TH}>Tenant</th><th style={TH}>Week</th>
                    <th style={TH}>Pieces</th><th style={TH}>Publish Mode</th><th style={TH}></th>
                  </tr>
                </thead>
                <tbody>
                  {packets.map(p => (
                    <tr key={p.packet_id}>
                      <td style={TD}>{p.packet_id.slice(0, 8)}…</td>
                      <td style={TD}>{p.tenant_id.slice(0, 8)}…</td>
                      <td style={TD}>{p.year} / W{p.week}</td>
                      <td style={TD}>{p.piece_count}</td>
                      <td style={TD}>{p.publish_mode}</td>
                      <td style={TD}>
                        <Btn size="sm" variant="primary" disabled={approvingId === p.packet_id}
                          onClick={() => handleApprove(p.packet_id)}>
                          {approvingId === p.packet_id ? "Approving…" : "Approve"}
                        </Btn>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
