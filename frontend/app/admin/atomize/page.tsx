"use client";
// app/admin/atomize/page.tsx — AA-345: pick tours from the 763-tour
// v_trip_registry floor and trigger N2 decompose (POST /admin/atoms/decompose).
// Scope boundary (AA-345 STEP 0 Phần 3.4): this page owns PRE-decompose
// (select tour -> trigger -> atoms appear); /admin/curation (AA-300) owns
// POST-decompose (curate/star/delete existing atoms). This page never edits
// tour_atoms rows itself — after a run it links straight to /admin/curation
// filtered to the tours just processed.
//
// Patterns reused verbatim from app/admin/curation/page.tsx and
// app/admin/s1-rewrite/page.tsx (this repo's established shapes): checkbox
// multi-select via Set<string>, AdminSidebar/adminUi tokens, table not
// cards, a floating bulk-action bar, FilterBar's dropdown-filter convention
// (Status/Destination/Sort — same shape as curation's Distinctiveness/Sort),
// the sticky-header-over-scrollable-main layout, and the "Load more (X / Y)"
// pagination pattern (LOAD_LIMIT batches, same as curation's).
//
// AA-345 fixes round 1 (401 silent-fail, atomized-only filter, pagination,
// sticky header, i18n) — see git history / AA-345-fixes.md for that round.
//
// AA-345 round 2 (this file, after live prod verify on round 1 found a new
// regression + 4 more asks):
// - Bug 5 (regression): status="" ("All tours") never reached the backend —
//   `if (statusFilter) params.set(...)` treated the falsy empty string as
//   "send nothing", so the request silently fell back to the backend's own
//   default ("pending"). Always send `status` explicitly now.
// - Việc 1 (destination blank cells): investigated, not a code bug — see
//   docs/implementation-notes/AA-345-round2.md for the real live NULL rate.
// - Việc 2: destination + sort now real filters (dropdowns, not free text).
// - Việc 3: dropped the inline "(pX)" percentile from the Source Length
//   column (internal-only number, not something content team acts on) —
//   kept as a hover tooltip instead of deleting it outright.
// - Việc 4: "Atomized on <date>" per row + tour_ids (plural) passed to the
//   Curation deep link so a multi-tour run doesn't get lost in a long list.

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";
import { Boxes, AlertTriangle, CheckCircle2, XCircle, SkipForward, ExternalLink } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { FilterBar } from "../_components/FilterBar";
import { A, sans, serif, Card, Btn, Badge, LoadingScreen, TH, TD } from "../_components/adminUi";

const LOAD_LIMIT = 150;

// AA-305 (api/routers/v1_atoms.py): Bedrock Batch hard-floors at 100
// records/job — below that, decompose runs INLINE and blocks the request
// until every tour is done. This UI must know the boundary in advance so it
// can warn "this will run synchronously, wait here" vs "this queues into
// Batch, come back later" BEFORE the user clicks, not just react to whatever
// the response turns out to be.
const INLINE_SYNC_MAX = 100;

type StatusFilter = "pending" | "atomized" | "";
type SortKey = "" | "length_asc" | "length_desc" | "duration_asc" | "duration_desc" | "atomized_desc" | "atomized_asc";

const STATUS_OPTIONS: { label: string; value: StatusFilter }[] = [
  { label: "Not yet atomized", value: "pending" },
  { label: "Already atomized", value: "atomized" },
];

// Duration is free text in the source data ("12days 11nights", "DAY TRIP",
// "40 MIN.", mixed units, embedded newlines — verified live) with no
// reliable way to parse a comparable day count, so its sort is plain
// alphabetical on the raw string (documented limitation, pre-approved
// rather than building a parser — see backend's _SORT_COLUMNS comment).
const BASE_SORT_OPTIONS: { label: string; value: SortKey }[] = [
  { label: "Source length (shortest first)", value: "length_asc" },
  { label: "Source length (longest first)", value: "length_desc" },
  { label: "Duration (A–Z, alphabetical)", value: "duration_asc" },
  { label: "Duration (Z–A, alphabetical)", value: "duration_desc" },
];
// AA-345 round 3, Việc 1 — symmetric with curation's "Newest first" (same
// MAX(tour_atoms.created_at) field, added PR #133). Every status=pending
// row has atomized_at=NULL (no atoms exist yet), so these two options
// would be a silent no-op there — hidden from the dropdown in that filter
// state instead of presenting a choice that visibly does nothing.
const ATOMIZED_SORT_OPTIONS: { label: string; value: SortKey }[] = [
  { label: "Newest atomized first", value: "atomized_desc" },
  { label: "Oldest atomized first", value: "atomized_asc" },
];

// AA-345 round 3: found live — with no explicit timeZone, this implicitly
// used whichever zone the rendering runtime happened to be in (the viewer's
// browser, or this "use client" page's server-side render pass — either is
// possible and not reliably one or the other), which could land on the
// wrong calendar day for a timestamp close to midnight VN time (e.g. a
// tour_atoms.created_at of 20:00 UTC is already 03:00 the NEXT day in VN).
// Checked the rest of the app first (61 toLocaleDateString/toLocaleString
// call sites, zero specify timeZone) — there is no existing convention to
// match, so Asia/Ho_Chi_Minh (UTC+7, the team's timezone) is hardcoded here
// as a local decision for these two pages, not a repo-wide fix.
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric", timeZone: "Asia/Ho_Chi_Minh",
  });
}

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
  atomized_at: string | null;
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

// Backend error bodies vary by layer: FastAPI uses {"detail": ...}, this
// repo's own BFF auth helper uses {"error": ...} (lib/auth-server.ts), and
// AWS API Gateway's own denials use {"message": ...} (the round-1 Bug 1
// shape — a request that never reached FastAPI at all). Checking all three
// means a real error message surfaces regardless of which layer produced it.
async function extractErrorMessage(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}) as Record<string, unknown>);
  const msg = (body as any).detail || (body as any).message || (body as any).error;
  return typeof msg === "string" && msg ? msg : `${fallback} (${res.status})`;
}

export default function AtomizePage() {
  const router = useRouter();

  const [tours, setTours] = useState<TourRow[]>([]);
  const [total, setTotal] = useState(0);
  const [distinctDestinations, setDistinctDestinations] = useState<string[]>([]);
  // Ref, not state — mirrors curation/page.tsx's own comment: loadTours()
  // below is memoized on filter values only, so a stale-closure bug would
  // silently re-read whatever `offset` was captured at that memoization
  // (typically 0) on every "Load more" click. A ref sidesteps the closure.
  const offsetRef = useRef(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [destinationFilter, setDestinationFilter] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("");
  const [search, setSearch] = useState("");

  const sortOptions = useMemo(
    () => statusFilter === "pending" ? BASE_SORT_OPTIONS : [...BASE_SORT_OPTIONS, ...ATOMIZED_SORT_OPTIONS],
    [statusFilter],
  );
  // Switching to "Not yet atomized" while an atomized_* sort is active would
  // otherwise leave it silently selected but hidden from the dropdown (every
  // row there has atomized_at=NULL, so it'd be a no-op the user can't even
  // see to undo) — fall back to the default instead.
  function handleStatusChange(v: StatusFilter) {
    setStatusFilter(v);
    if (v === "pending" && (sortBy === "atomized_desc" || sortBy === "atomized_asc")) setSortBy("");
  }

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<DecomposeResult | null>(null);
  const [resultError, setResultError] = useState("");
  // The inline response only carries a succeeded COUNT, not which tour_ids
  // succeeded (api/routers/v1_atoms.py's _decompose_inline() return shape) —
  // keep what was submitted so the deep link can still point at exactly the
  // tours from this run instead of the unfiltered list.
  const [submittedTourIds, setSubmittedTourIds] = useState<string[]>([]);

  const loadTours = useCallback(async (reset: boolean) => {
    const nextOffset = reset ? 0 : offsetRef.current;
    if (reset) setLoading(true); else setLoadingMore(true);
    setError("");
    try {
      // Bug 5 (AA-345 round 2 regression): statusFilter="" (the "All tours"
      // option) is a real, meaningful value here — unlike e.g. curation's
      // distinctiveness filter, this endpoint's default when the param is
      // OMITTED is "pending", not "all" (see GET /admin/tours-for-atomization's
      // docstring). A prior `if (statusFilter) params.set(...)` treated the
      // falsy empty string as "send nothing", so "All tours" silently fell
      // back to "pending" — status is now always sent explicitly.
      const params = new URLSearchParams({ limit: String(LOAD_LIMIT), offset: String(nextOffset), status: statusFilter });
      if (destinationFilter) params.set("destination", destinationFilter);
      if (sortBy) params.set("sort", sortBy);
      const res = await fetch(`/api/admin/tours-for-atomization?${params}`);
      if (!res.ok) throw new Error(await extractErrorMessage(res, "Failed to load tours"));
      const data = await res.json();
      setTours(prev => (reset ? data.tours : [...prev, ...data.tours]));
      setTotal(data.total);
      setDistinctDestinations(data.distinct_destinations || []);
      offsetRef.current = nextOffset + data.tours.length;
    } catch (err: any) {
      setError(err.message || "Failed to load tours.");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [statusFilter, destinationFilter, sortBy]);

  useEffect(() => { loadTours(true); }, [loadTours]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tours;
    return tours.filter(t =>
      t.name.toLowerCase().includes(q) || (t.destination || "").toLowerCase().includes(q));
  }, [tours, search]);

  // Already-atomized rows are visible (under the "Already atomized" or "All
  // tours" filter) but not selectable — re-decompose is a safe, idempotent
  // no-op (source_hash match in v1_atoms.py), but letting them into the
  // selection just invites accidental wasted clicks on tours that are done.
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
      const res = await fetch("/api/admin/atoms/decompose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tour_ids: tourIds }),
      });
      if (!res.ok) throw new Error(await extractErrorMessage(res, "Atomization failed"));
      const data: DecomposeResult = await res.json();
      setResult(data);
      setSelectedIds(new Set());
      loadTours(true); // refresh atom_count/has_atoms/atomized_at for the tours that just ran
    } catch (err: any) {
      setResultError(err.message || "Atomization failed. Please try again.");
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
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        {/* ── Sticky header: title + filters ───────────────────────────────── */}
        <div style={{
          position: "sticky", top: 0, zIndex: 20,
          background: "#fff", borderBottom: `1px solid ${A.line}`,
          padding: "16px 32px 4px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <Boxes size={18} color={A.gold} />
            <h1 style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: A.ink, margin: 0 }}>
              Atomize (N2 Decompose)
            </h1>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 12, color: A.muted }}>
              Showing {filtered.length} of {total} tours
            </span>
          </div>
          <p style={{ fontSize: 13, color: A.muted, marginTop: 4, marginBottom: 8, maxWidth: 900 }}>
            Select tours, then click "Atomize". No length threshold blocks a run up front (AA-345
            STEP 0 — a 20-tour random sample found no quality drop on short tours) — thin tours
            only get a <b>THIN</b> badge after atomizing, based on the real atom count.
          </p>

          <FilterBar
            search={search}
            onSearch={setSearch}
            placeholder="Search by name or destination…"
            filters={[
              {
                label: "Status", value: statusFilter, current: statusFilter,
                allLabel: "All tours",
                options: STATUS_OPTIONS,
                onChange: v => handleStatusChange(v as StatusFilter),
              },
              {
                label: "Destination", value: destinationFilter, current: destinationFilter,
                allLabel: "All destinations",
                options: distinctDestinations.map(d => ({ label: d, value: d })),
                onChange: setDestinationFilter,
              },
              {
                label: "Sort", value: sortBy, current: sortBy,
                allLabel: "Shortest source first (default)",
                options: sortOptions,
                onChange: v => setSortBy(v as SortKey),
              },
            ]}
          />
        </div>

        {/* ── Scrollable content ───────────────────────────────────────────── */}
        <main style={{ flex: 1, padding: "16px 32px 56px", overflowY: "auto" }}>
          {error && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8, fontSize: 13, padding: "10px 14px",
              borderRadius: 8, marginBottom: 14, background: A.redSoft, color: A.red,
            }}>
              <AlertTriangle size={15} />
              <span>{error}</span>
            </div>
          )}

          {/* ── Decompose result banner ────────────────────────────────────── */}
          {resultError && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8, fontSize: 13, padding: "10px 14px",
              borderRadius: 8, marginBottom: 14, background: A.redSoft, color: A.red,
            }}>
              <AlertTriangle size={15} />
              <div>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>Atomization failed to start</div>
                <div>{resultError}</div>
              </div>
            </div>
          )}
          {result && (
            <Card style={{ marginBottom: 16 }}>
              {result.mode === "inline" ? (
                <>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <CheckCircle2 size={16} color={A.green} />
                    <span style={{ fontFamily: serif, fontSize: 15, color: A.ink }}>
                      Ran synchronously — {result.tour_count} tour{result.tour_count === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 16, fontSize: 13, color: A.body, marginBottom: 8, flexWrap: "wrap" }}>
                    <span><CheckCircle2 size={13} color={A.green} style={{ verticalAlign: -2 }} /> {result.succeeded} succeeded</span>
                    {!!result.skipped && <span><SkipForward size={13} color={A.muted2} style={{ verticalAlign: -2 }} /> {result.skipped} skipped (source unchanged)</span>}
                    {!!result.failed && <span><XCircle size={13} color={A.red} style={{ verticalAlign: -2 }} /> {result.failed} failed</span>}
                    <span>{result.atoms_created} new atoms</span>
                  </div>
                  {!!result.failures?.length && (
                    <div style={{ fontSize: 12, color: A.red, marginBottom: 8 }}>
                      {result.failures.map(f => <div key={f.tour_id}>{f.tour_id}: {f.error}</div>)}
                    </div>
                  )}
                  <Btn
                    size="sm" variant="secondary"
                    onClick={() => router.push(`/admin/curation?tour_ids=${submittedTourIds.join(",")}`)}
                  >
                    <ExternalLink size={12} /> View in Atom Curation
                  </Btn>
                </>
              ) : (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <AlertTriangle size={16} color={A.amber} />
                  <span style={{ fontSize: 13, color: A.body }}>
                    Submitted to the Bedrock Batch queue ({result.tour_count} tours, job {result.job_id}) —
                    this runs asynchronously and can take hours. Atoms will appear in Atom Curation once
                    the Batch job finishes, NOT immediately here.
                  </span>
                </div>
              )}
            </Card>
          )}

          {loading ? (
            <LoadingScreen msg="Loading tours…" />
          ) : filtered.length === 0 ? (
            <Card><div style={{ fontSize: 13, color: A.muted, textAlign: "center", padding: 20 }}>
              No tours match the current filters.
            </div></Card>
          ) : (
            <div style={{
              border: `1px solid ${A.line}`, borderRadius: 10, background: "#fff",
              paddingBottom: selectedCount > 0 ? 92 : 0,
            }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={{ ...TH, width: 30 }}>
                      <input type="checkbox" onChange={toggleSelectAll} style={{ accentColor: A.gold }} />
                    </th>
                    <th style={TH}>Tour</th>
                    <th style={TH}>Destination</th>
                    <th style={TH}>Duration</th>
                    <th style={TH}>Source Length</th>
                    <th style={TH}>Status</th>
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
                        <td style={TD} title={`Percentile within all 763 tours: p${t.itinerary_length_percentile}`}>
                          {t.itinerary_length.toLocaleString()} chars
                        </td>
                        <td style={TD}>
                          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                              {t.is_published && <Badge color="green">published</Badge>}
                              {t.has_atoms ? (
                                <Badge color="blue">{t.atom_count} atoms</Badge>
                              ) : (
                                <Badge color="gray">not atomized</Badge>
                              )}
                              {t.is_thin && <Badge color="red">THIN</Badge>}
                            </div>
                            {t.atomized_at && (
                              <span style={{ fontSize: 11, color: A.muted2 }}>
                                Atomized {formatDate(t.atomized_at)}
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {tours.length < total && (
                <div style={{ padding: 16, textAlign: "center" }}>
                  <Btn variant="secondary" onClick={() => loadTours(false)} disabled={loadingMore}>
                    {loadingMore ? "Loading…" : `Load more (${tours.length} / ${total})`}
                  </Btn>
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      {/* ── Floating action bar ──────────────────────────────────────────── */}
      {selectedCount > 0 && (
        <div style={{
          position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
          background: A.ink, color: "#fff", borderRadius: 10, padding: "10px 16px",
          display: "flex", alignItems: "center", gap: 12, boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
          zIndex: 200, fontFamily: sans, maxWidth: 640,
        }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedCount} tour{selectedCount === 1 ? "" : "s"} selected</span>
          <span style={{ fontSize: 11, color: "#C9CFD8" }}>
            {willRunInline && "Runs synchronously — you'll wait right here"}
            {willRunBatch && "≥100 tours — runs via Bedrock Batch, asynchronously (hours)"}
          </span>
          <Btn size="sm" variant="primary" disabled={running} onClick={runDecompose}>
            {running ? "Running…" : "Atomize"}
          </Btn>
          <button onClick={() => setSelectedIds(new Set())}
            style={{ background: "none", border: "none", cursor: "pointer", color: "#C9CFD8", fontSize: 12 }}>
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
