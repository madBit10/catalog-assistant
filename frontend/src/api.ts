// Concept: ONE API CLIENT. Every request goes through request(), so the token,
// error messages and "session expired" are handled in ONE place, not per page.

// --- Types: the same shapes as the FastAPI schemas (TypeScript checks every use) ---
export type ItemStatus = "queued" | "processing" | "done" | "needs_review" | "failed";
export type Category = "women" | "men" | "kids" | "baby";

export interface Item {
  id: string;
  original_filename: string;
  status: ItemStatus;
  last_error: string | null;
  title: string | null;
  description: string | null;
  category: Category | null;
  colours: string[];
  tags: string[];
  is_product: boolean | null;
  edited_fields: string[];
}
export interface Progress { total: number; queued: number; processing: number; done: number; needs_review: number; failed: number }
export interface BatchSummary { id: string; created_at: string; progress: Progress }
export interface Batch extends BatchSummary { items: Item[]; rejected: { filename: string; reason: string }[] }
export interface User { id: string; email: string }

export class ApiError extends Error {
  // Explicit field (not a `public status` constructor shortcut): this project's
  // tsconfig has erasableSyntaxOnly, which only allows TypeScript that can be
  // stripped away without changing the JavaScript.
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// Concept: TOKEN STORAGE. localStorage survives page reloads. Trade-off: any
// injected script could read it (XSS). An httpOnly cookie is safer, but needs
// backend changes; noted for later. try/catch: private mode can block storage.
const TOKEN_KEY = "catalog_token";
export const tokenStore = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* still works this session */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* nothing to clear */ } },
};

// Set by auth.tsx: what to do when the token expires (log out -> login page)
let onSessionExpired = () => {};
export function setOnSessionExpired(fn: () => void) { onSessionExpired = fn; }

/** Why: FastAPI errors come in 3 shapes; the user should always see a sentence.
 *  Examples: {"detail": "Batch not found."}                    -> "Batch not found."
 *            {"detail": [{"msg": "String should have..."}]}    -> "String should have..."
 *            {"detail": {"message": "None of the files..."}}   -> "None of the files..." */
async function errorMessage(res: Response): Promise<string> {
  try {
    const { detail } = await res.json();
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail[0]?.msg ?? "Invalid input.";
    if (detail?.message) return detail.message;
  } catch { /* not JSON */ }
  return `Something went wrong (${res.status}).`;
}

/** Why: the single fetch wrapper. Adds the token; turns errors into ApiError.
 *  Example: request<Batch>("/batches/123") -> Batch, or throws ApiError("Batch not found.", 404)
 *  expireOn401=false for login itself: a wrong password is not an "expired session". */
async function request<T>(path: string, init: RequestInit = {}, expireOn401 = true): Promise<Response & { json(): Promise<T> }> {
  const token = tokenStore.get();
  const res = await fetch(path, {
    ...init,
    headers: { ...(init.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (res.status === 401 && expireOn401) {
    tokenStore.clear();
    onSessionExpired();
    throw new ApiError("Your session expired. Please log in again.", 401);
  }
  if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
  return res;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  register: async (email: string, password: string) =>
    (await request<User>("/auth/register", { method: "POST", ...json({ email, password }) }, false)).json(),

  /** OAuth2 form: the email goes in "username" (same as the /docs Authorize box) */
  login: async (email: string, password: string) => {
    const body = new URLSearchParams({ username: email, password });
    const res = await request<{ access_token: string }>("/auth/login", { method: "POST", body }, false);
    tokenStore.set((await res.json()).access_token);
  },

  me: async () => (await request<User>("/auth/me")).json(),
  listBatches: async () => (await request<BatchSummary[]>("/batches")).json(),
  getBatch: async (id: string) => (await request<Batch>(`/batches/${id}`)).json(),

  /** Concept: FormData = multipart upload. Each file is appended as "files".
   *  The key comes from the caller, ONE per upload click (double-click safe). */
  upload: async (files: File[], idempotencyKey: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return (await request<Batch>("/batches", { method: "POST", body: form, headers: { "Idempotency-Key": idempotencyKey } })).json();
  },

  updateItem: async (id: string, changes: Partial<Pick<Item, "title" | "description" | "category" | "colours" | "tags">>) =>
    (await request<Item>(`/items/${id}`, { method: "PATCH", ...json(changes) })).json(),

  retryItem: async (id: string) => (await request<Item>(`/items/${id}/retry`, { method: "POST" })).json(),

  /** Why: <img src> can't send our token, so fetch the image WITH the token and
   *  give <img> a local blob: URL instead.
   *  Example: await api.imageUrl(id) -> "blob:http://localhost:5173/9f2c..." */
  imageUrl: async (itemId: string, kind: "clean" | "original" = "clean") =>
    URL.createObjectURL(await (await request(`/items/${itemId}/image?kind=${kind}`)).blob()),

  /** Why: CSV/zip downloads need the token too: fetch -> blob -> click a hidden link. */
  download: async (path: string, filename: string) => {
    const url = URL.createObjectURL(await (await request(path)).blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    a.click();
    URL.revokeObjectURL(url);           // free the memory
  },
};
