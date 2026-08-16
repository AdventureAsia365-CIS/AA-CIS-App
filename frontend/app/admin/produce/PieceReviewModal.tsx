"use client";
// app/admin/produce/PieceReviewModal.tsx — AA-412: per-piece Gate C content review.
//
// Reads GET /api/admin/produce/packets/{packetId}/pieces (real body_tagged/gate_ledger/
// brand_seo_audit from acp_deliver.pieces, NOT silver_aa_internal.review_queue — see AA-412's
// own "Xác nhận" section on why those are two different data sources). Each piece gets its own
// Approve/Reject action (POST /api/admin/produce/pieces/{id}/review) — this does NOT itself move
// the packet's publish_mode ramp. The packet-level "Advance" button at the bottom only becomes
// enabled once every piece is individually approved; the backend enforces the same rule
// independently (POST .../gate-c/approve 409s otherwise) so this is UX convenience, not the only
// guard.
//
// AA-412 follow-up (readability): full-screen dialog instead of a small centered modal — a
// packet's 4 pieces × (content + 9-gate ledger + brand/SEO audit JSON) made the old fixed-width
// modal a very long scroll with the Approve/Reject buttons drifting out of view. Layout is now a
// 3-row flexbox: modal header and footer are flex items that never scroll (no manual `position:
// sticky` needed for them — only the middle row scrolls), and each PieceCard's own header (badges
// + Approve/Reject) is `position: sticky; top: 0` *within that scrolling middle row*, so it stays
// pinned while its piece's content scrolls underneath, then hands off to the next piece's sticky
// header. No content was removed or collapsed by default to make this fit — see PieceCard.

import { useState, useEffect, useCallback } from "react";
import { X, Check, XCircle, ChevronRight } from "lucide-react";
import { A, sans, mono, Btn, Badge, Spinner, TH, TD } from "../_components/adminUi";

interface GateResult {
  gate: string;
  passed: boolean;
  violations: string[];
}

interface PieceDetail {
  piece_id: string;
  channel: string;
  status: string; // gate outcome: in_progress | passed | held
  body_tagged: string;
  gate_ledger: GateResult[];
  brand_seo_audit: Record<string, unknown> | null;
  held_reason: string | null;
  repair_count: number;
  review_status: string; // pending | approved | rejected — human decision, independent of `status`
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
}

function getCookieUser(): string {
  if (typeof document === "undefined") return "admin";
  const n = document.cookie.split(";").find(c => c.trim().startsWith("cis_user="))?.split("=")[1];
  return n ? decodeURIComponent(n) : "admin";
}

function ReviewStatusBadge({ status }: { status: string }) {
  const map: Record<string, { color: "green" | "red" | "gray"; label: string }> = {
    approved: { color: "green", label: "Approved" },
    rejected: { color: "red", label: "Rejected" },
    pending: { color: "gray", label: "Pending Review" },
  };
  const s = map[status] ?? { color: "gray" as const, label: status };
  return <Badge color={s.color}>{s.label}</Badge>;
}

function GateLedgerTable({ ledger }: { ledger: GateResult[] }) {
  if (ledger.length === 0) {
    return <div style={{ fontSize: 12, color: A.muted }}>No gate results recorded.</div>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr><th style={TH}>Gate</th><th style={TH}>Result</th><th style={TH}>Violations</th></tr>
        </thead>
        <tbody>
          {ledger.map(g => (
            <tr key={g.gate}>
              <td style={{ ...TD, fontFamily: mono, fontSize: 12 }}>{g.gate}</td>
              <td style={TD}>{g.passed ? <Badge color="green">Pass</Badge> : <Badge color="red">Fail</Badge>}</td>
              <td style={{ ...TD, fontSize: 11.5, color: A.muted }}>
                {g.violations.length > 0 ? g.violations.join("; ") : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PieceCard({ piece, onReview }: {
  piece: PieceDetail;
  onReview: (pieceId: string, decision: "approve" | "reject", note?: string) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [showRejectInput, setShowRejectInput] = useState(false);

  async function handleApprove() {
    setBusy("approve");
    try { await onReview(piece.piece_id, "approve"); } finally { setBusy(null); }
  }

  async function handleReject() {
    setBusy("reject");
    try { await onReview(piece.piece_id, "reject", rejectNote || undefined); } finally {
      setBusy(null);
      setShowRejectInput(false);
    }
  }

  return (
    <div style={{
      border: `1px solid ${A.line}`, borderRadius: 12, marginBottom: 16,
      background: A.card, overflow: "hidden",
    }}>
      {/* Sticky per-piece header — stays pinned to the top of the scrolling content area while
          this piece's body/gate-ledger/audit scroll underneath, so Approve/Reject is always
          reachable without scrolling back up. Next piece's own sticky header takes over the
          instant it reaches the top (native stacking-context behavior, no JS needed). */}
      <div style={{
        position: "sticky", top: 0, zIndex: 2, background: A.card,
        borderBottom: `1px solid ${A.line}`, padding: "12px 18px",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button onClick={() => setExpanded(e => !e)} style={{
            background: "none", border: "none", cursor: "pointer", color: A.muted,
            display: "flex", alignItems: "center",
          }}>
            <ChevronRight size={16} style={{ transform: expanded ? "rotate(90deg)" : "none", transition: "transform .15s" }} />
          </button>
          <Badge color="blue">{piece.channel}</Badge>
          {piece.status === "passed" ? <Badge color="green">Gate: Passed</Badge> : <Badge color="amber">Gate: Held</Badge>}
          <ReviewStatusBadge status={piece.review_status} />
          <span style={{ fontSize: 11.5, color: A.muted2, fontFamily: mono }}>
            {piece.piece_id.split(":").slice(1).join(":")}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn size="sm" variant="primary" disabled={busy !== null || piece.review_status === "approved"}
            onClick={handleApprove}>
            <Check size={13} /> {busy === "approve" ? "Approving…" : "Approve"}
          </Btn>
          <Btn size="sm" variant="danger" disabled={busy !== null || piece.review_status === "rejected"}
            onClick={() => setShowRejectInput(v => !v)}>
            <XCircle size={13} /> Reject
          </Btn>
        </div>
      </div>

      <div style={{ padding: "14px 18px 18px" }}>
        {showRejectInput && (
          <div style={{ marginBottom: 10, display: "flex", gap: 8, alignItems: "center" }}>
            <input
              value={rejectNote} onChange={e => setRejectNote(e.target.value)}
              placeholder="Optional: why is this piece rejected?"
              style={{
                flex: 1, padding: "7px 10px", borderRadius: 7, border: `1px solid ${A.line}`,
                fontSize: 12.5, fontFamily: sans,
              }}
            />
            <Btn size="sm" variant="danger" disabled={busy !== null} onClick={handleReject}>
              {busy === "reject" ? "Rejecting…" : "Confirm Reject"}
            </Btn>
          </div>
        )}

        {piece.review_status !== "pending" && piece.reviewed_by && (
          <div style={{ marginBottom: 8, fontSize: 11.5, color: A.muted }}>
            {piece.review_status === "approved" ? "Approved" : "Rejected"} by {piece.reviewed_by}
            {piece.reviewed_at && ` — ${new Date(piece.reviewed_at).toLocaleString()}`}
            {piece.review_note && ` — "${piece.review_note}"`}
          </div>
        )}

        {piece.held_reason && (
          <div style={{
            marginBottom: 10, fontSize: 12, color: A.red, background: A.redTint,
            padding: "8px 12px", borderRadius: 8,
          }}>
            Held: {piece.held_reason} (repaired {piece.repair_count}×)
          </div>
        )}

        {expanded && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              Content
            </div>
            <div style={{
              background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8, padding: 14,
              whiteSpace: "pre-wrap", fontSize: 12.5,
              lineHeight: 1.6, color: A.body, marginBottom: 16,
            }}>
              {piece.body_tagged || "(empty)"}
            </div>

            <div style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              Gate Ledger
            </div>
            <GateLedgerTable ledger={piece.gate_ledger} />

            {piece.brand_seo_audit && (
              <>
                <div style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase", letterSpacing: "0.08em", margin: "16px 0 6px" }}>
                  Brand / SEO Audit
                </div>
                <pre style={{
                  background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8, padding: 12,
                  fontSize: 11.5, fontFamily: mono, overflowX: "auto", margin: 0,
                }}>
                  {JSON.stringify(piece.brand_seo_audit, null, 2)}
                </pre>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function PieceReviewModal({ packetId, onClose, onPacketAdvanced }: {
  packetId: string;
  onClose: () => void;
  onPacketAdvanced: () => void;
}) {
  const [pieces, setPieces] = useState<PieceDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [advancing, setAdvancing] = useState(false);
  const [advanceError, setAdvanceError] = useState("");

  const loadPieces = useCallback(() => {
    // No synchronous setLoading(true) here — called from the mount effect below too, and
    // react-hooks/set-state-in-effect flags setState invoked synchronously from an effect.
    // `loading` already starts true for the initial mount; handleReview() below sets it back to
    // true itself (inside an event-handler-triggered async function, not an effect) before
    // calling this again.
    fetch(`/api/admin/produce/packets/${packetId}/pieces`)
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then((d: PieceDetail[]) => { setPieces(d); setError(""); })
      .catch(() => setError("Failed to load pieces for this packet."))
      .finally(() => setLoading(false));
  }, [packetId]);

  useEffect(() => { loadPieces(); }, [loadPieces]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function handleReview(pieceId: string, decision: "approve" | "reject", note?: string) {
    const res = await fetch(`/api/admin/produce/pieces/${pieceId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, actor: getCookieUser(), note }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || "Review action failed.");
      return;
    }
    loadPieces();
  }

  async function handleAdvance() {
    setAdvancing(true);
    setAdvanceError("");
    try {
      const res = await fetch(`/api/admin/produce/packets/${packetId}/gate-c/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "approve_to_publish", actor: getCookieUser() }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setAdvanceError(data.detail || "Could not advance this packet.");
        return;
      }
      onPacketAdvanced();
    } catch {
      setAdvanceError("Could not reach the server. Please try again.");
    } finally {
      setAdvancing(false);
    }
  }

  const approvedCount = pieces.filter(p => p.review_status === "approved").length;
  const allApproved = pieces.length > 0 && approvedCount === pieces.length;

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(31,41,51,0.55)", zIndex: 100,
      display: "flex", padding: 16,
    }}>
      {/* Full-screen dialog: 3-row flex column. Header/footer are ordinary flex items (never
          scroll); only the middle row scrolls, which is what makes header/footer effectively
          "sticky" without fighting position:sticky across the whole page. */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column", minHeight: 0,
        background: A.bg, border: `1px solid ${A.line}`, borderRadius: 12, overflow: "hidden",
      }}>
        <div style={{
          flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "space-between",
          background: A.card, padding: "16px 24px", borderBottom: `1px solid ${A.line}`,
        }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: A.ink }}>Review Packet Pieces</div>
            <div style={{ fontSize: 11.5, color: A.muted, fontFamily: mono, marginTop: 2 }}>{packetId}</div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted }}>
            <X size={20} />
          </button>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 20 }}>
          {loading && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: 20 }}>
              <Spinner size={18} /> <span style={{ fontSize: 13, color: A.muted }}>Loading pieces…</span>
            </div>
          )}
          {error && (
            <div style={{ fontSize: 12.5, color: A.red, background: A.redTint, padding: "8px 12px", borderRadius: 8, marginBottom: 14 }}>
              {error}
            </div>
          )}
          {!loading && pieces.map(p => (
            <PieceCard key={p.piece_id} piece={p} onReview={handleReview} />
          ))}
          {!loading && pieces.length === 0 && !error && (
            <div style={{ fontSize: 13, color: A.muted, padding: "16px 0" }}>No pieces in this packet.</div>
          )}
        </div>

        {pieces.length > 0 && (
          <div style={{
            flexShrink: 0, background: A.card, borderTop: `1px solid ${A.line}`,
            padding: "14px 24px",
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
              <span style={{ fontSize: 12.5, color: A.body }}>
                {approvedCount} / {pieces.length} pieces individually approved
              </span>
              <Btn variant="primary" disabled={!allApproved || advancing} onClick={handleAdvance}>
                {advancing ? "Advancing…" : "Advance Packet to Approve-to-Publish"}
              </Btn>
            </div>
            {advanceError && (
              <div style={{ fontSize: 12.5, color: A.red, background: A.redTint, padding: "8px 12px", borderRadius: 8, marginTop: 10 }}>
                {advanceError}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
