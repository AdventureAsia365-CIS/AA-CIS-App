// frontend/app/api/tenant/[...path]/route.ts
//
// AA-232 hotfix: the staff (admin/content) branch used to forward the
// client-readable cis_api_token cookie as x-admin-secret. Pre-AA-232 that
// cookie held the raw ADMIN_SECRET (the admin typed it in), so it happened
// to work — and, as a side effect, exposed ADMIN_SECRET in a non-httpOnly
// client cookie. Post-AA-232, login now sets cis_api_token to a JWT, so the
// forwarded value stopped matching ADMIN_SECRET → every staff call through
// this proxy 403'd ("Invalid admin secret").
//
// Fix: inject process.env.ADMIN_SECRET server-side for the staff branch —
// exactly like /api/admin/[...path]/route.ts already does — instead of
// forwarding any client cookie as the secret. This closes the accidental
// cookie exposure permanently (good) and restores staff access (the bug).
//
// Tenant branch is unchanged — still Bearer cis_tenant_token, still a real
// per-tenant JWT, never was the problem.
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

async function handler(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const cookieStore = await cookies();
  const role        = cookieStore.get("cis_role")?.value ?? "";
  const isStaff     = role === "admin" || role === "content";

  const headers: Record<string, string> = { "Content-Type": "application/json" };

  if (isStaff) {
    if (!ADMIN_SECRET) {
      return NextResponse.json({ detail: "Admin secret not configured" }, { status: 503 });
    }
    headers["x-admin-secret"] = ADMIN_SECRET;

    // AA-232: forward verified admin identity when present, same as
    // /api/admin/[...path]/route.ts. Content-role sessions don't carry a
    // JWT (separate login path) — this is a no-op for them.
    const adminToken = cookieStore.get("cis_admin_token")?.value;
    if (adminToken) {
      const payload = decodeJwtPayloadUnsafe(adminToken);
      if (payload?.sub && typeof payload.sub === "string") {
        headers["x-admin-user-id"] = payload.sub;
      }
    }
  } else {
    const tenantToken = cookieStore.get("cis_tenant_token")?.value ?? "";
    if (!tenantToken) {
      return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
    }
    headers["Authorization"] = `Bearer ${tenantToken}`;
  }

  const { path } = await params;
  const pathStr = path.join("/");
  const search = req.nextUrl.search;
  const url = `${API_URL}/${pathStr}${search}`;

  let body: string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    try { body = await req.text(); } catch { /* empty body */ }
  }

  try {
    const res = await fetch(url, { method: req.method, headers, body });
    const data = await res.text();
    return new NextResponse(data, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json({ detail: "Upstream connection error" }, { status: 502 });
  }
}

/** Decode (not verify) a JWT payload — see admin_proxy_route.ts for the
 * same helper + rationale (middleware.ts already verified the signature
 * before this route is reached for any gated page). */
function decodeJwtPayloadUnsafe(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const json = Buffer.from(parts[1], "base64url").toString("utf-8");
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export const GET    = handler;
export const POST   = handler;
export const PATCH  = handler;
export const DELETE = handler;
