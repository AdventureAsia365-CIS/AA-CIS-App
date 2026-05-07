// app/(internal)/layout.tsx
// Passthrough — each internal page handles its own layout
export default function InternalLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
