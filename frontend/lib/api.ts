const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"\;

export async function fetchTours(limit = 50, offset = 0) {
  const res = await fetch(`${API_BASE}/tours?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error("Failed to fetch tours");
  return res.json();
}

export async function fetchTour(id: string) {
  const res = await fetch(`${API_BASE}/tours/${id}`);
  if (!res.ok) throw new Error("Tour not found");
  return res.json();
}

export async function fetchCatalog(status?: string) {
  const url = status
    ? `${API_BASE}/catalog?status=${status}`
    : `${API_BASE}/catalog`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch catalog");
  return res.json();
}

export async function fetchPipelineRuns() {
  const res = await fetch(`${API_BASE}/pipeline/runs`);
  if (!res.ok) throw new Error("Failed to fetch pipeline runs");
  return res.json();
}

export async function uploadFile(file: File): Promise<{ source_id: string; rows: number }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}

export async function approveVersion(versionId: string) {
  const res = await fetch(`${API_BASE}/versions/${versionId}/approve`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Approve failed");
  return res.json();
}

export async function rejectVersion(versionId: string, note: string) {
  const res = await fetch(`${API_BASE}/versions/${versionId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  if (!res.ok) throw new Error("Reject failed");
  return res.json();
}
