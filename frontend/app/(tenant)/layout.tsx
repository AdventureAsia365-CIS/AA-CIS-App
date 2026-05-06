// app/(tenant)/layout.tsx
// Portal tự handle layout hoàn toàn (sidebar + topbar trong page.tsx)
// Layout này chỉ pass children through

export default function TenantLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
