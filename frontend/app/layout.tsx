import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "AA-CIS",
  description: "Adventure Asia Content Intelligence System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light">
      <head>
        <script dangerouslySetInnerHTML={{ __html: `
          (function() {
            var t = localStorage.getItem('cis_theme') || 'light';
            document.documentElement.setAttribute('data-theme', t);
          })();
        `}} />
      </head>
      <body className={inter.variable} style={{ margin:0 }}>
        {children}
      </body>
    </html>
  );
}
