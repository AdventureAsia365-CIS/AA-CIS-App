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

  const contentType = req.headers.get("content-type") ?? "";
  const isMultipart = contentType.includes("multipart/form-data");

  const outHeaders: Record<string, string> = {
    "X-Admin-Secret": ADMIN_SECRET,
  };

  // AA-241: forward reviewer identity for the edit audit trail (generated_content.reviewed_by).
  // Temporary until AA-232 per-user auth; backend falls back to "admin" when absent.
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
