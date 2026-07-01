// frontend/app/api/admin/[...path]/route.ts
// AA-232: forward verified admin identity (JWT sub claim) to the backend
// as x-admin-user-id, alongside the existing X-Admin-Secret (unchanged —
// still the service-to-service auth between Vercel and ECS).
//
// x-reviewer-id (AA-241 shim) is kept as-is for backward compatibility
// with the current FE (frontend/app/admin/review/page.tsx still sends it
// from localStorage) — NOT removed in this slice. Once the backend
// (admin_pipeline.py) is updated to read x-admin-user-id and write a real
// UUID into generated_content.reviewed_by, x-reviewer-id becomes fully
// redundant and can be retired in a follow-up.
//
// The JWT is decoded here WITHOUT re-verifying the signature — middleware.ts
// already verified it via /auth/verify-admin before this route is reached
// for any INTERNAL_PATHS/ADMIN_PATHS page. Direct API calls that bypass the
// page (hitting /api/admin/* without ever loading a gated page) would skip
// that check; decoding-without-verifying here is a pragmatic middle ground
// (avoids a network round-trip to /auth/verify-admin on every single proxied
// request) but is NOT a substitute for real verification if this proxy is
// ever reachable from a path outside middleware.ts's matcher config.
import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

/** Decode (not verify) a JWT payload — base64url middle segment. Returns
 * null on any malformed input rather than throwing, since this runs on
 * every proxied request and a bad/missing cookie must not 500 the route. */
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

async function handler(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  if (!ADMIN_SECRET) {
    return NextResponse.json({ detail: "Admin secret not configured" }, { status: 503 });
  }

  const { path } = await params;
  const pathStr = path.join("/");
  const search = req.nextUrl.search;
  const url = `${API_URL}/admin/${pathStr}${search}`;

  const contentType = req.headers.get("content-type") ?? "";
  const isMultipart = contentType.includes("multipart/form-data");

  const outHeaders: Record<string, string> = {
    "X-Admin-Secret": ADMIN_SECRET,
  };

  // AA-232: forward verified admin identity when a JWT cookie is present.
  const adminToken = req.cookies.get("cis_admin_token")?.value;
  if (adminToken) {
    const payload = decodeJwtPayloadUnsafe(adminToken);
    if (payload?.sub && typeof payload.sub === "string") {
      outHeaders["x-admin-user-id"] = payload.sub;
    }
    if (payload?.username && typeof payload.username === "string") {
      outHeaders["x-admin-username"] = payload.username;
    }
  }

  // AA-241 shim — kept for backward compat until backend reads
  // x-admin-user-id instead. See file header.
  const reviewerId = req.headers.get("x-reviewer-id");
  if (reviewerId) {
    outHeaders["x-reviewer-id"] = reviewerId;
  }

  let body: ArrayBuffer | string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    if (isMultipart) {
      outHeaders["Content-Type"] = contentType;
      body = await req.arrayBuffer();
    } else {
      outHeaders["Content-Type"] = "application/json";
      try { body = await req.text(); } catch { /* empty body */ }
    }
  }

  try {
    const res = await fetch(url, { method: req.method, headers: outHeaders, body });
    const resContentType = res.headers.get("content-type") ?? "application/json";
    const data = await res.arrayBuffer();
    return new NextResponse(data, {
      status: res.status,
      headers: { "Content-Type": resContentType },
    });
  } catch {
    return NextResponse.json({ detail: "Upstream connection error" }, { status: 502 });
  }
}

export const GET    = handler;
export const POST   = handler;
export const PUT    = handler;
export const PATCH  = handler;
export const DELETE = handler;
