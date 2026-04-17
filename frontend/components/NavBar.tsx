"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Upload, ClipboardList, BookOpen } from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard",    icon: LayoutDashboard },
  { href: "/upload",    label: "Upload",       icon: Upload },
  { href: "/review",    label: "Review Queue", icon: ClipboardList },
  { href: "/catalog",   label: "Catalog",      icon: BookOpen },
];

export default function NavBar() {
  const pathname = usePathname();

  return (
    <nav style={{
      background: "var(--brand-blackblue)",
      borderBottom: "1px solid rgba(219,150,40,0.2)",
      padding: "0 32px", height: 56,
      display: "flex", alignItems: "center", justifyContent: "space-between",
      position: "sticky", top: 0, zIndex: 50,
    }}>
      {/* Logo */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{
          width: 32, height: 32, background: "var(--brand-gold)",
          borderRadius: 8, display: "flex", alignItems: "center",
          justifyContent: "center", fontWeight: 800, fontSize: 13,
          color: "white", letterSpacing: 1,
        }}>AA</div>
        <span style={{ fontWeight: 600, color: "var(--brand-offwhite)", fontSize: 15 }}>CIS</span>
        <span style={{ color: "var(--text-muted)", fontSize: 12, marginLeft: 4 }}>
          Content Intelligence System
        </span>
      </div>

      {/* Nav links */}
      <div style={{ display: "flex", gap: 4 }}>
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link key={href} href={href} style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", borderRadius: 8, fontSize: 13,
              textDecoration: "none", transition: "all 0.15s",
              color: active ? "var(--brand-gold)" : "var(--text-secondary)",
              background: active ? "rgba(219,150,40,0.1)" : "transparent",
              fontWeight: active ? 600 : 400,
            }}>
              <Icon size={14} />
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
