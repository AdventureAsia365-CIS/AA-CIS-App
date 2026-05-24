import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";

export async function POST(req: NextRequest) {
  const { username, password } = await req.json();

  if (!username || !password) {
    return NextResponse.json({ detail: "Missing credentials" }, { status: 400 });
  }

  // Content staff login — verified against CONTENT_PASSWORD env var
  if (username === "content") {
    const contentPassword = process.env.CONTENT_PASSWORD;
    if (!contentPassword) {
      return NextResponse.json({ detail: "Content login not configured" }, { status: 503 });
    }
    if (password !== contentPassword) {
      return NextResponse.json({ detail: "Invalid credentials" }, { status: 401 });
    }
    return NextResponse.json({ token: password, role: "content", name: "Content" });
  }

  // Admin login — verify secret against backend
  try {
    const res = await fetch(`${API_URL}/admin/tenants`, {
      method: "GET",
      headers: { "x-admin-secret": password, "Content-Type": "application/json" },
    });

    if (!res.ok) {
      return NextResponse.json({ detail: "Invalid credentials" }, { status: 401 });
    }

    return NextResponse.json({ token: password, role: "admin", name: username || "Admin" });
  } catch {
    return NextResponse.json({ detail: "Backend connection error" }, { status: 502 });
  }
}
