"use client";
// app/admin/atomize/page.tsx — AA-345: pick tours from the 763-tour
// v_trip_registry floor and trigger N2 decompose (POST /v1/atoms/decompose).
// Scope boundary (AA-345 STEP 0 Phần 3.4): this page owns PRE-decompose
// (select tour -> trigger -> atoms appear); /admin/curation (AA-300) owns
// POST-decompose (curate/star/delete existing atoms). This page never edits
// tour_atoms rows itself — after a run it links straight to /admin/curation
// filtered to that tour.
//
// Patterns reused verbatim from app/admin/curation/page.tsx (this repo's
// established shape for exactly this kind of page): checkbox multi-select
// via Set<string>, AdminSidebar/adminUi tokens, table not cards, a floating
// bulk-action bar.

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Boxes, AlertTriangle, CheckCircle2, XCircle, SkipForward, ExternalLink } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { FilterBar } from "../_components/FilterBar";
import { A, sans, serif, Card, Btn, Badge, LoadingScreen, TH, TD } from "../_components/adminUi";

// AA-305 (api/routers/v1_atoms.py): Bedrock Batch hard-floors at 100
// records/job — below that, decompose runs INLINE and blocks the request
// until every tour is done. This UI must know the boundary in advance so it
// can warn "this will run synchronously, wait here" vs "this queues into
// Batch, come back later" BEFORE the user clicks, not just react to whatever
// the response turns out to be.
const INLINE_SYNC_MAX = 100;

interface TourRow {
  tour_id: string;
  name: string;
  destination: string | null;
  duration_raw: string | null;
  itinerary_length: number;
  itinerary_length_percentile: number;
  quality_score: number | null;
  trip_url: string | null;
  url_alive: boolean | null;
  is_published: boolean;
  atom_count: number;
  has_atoms: boolean;
  is_thin: boolean;
}

interface DecomposeResult {
  job_id: string;
  tour_count: number;
  mode?: "inline"; // absent on the Batch path
  status?: string;
  succeeded?: number;
  failed?: number;
  skipped?: number;
  atoms_created?: number;
  failures?: { tour_id: string; error: string }[];
  skipped_tours?: { tour_id: string; reason: string }[];
  message?: string;
}

export default function AtomizePage() {
  const router = useRouter();

  const [tours, setTours] = useState<TourRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [includeAtomized, setIncludeAtomized] = useState(false);
  const [search, setSearch] = useState("");

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<DecomposeResult | null>(null);
  const [resultError, setResultError] = useState("");
  // The inline response only carries a succeeded COUNT, not which tour_ids
  // succeeded (api/routers/v1_atoms.py's _decompose_inline() return shape) —
  // keep what was submitted so a single-tour run can still deep-link
  // straight to it in /admin/curation instead of the unfiltered list.
  const [submittedTourIds, setSubmittedTourIds] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (includeAtomized) params.set("include_atomized", "true");
      const res = await fetch(`/api/admin/tours-for-atomization?${params}`);
      if (!res.ok) throw new Error(`Failed to load tours (${res.status})`);
      const data = await res.json();
      setTours(data.tours);
      setTotal(data.total);
    } catch (err: any) {
      setError(err.message || "Failed to load tours.");
    } finally {
      setLoading(false);
    }
  }, [includeAtomized]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tours;
    return tours.filter(t =>
      t.name.toLowerCase().includes(q) || (t.destination || "").toLowerCase().includes(q));
  }, [tours, search]);

  // Already-atomized rows are visible (when includeAtomized is on) but not
  // selectable — re-decompose is a safe, idempotent no-op (source_hash match
  // in v1_atoms.py), but letting them into the selection just invites
  // accidental wasted clicks on tours that are done.
  function toggleRow(tourId: string, selectable: boolean) {
    if (!selectable) return;
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(tourId) ? next.delete(tourId) : next.add(tourId);
      return next;
    });
  }

  function toggleSelectAll() {
    const selectableIds = filtered.filter(t => !t.has_atoms).map(t => t.tour_id);
    const allSelected = selectableIds.length > 0 && selectableIds.every(id => selectedIds.has(id));
    setSelectedIds(allSelected ? new Set() : new Set(selectableIds));
  }

  async function runDecompose() {
    const tourIds = [...selectedIds];
    if (tourIds.length === 0) return;
    setRunning(true);
    setResult(null);
    setResultError("");
    setSubmittedTourIds(tourIds);
    try {
      const res = await fetch("/api/atoms/decompose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tour_ids: tourIds }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Decompose failed (${res.status})`);
      }
      const data: DecomposeResult = await res.json();
      setResult(data);
      setSelectedIds(new Set());
      load(); // refresh atom_count/has_atoms for the tours that just ran
    } catch (err: any) {
      setResultError(err.message || "Decompose failed.");
    } finally {
      setRunning(false);
    }
  }

  const selectedCount = selectedIds.size;
  const willRunInline = selectedCount > 0 && selectedCount < INLINE_SYNC_MAX;
  const willRunBatch = selectedCount >= INLINE_SYNC_MAX;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "28px 32px", maxWidth: 1400, margin: "0 auto", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <Boxes size={18} color={A.gold} />
          <h1 style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: A.ink, margin: 0 }}>
            Atom hoá (N2 decompose)
          </h1>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: A.muted }}>{total} tour</span>
        </div>
        <p style={{ fontSize: 13, color: A.muted, marginTop: 4, marginBottom: 16 }}>
          Chọn tour rồi bấm "Atom hoá". Không có ngưỡng độ dài chặn trước (AA-345 STEP 0 — thử
          nghiệm 20 tour ngẫu nhiên không thấy chất lượng kém ở tour ngắn) — tour mỏng chỉ được
          gắn badge <b>THIN</b> sau khi atom hoá xong, dựa trên atom_count thật.
        </p>

        <FilterBar
          search={search}
          onSearch={setSearch}
          placeholder="Tìm theo tên hoặc điểm đến…"
          extra={
            <Btn variant={includeAtomized ? "primary" : "secondary"} size="sm" onClick={() => setIncludeAtomized(v => !v)}>
              {includeAtomized ? "Đang hiện cả tour đã atom hoá" : "Chỉ hiện tour chưa atom hoá"}
            </Btn>
          }
        />

        {error && (
          <div style={{ fontSize: 12, padding: "8px 12px", borderRadius: 6, marginBottom: 14, background: A.redSoft, color: A.red }}>
            {error}
          </div>
        )}

        {/* ── Decompose result banner ──────────────────────────────────────── */}
        {resultError && (
          <div style={{ fontSize: 12, padding: "10px 14px", borderRadius: 8, marginBottom: 14, background: A.redSoft, color: A.red }}>
            {resultError}
          </div>
        )}
        {result && (
          <Card style={{ marginBottom: 16 }}>
            {result.mode === "inline" ? (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <CheckCircle2 size={16} color={A.green} />
                  <span style={{ fontFamily: serif, fontSize: 15, color: A.ink }}>
                    Chạy đồng bộ xong — {result.tour_count} tour
                  </span>
                </div>
                <div style={{ display: "flex", gap: 16, fontSize: 13, color: A.body, marginBottom: 8 }}>
                  <span><CheckCircle2 size={13} color={A.green} style={{ verticalAlign: -2 }} /> {result.succeeded} thành công</span>
                  {!!result.skipped && <span><SkipForward size={13} color={A.muted2} style={{ verticalAlign: -2 }} /> {result.skipped} bỏ qua (nguồn không đổi)</span>}
                  {!!result.failed && <span><XCircle size={13} color={A.red} style={{ verticalAlign: -2 }} /> {result.failed} lỗi</span>}
                  <span>{result.atoms_created} atom mới</span>
                </div>
                {!!result.failures?.length && (
                  <div style={{ fontSize: 12, color: A.red, marginBottom: 8 }}>
                    {result.failures.map(f => <div key={f.tour_id}>{f.tour_id}: {f.error}</div>)}
                  </div>
                )}
                <Btn
                  size="sm" variant="secondary"
                  onClick={() => router.push(
                    submittedTourIds.length === 1
                      ? `/admin/curation?tour_id=${submittedTourIds[0]}`
                      : "/admin/curation",
                  )}
                >
                  <ExternalLink size={12} /> Xem trong Atom Curation
                </Btn>
              </>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <AlertTriangle size={16} color={A.amber} />
                <span style={{ fontSize: 13, color: A.body }}>
                  Đã gửi vào hàng đợi Bedrock Batch ({result.tour_count} tour, job {result.job_id}) —
                  đây là xử lý bất đồng bộ, có thể mất hàng giờ. Atom sẽ xuất hiện trong Atom Curation
                  sau khi Batch chạy xong, KHÔNG hiện ngay ở đây.
                </span>
              </div>
            )}
          </Card>
        )}

        {loading ? (
          <LoadingScreen msg="Loading tours…" />
        ) : filtered.length === 0 ? (
          <Card><div style={{ fontSize: 13, color: A.muted, textAlign: "center", padding: 20 }}>
            Không có tour nào khớp bộ lọc hiện tại.
          </div></Card>
        ) : (
          <div style={{
            flex: 1, minHeight: 0, overflowY: "auto", border: `1px solid ${A.line}`, borderRadius: 10, background: "#fff",
            paddingBottom: selectedCount > 0 ? 92 : 0,
          }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ ...TH, width: 30 }}>
                    <input type="checkbox" onChange={toggleSelectAll} style={{ accentColor: A.gold }} />
                  </th>
                  <th style={TH}>Tour</th>
                  <th style={TH}>Điểm đến</th>
                  <th style={TH}>Thời lượng</th>
                  <th style={TH}>Độ dài nguồn</th>
                  <th style={TH}>Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t, i) => {
                  const selectable = !t.has_atoms;
                  const isSelected = selectedIds.has(t.tour_id);
                  return (
                    <tr key={t.tour_id} style={{
                      background: isSelected ? `${A.gold}10` : i % 2 === 0 ? "#fff" : A.bg,
                      opacity: selectable ? 1 : 0.6,
                    }}>
                      <td style={TD}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          disabled={!selectable}
                          onChange={() => toggleRow(t.tour_id, selectable)}
                          style={{ accentColor: A.gold, cursor: selectable ? "pointer" : "not-allowed" }}
                        />
                      </td>
                      <td style={TD}>
                        <div style={{ fontWeight: 600, color: A.ink }}>{t.name}</div>
                      </td>
                      <td style={TD}>{t.destination || "—"}</td>
                      <td style={TD}>{t.duration_raw || "—"}</td>
                      <td style={TD}>
                        {t.itinerary_length.toLocaleString()} ký tự
                        <span style={{ color: A.muted2, marginLeft: 4 }}>(p{t.itinerary_length_percentile})</span>
                      </td>
                      <td style={TD}>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {t.is_published && <Badge color="green">đã publish</Badge>}
                          {t.has_atoms ? (
                            <Badge color="blue">{t.atom_count} atom</Badge>
                          ) : (
                            <Badge color="gray">chưa atom hoá</Badge>
                          )}
                          {t.is_thin && <Badge color="red">THIN</Badge>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Floating action bar ──────────────────────────────────────────── */}
        {selectedCount > 0 && (
          <div style={{
            position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
            background: A.ink, color: "#fff", borderRadius: 10, padding: "10px 16px",
            display: "flex", alignItems: "center", gap: 12, boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
            zIndex: 200, fontFamily: sans, maxWidth: 640,
          }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedCount} tour đã chọn</span>
            <span style={{ fontSize: 11, color: "#C9CFD8" }}>
              {willRunInline && "Chạy đồng bộ — chờ ngay trong request"}
              {willRunBatch && "≥100 tour — chạy qua Bedrock Batch, bất đồng bộ (hàng giờ)"}
            </span>
            <Btn size="sm" variant="primary" disabled={running} onClick={runDecompose}>
              {running ? "Đang chạy…" : "Atom hoá"}
            </Btn>
            <button onClick={() => setSelectedIds(new Set())}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#C9CFD8", fontSize: 12 }}>
              Bỏ chọn
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
