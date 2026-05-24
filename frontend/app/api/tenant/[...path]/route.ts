import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";

async function handler(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const cookieStore = await cookies();
  const tenantToken = cookieStore.get("cis_tenant_token")?.value ?? "";
  const adminSecret = cookieStore.get("cis_api_token")?.value ?? "";

  if (!tenantToken && !adminSecret) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const { path } = await params;
  const pathStr = path.join("/");
  const search = req.nextUrl.search;
  const url = `${API_URL}/${pathStr}${search}`;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (adminSecret) {
    headers["x-admin-secret"] = adminSecret;
  } else {
    headers["Authorization"] = `Bearer ${tenantToken}`;
  }

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

export const GET    = handler;
export const POST   = handler;
export const PATCH  = handler;
export const DELETE = handler;
