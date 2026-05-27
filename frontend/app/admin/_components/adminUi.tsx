// app/(admin)/_components/adminUi.tsx
// Design system for admin — red accent, same base tokens as portal

import { Loader2 } from "lucide-react";

export const A = {
  // Accent
  red:       "#EF4444",
  redSoft:   "#FEE2E2",
  redTint:   "#FFF1F1",
  redBorder: "#FECACA",
  // Base (shared with portal)
  ink:       "#1F2933",
  ink2:      "#2A333E",
  ink3:      "#3A4453",
  body:      "#33363D",
  muted:     "#6B7380",
  muted2:    "#9099A6",
  bg:        "#F8F6F2",
  card:      "#FFFFFF",
  line:      "#E9E4DB",
  line2:     "#F0EBE0",
  green:     "#22C55E",
  greenSoft: "#E4F1E9",
  amber:     "#F59E0B",
  amberSoft: "#FEF3C7",
  gold:      "#DB9628",
  goldTint:  "#FBF3E3",
} as const;

export const serif = "'Fraunces', Georgia, serif";
export const mono  = "'JetBrains Mono', 'IBM Plex Mono', monospace";
export const sans  = "'IBM Plex Sans', system-ui, sans-serif";

// ── Card ─────────────────────────────────────────────────────────────────────
export function Card({ children, style = {}, dark = false }: {
  children: React.ReactNode; style?: React.CSSProperties; dark?: boolean;
}) {
  return (
    <div style={{
      background: dark ? `linear-gradient(160deg,${A.ink} 0%,${A.ink2} 100%)` : A.card,
      border: `1px solid ${dark ? A.ink2 : A.line}`,
      borderRadius: 12, padding: "20px 22px", position: "relative",
      ...style,
    }}>{children}</div>
  );
}

// ── Section label ─────────────────────────────────────────────────────────────
export function SLabel({ children, light = false, style }: { children: React.ReactNode; light?: boolean; style?: React.CSSProperties }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 600, textTransform: "uppercase",
      letterSpacing: "0.14em", color: light ? "rgba(255,255,255,0.5)" : A.muted,
      marginBottom: 14, ...style,
    }}>{children}</div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────
export function StatCard({ label, value, sub, accent = A.red, icon }: {
  label: string; value: string; sub?: string; accent?: string; icon?: React.ReactNode;
}) {
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        {icon && (
          <div style={{ padding: 8, borderRadius: 8, background: `${accent}15`, color: accent }}>
            {icon}
          </div>
        )}
        <span style={{ fontSize: 12, color: A.muted }}>{label}</span>
      </div>
      <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500, color: A.ink, letterSpacing: "-0.02em" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: A.muted2, marginTop: 4 }}>{sub}</div>}
    </Card>
  );
}

// ── Tab bar ───────────────────────────────────────────────────────────────────
export function TabBar({ tabs, active, onChange }: {
  tabs: { key: string; label: string }[];
  active: string;
  onChange: (k: string) => void;
}) {
  return (
    <div style={{
      display: "flex", gap: 4, padding: "4px",
      background: A.line2, borderRadius: 10, width: "fit-content",
    }}>
      {tabs.map(t => (
        <button key={t.key} onClick={() => onChange(t.key)} style={{
          padding: "7px 16px", borderRadius: 7, border: "none",
          background: active === t.key ? A.card : "transparent",
          color: active === t.key ? A.ink : A.muted,
          fontSize: 13, fontWeight: active === t.key ? 600 : 400,
          cursor: "pointer", fontFamily: sans,
          boxShadow: active === t.key ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
          transition: "all .15s",
        }}>{t.label}</button>
      ))}
    </div>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────────
export function Badge({ children, color = "gray" }: {
  children: React.ReactNode;
  color?: "red" | "green" | "amber" | "gray" | "gold" | "blue" | "purple";
}) {
  const s = {
    red:    { bg: "#FEE2E2", c: "#991B1B" },
    green:  { bg: "#D1FAE5", c: "#065F46" },
    amber:  { bg: "#FEF3C7", c: "#92400E" },
    gray:   { bg: "#F3F4F6", c: "#4B5563" },
    gold:   { bg: "#FBF3E3", c: "#92400E" },
    blue:   { bg: "#DBEAFE", c: "#1E40AF" },
    purple: { bg: "#EDE9FE", c: "#5B21B6" },
  }[color];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: 11, fontWeight: 600, padding: "3px 9px",
      borderRadius: 999, letterSpacing: "0.04em", textTransform: "uppercase",
      background: s.bg, color: s.c,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: s.c, display: "block", flexShrink: 0 }} />
      {children}
    </span>
  );
}

// ── Spinner ───────────────────────────────────────────────────────────────────
export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} style={{ animation: "spin 1s linear infinite", color: A.red }} />;
}

export function LoadingScreen({ msg = "Loading..." }: { msg?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 300, gap: 10 }}>
      <Spinner size={22} /><span style={{ fontSize: 13, color: A.muted }}>{msg}</span>
    </div>
  );
}

// ── Button ────────────────────────────────────────────────────────────────────
export function Btn({ children, onClick, variant = "secondary", size = "md", disabled = false, style = {} }: {
  children: React.ReactNode; onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg"; disabled?: boolean; style?: React.CSSProperties;
}) {
  const pad = { sm: "5px 12px", md: "8px 16px", lg: "10px 22px" }[size];
  const fz  = { sm: 11, md: 13, lg: 14 }[size];
  const base: Record<string, React.CSSProperties> = {
    primary:   { background: A.red,     color: "#fff",  border: `1px solid ${A.red}` },
    secondary: { background: A.card,    color: A.ink3,  border: `1px solid ${A.line}` },
    danger:    { background: A.redSoft, color: A.red,   border: `1px solid ${A.redBorder}` },
    ghost:     { background: "transparent", color: A.muted, border: `1px solid ${A.line}` },
  };
  return (
    <button onClick={onClick} disabled={disabled} style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
      padding: pad, borderRadius: 8, fontSize: fz, fontWeight: 600,
      cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
      transition: "opacity .15s", fontFamily: sans,
      ...base[variant], ...style,
    }}>{children}</button>
  );
}

// ── Table wrapper ─────────────────────────────────────────────────────────────
export const TH: React.CSSProperties = {
  padding: "10px 16px", fontSize: 11, fontWeight: 600,
  textTransform: "uppercase", letterSpacing: "0.1em",
  color: A.muted, textAlign: "left", background: A.bg,
  borderBottom: `1px solid ${A.line}`,
};

export const TD: React.CSSProperties = {
  padding: "13px 16px", fontSize: 13, color: A.body,
  borderBottom: `1px solid ${A.line2}`,
};

// ── TOOLTIP (recharts) ────────────────────────────────────────────────────────
export const CHART_TOOLTIP = {
  contentStyle: {
    background: A.ink, border: `1px solid ${A.ink2}`,
    borderRadius: 8, fontSize: 12, color: "#F8F6F2",
  },
  labelStyle: { color: "#F8F6F2" },
};

// ── Chart card ────────────────────────────────────────────────────────────────
export function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <SLabel>{title}</SLabel>
      {children}
    </Card>
  );
}
