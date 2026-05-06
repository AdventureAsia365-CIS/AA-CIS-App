// app/layout.tsx
// SAFE VERSION:
// - Giữ nguyên Inter cho admin/internal (không thay đổi gì)
// - Thêm Fraunces + JetBrains Mono qua Google Fonts <link> cho portal dùng
// - IBM Plex Sans cũng load nhưng không đặt làm default body font
// Admin/Internal layout KHÔNG bị ảnh hưởng vì họ set font riêng trong layout của mình

import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Giữ Inter — đây là font default cho admin + internal + login (không thay đổi)
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "AA-CIS",
  description: "Adventure Asia Content Intelligence System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light">
      <head>
        {/* Theme restore — giữ nguyên như cũ */}
        <script dangerouslySetInnerHTML={{ __html: `
          (function() {
            var t = localStorage.getItem('cis_theme') || 'light';
            document.documentElement.setAttribute('data-theme', t);
          })();
        `}} />

        {/* Fraunces + JetBrains Mono — CHỈ dùng bởi portal _components/ui.tsx
            Admin/Internal không dùng các font này nên không bị ảnh hưởng */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=JetBrains+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className={inter.variable} style={{ margin: 0 }}>
        {children}
      </body>
    </html>
  );
}
