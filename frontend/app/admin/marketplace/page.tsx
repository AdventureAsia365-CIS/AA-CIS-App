"use client";
// app/admin/marketplace/page.tsx — AA-384: real Marketplace UI, built in AA-CIS-App (the AA-ACP-App
// version — src/app/(admin)/workspace/marketplace/page.tsx — is abandoned, 0 traffic since
// 09/07/2026, not touched by this change). Same functional scope as that version (catalog
// browse/filter, select tours, save draft portfolio, finalize) but following THIS repo's admin
// page pattern: AdminSidebar + adminUi design tokens + /api/admin/[...path] proxy, not Tailwind.
//
// Wires to the AA-330 Part A/B endpoints exactly as-is (no backend change here):
//   GET   /admin/marketplace/catalog
//   POST  /admin/marketplace/portfolios
//   PATCH /admin/marketplace/portfolios/{id}/finalize

import { useCallback, useEffect, useState } from "react";
import { Search, CheckSquare, Package, ExternalLink, Image as ImageIcon, AlertCircle } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, mono, sans, Card, SLabel, Btn, Badge, LoadingScreen, TH, TD } from "../_components/adminUi";

// ─── Types ────────────────────────────────────────────────────────────────────

interface CatalogTour {
  tour_id: string;
  name: string;
  destination: string | null;
  duration_raw: string | null;
  period: string | null;
  trip_url: string | null;
  url_alive: boolean | null;
  total_atoms: number;
  high_atoms_count: number;
  has_image: boolean;
  price_usd: number | null;
  price_available: boolean;
}

interface SavedPortfolio {
  portfolio_id: string;
  tour_ids: string[];
  atom_snapshot: { total_atoms: number; runway_months: number | null; posts_per_week: number | null };
  status: "draft" | "finalized";
  created_at: string;
  finalized_at: string | null;
}

const MONTH_OPTIONS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
].map((label, i) => ({ value: i + 1, label }));

// ─── Filter bar ───────────────────────────────────────────────────────────────

interface Filters {
  destination: string; durationMin: string; durationMax: string;
  periodMonth: string; minAtoms: string; minPrice: string; maxPrice: string;
}
const EMPTY_FILTERS: Filters = {
  destination: "", durationMin: "", durationMax: "",
  periodMonth: "", minAtoms: "", minPrice: "", maxPrice: "",
};

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label style={{ fontSize: 10.5, color: A.muted, display: "block", marginBottom: 5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "7px 10px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 7,
  color: A.body, fontSize: 12.5, outline: "none", fontFamily: sans, width: 110,
};

function FilterBar({ filters, onChange, onApply, loading }: {
  filters: Filters; onChange: (f: Filters) => void; onApply: () => void; loading: boolean;
}) {
  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
        <FilterField label="Destination">
          <input style={{ ...inputStyle, width: 150 }} placeholder="Search…" value={filters.destination}
            onChange={e => onChange({ ...filters, destination: e.target.value })} />
        </FilterField>
        <FilterField label="Duration min (days)">
          <input type="number" min={0} style={inputStyle} value={filters.durationMin}
            onChange={e => onChange({ ...filters, durationMin: e.target.value })} />
        </FilterField>
        <FilterField label="Duration max (days)">
          <input type="number" min={0} style={inputStyle} value={filters.durationMax}
            onChange={e => onChange({ ...filters, durationMax: e.target.value })} />
        </FilterField>
        <FilterField label="Season (month)">
          <select style={{ ...inputStyle, width: 110 }} value={filters.periodMonth}
            onChange={e => onChange({ ...filters, periodMonth: e.target.value })}>
            <option value="">Any month</option>
            {MONTH_OPTIONS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </FilterField>
        <FilterField label="Min atoms">
          <input type="number" min={0} style={inputStyle} value={filters.minAtoms}
            onChange={e => onChange({ ...filters, minAtoms: e.target.value })} />
        </FilterField>
        <FilterField label="Price min (USD)">
          <input type="number" min={0} style={inputStyle} value={filters.minPrice}
            onChange={e => onChange({ ...filters, minPrice: e.target.value })} />
        </FilterField>
        <FilterField label="Price max (USD)">
          <input type="number" min={0} style={inputStyle} value={filters.maxPrice}
            onChange={e => onChange({ ...filters, maxPrice: e.target.value })} />
        </FilterField>
        <Btn variant="primary" onClick={onApply} disabled={loading}>
          <Search size={13} /> Apply
        </Btn>
        <Btn variant="ghost" onClick={() => onChange(EMPTY_FILTERS)} disabled={loading}>
          Clear
        </Btn>
      </div>
      <p style={{ fontSize: 11, color: A.muted2, marginTop: 12, marginBottom: 0, fontStyle: "italic" }}>
        Tours without a reliable price show &quot;Price: contact us&quot; and always appear — not hidden by the price filter.
      </p>
    </Card>
  );
}

// ─── Catalog table ────────────────────────────────────────────────────────────

function AtomCell({ total, high }: { total: number; high: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontWeight: 600, color: A.ink, fontSize: 12.5 }}>{total}</span>
      {high > 0 && <Badge color="amber">{high} HIGH</Badge>}
    </div>
  );
}

function CatalogRow({ tour, checked, onToggle }: {
  tour: CatalogTour; checked: boolean; onToggle: () => void;
}) {
  return (
    <tr style={{ borderBottom: `1px solid ${A.line2}` }}>
      <td style={{ ...TD, width: 36 }}>
        <input type="checkbox" checked={checked} onChange={onToggle} style={{ cursor: "pointer" }} />
      </td>
      <td style={{ ...TD, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600 }}>
        {tour.name || <span style={{ color: A.muted2, fontStyle: "italic" }}>Unnamed</span>}
      </td>
      <td style={{ ...TD, color: A.muted }}>{tour.destination ?? "—"}</td>
      <td style={{ ...TD, color: A.muted }}>{tour.duration_raw ?? "—"}</td>
      <td style={{ ...TD, color: A.muted }}>{tour.period ?? "—"}</td>
      <td style={TD}>
        {tour.price_available
          ? <span style={{ fontFamily: mono }}>${tour.price_usd?.toLocaleString()}</span>
          : <span style={{ color: A.muted2, fontStyle: "italic" }}>Price: contact us</span>}
      </td>
      <td style={TD}><AtomCell total={tour.total_atoms} high={tour.high_atoms_count} /></td>
      <td style={{ ...TD, textAlign: "center" }}>
        {tour.has_image
          ? <ImageIcon size={14} color={A.green} />
          : <span style={{ color: A.line }}>—</span>}
      </td>
      <td style={TD}>
        {tour.trip_url ? (
          <a href={tour.trip_url} target="_blank" rel="noreferrer" style={{
            display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11,
            color: tour.url_alive === false ? A.red : A.green, textDecoration: "none",
          }}>
            {tour.url_alive === false ? "dead" : "live"} <ExternalLink size={10} />
          </a>
        ) : <span style={{ color: A.line }}>—</span>}
      </td>
    </tr>
  );
}

// ─── Portfolio bar ────────────────────────────────────────────────────────────

function PortfolioBar({ selectedCount, postsPerWeek, onPostsPerWeekChange, onSave, saving, saveError }: {
  selectedCount: number; postsPerWeek: string; onPostsPerWeekChange: (v: string) => void;
  onSave: () => void; saving: boolean; saveError: string;
}) {
  return (
    <Card style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
      <FilterField label="Posts/week (estimates runway)">
        <input type="number" min={0} step={0.5} style={inputStyle} value={postsPerWeek}
          onChange={e => onPostsPerWeekChange(e.target.value)} />
      </FilterField>
      <Btn variant="primary" onClick={onSave} disabled={selectedCount === 0 || saving}>
        <Package size={13} /> {saving ? "Saving…" : `Save portfolio (draft) — ${selectedCount} tour`}
      </Btn>
      {saveError && (
        <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: A.red }}>
          <AlertCircle size={13} /> {saveError}
        </span>
      )}
    </Card>
  );
}

function PortfolioResult({ portfolio, onFinalize, finalizing, finalizeError }: {
  portfolio: SavedPortfolio; onFinalize: () => void; finalizing: boolean; finalizeError: string;
}) {
  const isFinalized = portfolio.status === "finalized";
  return (
    <Card style={{ marginTop: 16, maxWidth: 460 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <div style={{ fontFamily: serif, fontSize: 16, fontWeight: 500, color: A.ink }}>
          Portfolio {isFinalized ? "finalized" : "saved (draft)"}
        </div>
        <Badge color={isFinalized ? "green" : "gray"}>{portfolio.status}</Badge>
      </div>
      <div style={{ fontSize: 10.5, fontFamily: mono, color: A.muted2, marginBottom: 10 }}>
        {portfolio.portfolio_id}
      </div>
      <div style={{ fontSize: 13, color: A.body }}>
        {portfolio.atom_snapshot.total_atoms} real atoms · {portfolio.tour_ids.length} tours
      </div>
      {portfolio.atom_snapshot.runway_months != null ? (
        <div style={{ fontSize: 13, color: A.body, marginTop: 4 }}>
          Estimated runway: <strong>~{portfolio.atom_snapshot.runway_months} months</strong>
          {" "}@ {portfolio.atom_snapshot.posts_per_week} posts/week
        </div>
      ) : (
        <div style={{ fontSize: 11.5, color: A.muted2, marginTop: 4 }}>
          Runway: not calculated yet (posts/week not entered)
        </div>
      )}
      {!isFinalized ? (
        <Btn variant="secondary" onClick={onFinalize} disabled={finalizing} style={{ marginTop: 12 }}>
          {finalizing ? "Finalizing…" : "Finalize portfolio"}
        </Btn>
      ) : (
        <div style={{ fontSize: 11, color: A.muted2, marginTop: 12 }}>
          Finalized at {portfolio.finalized_at ? new Date(portfolio.finalized_at).toLocaleString() : "—"} —
          use this portfolio_id in the Tenants → New Tenant → Seed Atoms step.
        </div>
      )}
      {finalizeError && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: A.red, marginTop: 8 }}>
          <AlertCircle size={13} /> {finalizeError}
        </div>
      )}
    </Card>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function MarketplacePage() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [tours, setTours] = useState<CatalogTour[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState("");

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [postsPerWeek, setPostsPerWeek] = useState("3");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [portfolio, setPortfolio] = useState<SavedPortfolio | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState("");

  const fetchCatalog = useCallback(async () => {
    setLoading(true); setFetchError("");
    try {
      const qs = new URLSearchParams();
      if (filters.destination) qs.set("destination", filters.destination);
      if (filters.durationMin) qs.set("duration_min", filters.durationMin);
      if (filters.durationMax) qs.set("duration_max", filters.durationMax);
      if (filters.periodMonth) qs.set("period_month", filters.periodMonth);
      if (filters.minAtoms) qs.set("min_atoms", filters.minAtoms);
      if (filters.minPrice) qs.set("min_price", filters.minPrice);
      if (filters.maxPrice) qs.set("max_price", filters.maxPrice);
      qs.set("limit", "200");
      const res = await fetch(`/api/admin/marketplace/catalog?${qs}`);
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      setTours(data.tours ?? []);
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "Failed to load catalog");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => { fetchCatalog(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function toggle(tourId: string) {
    setSelected(prev => {
      const n = new Set(prev);
      n.has(tourId) ? n.delete(tourId) : n.add(tourId);
      return n;
    });
    setPortfolio(null);
  }

  async function savePortfolio() {
    setSaving(true); setSaveError(""); setFinalizeError(""); setPortfolio(null);
    try {
      const res = await fetch("/api/admin/marketplace/portfolios", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tour_ids: Array.from(selected),
          filters_used: {
            destination: filters.destination || null,
            duration_min: filters.durationMin || null,
            duration_max: filters.durationMax || null,
            period_month: filters.periodMonth || null,
            min_atoms: filters.minAtoms || null,
            min_price: filters.minPrice || null,
            max_price: filters.maxPrice || null,
          },
          posts_per_week: postsPerWeek ? Number(postsPerWeek) : null,
        }),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      setPortfolio(await res.json());
      setSelected(new Set());
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save portfolio");
    } finally {
      setSaving(false);
    }
  }

  async function finalizePortfolio() {
    if (!portfolio) return;
    setFinalizing(true); setFinalizeError("");
    try {
      const res = await fetch(`/api/admin/marketplace/portfolios/${portfolio.portfolio_id}/finalize`, {
        method: "PATCH",
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      setPortfolio(await res.json());
    } catch (e) {
      setFinalizeError(e instanceof Error ? e.message : "Failed to finalize portfolio");
    } finally {
      setFinalizing(false);
    }
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: sans, background: A.bg }}>
      <AdminSidebar />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <header style={{ height: 56, background: "#fff", borderBottom: `1px solid ${A.line}`, display: "flex", alignItems: "center", padding: "0 32px", gap: 8, position: "sticky", top: 0, zIndex: 10 }}>
          <span style={{ fontSize: 12, color: A.muted2 }}>Admin /</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: A.body }}>Marketplace</span>
        </header>

        <main style={{ flex: 1, overflowY: "auto", padding: "28px 36px 56px" }}>
          <div style={{ marginBottom: 20 }}>
            <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink, margin: "0 0 6px", letterSpacing: "-0.01em" }}>
              Marketplace
            </h1>
            <p style={{ fontSize: 13, color: A.muted, margin: 0 }}>
              Browse the AA catalog, select tours for a new tenant, save and finalize a portfolio —
              the prerequisite step for N1 onboarding (Tenants → Seed Atoms).
            </p>
          </div>

          <FilterBar filters={filters} onChange={setFilters} onApply={fetchCatalog} loading={loading} />

          {fetchError && (
            <div style={{ marginBottom: 16, padding: "10px 14px", background: A.redSoft, border: `1px solid ${A.redBorder}`, borderRadius: 8, fontSize: 13, color: A.red, display: "flex", alignItems: "center", gap: 8 }}>
              <AlertCircle size={14} /> {fetchError}
            </div>
          )}

          <Card style={{ padding: 0, overflow: "hidden" }}>
            {loading ? <LoadingScreen msg="Loading catalog…" /> : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["", "Tour", "Destination", "Duration", "Season", "Price (USD)", "Atoms", "Image", "URL"].map((h, i) => (
                        <th key={i} style={TH}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tours.length === 0 ? (
                      <tr><td colSpan={9} style={{ padding: 48, textAlign: "center", color: A.muted, fontSize: 13 }}>No tours match these filters</td></tr>
                    ) : tours.map(t => (
                      <CatalogRow key={t.tour_id} tour={t} checked={selected.has(t.tour_id)} onToggle={() => toggle(t.tour_id)} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {tours.length > 0 && (
            <div style={{ fontSize: 11.5, color: A.muted2, marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
              <CheckSquare size={12} /> {selected.size} selected of {tours.length} shown
            </div>
          )}
        </main>

        {/* AA-387: sticky footer — Save/Finalize toolbar + result stay visible without scrolling
            through the (growing, ~54 → ~763 after AA-345) tour list above. */}
        <div style={{
          position: "sticky", bottom: 0, zIndex: 10, background: A.bg,
          borderTop: `1px solid ${A.line}`, padding: "16px 36px",
          boxShadow: "0 -2px 8px rgba(0,0,0,0.04)",
        }}>
          <PortfolioBar
            selectedCount={selected.size} postsPerWeek={postsPerWeek}
            onPostsPerWeekChange={setPostsPerWeek} onSave={savePortfolio}
            saving={saving} saveError={saveError}
          />

          {portfolio && (
            <PortfolioResult
              portfolio={portfolio} onFinalize={finalizePortfolio}
              finalizing={finalizing} finalizeError={finalizeError}
            />
          )}
        </div>
      </div>
    </div>
  );
}
