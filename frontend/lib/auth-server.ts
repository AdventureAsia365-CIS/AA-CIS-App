// frontend/lib/auth-server.ts
// AA-253 — shared server-side verification for BFF proxy route handlers.
//
// Route handlers under app/api/**/route.ts run outside middleware.ts's
// matcher (see middleware.ts header comment) — a cookie present on the
// request is NOT proof it was already checked. These helpers call the
// backend's real verify endpoints (same ones middleware.ts uses for page
// gating) so a route handler can independently confirm the caller's
// identity before forwarding X-Admin-Secret or a tenant Bearer token.
//
// Deliberately no dev/prod fail-open branch here (unlike middleware.ts):
// this is the last line of defense before the backend admin secret is
// attached to an outbound request, and there's no page to redirect to on
// failure — always fail closed.
import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";

function unauthorized(): NextResponse {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

export type RequireAdminResult =
  | { ok: true; adminId: string; role: string }
  | { ok: false; response: NextResponse };

export async function requireAdmin(request: NextRequest): Promise<RequireAdminResult> {
  const token = request.cookies.get("cis_admin_token")?.value;
  if (!token) {
    return { ok: false, response: unauthorized() };
  }

  try {
    const res = await fetch(`${API_URL}/auth/verify-admin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      signal: AbortSignal.timeout(3000),
    });

    if (!res.ok) {
      return { ok: false, response: unauthorized() };
    }

    const data = await res.json();
    return { ok: true, adminId: data.admin_id, role: data.role };
  } catch {
    // Network error / timeout — fail closed, no dev carve-out (see file header).
    return { ok: false, response: unauthorized() };
  }
}

export type RequireTenantResult =
  | { ok: true; tenantId: string }
  | { ok: false; response: NextResponse };

export async function requireTenant(request: NextRequest): Promise<RequireTenantResult> {
  const token = request.cookies.get("cis_tenant_token")?.value;
  if (!token) {
    return { ok: false, response: unauthorized() };
  }

  try {
    const res = await fetch(`${API_URL}/auth/verify-tenant`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      signal: AbortSignal.timeout(3000),
    });

    if (!res.ok) {
      return { ok: false, response: unauthorized() };
    }

    const data = await res.json();
    return { ok: true, tenantId: data.tenant_id };
  } catch {
    return { ok: false, response: unauthorized() };
  }
}
