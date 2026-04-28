"use client";
import { useState, useEffect } from "react";
import { Search, Globe, Filter, Loader } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

const TYPE_COLORS: Record<string, { bg: string; color: string }> = {
  cultural:  { bg: "rgba(139,92,246,0.15)", color: "#a78bfa" },
  adventure: { bg: "rgba(249,115,22,0.15)", color: "#fb923c" },
  wellness:  { bg: "rgba(34,197,94,0.15)",  color: "#4ade80" },
  culinary:  { bg: "rgba(234,179,8,0.15)",  color: "#facc15" },
  wildlife:  { bg: "rgba(16,185,129,0.15)", color: "#34d399" },
  coastal:   { bg: "rgba(59,130,246,0.15)", color: "#60a5fa" },
  trekking:  { bg: "rgba(239,68,68,0.15)",  color: "#f87171" },
  pilgrimage:{ bg: "rgba(168,85,247,0.15)", color: "#c084fc" },
};

const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  published:   { bg: "rgba(34,197,94,0.12)",  color: "#22c55e" },
  draft:       { bg: "rgba(100,116,139,0.15)", color: "#94a3b8" },
  unpublished: { bg: "rgba(239,68,68,0.12)",  color: "#f87171" },
};

function Badge({ label, bg, color }: { label: string; bg: string; color: string }) {
  return (
    <span style={{ padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: bg, color, border: `1px solid ${color}33` }}>
      {label}
    </span>
  );
}

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/cis_api_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

interface Tour {
  id: string;
  tour_id: string;
  aa_name: string;
  aa_subtitle: string;
  seo_title: string;
  quality_score: number | null;
  published_at: string;
}

export default function CatalogPage() {
  const [tours, setTours]       = useState<Tour[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState("");
  const [search, setSearch]     = useState("");
  const [page, setPage]         = useState(1);
  const [total, setTotal]       = useState(0);

  useEffect(() => {
    const token = getToken();
    if (!token) { setError("Not authenticated"); setLoading(false); return; }

    fetch(`${API_URL}/v1/tours?page=${page}&page_size=20`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(r => r.json())
      .then(d => {
        setTours(d.data || []);
        setTotal(d.pagination?.total || 0);
        setLoading(false);
      })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [page]);

  const filtered = tours.filter(t =>
    t.aa_name?.toLowerCase().includes(search.toLowerCase()) ||
    t.aa_subtitle?.toLowerCase().includes(search.toLowerCase())
  );

  const selectStyle: React.CSSProperties = {
    padding: "8px 14px", background: "var(--bg-card)",
    border: "1px solid var(--border)", borderRadius: 8,
    color: "var(--text-primary)", fontSize: 13, cursor: "pointer",
  };

  if (loading) return (
    <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:400, gap:12, color:"var(--text-muted)" }}>
      <Loader size={20} style={{ animation:"spin 1s linear infinite" }} /> Loading tours...
    </div>
  );

  if (error) return (
    <div style={{ padding:32, color:"#f87171", textAlign:"center" }}>Error: {error}</div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>Published Catalog</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 6 }}>Gold layer — {total} business-ready tours</p>
        </div>
        <div style={{ display: "flex", gap: 28 }}>
          {[
            { label: "Total Tours", value: total,   color: "#22c55e" },
            { label: "This Page",   value: tours.length, color: "#DB9628" },
          ].map(s => (
            <div key={s.label} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Filter size={14} style={{ color: "var(--text-muted)" }} />
        <div style={{ position: "relative" }}>
          <Search size={13} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)" }} />
          <input type="text" placeholder="Search tours..." value={search} onChange={e => setSearch(e.target.value)}
            style={{ ...selectStyle, paddingLeft: 32, width: 280, outline: "none" }} />
        </div>
      </div>

      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "var(--bg-primary)", borderBottom: "1px solid var(--border)" }}>
              {["Tour Name", "Subtitle", "SEO Title", "Score", "Published"].map((h, i) => (
                <th key={h} style={{ padding: "10px 16px", fontSize: 11, color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1, textAlign: i >= 3 ? "right" : "left" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(item => {
              const scoreColor = !item.quality_score ? "#94a3b8" :
                item.quality_score >= 9 ? "#22c55e" :
                item.quality_score >= 8 ? "#DB9628" : "#f59e0b";
              return (
                <tr key={item.id} style={{ borderBottom: "1px solid var(--border)" }}
                  onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "var(--bg-card-hover)"}
                  onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}>
                  <td style={{ padding: "14px 16px", fontWeight: 600, color: "var(--text-primary)", fontSize: 13, maxWidth: 200 }}>{item.aa_name}</td>
                  <td style={{ padding: "14px 16px", color: "var(--text-secondary)", fontSize: 12, maxWidth: 240 }}>{item.aa_subtitle}</td>
                  <td style={{ padding: "14px 16px", color: "var(--text-muted)", fontSize: 11, fontFamily: "monospace", maxWidth: 200 }}>{item.seo_title}</td>
                  <td style={{ padding: "14px 16px", textAlign: "right" }}>
                    <span style={{ fontWeight: 800, fontSize: 14, color: scoreColor }}>
                      {item.quality_score?.toFixed(1) ?? "—"}
                    </span>
                  </td>
                  <td style={{ padding: "14px 16px", textAlign: "right", fontSize: 12, color: "var(--text-muted)" }}>
                    {item.published_at ? new Date(item.published_at).toLocaleDateString() : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: "48px 0", color: "var(--text-muted)" }}>
            <Search size={28} style={{ margin: "0 auto 10px" }} /> <div>No tours found</div>
          </div>
        )}
      </div>

      {/* Pagination */}
      {total > 20 && (
        <div style={{ display:"flex", justifyContent:"center", gap:8 }}>
          <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page===1}
            style={{ ...selectStyle, opacity: page===1 ? 0.4 : 1 }}>← Prev</button>
          <span style={{ padding:"8px 16px", color:"var(--text-muted)", fontSize:13 }}>Page {page}</span>
          <button onClick={() => setPage(p => p+1)} disabled={tours.length < 20}
            style={{ ...selectStyle, opacity: tours.length < 20 ? 0.4 : 1 }}>Next →</button>
        </div>
      )}
    </div>
  );
}
