"use client";
import { useState } from "react";
import {
  CheckCircle, XCircle, RotateCcw, ChevronDown, ChevronUp,
  Filter, AlertTriangle, Edit3, Flag,
} from "lucide-react";

const MOCK_REVIEWS = [
  {
    id: "v-001",
    name: "Halong Bay Private Cruise",
    country: "Vietnam", score: 6.2, date: "2026-04-17",
    hitl_status: "pending",
    issues: ["L2-08: No preferred brand words found", "L3-21: seo_meta too short (42 chars, min 80)"],
    original: {
      name: "Halong Bay 3D2N Tour",
      summary: "Join our Halong Bay tour for an amazing experience at the best price! Great value for money.",
      highlights: ["Boat trip included", "Caves visit", "Seafood dinner", "Guide provided"],
      seo_title: "Halong Bay 3D2N Tour - Best Price",
      seo_meta: "Book now for best deals on Halong Bay!",
    },
    generated: {
      name: "Halong Bay Private Cruise",
      subtitle: "A curated journey through Vietnam's karst seascape",
      summary: "Discover the timeless grandeur of Halong Bay aboard a refined private vessel, designed for discerning travellers seeking an immersive encounter with Vietnam's most celebrated natural wonder.",
      highlights: [
        "Private sundeck with panoramic karst landscape views",
        "Chef-prepared Vietnamese cuisine onboard",
        "Guided kayaking through hidden emerald lagoons",
        "Overnight anchoring in secluded bay coves",
      ],
      seo_title: "Halong Bay Private Cruise | Adventure Asia",
      seo_meta: "Curated private cruise on Halong Bay.",
    },
    seo_checks: [
      { label: "Title length (≤60 chars)", status: "pass", value: "44 chars" },
      { label: "Meta length (80–160 chars)", status: "fail", value: "34 chars — too short" },
      { label: "No forbidden words",        status: "pass", value: "Clean" },
      { label: "Preferred brand words",     status: "warn", value: "0 found (min 1)" },
      { label: "Trip type defined",         status: "pass", value: "coastal" },
    ],
  },
  {
    id: "v-002",
    name: "Angkor Wat Sunrise Trek",
    country: "Cambodia", score: 5.8, date: "2026-04-17",
    hitl_status: "pending",
    issues: ["L2-09: Exclamation mark detected", "L2-07: Forbidden word 'deal' found"],
    original: {
      name: "Angkor Sunrise Tour",
      summary: "Best deal for Angkor Wat! Don't miss this amazing offer! Book now for instant access.",
      highlights: ["Sunrise view", "Temple tour", "Guide included"],
      seo_title: "Angkor Wat Best Deal - Book Now!",
      seo_meta: "Best deals on Angkor Wat tours. Book now for instant booking!",
    },
    generated: {
      name: "Angkor Wat Sunrise Trek",
      subtitle: "A tailored dawn pilgrimage through Khmer antiquity",
      summary: "Witness the ethereal dawn light cascade across Angkor Wat's ancient spires on a thoughtfully guided journey through Cambodia's most sacred temple complex, refined for the discerning traveller.",
      highlights: [
        "Private sunrise access before public crowds arrive",
        "Expert Khmer history narration by specialist guide",
        "Curated route through Bayon and Ta Prohm temples",
      ],
      seo_title: "Angkor Wat Sunrise Trek | Adventure Asia",
      seo_meta: "Experience Angkor Wat at sunrise on a curated private trek with Adventure Asia. Tailored for discerning travellers.",
    },
    seo_checks: [
      { label: "Title length (≤60 chars)", status: "pass",  value: "44 chars" },
      { label: "Meta length (80–160 chars)", status: "pass", value: "112 chars" },
      { label: "No forbidden words",        status: "fail", value: "'deal' detected" },
      { label: "Preferred brand words",     status: "pass", value: "curated, tailored, refined" },
      { label: "Trip type defined",         status: "pass", value: "cultural" },
    ],
  },
];

const SEO_STATUS_STYLE: Record<string, { bg: string; color: string; label: string }> = {
  pass: { bg: "rgba(34,197,94,0.1)",  color: "#22c55e", label: "Pass" },
  warn: { bg: "rgba(245,158,11,0.1)", color: "#f59e0b", label: "Warning" },
  fail: { bg: "rgba(239,68,68,0.1)",  color: "#ef4444", label: "Fail" },
};

function SEOBreakdown({ checks }: { checks: typeof MOCK_REVIEWS[0]["seo_checks"] }) {
  return (
    <div style={{
      borderTop: "1px solid var(--border)", padding: "16px 24px",
      background: "var(--bg-primary)",
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 1, marginBottom: 12 }}>
        SEO Validation Breakdown
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {checks.map((c, i) => {
          const s = SEO_STATUS_STYLE[c.status];
          return (
            <div key={i} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "6px 12px", borderRadius: 6, background: s.bg,
            }}>
              <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{c.label}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{c.value}</span>
                <span style={{
                  fontSize: 10, fontWeight: 700, color: s.color,
                  padding: "2px 6px", borderRadius: 4,
                  border: `1px solid ${s.color}33`,
                }}>{s.label}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BeforeAfterPanel({ item }: { item: typeof MOCK_REVIEWS[0] }) {
  const [editedSummary, setEditedSummary] = useState(item.generated.summary);
  const [editedSeoMeta, setEditedSeoMeta] = useState(item.generated.seo_meta);

  const colStyle = (side: "before" | "after"): React.CSSProperties => ({
    flex: 1, display: "flex", flexDirection: "column",
    background: side === "before" ? "var(--before-bg)" : "var(--after-bg)",
    borderRadius: 8,
    border: `1px solid ${side === "before" ? "var(--before-border)" : "var(--after-border)"}`,
    overflow: "hidden",
  });

  const headerStyle = (side: "before" | "after"): React.CSSProperties => ({
    padding: "10px 16px",
    background: side === "before" ? "#F5C6C6" : "#B8DFA0",
    fontSize: 11, fontWeight: 700, letterSpacing: 1,
    color: side === "before" ? "#7F1D1D" : "#166534",
    textTransform: "uppercase",
    display: "flex", alignItems: "center", gap: 6,
  });

  const bodyStyle: React.CSSProperties = {
    padding: 16, flex: 1,
    display: "flex", flexDirection: "column", gap: 12,
    overflowY: "auto", maxHeight: 360,
  };

  const fieldLabel: React.CSSProperties = {
    fontSize: 10, fontWeight: 600, color: "#6B7280",
    textTransform: "uppercase", letterSpacing: 1, marginBottom: 4,
  };

  return (
    <div>
      {/* Before / After columns */}
      <div style={{ display: "flex", gap: 12, padding: "16px 24px" }}>
        {/* BEFORE */}
        <div style={colStyle("before")}>
          <div style={headerStyle("before")}>
            ✕ Before — Original Supplier Content
          </div>
          <div style={bodyStyle}>
            <div>
              <div style={fieldLabel}>Name</div>
              <div style={{ fontFamily: "monospace", fontSize: 13, color: "#374151" }}>
                {item.original.name}
              </div>
            </div>
            <div>
              <div style={fieldLabel}>Summary</div>
              <div style={{ fontFamily: "monospace", fontSize: 12, color: "#374151", lineHeight: 1.6 }}>
                {item.original.summary}
              </div>
            </div>
            <div>
              <div style={fieldLabel}>Highlights</div>
              <ul style={{ margin: 0, padding: "0 0 0 16px" }}>
                {item.original.highlights.map((h, i) => (
                  <li key={i} style={{ fontFamily: "monospace", fontSize: 12, color: "#374151", marginBottom: 4 }}>
                    {h}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div style={fieldLabel}>SEO Title</div>
              <div style={{ fontFamily: "monospace", fontSize: 12, color: "#374151" }}>
                {item.original.seo_title}
              </div>
            </div>
            <div>
              <div style={fieldLabel}>SEO Meta</div>
              <div style={{ fontFamily: "monospace", fontSize: 12, color: "#374151" }}>
                {item.original.seo_meta}
              </div>
            </div>
          </div>
        </div>

        {/* AFTER */}
        <div style={colStyle("after")}>
          <div style={headerStyle("after")}>
            <Edit3 size={11} /> After — AI Rewrite (Editable)
          </div>
          <div style={bodyStyle}>
            <div>
              <div style={{ ...fieldLabel, color: "#166534" }}>Name</div>
              <div style={{ fontSize: 13, color: "#14532D", fontWeight: 600 }}>
                {item.generated.name}
              </div>
            </div>
            <div>
              <div style={{ ...fieldLabel, color: "#166534" }}>Subtitle</div>
              <div style={{ fontSize: 12, color: "#166534", fontStyle: "italic" }}>
                {item.generated.subtitle}
              </div>
            </div>
            <div>
              <div style={{ ...fieldLabel, color: "#166534" }}>Summary</div>
              <div
                contentEditable suppressContentEditableWarning
                onInput={e => setEditedSummary((e.target as HTMLElement).innerText)}
                style={{
                  fontSize: 12, color: "#14532D", lineHeight: 1.7,
                  padding: "6px 8px", borderRadius: 4,
                  background: "rgba(255,255,255,0.5)",
                  minHeight: 60,
                }}>
                {item.generated.summary}
              </div>
            </div>
            <div>
              <div style={{ ...fieldLabel, color: "#166534" }}>Highlights</div>
              <ul style={{ margin: 0, padding: "0 0 0 16px" }}>
                {item.generated.highlights.map((h, i) => (
                  <li key={i} style={{ fontSize: 12, color: "#14532D", marginBottom: 4 }}>{h}</li>
                ))}
              </ul>
            </div>
            <div>
              <div style={{ ...fieldLabel, color: "#166534" }}>SEO Title</div>
              <div style={{ fontSize: 12, color: "#14532D", fontFamily: "monospace",
                padding: "4px 8px", background: "rgba(255,255,255,0.5)", borderRadius: 4 }}>
                {item.generated.seo_title}
              </div>
            </div>
            <div>
              <div style={{ ...fieldLabel, color: "#166534" }}>SEO Meta</div>
              <div
                contentEditable suppressContentEditableWarning
                onInput={e => setEditedSeoMeta((e.target as HTMLElement).innerText)}
                style={{
                  fontSize: 12, color: "#14532D", fontFamily: "monospace",
                  padding: "4px 8px", background: "rgba(255,255,255,0.5)",
                  borderRadius: 4, minHeight: 40,
                }}>
                {item.generated.seo_meta}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* SEO Breakdown */}
      <SEOBreakdown checks={item.seo_checks} />
    </div>
  );
}

function ReviewCard({ item, onApprove, onReject, onRegenerate, onFlag }: {
  item: typeof MOCK_REVIEWS[0];
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onRegenerate: (id: string) => void;
  onFlag: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const hasFail = item.seo_checks.some(c => c.status === "fail");

  return (
    <div style={{
      background: "var(--bg-card)", border: "1px solid var(--border)",
      borderRadius: 12, overflow: "hidden",
    }}>
      {/* Header row */}
      <div style={{
        padding: "14px 24px", display: "flex",
        alignItems: "center", gap: 12,
      }}>
        {/* Score badge */}
        <div style={{
          width: 44, height: 44, borderRadius: 10, flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          background: item.score >= 7 ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
          color: item.score >= 7 ? "#22c55e" : "#ef4444",
          fontWeight: 800, fontSize: 14,
        }}>
          {item.score}
        </div>

        {/* Info */}
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, color: "var(--text-primary)", fontSize: 14 }}>
            {item.name}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            {item.country} · {item.date}
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button onClick={() => onFlag(item.id)} title="Report content issue"
            style={{ padding: 8, border: "1px solid var(--border)", borderRadius: 8,
              background: "none", cursor: "pointer", color: "var(--text-muted)",
              display: "flex", alignItems: "center" }}>
            <Flag size={14} />
          </button>
          <button onClick={() => onRegenerate(item.id)} title="Regenerate"
            style={{ padding: 8, border: "1px solid var(--border)", borderRadius: 8,
              background: "none", cursor: "pointer", color: "var(--text-muted)",
              display: "flex", alignItems: "center" }}>
            <RotateCcw size={14} />
          </button>
          <button onClick={() => onReject(item.id)}
            style={{ padding: "7px 14px", border: "1px solid rgba(239,68,68,0.3)",
              borderRadius: 8, background: "rgba(239,68,68,0.08)",
              cursor: "pointer", color: "#ef4444", fontSize: 12, fontWeight: 600,
              display: "flex", alignItems: "center", gap: 5 }}>
            <XCircle size={13} /> Reject
          </button>
          <button onClick={() => onApprove(item.id)} disabled={hasFail}
            style={{ padding: "7px 16px",
              border: `1px solid ${hasFail ? "var(--border)" : "rgba(34,197,94,0.3)"}`,
              borderRadius: 8,
              background: hasFail ? "var(--border)" : "rgba(34,197,94,0.15)",
              cursor: hasFail ? "not-allowed" : "pointer",
              color: hasFail ? "var(--text-muted)" : "#22c55e",
              fontSize: 12, fontWeight: 700,
              display: "flex", alignItems: "center", gap: 5 }}>
            <CheckCircle size={13} />
            {hasFail ? "Fix Issues First" : "Approve & Publish"}
          </button>
          <button onClick={() => setExpanded(!expanded)}
            style={{ padding: 8, border: "1px solid var(--border)", borderRadius: 8,
              background: "none", cursor: "pointer", color: "var(--text-muted)",
              display: "flex", alignItems: "center" }}>
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {/* Issue badges */}
      {item.issues.length > 0 && (
        <div style={{ padding: "0 24px 12px", display: "flex", flexWrap: "wrap", gap: 6 }}>
          {item.issues.map((issue, i) => (
            <span key={i} style={{
              fontSize: 11, padding: "3px 10px",
              background: "rgba(239,68,68,0.1)", color: "#f87171",
              border: "1px solid rgba(239,68,68,0.2)", borderRadius: 20,
            }}>
              {issue}
            </span>
          ))}
        </div>
      )}

      {/* Before/After expanded */}
      {expanded && (
        <div style={{ borderTop: "1px solid var(--border)" }}>
          <BeforeAfterPanel item={item} />
        </div>
      )}
    </div>
  );
}

export default function ReviewPage() {
  const [items, setItems]           = useState(MOCK_REVIEWS);
  const [filterCountry, setCountry] = useState("all");
  const [filterScore, setScore]     = useState("all");
  const [approved, setApproved]     = useState(0);
  const [rejected, setRejected]     = useState(0);

  const countries = [...new Set(MOCK_REVIEWS.map(i => i.country))];

  const filtered = items.filter(item => {
    const matchCountry = filterCountry === "all" || item.country === filterCountry;
    const matchScore   = filterScore === "all" ||
      (filterScore === "critical" && item.score < 5) ||
      (filterScore === "low"      && item.score >= 5 && item.score < 7);
    return matchCountry && matchScore;
  });

  const onApprove    = (id: string) => { setApproved(a => a+1); setItems(prev => prev.filter(i => i.id !== id)); };
  const onReject     = (id: string) => { setRejected(r => r+1); setItems(prev => prev.filter(i => i.id !== id)); };
  const onRegenerate = (id: string) => { console.log("Regenerate", id); };
  const onFlag       = (id: string) => { alert(`Content issue reported for ${id}`); };

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
            Review Queue
          </h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 6 }}>
            Tours requiring human review · Quality score below 7.0
          </p>
        </div>
        <div style={{ display: "flex", gap: 20, fontSize: 13 }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ color: "#22c55e", fontWeight: 700, fontSize: 20 }}>{approved}</div>
            <div style={{ color: "var(--text-muted)", fontSize: 11 }}>Approved</div>
          </div>
          <div style={{ textAlign: "center" }}>
            <div style={{ color: "#ef4444", fontWeight: 700, fontSize: 20 }}>{rejected}</div>
            <div style={{ color: "var(--text-muted)", fontSize: 11 }}>Rejected</div>
          </div>
          <div style={{ textAlign: "center" }}>
            <div style={{ color: "var(--brand-gold)", fontWeight: 700, fontSize: 20 }}>{items.length}</div>
            <div style={{ color: "var(--text-muted)", fontSize: 11 }}>Pending</div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, alignItems: "center" }}>
        <Filter size={14} style={{ color: "var(--text-muted)" }} />
        <select value={filterCountry} onChange={e => setCountry(e.target.value)}
          style={{ padding: "7px 14px", background: "var(--bg-card)",
            border: "1px solid var(--border)", borderRadius: 8,
            color: "var(--text-primary)", fontSize: 13 }}>
          <option value="all">All Countries</option>
          {countries.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={filterScore} onChange={e => setScore(e.target.value)}
          style={{ padding: "7px 14px", background: "var(--bg-card)",
            border: "1px solid var(--border)", borderRadius: 8,
            color: "var(--text-primary)", fontSize: 13 }}>
          <option value="all">All Scores</option>
          <option value="critical">Critical (&lt;5.0)</option>
          <option value="low">Low (5.0–6.9)</option>
        </select>
      </div>

      {/* Cards */}
      {filtered.length === 0 ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-muted)" }}>
          <CheckCircle size={40} style={{ margin: "0 auto 12px", color: "#166534" }} />
          <div style={{ fontWeight: 600 }}>Review queue is empty</div>
          <div style={{ fontSize: 13, marginTop: 6 }}>All tours have been reviewed</div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {filtered.map(item => (
            <ReviewCard key={item.id} item={item}
              onApprove={onApprove} onReject={onReject}
              onRegenerate={onRegenerate} onFlag={onFlag} />
          ))}
        </div>
      )}
    </div>
  );
}
