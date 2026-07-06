export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req(path: string, opts: RequestInit = {}) {
  const res = await fetch(path, { credentials: "include", ...opts });
  let body: any = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? res.statusText);
  return body;
}

function jsonPost(path: string, data: unknown) {
  return req(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

export const api = {
  register: (username: string, password: string) => jsonPost("/api/auth/register", { username, password }),
  login: (username: string, password: string) => jsonPost("/api/auth/login", { username, password }),
  logout: () => req("/api/auth/logout", { method: "POST" }),
  me: () => req("/api/auth/me"),
  uploadImport: (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return req("/api/imports", { method: "POST", body: fd });
  },
  listImports: () => req("/api/imports"),
  getImport: (id: number) => req(`/api/imports/${id}`),
  getSummary: () => req("/api/dashboard/summary"),
  getSeries: (key: string, range = "90d") => req(`/api/dashboard/metrics/${key}?range=${range}`),
  getRecords: () => req("/api/dashboard/records"),
};
