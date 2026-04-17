import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import NavBar from "@/components/NavBar";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "AA-CIS — Content Intelligence System",
  description: "Adventure Asia Content Pipeline",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.variable} style={{ margin: 0 }}>
        <NavBar />
        <main style={{ maxWidth: 1280, margin: "0 auto", padding: "32px 32px" }}>
          {children}
        </main>
      </body>
    </html>
  );
}
