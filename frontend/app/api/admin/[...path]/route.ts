import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

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

  const headers: Record<string, string> = {
    "X-Admin-Secret": ADMIN_SECRET,
    "Content-Type": "application/json",
  };

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
