import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";

const USERS = [
  {
    username: process.env.ADMIN_USERNAME ?? "",
    password: process.env.ADMIN_PASSWORD ?? "",
    role: "admin",
    name: process.env.ADMIN_DISPLAY_NAME ?? "Admin",
  },
  {
    username: process.env.CONTENT_USERNAME ?? "",
    password: process.env.CONTENT_PASSWORD ?? "",
    role: "content",
    name: process.env.CONTENT_DISPLAY_NAME ?? "Content Staff",
  },
  // Test accounts (optional — only active if env vars set)
  ...(process.env.ADMIN2_USERNAME ? [{
    username: process.env.ADMIN2_USERNAME,
    password: process.env.ADMIN2_PASSWORD ?? "",
    role: "admin" as const,
    name: "Admin (Test)",
  }] : []),
  ...(process.env.CONTENT2_USERNAME ? [{
    username: process.env.CONTENT2_USERNAME,
    password: process.env.CONTENT2_PASSWORD ?? "",
    role: "content" as const,
    name: "Content (Test)",
  }] : []),
];

export async function POST(req: NextRequest) {
  const { username, password } = await req.json();

  if (!username || !password) {
    return NextResponse.json({ detail: "Missing credentials" }, { status: 400 });
  }

  const user = USERS.find(
    (u) => u.username && u.password && u.username === username && u.password === password
  );

  if (!user) {
    await new Promise((r) => setTimeout(r, 200));
    return NextResponse.json({ detail: "Invalid username or password" }, { status: 401 });
  }

  const internalApiKey = process.env.INTERNAL_API_KEY ?? "";
  if (!internalApiKey) {
    return NextResponse.json({ detail: "Internal API key not configured" }, { status: 503 });
  }

  try {
    const res = await fetch(`${API_URL}/auth/tenant-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: internalApiKey }),
    });

    if (!res.ok) {
      return NextResponse.json({ detail: "Backend auth failed" }, { status: 502 });
    }

    const data = await res.json();

    return NextResponse.json({
      token: data.token,
      role: user.role,
      name: user.name,
    });
  } catch {
    return NextResponse.json({ detail: "Backend connection error" }, { status: 502 });
  }
}
