"use client";
// app/(internal)/_components/InternalSidebar.tsx

import { useRouter, usePathname } from "next/navigation";
import { Upload, ClipboardList, BookOpen, LayoutDashboard, LogOut } from "lucide-react";
import { A, serif, sans } from "./internalUi";

const NAV = [
  { href: "/upload",    icon: <Upload size={15} />,       label: "Upload" },
  { href: "/review",    icon: <ClipboardList size={15} />, label: "Review Queue" },
  { href: "/catalog",   icon: <BookOpen size={15} />,     label: "Catalog" },
];

export default function InternalSidebar({ isAdmin = false, userName = "Content" }: {
  isAdmin?: boolean; userName?: string;
}) {
  const router   = useRouter();
  const pathname = usePathname();

  function logout() {
    ["cis_role","cis_user","cis_api_token"].forEach(k => (document.cookie = `${k}=; path=/; max-age=0`));
    router.push("/login");
  }

  return (
    <aside style={{
      width: 220, flexShrink: 0, background: A.ink, color: "#C9CFD8",
      padding: "22px 14px 24px", display: "flex", flexDirection: "column",
      gap: 28, position: "sticky", top: 0, height: "100vh", overflowY: "auto",
    }}>
      {/* Brand */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, paddingBottom: 18, borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
        <div style={{
          width: 32, height: 32, borderRadius: 7, flexShrink: 0,
          background: `linear-gradient(135deg, ${A.gold} 0%, #B97A1B 100%)`,
          display: "grid", placeItems: "center",
          fontFamily: serif, fontWeight: 600, color: A.ink, fontSize: 14,
        }}>A</div>
        <div>
          <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 500, color: "#F4F1EC", letterSpacing: "-0.01em", lineHeight: 1.2 }}>
            CIS Content
          </div>
          <div style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: "0.18em", color: A.gold, fontWeight: 600, marginTop: 1 }}>
            {isAdmin ? "Admin access" : "Content Team"}
          </div>
        </div>
      </div>

      {/* Nav */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 26 }}>
        {isAdmin && (
          <div>
            <div style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: "0.16em", color: "#6E7681", padding: "0 10px 8px", fontWeight: 600 }}>Admin</div>
            <NavItem active={false} icon={<LayoutDashboard size={15} />} label="Dashboard" onClick={() => router.push("/dashboard")} />
          </div>
        )}
        <div>
          <div style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: "0.16em", color: "#6E7681", padding: "0 10px 8px", fontWeight: 600 }}>Content</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {NAV.map(n => (
              <NavItem key={n.href} active={pathname === n.href}
                icon={n.icon} label={n.label} onClick={() => router.push(n.href)} />
            ))}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div style={{ paddingTop: 14, borderTop: "1px solid rgba(255,255,255,0.07)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, padding: 8, borderRadius: 8, background: "rgba(255,255,255,0.03)" }}>
          <div style={{
            width: 30, height: 30, borderRadius: 6, background: A.ink3,
            display: "grid", placeItems: "center",
            color: "#F4E2C2", fontWeight: 600, fontSize: 12, flexShrink: 0,
          }}>
            {userName.charAt(0).toUpperCase()}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: "#F4F1EC", fontSize: 12, fontWeight: 600 }}>{userName}</div>
            <div style={{ color: "#8A929D", fontSize: 10.5 }}>{isAdmin ? "Admin" : "Content"}</div>
          </div>
          <button onClick={logout} title="Sign out" style={{ background: "none", border: "none", cursor: "pointer", color: "#8A929D", display: "flex" }}>
            <LogOut size={13} />
          </button>
        </div>
      </div>
    </aside>
  );
}

function NavItem({ active, icon, label, onClick }: {
  active: boolean; icon: React.ReactNode; label: string; onClick: () => void;
}) {
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 10, width: "100%",
      padding: "8px 10px", borderRadius: 7, border: "none",
      background: active ? "rgba(219,150,40,0.12)" : "transparent",
      color: active ? "#fff" : "#C9CFD8",
      fontSize: 13, fontWeight: 500, cursor: "pointer",
      textAlign: "left", fontFamily: sans, position: "relative",
      transition: "background .15s, color .15s",
    }}>
      {active && <span style={{ position: "absolute", left: 0, top: 8, bottom: 8, width: 2, background: A.gold, borderRadius: "0 2px 2px 0" }} />}
      <span style={{ flexShrink: 0, opacity: active ? 1 : 0.75 }}>{icon}</span>
      <span style={{ flex: 1 }}>{label}</span>
    </button>
  );
}
