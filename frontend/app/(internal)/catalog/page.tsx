"use client";
import { useState } from "react";
import { Search, Globe, Filter } from "lucide-react";

const MOCK_CATALOG = [
  { id:"c-001", name:"Halong Bay Private Cruise",  country:"Vietnam",   trip_type:"coastal",   quality_score:9.2, status:"published", slug:"halong-bay-private-cruise-vietnam",    published_at:"2026-04-16" },
  { id:"c-002", name:"Angkor Wat Sunrise Trek",    country:"Cambodia",  trip_type:"cultural",  quality_score:8.7, status:"published", slug:"angkor-wat-sunrise-trek-cambodia",     published_at:"2026-04-16" },
  { id:"c-003", name:"Bali Wellness Retreat",      country:"Indonesia", trip_type:"wellness",  quality_score:9.5, status:"published", slug:"bali-wellness-retreat-indonesia",      published_at:"2026-04-15" },
  { id:"c-004", name:"Kyoto Culinary Journey",     country:"Japan",     trip_type:"culinary",  quality_score:8.9, status:"draft",     slug:"kyoto-culinary-journey-japan",         published_at:"" },
  { id:"c-005", name:"Mekong Delta Explorer",      country:"Vietnam",   trip_type:"adventure", quality_score:8.1, status:"draft",     slug:"mekong-delta-explorer-vietnam",        published_at:"" },
  { id:"c-006", name:"Sri Lanka Wildlife Safari",  country:"Sri Lanka", trip_type:"wildlife",  quality_score:9.0, status:"published", slug:"sri-lanka-wildlife-safari",            published_at:"2026-04-14" },
];

const TYPE_COLORS: Record<string, { bg: string; color: string }> = {
  cultural:  { bg: "rgba(139,92,246,0.15)", color: "#a78bfa" },
  adventure: { bg: "rgba(249,115,22,0.15)", color: "#fb923c" },
  wellness:  { bg: "rgba(34,197,94,0.15)",  color: "#4ade80" },
  culinary:  { bg: "rgba(234,179,8,0.15)",  color: "#facc15" },
  wildlife:  { bg: "rgba(16,185,129,0.15)", color: "#34d399" },
  coastal:   { bg: "rgba(59,130,246,0.15)", color: "#60a5fa" },
};

const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  published:   { bg: "rgba(34,197,94,0.12)",  color: "#22c55e" },
  draft:       { bg: "rgba(100,116,139,0.15)", color: "#94a3b8" },
  unpublished: { bg: "rgba(239,68,68,0.12)",  color: "#f87171" },
};

function Badge({ label, bg, color }: { label: string; bg: string; color: string }) {
  return (
    <span style={{
      padding: "3px 10px", borderRadius: 20, fontSize: 11,
      fontWeight: 600, background: bg, color,
      border: `1px solid ${color}33`,
    }}>{label}</span>
  );
}

export default function CatalogPage() {
  const [search,       setSearch]  = useState("");
  const [filterStatus, setStatus]  = useState("all");
  const [filterType,   setType]    = useState("all");

  const filtered = MOCK_CATALOG.filter(item => {
    const q = search.toLowerCase();
    return (
      (item.name.toLowerCase().includes(q) || item.country.toLowerCase().includes(q)) &&
      (filterStatus === "all" || item.status    === filterStatus) &&
      (filterType   === "all" || item.trip_type === filterType)
    );
  });

  const published = MOCK_CATALOG.filter(i => i.status === "published").length;
  const draft     = MOCK_CATALOG.filter(i => i.status === "draft").length;
  const avgScore  = (MOCK_CATALOG.reduce((s,i) => s + i.quality_score, 0) / MOCK_CATALOG.length).toFixed(1);

  const selectStyle: React.CSSProperties = {
    padding: "8px 14px", background: "var(--bg-card)",
    border: "1px solid var(--border)", borderRadius: 8,
    color: "var(--text-primary)", fontSize: 13, cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
            Published Catalog
          </h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 6 }}>
            Gold layer — business-ready tour content
          </p>
        </div>
        {/* Stats */}
        <div style={{ display: "flex", gap: 28 }}>
          {[
            { label: "Published", value: published, color: "#22c55e" },
            { label: "Draft",     value: draft,     color: "#94a3b8" },
            { label: "Avg Score", value: avgScore,  color: "#DB9628" },
          ].map(s => (
            <div key={s.label} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Filter size={14} style={{ color: "var(--text-muted)" }} />
        <div style={{ position: "relative" }}>
          <Search size={13} style={{
            position: "absolute", left: 10, top: "50%",
            transform: "translateY(-50%)", color: "var(--text-muted)",
          }} />
          <input type="text" placeholder="Search tours or countries..."
            value={search} onChange={e => setSearch(e.target.value)}
            style={{
              ...selectStyle, paddingLeft: 32, width: 240,
              outline: "none",
            }} />
        </div>
        <select value={filterStatus} onChange={e => setStatus(e.target.value)} style={selectStyle}>
          <option value="all">All Status</option>
          <option value="published">Published</option>
          <option value="draft">Draft</option>
        </select>
        <select value={filterType} onChange={e => setType(e.target.value)} style={selectStyle}>
          <option value="all">All Types</option>
          {["cultural","adventure","wellness","culinary","wildlife","coastal"].map(t => (
            <option key={t} value={t}>{t.charAt(0).toUpperCase()+t.slice(1)}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div style={{
        background: "var(--bg-card)", border: "1px solid var(--border)",
        borderRadius: 12, overflow: "hidden",
      }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "var(--bg-primary)", borderBottom: "1px solid var(--border)" }}>
              {["Tour", "Country", "Type", "Score", "Status", "Slug", "Published"].map((h, i) => (
                <th key={h} style={{
                  padding: "10px 16px", fontSize: 11,
                  color: "var(--text-muted)", fontWeight: 600,
                  textTransform: "uppercase", letterSpacing: 1,
                  textAlign: i === 0 || i === 4 || i === 5 ? "left" : i === 3 || i === 6 ? "right" : "left",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(item => {
              const tc = TYPE_COLORS[item.trip_type]   || { bg: "var(--border)", color: "var(--text-muted)" };
              const sc = STATUS_COLORS[item.status]     || { bg: "var(--border)", color: "var(--text-muted)" };
              const scoreColor = item.quality_score >= 9 ? "#22c55e" :
                                 item.quality_score >= 8 ? "#DB9628" : "#f59e0b";
              return (
                <tr key={item.id} style={{ borderBottom: "1px solid var(--border)" }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "var(--bg-card-hover)"}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}>
                  <td style={{ padding: "14px 16px", fontWeight: 600,
                    color: "var(--text-primary)", fontSize: 13 }}>
                    {item.name}
                  </td>
                  <td style={{ padding: "14px 16px" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 6,
                      color: "var(--text-secondary)", fontSize: 13 }}>
                      <Globe size={12} /> {item.country}
                    </span>
                  </td>
                  <td style={{ padding: "14px 16px" }}>
                    <Badge label={item.trip_type} bg={tc.bg} color={tc.color} />
                  </td>
                  <td style={{ padding: "14px 16px", textAlign: "right" }}>
                    <span style={{ fontWeight: 800, fontSize: 14, color: scoreColor }}>
                      {item.quality_score}
                    </span>
                  </td>
                  <td style={{ padding: "14px 16px" }}>
                    <Badge label={item.status} bg={sc.bg} color={sc.color} />
                  </td>
                  <td style={{ padding: "14px 16px" }}>
                    <span style={{
                      fontFamily: "monospace", fontSize: 11,
                      color: "var(--text-muted)", display: "block",
                      maxWidth: 200, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>/{item.slug}</span>
                  </td>
                  <td style={{ padding: "14px 16px", textAlign: "right",
                    fontSize: 12, color: "var(--text-muted)" }}>
                    {item.published_at || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: "48px 0", color: "var(--text-muted)" }}>
            <Search size={28} style={{ margin: "0 auto 10px" }} />
            <div>No tours match your filters</div>
          </div>
        )}
      </div>
    </div>
  );
}
