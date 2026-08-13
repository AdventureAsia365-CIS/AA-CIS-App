// AA-345: same-origin proxy for /v1/atoms/* (POST /v1/atoms/decompose), needed
// by the new tour-atomization UI. Copied verbatim from
// app/api/pipeline/[...path]/route.ts (this repo's established pattern for a
// pass-through admin proxy: requireAdmin() verifies the real JWT server-side,
// then X-Admin-Secret is attached before the request ever reaches the ECS API
// — the client never sees or sends the secret itself).
import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/auth-server";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

async function handler(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const auth = await requireAdmin(req);
  if (!auth.ok) return auth.response;

  if (!ADMIN_SECRET) {
    return NextResponse.json({ detail: "Admin secret not configured" }, { status: 503 });
  }

  const { path } = await params;
  const pathStr = path.join("/");
  const search = req.nextUrl.search;
  const url = `${API_URL}/v1/atoms/${pathStr}${search}`;

  let body: string | undefined;
  const outHeaders: Record<string, string> = {
    "X-Admin-Secret": ADMIN_SECRET,
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    outHeaders["Content-Type"] = "application/json";
    try { body = await req.text(); } catch { /* empty body */ }
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

export const GET   = handler;
export const POST  = handler;
export const PUT   = handler;
export const PATCH = handler;
