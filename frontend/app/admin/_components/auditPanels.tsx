// app/admin/_components/auditPanels.tsx — AA-551.
//
// Extracted from the original single-page `/admin/atom-curation` (AA-527 bổ sung) when that page
// was split in two (AA-551, per AA-550's audit): `/admin/atom-curation` (01-05, platform-wide) and
// `/admin/tenant-activity` (06-08, per-Tour tenant activity, new). Everything here is shared by
// both pages' own page.tsx — small generic UI helpers (EmptyState/ErrorState/AuditTable/
// fetchJson/useTourScopedFetch) plus the 3 sections (Write/Gate, Review, Publish) that moved to
// `/admin/tenant-activity` UNCHANGED in content/behavior — only their home page moved.
//
// PickTourPrompt's copy is now English (was "Chọn 1 Tour cụ thể" — AA-550 point D, the Vietnamese
// string mixed into an otherwise all-English admin UI).
import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, RotateCw } from "lucide-react";
import { A, sans, Card, Badge, Btn, LoadingScreen, TH, TD } from "./adminUi";

export async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return res.json();
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <Card>
      <div style={{ textAlign: "center", padding: "40px 20px" }}>
        <div style={{ fontSize: 32, marginBottom: 10 }}>🗒️</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: A.ink, marginBottom: 6 }}>{title}</div>
        <div style={{ fontSize: 13, color: A.muted }}>{body}</div>
      </div>
    </Card>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Card style={{ borderColor: A.redBorder }}>
      <div style={{ textAlign: "center", padding: "32px 20px" }}>
        <AlertTriangle size={26} color={A.red} style={{ marginBottom: 10 }} />
        <div style={{ fontSize: 14, fontWeight: 600, color: A.ink, marginBottom: 6 }}>Could not load this panel</div>
        <div style={{ fontSize: 12.5, color: A.muted, marginBottom: 14 }}>{message}</div>
        <Btn variant="secondary" size="sm" onClick={onRetry}><RotateCw size={13} /> Retry</Btn>
      </div>
    </Card>
  );
}

// AA-551 — copy translated (was "Chọn 1 Tour cụ thể", AA-550 point D). Still used by
// `/admin/tenant-activity` (06-08 genuinely require one Tour, unchanged); no longer used by the
// rebuilt `/admin/atom-curation` (01-04 now work with no Tour selected — only 05 Slate still
// prompts, with its own tour-specific copy, see that page's SlateSection).
export function PickTourPrompt({ sectionLabel }: { sectionLabel: string }) {
  return (
    <EmptyState
      title="Select a Tour"
      body={`${sectionLabel} is Tour-scoped data — pick one Tour from the dropdown above to view it.`}
    />
  );
}

// AA-557 D.6/E.8/F.10/G.13 — `sortValue`/`filterValue` are optional per-column accessors that
// opt a column into AuditTable's own sort/filter UI (see `sortable` prop below). Omitting both on
// every column (every EXISTING caller — Review/Publish sections above, tenant-activity's own
// tables) keeps AuditTable rendering byte-identical to before; no caller needed to change.
export interface Col<T> {
  key: string; label: string; render: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number | null;
  filterValue?: (row: T) => string;
}

// AA-557 — client-side sort/filter over whatever page of rows is already loaded (same scope as
// the existing focusRouteId/focusSegmentId cross-filters in atom-curation/page.tsx, which also
// narrow the fetched page rather than adding a new backend query param per column). Real row
// counts here (Segment 138, Score ~138, Route handful) fit in 1-3 pages at PAGE_SIZE=50, so a
// per-page sort/filter is legible; it does NOT re-sort/filter across page boundaries — the
// existing pagination footer is unaffected.
export function AuditTable<T>({ rows, columns, rowKey, sortable = false }: {
  rows: T[]; columns: Col<T>[]; rowKey: (row: T) => string; sortable?: boolean;
}) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [colFilters, setColFilters] = useState<Record<string, string>>({});

  let displayRows = rows;
  if (sortable) {
    displayRows = rows.filter(r => columns.every(c => {
      const f = colFilters[c.key];
      if (!f || !c.filterValue) return true;
      return c.filterValue(r).toLowerCase().includes(f.toLowerCase());
    }));
    const sortCol = sortKey ? columns.find(c => c.key === sortKey) : undefined;
    if (sortCol?.sortValue) {
      const sv = sortCol.sortValue;
      displayRows = [...displayRows].sort((a, b) => {
        const av = sv(a), bv = sv(b);
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
        return sortDir === "asc" ? cmp : -cmp;
      });
    }
  }

  function toggleSort(key: string) {
    if (sortKey !== key) { setSortKey(key); setSortDir("asc"); }
    else if (sortDir === "asc") setSortDir("desc");
    else { setSortKey(null); setSortDir("asc"); }
  }

  const hasFilterRow = sortable && columns.some(c => c.filterValue);

  return (
    <div style={{ overflowX: "auto", border: `1px solid ${A.line}`, borderRadius: 10 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
        <thead>
          <tr>
            {columns.map(c => (
              <th key={c.key} style={TH}>
                {sortable && c.sortValue ? (
                  <button onClick={() => toggleSort(c.key)} style={{
                    background: "none", border: "none", padding: 0, cursor: "pointer",
                    font: "inherit", color: sortKey === c.key ? A.gold : "inherit",
                    display: "flex", alignItems: "center", gap: 4,
                  }}>
                    {c.label}
                    <span style={{ fontSize: 9, opacity: sortKey === c.key ? 1 : 0.35 }}>
                      {sortKey === c.key ? (sortDir === "asc" ? "▲" : "▼") : "▲▼"}
                    </span>
                  </button>
                ) : c.label}
              </th>
            ))}
          </tr>
          {hasFilterRow && (
            <tr>
              {columns.map(c => (
                <th key={`${c.key}-filter`} style={{ ...TH, padding: "4px 16px 8px", textTransform: "none", fontWeight: 400 }}>
                  {c.filterValue && (
                    <input
                      value={colFilters[c.key] ?? ""}
                      onChange={e => setColFilters(prev => ({ ...prev, [c.key]: e.target.value }))}
                      placeholder="Filter…"
                      style={{
                        width: "100%", fontSize: 11.5, padding: "4px 7px", boxSizing: "border-box",
                        border: `1px solid ${A.line}`, borderRadius: 5, background: A.card, color: A.body,
                      }}
                    />
                  )}
                </th>
              ))}
            </tr>
          )}
        </thead>
        <tbody>
          {displayRows.map(row => (
            <tr key={rowKey(row)}>
              {columns.map(c => <td key={c.key} style={TD}>{c.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {sortable && displayRows.length === 0 && rows.length > 0 && (
        <div style={{ padding: "16px", textAlign: "center", fontSize: 12.5, color: A.muted2 }}>
          No rows match the current column filter(s).
        </div>
      )}
    </div>
  );
}

export function useTourScopedFetch<T>(endpoint: string, tourId: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!tourId) { setData(null); setLoading(false); setError(null); return; }
    setLoading(true); setError(null);
    fetchJson<T>(`${endpoint}?tour_id=${encodeURIComponent(tourId)}`)
      .then(setData)
      .catch(e => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [endpoint, tourId]);

  useEffect(() => { load(); }, [load]);
  return { data, loading, error, reload: load };
}

// ══════════════════════════════════════════════════════════════════════════
// Sections 06-07 — Write/Gate + Review (both read admin_a4.py's content-log — 2 lenses, 1 dataset)
// ══════════════════════════════════════════════════════════════════════════

export interface ContentLogRow {
  piece_id: string; tenant_name: string | null; channel: string; status: string; held_reason: string | null;
  gate_ledger: { gate?: string; passed?: boolean; violations?: string[] }[];
  gate_pass_count: number; gate_total_count: number; repair_log: unknown[]; attempt_number: number;
  content_preview: string; publish_status: string; created_at: string;
  tour: { name: string; destination: string } | null;
}

export function useContentLog(tourId: string | null) {
  return useTourScopedFetch<{ data: ContentLogRow[]; total: number }>("/api/admin/a4/content-log", tourId);
}

export const STATUS_COLOR: Record<string, "green" | "amber" | "red" | "gray"> = {
  approved: "green", held: "amber", processing: "gray", failed: "red",
};

export function WriteGateSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useContentLog(tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Write/Gate" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading) return <LoadingScreen msg="Loading Write/Gate…" />;
  if (!data || data.total === 0) return <EmptyState title="No write attempts yet" body="No content written yet for this Tour — T9 write hasn't run for any Slate/angle pick here yet." />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {data.data.map(p => (
        <Card key={p.piece_id} style={{ padding: "14px 18px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 8 }}>
            <div>
              <span style={{ fontSize: 12, fontFamily: "monospace", color: A.muted2, marginRight: 8 }}>#{p.attempt_number}</span>
              <Badge color={STATUS_COLOR[p.status] ?? "gray"}>{p.status}</Badge>{" "}
              <Badge color="gray">{p.channel}</Badge>{" "}
              <span style={{ fontSize: 12, color: A.muted }}>{p.tenant_name}</span>
            </div>
            <span style={{ fontSize: 11.5, fontFamily: "monospace", color: A.muted2 }}>{p.gate_pass_count}/{p.gate_total_count} gates</span>
          </div>
          <div style={{ fontSize: 13, color: A.body, marginBottom: 8 }}>{p.content_preview}…</div>
          {p.held_reason && <div style={{ fontSize: 12, color: A.red, marginBottom: 6 }}>Held: {p.held_reason}</div>}
          {p.gate_ledger.filter(g => g.passed === false).length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {p.gate_ledger.filter(g => g.passed === false).map((g, i) => (
                <Badge key={i} color="red">{g.gate ?? "gate"}</Badge>
              ))}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

// AA-554 I.26 — cross-link copy, shared by ReviewSection/PublishSection below: same dataset as
// Cross-Tenant Oversight's Content Log/Publish Log, just filtered to one Tour here vs across all
// tenants there. Rendered unconditionally (ABOVE the loading/error/empty early returns) — an
// earlier version only showed it once real rows existed, which meant it never appeared for the
// (common) case of a Tour with 0 rows yet, exactly when a reader most benefits from a pointer to
// the cross-tenant view to check whether the data exists elsewhere.
function CrossLinkNote({ oversightSection }: { oversightSection: string }) {
  return (
    <div style={{ fontSize: 11.5, color: A.muted2, marginBottom: 10 }}>
      Same dataset as{" "}
      <a href="/admin/a4-oversight" style={{ color: A.gold }}>Cross-Tenant Oversight</a>&apos;s
      {" "}{oversightSection} — across all tenants there, filtered to this one Tour here.
    </div>
  );
}

export function ReviewSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useContentLog(tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Review" />;
  const crossLink = <CrossLinkNote oversightSection="Content Log" />;
  if (error) return <>{crossLink}<ErrorState message={error} onRetry={reload} /></>;
  if (loading) return <>{crossLink}<LoadingScreen msg="Loading Review…" /></>;
  if (!data || data.total === 0) return <>{crossLink}<EmptyState title="Nothing to review yet" body="No content written yet for this Tour." /></>;
  // Review = same content-log dataset as Write/Gate, a queue-status lens instead of gate-detail —
  // "which pieces are waiting on what" rather than "why did this attempt hold" (per AA-501: AA's
  // review need is already fully served by content-log, no separate table/query).
  return (
    <>
      {crossLink}
      <AuditTable rows={data.data} rowKey={r => r.piece_id} columns={[
      { key: "tour", label: "Tour", render: r => r.tour?.name ?? "—" },
      { key: "tenant", label: "Tenant", render: r => r.tenant_name ?? "—" },
      { key: "channel", label: "Channel", render: r => r.channel },
      { key: "status", label: "Gate status", render: r => <Badge color={STATUS_COLOR[r.status] ?? "gray"}>{r.status}</Badge> },
      { key: "publish", label: "Publish status", render: r => <Badge color={r.publish_status === "published" ? "green" : r.publish_status === "pending_publish" ? "amber" : "gray"}>{r.publish_status}</Badge> },
      { key: "created", label: "Written", render: r => new Date(r.created_at).toLocaleString() },
      ]} />
    </>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Section 08 — Publish (admin_a4.py's publish-log, tour_id filter added AA-527)
// ══════════════════════════════════════════════════════════════════════════

export interface PublishRow {
  publish_id: string; tenant_name: string | null; channel: string; status: string;
  external_url: string | null; last_error: string | null; published_at: string | null; created_at: string;
}

export function PublishSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useTourScopedFetch<{ data: PublishRow[]; total: number }>("/api/admin/a4/publish-log", tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Publish" />;
  const crossLink = <CrossLinkNote oversightSection="Publish Log" />;
  if (error) return <>{crossLink}<ErrorState message={error} onRetry={reload} /></>;
  if (loading) return <>{crossLink}<LoadingScreen msg="Loading Publish…" /></>;
  if (!data || data.total === 0) return <>{crossLink}<EmptyState title="Nothing published yet" body="Nothing published yet for this Tour — T11 hasn't published any piece from it yet." /></>;
  return (
    <>
      {crossLink}
      <AuditTable rows={data.data} rowKey={r => r.publish_id} columns={[
        { key: "tenant", label: "Tenant", render: r => r.tenant_name ?? "—" },
        { key: "channel", label: "Channel", render: r => r.channel },
        { key: "status", label: "Status", render: r => <Badge color={r.status === "published" ? "green" : r.status === "failed" ? "red" : "gray"}>{r.status}</Badge> },
        { key: "url", label: "URL", render: r => r.external_url ? <a href={r.external_url} target="_blank" rel="noreferrer" style={{ color: A.gold }}>Link ↗</a> : "—" },
        { key: "error", label: "Last error", render: r => r.last_error ?? "—" },
        { key: "when", label: "When", render: r => new Date(r.published_at ?? r.created_at).toLocaleString() },
      ]} />
    </>
  );
}
