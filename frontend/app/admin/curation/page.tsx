"use client";
// app/admin/curation/page.tsx — AA-300 atom curation, redesigned per
// Nghiep's direct feedback after reviewing the live card-grid version:
// table rows (not cards), grouped by tour (accordion, default-open for
// thin/unreviewed tours per the curation rule in the original issue),
// multi-select with a floating bulk-action bar, a full dashboard of
// counts, and load-more instead of Pagination.tsx.
//
// Patterns reused verbatim from frontend/app/admin/master-content/page.tsx
// (this repo's own established convention for exactly this shape of page):
// checkbox multi-select via `Set<string>` state + toggleSelect(), StatCard
// row for dashboard counts, <table>/<thead>/<tbody> instead of a card grid.
// No small centered confirm-dialog convention existed anywhere in the repo
// (CompareModal.tsx is a full-screen modal, a different shape) — the
// delete-confirmation dialog here is a self-chosen minimal adaptation of
// the same fixed/backdrop overlay technique, not a new pattern invented
// from scratch.

import { Suspense, useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Star, Trash2, ImageIcon, Sparkles, Pencil, Check, X as XIcon,
  Grid3x3, ChevronDown, ChevronRight, AlertTriangle,
} from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { FilterBar } from "../_components/FilterBar";
import { A, sans, serif, Card, Btn, Badge, LoadingScreen, StatCard } from "../_components/adminUi";

// AA-345 round 7 — see the `sortedTours`/`loadAtoms` comment below for why
// pagination is tour-based now, not atom-row-based. This budget keeps each
// batch's cumulative atom_count safely under GET /admin/atoms's hard
// `limit <= 200` cap (api/routers/admin_atoms.py) even though we always
// request the backend's max limit=200 for the actual fetch — margin for
// the gap between a tour's raw atom_count (from summary, unfiltered) and
// what a batch might return once distinctiveness/unreviewed_only trim it
// (always ≤ the raw count, so this margin is conservative, never unsafe).
const TOUR_BATCH_ATOM_BUDGET = 180;

// Greedily grows a batch of tour_ids from `tours` starting at `startIndex`
// until adding the next tour would push cumulative atom_count over
// `budget` — always includes at least one tour so a single very-large
// tour can't stall pagination entirely (its own atoms may still get
// truncated by the backend's limit=200 cap in that edge case, same
// pre-existing ceiling the old offset/limit pagination had too).
function nextTourBatch(
  tours: TourSummary[], startIndex: number, budget: number,
): { ids: string[]; endIndex: number } {
  const ids: string[] = [];
  let atomSum = 0;
  let i = startIndex;
  while (i < tours.length) {
    const t = tours[i];
    if (ids.length > 0 && atomSum + t.atom_count > budget) break;
    ids.push(t.tour_id);
    atomSum += t.atom_count;
    i++;
  }
  return { ids, endIndex: i };
}

interface Atom {
  atom_id: string;
  tour_id: string;
  tour_name: string;
  text: string;
  activity_type: string | null;
  emotional_hook: string | null;
  visual_potential: number;
  distinctiveness: "HIGH" | "MED" | "LOW";
  media: { has_photo?: boolean; has_video?: boolean; media_refs?: string[] };
  starred: boolean;
  deleted: boolean;
  unreviewed: boolean;
  tour_atom_count: number;
}

interface TourSummary {
  tour_id: string;
  tour_name: string;
  atom_count: number;
  is_thin: boolean;
  unreviewed_count: number;
  // AA-345 round 2, Việc 4: MAX(tour_atoms.created_at) for this tour — same
  // "last touched" choice as GET /admin/tours-for-atomization's atomized_at.
  atomized_at: string | null;
}

interface Summary {
  distinctiveness_breakdown: { HIGH: number; MED: number; LOW: number };
  total_count: number;
  reviewed_count: number;
  by_tour: TourSummary[];
}

const DIST_BADGE: Record<string, "green" | "amber" | "gray"> = { HIGH: "green", MED: "amber", LOW: "gray" };

// Clearance so the fixed floating bulk-action bar (~56px tall, sitting 24px
// off the viewport bottom) never covers the Load More button underneath it.
const FLOATING_BAR_CLEARANCE = 92;

type SortKey = "" | "atoms_asc" | "atoms_desc" | "unreviewed_desc" | "name_asc" | "atomized_desc";

const SORT_OPTIONS: { label: string; value: SortKey }[] = [
  { label: "Atom count (asc)", value: "atoms_asc" },
  { label: "Atom count (desc)", value: "atoms_desc" },
  { label: "% unreviewed (most first)", value: "unreviewed_desc" },
  { label: "Tour name (A–Z)", value: "name_asc" },
  { label: "Newest first", value: "atomized_desc" },
];

// AA-345 round 3: see the matching comment in app/admin/atomize/page.tsx —
// hardcoding Asia/Ho_Chi_Minh (UTC+7) here is a local decision for these two
// pages specifically, not a repo-wide convention (checked: none exists yet
// across the other 61 toLocaleDateString/toLocaleString call sites).
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric", timeZone: "Asia/Ho_Chi_Minh",
  });
}

function CurationPageInner() {
  const router = useRouter();

  const [summary, setSummary] = useState<Summary | null>(null);
  const [atoms, setAtoms] = useState<Atom[]>([]);
  // AA-345 round 7 — how many tours (from the front of `sortedTours`, see
  // below) have had their atoms fetched so far. Reactive state, not just
  // the ref below, because it drives the "Load more (X / Y tours)" button
  // text and visibility directly.
  const [loadedTourCount, setLoadedTourCount] = useState(0);
  // Ref, not state — loadAtoms() below is memoized on filter values only, so a
  // stale-closure bug would silently re-read whatever index was captured at
  // that memoization (typically 0) on every "Load more" click, re-fetching and
  // duplicating the first page instead of advancing. A ref sidesteps the
  // closure entirely: .current is always current, no matter how old the
  // closure that reads it is. Tracks an INDEX INTO `sortedTours` now (round
  // 7), not a raw atom offset — see `sortedTours`/`loadAtoms` below for why.
  const tourIndexRef = useRef(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [distinctiveness, setDistinctiveness] = useState("");
  const [unreviewedOnly, setUnreviewedOnly] = useState(false);
  const [thinOnly, setThinOnly] = useState(false);
  const [sortBy, setSortBy] = useState<SortKey>("");
  // AA-345: deep link from the new atomize UI (/admin/atomize) after a
  // decompose run.
  //
  // AA-345 round 5 — the previous approach (a lazy useState initializer
  // reading window.location.search once at mount, chosen specifically to
  // avoid useSearchParams()'s Suspense-boundary requirement) had a real,
  // reproducible bug: on a client-side router.push() navigation FROM
  // /admin/atomize (not a hard reload), React can mount this page and run
  // that initializer before Next.js's router has actually applied the new
  // URL, so it silently read the OLD (pre-navigation) window.location and
  // initialized to []. The URL bar still showed the correct ?tour_ids=...
  // (confirmed live: Nghiep's screenshot, and reproduced here via
  // Playwright — a hard page.goto() to the exact same URL works correctly,
  // only the router.push() soft-navigation path fails), but the filter
  // silently never applied — full unfiltered list, no "Filtering to"
  // banner, no error. useSearchParams() is the router-integrated way to
  // read this and is guaranteed to reflect the params of the navigation
  // actually being rendered, which eliminates this race by construction —
  // worth the Suspense boundary this time (added below, wrapping the
  // default export).
  //
  // AA-345 round 2, Việc 4: accepts both `?tour_ids=id1,id2` (plural, the
  // new multi-tour link from a batch Atomize run) and the older single
  // `?tour_id=id` (kept for anything still linking that way) — tour_ids
  // wins if both are present, same precedence as the backend's own
  // GET /admin/atoms?tour_ids= param.
  const searchParams = useSearchParams();
  // AA-345 round 6 — "Clear filter" (below) used to call router.replace()
  // to a same-pathname, search-params-only URL (?tour_ids=X -> no query at
  // all). Confirmed live in a real production build (next build && next
  // start — the round 5 bug only showed up cross-pathname in `next dev`;
  // this one is same-pathname and ONLY reproduced in a production build,
  // not dev) that this specific class of router.replace() call updated
  // neither window.location NOR triggered a re-render with fresh
  // useSearchParams() output — confirmed via a console.log placed directly
  // in the button's onClick: it fired, router.replace() was called, and
  // the URL bar + this hook's value were both simply frozen afterward. A
  // known, long-standing class of Next.js App Router flakiness
  // (same-pathname, search-params-only navigations), distinct from round
  // 5's issue (which was a cross-pathname push() race and is unaffected by
  // this change). Rather than depend on the router reliably re-rendering
  // this component for that one specific transition, `cleared` is a plain,
  // guaranteed-to-rerender local flag the button sets directly — the URL
  // itself is cleaned up via a raw history.replaceState() call instead of
  // router.replace() (see the button's onClick for why).
  const [cleared, setCleared] = useState(false);
  const highlightTourIds = useMemo(() => {
    if (cleared) return [];
    const plural = searchParams.get("tour_ids");
    if (plural) return plural.split(",").map(s => s.trim()).filter(Boolean);
    const single = searchParams.get("tour_id");
    return single ? [single] : [];
  }, [searchParams, cleared]);
  const highlightSet = useMemo(() => new Set(highlightTourIds), [highlightTourIds]);

  // AA-345 round 7 — real bug, live-verified: "Newest first" (and every
  // other Sort option) used to be applied client-side to `combined`, which
  // was `summary.by_tour` FILTERED DOWN to only the tours already present
  // in `atomsByTour` — i.e. only tours whose atoms happened to already be
  // loaded. Atoms were loaded via GET /admin/atoms's plain offset/limit
  // pagination, `ORDER BY ta.tour_id, ta.created_at` (api/routers/
  // admin_atoms.py) — tour_id order, essentially random with respect to
  // recency. Verified live against the real dev DB: of 24 tours atomized
  // "today," 23 were missing from the very first page (offset=0,
  // limit=150) under that ordering — so "Newest first" was sorting a
  // near-arbitrary ~10-tour subset that had almost nothing to do with
  // which tours were actually newest. This wasn't specific to "Newest
  // first" either — every sort option filtered the SAME already-loaded
  // subset first, so all of them shared this defect; "Newest first" and
  // "Load more" just happened to be the two symptoms Nghiep noticed.
  //
  // Fix: `summary.by_tour` is already a COMPLETE, unpaginated per-tour
  // aggregate (GET /admin/atoms/summary has no LIMIT) with every field
  // every sort option needs (atom_count, unreviewed_count, tour_name,
  // atomized_at, is_thin) — sort THAT (the real, complete list) instead of
  // whatever's already loaded, and let pagination follow the sorted tour
  // order rather than deciding it. `thinOnly` is a real per-tour property
  // already on TourSummary, so it filters here too, before pagination;
  // `distinctiveness`/`unreviewedOnly` stay as GET /admin/atoms query
  // params (per-atom properties summary.by_tour can't pre-filter by) — a
  // "page" of tours can still legitimately return fewer atoms than its raw
  // atom_count sum once those apply, same tolerance the old pagination had.
  const sortedTours = useMemo(() => {
    if (!summary) return [];
    let list = summary.by_tour;
    if (highlightTourIds.length > 0) {
      const hSet = highlightSet;
      list = list.filter(t => hSet.has(t.tour_id));
    }
    if (thinOnly) list = list.filter(t => t.is_thin);
    const sorted = [...list];
    if (sortBy === "atoms_asc") sorted.sort((a, b) => a.atom_count - b.atom_count);
    else if (sortBy === "atoms_desc") sorted.sort((a, b) => b.atom_count - a.atom_count);
    else if (sortBy === "unreviewed_desc") {
      sorted.sort((a, b) => (b.unreviewed_count / (b.atom_count || 1)) - (a.unreviewed_count / (a.atom_count || 1)));
    } else if (sortBy === "name_asc") sorted.sort((a, b) => a.tour_name.localeCompare(b.tour_name));
    else if (sortBy === "atomized_desc") {
      // Nulls (no atoms ever recorded a timestamp, shouldn't happen in
      // practice but keeps this defensive) sort last.
      sorted.sort((a, b) => (b.atomized_at ? Date.parse(b.atomized_at) : 0) - (a.atomized_at ? Date.parse(a.atomized_at) : 0));
    }
    // default (no sortBy): summary.by_tour's own backend order (ORDER BY
    // rt.src_name — alphabetical), unchanged.
    return sorted;
  }, [summary, sortBy, highlightTourIds, highlightSet, thinOnly]);

  const [expandedTourIds, setExpandedTourIds] = useState<Set<string>>(new Set());
  const didInitExpand = useRef(false);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // AA-345 round 7 — set true once the summary fetch SETTLES, success or
  // failure, distinct from `summary` itself (which stays null on failure).
  // loadAtoms below needs this: pagination is now derived from
  // summary.by_tour (see sortedTours), so it has to wait for summary to
  // resolve before it knows what to fetch — but if it waited on `summary`
  // being truthy alone, a summary fetch failure (e.g. a 401) would leave
  // `summary` null forever and loadAtoms would just return early forever
  // too, stuck on the loading spinner with no error ever surfacing. This
  // flag lets loadAtoms distinguish "still waiting" from "summary failed,
  // stop waiting and show the honest empty/error state instead."
  const [summaryReady, setSummaryReady] = useState(false);

  // ── dashboard summary — independent of the atom list's current filter ────
  const loadSummary = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/atoms/summary");
      if (!res.ok) throw new Error(`Failed to load summary (${res.status})`);
      const data: Summary = await res.json();
      setSummary(data);
      if (!didInitExpand.current) {
        didInitExpand.current = true;
        setExpandedTourIds(new Set(
          data.by_tour
            .filter(t => t.is_thin || t.unreviewed_count > 0 || highlightSet.has(t.tour_id))
            .map(t => t.tour_id),
        ));
      }
    } catch (err: any) {
      setError(err.message || "Failed to load summary.");
    } finally {
      setSummaryReady(true);
    }
  }, [highlightSet]);

  // ── atom list — tour-based pagination (round 7), resets on filter/sort
  // change, appends on "Load more" ──────────────────────────────────────
  const loadAtoms = useCallback(async (reset: boolean) => {
    // sortedTours (and thus the correct batch) isn't known until summary
    // has settled — see the `summaryReady` comment above for why this
    // isn't just `if (!summary) return`.
    if (!summaryReady) return;
    if (!summary) {
      // Summary fetch failed — nothing to paginate. Surface that through
      // the normal loading/empty-state UI (orderedSections.length === 0
      // below) instead of leaving the page stuck on "Loading atoms…"
      // forever.
      setLoading(false);
      setLoadingMore(false);
      return;
    }
    const startIndex = reset ? 0 : tourIndexRef.current;
    if (reset) setLoading(true); else setLoadingMore(true);
    setError("");
    const { ids, endIndex } = nextTourBatch(sortedTours, startIndex, TOUR_BATCH_ATOM_BUDGET);
    if (ids.length === 0) {
      setAtoms(prev => (reset ? [] : prev));
      tourIndexRef.current = endIndex;
      setLoadedTourCount(endIndex);
      setLoading(false);
      setLoadingMore(false);
      return;
    }
    const params = new URLSearchParams({ limit: "200", offset: "0", tour_ids: ids.join(",") });
    if (distinctiveness) params.set("distinctiveness", distinctiveness);
    if (unreviewedOnly) params.set("unreviewed_only", "true");
    try {
      const res = await fetch(`/api/admin/atoms?${params}`);
      if (!res.ok) throw new Error(`Failed to load atoms (${res.status})`);
      const data = await res.json();
      setAtoms(prev => (reset ? data.atoms : [...prev, ...data.atoms]));
      tourIndexRef.current = endIndex;
      setLoadedTourCount(endIndex);
    } catch (err: any) {
      setError(err.message || "Failed to load atoms.");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [summaryReady, summary, sortedTours, distinctiveness, unreviewedOnly]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadAtoms(true); }, [loadAtoms]);

  // ── single-atom actions ────────────────────────────────────────────────
  async function patchAtom(atomId: string, body: Record<string, unknown>) {
    setBusyIds(prev => new Set(prev).add(atomId));
    try {
      const res = await fetch(`/api/admin/atoms/${atomId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Update failed (${res.status})`);
      }
      const updated = await res.json();
      if (updated.deleted) {
        setAtoms(prev => prev.filter(a => a.atom_id !== atomId));
        setSelectedIds(prev => { const n = new Set(prev); n.delete(atomId); return n; });
      } else {
        setAtoms(prev => prev.map(a => (a.atom_id === atomId ? { ...a, ...updated } : a)));
      }
      loadSummary();
    } catch (err: any) {
      setError(err.message || "Update failed.");
    } finally {
      setBusyIds(prev => { const n = new Set(prev); n.delete(atomId); return n; });
    }
  }

  function toggleStar(atom: Atom) { patchAtom(atom.atom_id, { starred: !atom.starred }); }
  function deleteAtom(atom: Atom) { patchAtom(atom.atom_id, { deleted: true }); }
  function startEdit(atom: Atom) { setEditingId(atom.atom_id); setEditText(atom.text); }
  function saveEdit(atomId: string) {
    if (!editText.trim()) return;
    patchAtom(atomId, { text: editText.trim() });
    setEditingId(null);
  }

  // ── bulk actions ───────────────────────────────────────────────────────
  async function bulkPatch(body: Record<string, unknown>) {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    setBulkBusy(true);
    try {
      const res = await fetch("/api/admin/atoms/bulk", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ atom_ids: ids, ...body }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Bulk update failed (${res.status})`);
      }
      if (body.deleted) {
        setAtoms(prev => prev.filter(a => !selectedIds.has(a.atom_id)));
      } else {
        const idSet = new Set(ids);
        setAtoms(prev => prev.map(a => (idSet.has(a.atom_id) ? { ...a, ...body } : a)));
      }
      setSelectedIds(new Set());
      loadSummary();
    } catch (err: any) {
      setError(err.message || "Bulk update failed.");
    } finally {
      setBulkBusy(false);
      setShowDeleteConfirm(false);
    }
  }

  function toggleSelectRow(atomId: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(atomId) ? next.delete(atomId) : next.add(atomId);
      return next;
    });
  }

  function toggleSelectSection(sectionAtoms: Atom[]) {
    const ids = sectionAtoms.map(a => a.atom_id);
    const allSelected = ids.every(id => selectedIds.has(id));
    setSelectedIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => (allSelected ? next.delete(id) : next.add(id)));
      return next;
    });
  }

  function toggleTourExpand(tourId: string) {
    setExpandedTourIds(prev => {
      const next = new Set(prev);
      next.has(tourId) ? next.delete(tourId) : next.add(tourId);
      return next;
    });
  }

  // ── keyboard shortcuts: X = delete, S = star (hovered row) ───────────────
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      if (!hoveredId) return;
      const atom = atoms.find(a => a.atom_id === hoveredId);
      if (!atom) return;
      if (e.key === "x" || e.key === "X") { e.preventDefault(); deleteAtom(atom); }
      if (e.key === "s" || e.key === "S") { e.preventDefault(); toggleStar(atom); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hoveredId, atoms]);

  // ── group loaded atoms by tour, in summary.by_tour order ─────────────────
  const atomsByTour = useMemo(() => {
    const map = new Map<string, Atom[]>();
    for (const a of atoms) {
      if (!map.has(a.tour_id)) map.set(a.tour_id, []);
      map.get(a.tour_id)!.push(a);
    }
    return map;
  }, [atoms]);

  // AA-345 round 7 — section order now comes straight from `sortedTours`
  // (already correctly sorted over the COMPLETE tour list, see its own
  // comment above), filtered to tours that actually have loaded atoms — no
  // re-sorting needed here anymore, `sortedTours`'s order already reflects
  // both the fetch order (loadAtoms fetched tours in exactly this order,
  // batch by batch) and the display order.
  const orderedSections = useMemo(() => {
    const known = new Set(sortedTours.map(t => t.tour_id));
    const order = sortedTours.filter(t => atomsByTour.has(t.tour_id));
    // tours with loaded atoms but not (yet) in the sortedTours snapshot —
    // keep them visible (defensive: a summary/atoms race at the very start
    // of a load, same reasoning as before round 7).
    const extra: TourSummary[] = [];
    for (const [tourId, list] of atomsByTour) {
      if (!known.has(tourId)) {
        extra.push({
          tour_id: tourId, tour_name: list[0].tour_name, atom_count: list.length,
          is_thin: false, unreviewed_count: 0, atomized_at: null,
        });
      }
    }
    return [...order, ...extra];
  }, [sortedTours, atomsByTour]);

  const searchLower = search.trim().toLowerCase();

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "28px 32px", maxWidth: 1400, margin: "0 auto", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <Sparkles size={18} color={A.gold} />
          <h1 style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: A.ink, margin: 0 }}>
            Atom Curation
          </h1>
          <div style={{ flex: 1 }} />
          <Btn size="sm" variant="secondary" onClick={() => router.push("/admin/curation/preview")}>
            <Grid3x3 size={12} /> Preview Slot Grid (N6)
          </Btn>
        </div>
        <p style={{ fontSize: 13, color: A.muted, marginTop: 4, marginBottom: 16 }}>
          Grouped by tour — thin tours (&lt; 5 atoms) or tours with unreviewed atoms open by
          default. Hover a row and press <b>X</b> to delete, <b>S</b> to star.
        </p>

        {highlightTourIds.length > 0 && (
          <div style={{
            display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: A.body,
            background: A.line2, borderRadius: 8, padding: "8px 12px", marginBottom: 14,
          }}>
            <span>
              Filtering to {highlightTourIds.length} tour{highlightTourIds.length === 1 ? "" : "s"} just atomized.
            </span>
            <button
              onClick={() => {
                // See the `cleared` comment above — this flag is what
                // actually drives the filter off, independent of the URL.
                setCleared(true);
                // Drop the ?tour_ids=/?tour_id= from the URL too —
                // otherwise a refresh after "clearing" silently re-applies
                // the filter (found live during AA-345 round 1 verify).
                // router.replace() alone confirmed unreliable here in a
                // real production build (round 6 — same-pathname,
                // search-params-only navigations are a known flaky class in
                // Next's App Router: it sometimes silently no-ops, and on
                // the runs where it doesn't, it triggers a second, redundant
                // refetch on top of the one `cleared` already causes).
                // history.replaceState() is a raw browser API call not
                // subject to that same-page router-cache path — reliably
                // updates the visible URL on every run, is a "replace" (not
                // "push", same as router.replace() would have been) so
                // back-button behavior is unaffected, and doesn't also fire
                // its own re-render — no router.replace() call needed
                // alongside it.
                window.history.replaceState(null, "", "/admin/curation");
              }}
              style={{ background: "none", border: "none", cursor: "pointer", color: A.gold, fontWeight: 600, fontSize: 12 }}
            >
              Clear filter
            </button>
          </div>
        )}

        {/* ── Dashboard ──────────────────────────────────────────────────── */}
        {summary && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 10, marginBottom: 18 }}>
            <StatCard icon={<Sparkles size={16} />} label="Total Atoms" value={String(summary.total_count)} />
            {(["HIGH", "MED", "LOW"] as const).map(level => {
              const count = summary.distinctiveness_breakdown[level];
              return (
                <div key={level} style={{ opacity: count === 0 ? 0.45 : 1 }}>
                  <StatCard
                    icon={<Star size={16} />} label={level} value={String(count)}
                    accent={count === 0 ? A.muted2 : DIST_BADGE[level] === "green" ? A.green : DIST_BADGE[level] === "amber" ? A.amber : A.muted}
                    sub={count === 0 ? "none yet (AA-317)" : "distinctiveness"}
                  />
                </div>
              );
            })}
            <StatCard
              icon={<Check size={16} />} label="Reviewed"
              value={`${summary.reviewed_count} / ${summary.total_count}`}
            />
          </div>
        )}

        <FilterBar
          search={search}
          onSearch={setSearch}
          placeholder="Filter loaded batch by text or tour…"
          filters={[
            {
              label: "Distinctiveness", value: distinctiveness, current: distinctiveness,
              options: [
                { label: "All", value: "" },
                { label: "HIGH", value: "HIGH" },
                { label: "MED", value: "MED" },
                { label: "LOW", value: "LOW" },
              ],
              onChange: setDistinctiveness,
            },
            {
              label: "Sort", value: sortBy, current: sortBy,
              allLabel: "Default",
              options: SORT_OPTIONS,
              onChange: v => setSortBy(v as SortKey),
            },
          ]}
          extra={
            <>
              <Btn variant={unreviewedOnly ? "primary" : "secondary"} size="sm" onClick={() => setUnreviewedOnly(v => !v)}>
                Unreviewed only
              </Btn>
              <Btn variant={thinOnly ? "primary" : "secondary"} size="sm" onClick={() => setThinOnly(v => !v)}>
                Thin tours only
              </Btn>
            </>
          }
        />

        {error && (
          <div style={{ fontSize: 12, padding: "8px 12px", borderRadius: 6, marginBottom: 14, background: A.redSoft, color: A.red }}>
            {error}
          </div>
        )}

        {loading ? (
          <LoadingScreen msg="Loading atoms…" />
        ) : orderedSections.length === 0 ? (
          <Card><div style={{ fontSize: 13, color: A.muted, textAlign: "center", padding: 20 }}>
            No atoms match the current filters.
          </div></Card>
        ) : (
          // Fixed-height scroll container, not a page-length scroll + separate
          // Pagination — replaces Pagination.tsx per Nghiep's direct feedback.
          <div style={{
            flex: 1, minHeight: 0, overflowY: "auto", border: `1px solid ${A.line}`, borderRadius: 10, background: "#fff",
            // Room for Load More to scroll clear of the floating bulk-action
            // bar, which is position:fixed and would otherwise sit on top of it.
            paddingBottom: selectedIds.size > 0 ? FLOATING_BAR_CLEARANCE : 0,
          }}>
            {orderedSections.map(section => {
              const sectionAtoms = (atomsByTour.get(section.tour_id) || []).filter(a =>
                !searchLower || a.text.toLowerCase().includes(searchLower) || a.tour_name.toLowerCase().includes(searchLower));
              if (sectionAtoms.length === 0 && searchLower) return null;
              const isExpanded = expandedTourIds.has(section.tour_id);
              const allSelected = sectionAtoms.length > 0 && sectionAtoms.every(a => selectedIds.has(a.atom_id));
              const justAtomized = highlightSet.has(section.tour_id);

              return (
                <div key={section.tour_id} style={{ borderBottom: `1px solid ${A.line}` }}>
                  <div
                    onClick={() => toggleTourExpand(section.tour_id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 8, padding: "10px 16px",
                      cursor: "pointer", background: justAtomized ? `${A.gold}18` : A.line2, fontFamily: sans,
                    }}
                  >
                    {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onClick={e => e.stopPropagation()}
                      onChange={() => toggleSelectSection(sectionAtoms)}
                      style={{ accentColor: A.gold }}
                    />
                    <span style={{ fontWeight: 600, color: A.ink, fontSize: 13 }}>{section.tour_name}</span>
                    <Badge color="gray">{section.atom_count} atoms</Badge>
                    {section.is_thin && <Badge color="red">thin</Badge>}
                    {section.unreviewed_count > 0 && <Badge color="blue">{section.unreviewed_count} unreviewed</Badge>}
                    {justAtomized && <Badge color="gold">Just atomized</Badge>}
                    {section.atomized_at && (
                      <span style={{ fontSize: 11, color: A.muted2 }}>Atomized {formatDate(section.atomized_at)}</span>
                    )}
                  </div>

                  {isExpanded && (
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                      <thead>
                        <tr>
                          <th style={{ width: 30 }} />
                          <th style={thStyle}>Distinctiveness</th>
                          <th style={thStyle}>Text</th>
                          <th style={{ ...thStyle, width: 70 }}>Visual</th>
                          <th style={{ ...thStyle, width: 60 }}>Photo</th>
                          <th style={{ ...thStyle, width: 110 }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sectionAtoms.map((atom, i) => (
                          <tr
                            key={atom.atom_id}
                            onMouseEnter={() => setHoveredId(atom.atom_id)}
                            onMouseLeave={() => setHoveredId(id => (id === atom.atom_id ? null : id))}
                            style={{
                              background: hoveredId === atom.atom_id ? `${A.gold}10` : i % 2 === 0 ? "#fff" : A.bg,
                              opacity: busyIds.has(atom.atom_id) ? 0.5 : 1,
                            }}
                          >
                            <td style={tdStyle}>
                              <input
                                type="checkbox"
                                checked={selectedIds.has(atom.atom_id)}
                                onChange={() => toggleSelectRow(atom.atom_id)}
                                style={{ accentColor: A.gold }}
                              />
                            </td>
                            <td style={tdStyle}><Badge color={DIST_BADGE[atom.distinctiveness]}>{atom.distinctiveness}</Badge></td>
                            <td style={{ ...tdStyle, maxWidth: 480 }}>
                              {editingId === atom.atom_id ? (
                                <div>
                                  <textarea
                                    value={editText}
                                    onChange={e => setEditText(e.target.value)}
                                    style={{
                                      width: "100%", boxSizing: "border-box", fontFamily: sans, fontSize: 13,
                                      padding: "6px 8px", borderRadius: 6, border: `1px solid ${A.line}`, minHeight: 50,
                                    }}
                                  />
                                  <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                                    <Btn size="sm" variant="primary" onClick={() => saveEdit(atom.atom_id)}><Check size={11} /> Save</Btn>
                                    <Btn size="sm" variant="ghost" onClick={() => setEditingId(null)}><XIcon size={11} /> Cancel</Btn>
                                  </div>
                                </div>
                              ) : (
                                <span style={{ fontSize: 13, color: A.body }}>{atom.text}</span>
                              )}
                            </td>
                            <td style={tdStyle}>
                              <span style={{ fontSize: 11, color: A.muted2 }}>
                                {"●".repeat(atom.visual_potential)}{"○".repeat(3 - atom.visual_potential)}
                              </span>
                            </td>
                            <td style={tdStyle}>{atom.media?.has_photo && <ImageIcon size={13} color={A.muted2} />}</td>
                            <td style={tdStyle}>
                              <div style={{ display: "flex", gap: 6 }}>
                                <button title="Star (S)" onClick={() => toggleStar(atom)}
                                  style={{ background: "none", border: "none", cursor: "pointer", color: atom.starred ? A.gold : A.muted2, display: "flex" }}>
                                  <Star size={14} fill={atom.starred ? A.gold : "none"} />
                                </button>
                                <button title="Edit text" onClick={() => startEdit(atom)}
                                  style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, display: "flex" }}>
                                  <Pencil size={13} />
                                </button>
                                <button title="Delete (X)" onClick={() => deleteAtom(atom)}
                                  style={{ background: "none", border: "none", cursor: "pointer", color: A.red, display: "flex" }}>
                                  <Trash2 size={13} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              );
            })}

            {loadedTourCount < sortedTours.length && (
              <div style={{ padding: 16, textAlign: "center" }}>
                <Btn variant="secondary" onClick={() => loadAtoms(false)} disabled={loadingMore}>
                  {loadingMore ? "Loading…" : `Load more (${loadedTourCount} / ${sortedTours.length} tours)`}
                </Btn>
              </div>
            )}
          </div>
        )}

        {/* ── Floating bulk-action bar ─────────────────────────────────────── */}
        {selectedIds.size > 0 && (
          <div style={{
            position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
            background: A.ink, color: "#fff", borderRadius: 10, padding: "10px 16px",
            display: "flex", alignItems: "center", gap: 12, boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
            zIndex: 200, fontFamily: sans,
          }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedIds.size} atoms selected</span>
            <Btn size="sm" variant="secondary" disabled={bulkBusy} onClick={() => bulkPatch({ starred: true })}>
              <Star size={12} /> Star all
            </Btn>
            <Btn size="sm" variant="danger" disabled={bulkBusy} onClick={() => setShowDeleteConfirm(true)}>
              <Trash2 size={12} /> Delete all
            </Btn>
            <button onClick={() => setSelectedIds(new Set())}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#C9CFD8", fontSize: 12 }}>
              Clear
            </button>
          </div>
        )}

        {/* ── Delete-all confirmation dialog ───────────────────────────────── */}
        {showDeleteConfirm && (
          <div style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300,
          }}>
            <div style={{ background: "#fff", borderRadius: 12, padding: 24, maxWidth: 380, fontFamily: sans }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <AlertTriangle size={18} color={A.red} />
                <span style={{ fontFamily: serif, fontSize: 17, color: A.ink }}>Delete {selectedIds.size} atoms?</span>
              </div>
              <p style={{ fontSize: 13, color: A.muted, marginBottom: 18 }}>
                This cannot be undone. These atoms will never appear in the slot allocator again.
              </p>
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <Btn variant="ghost" onClick={() => setShowDeleteConfirm(false)}>Cancel</Btn>
                <Btn variant="danger" disabled={bulkBusy} onClick={() => bulkPatch({ deleted: true })}>
                  {bulkBusy ? "Deleting…" : "Confirm Delete"}
                </Btn>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

// AA-345 round 5 — useSearchParams() (used inside CurationPageInner, see
// its comment above) requires a Suspense boundary around any component
// that calls it, per Next.js App Router. The fallback is brief (only
// blocks on search params resolving, not on this page's own data fetches,
// which still show their own LoadingScreen once mounted).
export default function CurationPage() {
  return (
    <Suspense fallback={<LoadingScreen msg="Loading…" />}>
      <CurationPageInner />
    </Suspense>
  );
}

const thStyle: React.CSSProperties = {
  padding: "8px 12px", fontSize: 10, fontWeight: 600, textTransform: "uppercase",
  letterSpacing: "0.08em", color: A.muted, textAlign: "left", borderBottom: `1px solid ${A.line}`,
};
const tdStyle: React.CSSProperties = {
  padding: "8px 12px", fontSize: 13, color: A.body, borderBottom: `1px solid ${A.line2}`,
};
