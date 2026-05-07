"use client";
import { useState, useEffect } from "react";
import InternalSidebar from "../_components/InternalSidebar";
import { A, sans, Card, SLabel, Btn, TopBar } from "../_components/internalUi";

interface BrandData {
  configured: boolean;
  system_prompt: string | null;
  style_guide: string | null;
  forbidden_words: string[];
  version?: number;
  updated_at?: string;
  history?: { version: number; is_active: boolean; system_prompt: string; style_guide: string; forbidden_words: string[]; updated_at: string | null }[];
}

export default function BrandPage() {
  const [data, setData]     = useState<BrandData | null>(null);
  const [saving, setSaving] = useState(false);
  const [sp, setSp]         = useState("");
  const [sg, setSg]         = useState("");
  const [fw, setFw]         = useState("");
  const [msg, setMsg]       = useState("");
  const [isAdmin, setIsAdmin]   = useState(false);
  const [userName, setUserName] = useState("");

  useEffect(() => {
    const role = document.cookie.split(";").find(c => c.trim().startsWith("cis_role="))?.split("=")[1];
    const name = document.cookie.split(";").find(c => c.trim().startsWith("cis_user="))?.split("=")[1];
    setIsAdmin(role === "admin");
    setUserName(name ? decodeURIComponent(name) : "");

    fetch("/api/tenant/pipeline/brand-identity")
      .then(r => r.json())
      .then((d: BrandData) => {
        setData(d);
        setSp(d.system_prompt || "");
        setSg(d.style_guide || "");
        setFw((d.forbidden_words || []).join(", "));
      });
  }, []);

  async function save() {
    setSaving(true); setMsg("");
    const r = await fetch("/api/tenant/pipeline/brand-identity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        system_prompt: sp,
        style_guide: sg,
        forbidden_words: fw.split(",").map(w => w.trim()).filter(Boolean),
      }),
    });
    setSaving(false);
    if (r.ok) {
      setMsg("Saved ✓");
      fetch("/api/tenant/pipeline/brand-identity").then(r => r.json()).then(setData);
    } else {
      setMsg("Save failed");
    }
  }

  function restore(v: NonNullable<BrandData["history"]>[0]) {
    setSp(v.system_prompt || "");
    setSg(v.style_guide || "");
    setFw((v.forbidden_words || []).join(", "));
    setMsg(`Restored version ${v.version} — save to apply`);
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: sans, background: A.bg }}>
      <InternalSidebar isAdmin={isAdmin} userName={userName} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar breadcrumb={["Content", "Brand Identity"]} />
        <main style={{ flex: 1, overflowY: "auto", padding: "28px 36px 56px" }}>
          <div style={{ maxWidth: 800 }}>
            {!data ? (
              <div style={{ color: A.muted, padding: 40 }}>Loading…</div>
            ) : (
              <>
                <Card style={{ marginBottom: 24 }}>
                  <SLabel>Brand Context / System Prompt</SLabel>
                  <textarea value={sp} onChange={e => setSp(e.target.value)} rows={5}
                    placeholder="e.g. You are a travel editor for Adventure Asia. Write for senior professionals aged 40-60..."
                    style={{ width: "100%", fontFamily: sans, fontSize: 13, border: `1px solid ${A.line}`, borderRadius: 6, padding: "10px 12px", resize: "vertical", boxSizing: "border-box", marginTop: 8 }} />

                  <div style={{ marginTop: 16, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", color: A.muted, marginBottom: 6 }}>Style Guide</div>
                  <textarea value={sg} onChange={e => setSg(e.target.value)} rows={4}
                    placeholder="e.g. Tone: calm, factual, editorial. Use active verbs. No superlatives..."
                    style={{ width: "100%", fontFamily: sans, fontSize: 13, border: `1px solid ${A.line}`, borderRadius: 6, padding: "10px 12px", resize: "vertical", boxSizing: "border-box" }} />

                  <div style={{ marginTop: 16, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", color: A.muted, marginBottom: 6 }}>Forbidden Words (comma-separated)</div>
                  <input value={fw} onChange={e => setFw(e.target.value)}
                    placeholder="e.g. curated, stunning, bespoke, paradise"
                    style={{ width: "100%", fontFamily: sans, fontSize: 13, border: `1px solid ${A.line}`, borderRadius: 6, padding: "8px 12px", boxSizing: "border-box" }} />

                  <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 20 }}>
                    <Btn onClick={save} disabled={saving}>{saving ? "Saving…" : "Save Brand Identity"}</Btn>
                    {msg && <span style={{ fontSize: 12, color: msg.includes("✓") ? A.green : A.red }}>{msg}</span>}
                  </div>
                </Card>

                {data.history && data.history.length > 1 && (
                  <Card>
                    <SLabel>Version History</SLabel>
                    {data.history.map(v => (
                      <div key={v.version} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: `1px solid ${A.line}` }}>
                        <div>
                          <span style={{ fontSize: 13, fontWeight: 500 }}>v{v.version}</span>
                          <span style={{ fontSize: 11, color: A.muted, marginLeft: 8 }}>{v.updated_at?.slice(0, 10)}</span>
                          {v.is_active && <span style={{ fontSize: 10, background: A.gold, color: "#fff", borderRadius: 4, padding: "1px 6px", marginLeft: 8 }}>active</span>}
                        </div>
                        <button onClick={() => restore(v)} style={{ fontSize: 11, color: A.gold, background: "none", border: "none", cursor: "pointer" }}>Restore</button>
                      </div>
                    ))}
                  </Card>
                )}
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
