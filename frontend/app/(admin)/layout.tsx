// app/(admin)/layout.tsx
// Passthrough — each admin page handles its own layout (sidebar + topbar)
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
