"use client";
// app/admin/_components/AdminSidebar.tsx

import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { LayoutDashboard, Users, Upload, Wand2, ClipboardList, Palette, Library, LogOut, Bell, Settings } from "lucide-react";
import { A, serif, sans } from "./adminUi";

interface Notif {
  id: number;
  event_type: string;
  title: string;
  message: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
}

const CONTENT_NAV = [
  { href: "/admin/upload",         icon: <Upload size={15} />,        label: "Upload (S0)" },
  { href: "/admin/s1-rewrite",      icon: <Wand2 size={15} />,         label: "S1 Rewrite" },
  { href: "/admin/review",         icon: <ClipboardList size={15} />, label: "Review Queue" },
  { href: "/admin/brand",          icon: <Palette size={15} />,       label: "Brand Identity" },
  { href: "/admin/master-content", icon: <Library size={15} />,       label: "Master Content" },
];

export default function AdminSidebar() {
  const router   = useRouter();
  const pathname = usePathname();
  const [role, setRole]         = useState("");
  const [userName, setUserName] = useState("");
  const [unread, setUnread]     = useState(0);
  const [showNotifs, setShowNotifs] = useState(false);
  const [notifs, setNotifs]     = useState<Notif[]>([]);

  const fetchCount = useCallback(() => {
    fetch("/api/admin/notifications/count")
      .then(r => r.ok ? r.json() : null)
      .then(d => d && setUnread(d.unread))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchCount();
    const id = setInterval(fetchCount, 30000);
    return () => clearInterval(id);
  }, [fetchCount]);

  function openNotifs() {
    setShowNotifs(v => !v);
    if (!showNotifs) {
      fetch("/api/admin/notifications?unread_only=false&limit=10")
        .then(r => r.ok ? r.json() : null)
        .then(d => d && setNotifs(d.items))
        .catch(() => {});
    }
  }

  function markAllRead() {
    fetch("/api/admin/notifications/read-all", { method: "PUT" })
      .then(() => { setUnread(0); setNotifs(n => n.map(x => ({ ...x, is_read: true }))); })
      .catch(() => {});
  }

  useEffect(() => {
    const r = document.cookie.split(";").find(c => c.trim().startsWith("cis_role="))?.split("=")[1] ?? "";
    const n = document.cookie.split(";").find(c => c.trim().startsWith("cis_user="))?.split("=")[1] ?? "";
    setRole(r);
    setUserName(n ? decodeURIComponent(n) : r === "admin" ? "Admin" : "Content");
  }, []);

  const isAdmin = role === "admin";

  function logout() {
    ["cis_role", "cis_user", "cis_api_token"]
      .forEach(k => (document.cookie = `${k}=; path=/; max-age=0`));
    router.push("/login");
  }

  function active(href: string) {
    return pathname === href || pathname.startsWith(href + "/");
  }

  return (
    <aside style={{
      width: 220, flexShrink: 0, background: A.ink, color: "#C9CFD8",
      padding: "22px 14px 24px", display: "flex", flexDirection: "column",
      gap: 28, position: "sticky", top: 0, height: "100vh", overflowY: "auto",
    }}>
      {/* Brand */}
      <div style={{ position: "relative" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, paddingBottom: 18, borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
          <div style={{
            width: 32, height: 32, borderRadius: 7, flexShrink: 0,
            background: isAdmin ? A.red : A.gold,
            display: "grid", placeItems: "center",
            fontFamily: serif, fontWeight: 700, color: "#fff", fontSize: 13,
          }}>AA</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: serif, fontSize: 14, fontWeight: 500, color: "#F4F1EC", letterSpacing: "-0.01em", lineHeight: 1.2 }}>
              CIS Admin
            </div>
            <div style={{ fontSize: 9.5, textTransform: "uppercase" as const, letterSpacing: "0.18em", color: isAdmin ? A.red : A.gold, fontWeight: 600, marginTop: 1 }}>
              {isAdmin ? "Administrator" : "Content Team"}
            </div>
          </div>
          {/* Notification bell */}
          <button onClick={openNotifs} title="Notifications" style={{
            position: "relative", background: "none", border: "none", cursor: "pointer",
            color: "#C9CFD8", display: "flex", padding: 4,
          }}>
            <Bell size={15} />
            {unread > 0 && (
              <span style={{
                position: "absolute", top: 0, right: 0,
                background: A.red, color: "#fff",
                borderRadius: 999, fontSize: 9, fontWeight: 700,
                minWidth: 14, height: 14, display: "grid", placeItems: "center",
                padding: "0 3px",
              }}>{unread > 99 ? "99+" : unread}</span>
            )}
          </button>
        </div>

        {/* Notification dropdown */}
        {showNotifs && (
          <div style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 100,
            background: "#2A333E", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
            maxHeight: 320, overflowY: "auto",
          }}>
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "10px 12px 8px", borderBottom: "1px solid rgba(255,255,255,0.07)",
            }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: "#F4F1EC" }}>Notifications</span>
              {unread > 0 && (
                <button onClick={markAllRead} style={{
                  background: "none", border: "none", cursor: "pointer",
                  fontSize: 10, color: A.gold, fontWeight: 600,
                }}>Mark all read</button>
              )}
            </div>
            {notifs.length === 0 ? (
              <div style={{ padding: "16px 12px", fontSize: 11, color: "#6E7681", textAlign: "center" }}>
                No notifications
              </div>
            ) : notifs.map(n => (
              <div key={n.id} style={{
                padding: "8px 12px",
                background: n.is_read ? "transparent" : "rgba(239,68,68,0.06)",
                borderBottom: "1px solid rgba(255,255,255,0.04)",
              }}>
                <div style={{ fontSize: 11, color: "#C9CFD8", fontWeight: n.is_read ? 400 : 600 }}>
                  {n.title || n.event_type}
                </div>
                {n.message && (
                  <div style={{ fontSize: 10, color: "#6E7681", marginTop: 2 }}>{n.message}</div>
                )}
                <div style={{ fontSize: 9.5, color: "#6E7681", marginTop: 2 }}>
                  {new Date(n.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Nav */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 24 }}>
        {/* Admin-only section */}
        {isAdmin && (
          <NavGroup label="Admin">
            <NavItem active={active("/admin/dashboard")} accent={A.red}
              icon={<LayoutDashboard size={15} />} label="Dashboard"
              onClick={() => router.push("/admin/dashboard")} />
            <NavItem active={active("/admin/tenants")} accent={A.red}
              icon={<Users size={15} />} label="Tenants"
              onClick={() => router.push("/admin/tenants")} />
          </NavGroup>
        )}

        {/* Content section — visible to all roles */}
        <NavGroup label={isAdmin ? "Content Team" : "Tools"}>
          {!isAdmin && (
            <NavItem active={active("/admin/dashboard")} accent={A.gold}
              icon={<LayoutDashboard size={15} />} label="Dashboard"
              onClick={() => router.push("/admin/dashboard")} />
          )}
          {CONTENT_NAV.map(n => (
            <NavItem key={n.href} active={active(n.href)} accent={isAdmin ? A.gold : A.gold}
              icon={n.icon} label={n.label} onClick={() => router.push(n.href)} />
          ))}
        </NavGroup>
      </div>

      {/* Settings — admin only */}
      {isAdmin && (
        <NavItem active={active("/admin/settings")} accent={A.red}
          icon={<Settings size={15} />} label="Settings"
          onClick={() => router.push("/admin/settings")} />
      )}

      {/* Footer */}
      <div style={{ paddingTop: 14, borderTop: "1px solid rgba(255,255,255,0.07)" }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 9,
          padding: 8, borderRadius: 8, background: "rgba(255,255,255,0.03)",
        }}>
          <div style={{
            width: 30, height: 30, borderRadius: 6,
            background: isAdmin ? A.red : A.gold,
            display: "grid", placeItems: "center",
            color: "#fff", fontWeight: 700, fontSize: 12, flexShrink: 0,
          }}>
            {userName.charAt(0).toUpperCase()}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: "#F4F1EC", fontSize: 12, fontWeight: 600 }}>{userName}</div>
            <div style={{ color: "#8A929D", fontSize: 10.5 }}>{isAdmin ? "Admin" : "Content"}</div>
          </div>
          <button onClick={logout} title="Sign out"
            style={{ background: "none", border: "none", cursor: "pointer", color: "#8A929D", display: "flex" }}>
            <LogOut size={13} />
          </button>
        </div>
      </div>
    </aside>
  );
}

function NavGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 9.5, textTransform: "uppercase" as const, letterSpacing: "0.16em", color: "#6E7681", padding: "0 10px 8px", fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>{children}</div>
    </div>
  );
}

function NavItem({ active, icon, label, accent, onClick }: {
  active: boolean; icon: React.ReactNode; label: string;
  accent: string; onClick: () => void;
}) {
  return (
    <button onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 10, width: "100%",
      padding: "8px 10px", borderRadius: 7, border: "none",
      background: active ? `${accent}18` : "transparent",
      color: active ? "#fff" : "#C9CFD8",
      fontSize: 13, fontWeight: 500, cursor: "pointer",
      textAlign: "left" as const, fontFamily: sans, position: "relative",
      transition: "background .15s, color .15s",
    }}>
      {active && (
        <span style={{ position: "absolute", left: 0, top: 8, bottom: 8, width: 2, background: accent, borderRadius: "0 2px 2px 0" }} />
      )}
      <span style={{ flexShrink: 0, opacity: active ? 1 : 0.75 }}>{icon}</span>
      <span style={{ flex: 1 }}>{label}</span>
    </button>
  );
}
