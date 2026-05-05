"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { User, Lock } from "lucide-react";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);
  const router = useRouter();

  const login = async () => {
    if (!username || !password) { setError("Enter username and password"); return; }
    setLoading(true);
    setError("");

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || "Invalid username or password");
        setLoading(false);
        return;
      }

      document.cookie = `cis_api_token=${encodeURIComponent(data.token)}; path=/; max-age=86400`;
      document.cookie = `cis_role=${data.role}; path=/; max-age=86400`;
      document.cookie = `cis_user=${encodeURIComponent(data.name)}; path=/; max-age=86400`;

      router.push(data.role === "admin" ? "/dashboard" : "/upload");
    } catch {
      setError("Network error — check connection");
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight:"100vh", display:"flex", alignItems:"center", justifyContent:"center", background:"var(--bg-primary)" }}>
      <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:16, padding:40, width:380 }}>
        <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:32 }}>
          <div style={{ width:36, height:36, background:"var(--brand-gold)", borderRadius:8, display:"flex", alignItems:"center", justifyContent:"center", fontWeight:800, color:"white" }}>AA</div>
          <div>
            <div style={{ fontWeight:700, color:"var(--text-primary)", fontSize:16 }}>CIS Internal</div>
            <div style={{ fontSize:11, color:"var(--text-muted)" }}>Staff Login</div>
          </div>
        </div>

        <div style={{ marginBottom:14 }}>
          <label style={{ fontSize:11, fontWeight:600, color:"var(--text-muted)", textTransform:"uppercase" as const, letterSpacing:1, display:"block", marginBottom:8 }}>Username</label>
          <div style={{ position:"relative" }}>
            <User size={13} style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:"var(--text-muted)" }} />
            <input type="text" value={username} onChange={e => { setUsername(e.target.value); setError(""); }}
              placeholder="Username"
              onKeyDown={e => e.key === "Enter" && login()}
              style={{ width:"100%", padding:"10px 12px 10px 34px", background:"var(--bg-primary)", border:`1px solid ${error ? "#ef4444" : "var(--border)"}`, borderRadius:8, color:"var(--text-primary)", fontSize:13, outline:"none" }} />
          </div>
        </div>

        <div style={{ marginBottom:20 }}>
          <label style={{ fontSize:11, fontWeight:600, color:"var(--text-muted)", textTransform:"uppercase" as const, letterSpacing:1, display:"block", marginBottom:8 }}>Password</label>
          <div style={{ position:"relative" }}>
            <Lock size={13} style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:"var(--text-muted)" }} />
            <input type="password" value={password} onChange={e => { setPassword(e.target.value); setError(""); }}
              placeholder="••••••••"
              onKeyDown={e => e.key === "Enter" && login()}
              style={{ width:"100%", padding:"10px 12px 10px 34px", background:"var(--bg-primary)", border:`1px solid ${error ? "#ef4444" : "var(--border)"}`, borderRadius:8, color:"var(--text-primary)", fontSize:13, outline:"none" }} />
          </div>
          {error && <div style={{ fontSize:12, color:"#ef4444", marginTop:6 }}>{error}</div>}
        </div>

        <button onClick={login} disabled={loading}
          style={{ width:"100%", padding:12, background:"var(--brand-gold)", border:"none", borderRadius:8, color:"white", fontSize:14, fontWeight:700, cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1 }}>
          {loading ? "Connecting..." : "Login"}
        </button>

        <div style={{ marginTop:16, textAlign:"center" as const }}>
          <a href="/tenant-login" style={{ fontSize:12, color:"var(--text-muted)", textDecoration:"none" }}>B2B Tenant login →</a>
        </div>
      </div>
    </div>
  );
}
