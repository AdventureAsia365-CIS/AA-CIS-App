import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";

export async function POST(req: NextRequest) {
  const { username, password } = await req.json();

  if (!password) {
    return NextResponse.json({ detail: "Missing credentials" }, { status: 400 });
  }

  try {
    const res = await fetch(`${API_URL}/admin/tenants`, {
      method: "GET",
      headers: { "x-admin-secret": password, "Content-Type": "application/json" },
    });

    if (!res.ok) {
      return NextResponse.json({ detail: "Backend auth failed" }, { status: 401 });
    }

    return NextResponse.json({
      token: password,
      role: "admin",
      name: username || "Admin",
    });
  } catch {
    return NextResponse.json({ detail: "Backend connection error" }, { status: 502 });
  }
}
