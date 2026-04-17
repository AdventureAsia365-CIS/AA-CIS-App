"use client";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";

export default function LogoutButton({ redirectTo = "/login" }: { redirectTo?: string }) {
  const router = useRouter();

  const logout = () => {
    document.cookie = "cis_role=; path=/; max-age=0";
    document.cookie = "cis_user=; path=/; max-age=0";
    document.cookie = "cis_tenant_key=; path=/; max-age=0";
    router.push(redirectTo);
  };

  return (
    <button onClick={logout} style={{
      display:"flex", alignItems:"center", gap:6,
      padding:"6px 14px", borderRadius:8, fontSize:13,
      background:"none", border:"1px solid var(--border)",
      color:"var(--text-muted)", cursor:"pointer",
      transition:"all 0.15s",
    }}
    onMouseEnter={e => {
      (e.currentTarget as HTMLElement).style.color = "#ef4444";
      (e.currentTarget as HTMLElement).style.borderColor = "rgba(239,68,68,0.3)";
    }}
    onMouseLeave={e => {
      (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
      (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
    }}>
      <LogOut size={13} /> Logout
    </button>
  );
}
