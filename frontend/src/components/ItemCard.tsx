import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type Category, type Item, type ItemStatus } from "../api";

const BADGE: Record<ItemStatus, string> = {
  queued: "bg-gray-200 text-gray-700",
  processing: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  needs_review: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
};
const CATEGORIES: Category[] = ["women", "men", "kids", "baby"];
const busy = (s: ItemStatus) => s === "queued" || s === "processing";

/** Why: show the clean photo if it exists, else the original (still processing / failed).
 *  Concept: OBJECT URL CLEANUP. Each blob URL holds the image in memory until revoked,
 *  so the cleanup function frees it when the card changes or disappears. */
function useItemImage(item: Item) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;              // Concept: ignore a slow answer if the card already changed
    api.imageUrl(item.id, "clean")
      .catch(() => api.imageUrl(item.id, "original"))
      .then((u) => { url = u; if (!cancelled) setSrc(u); })
      .catch(() => setSrc(null));
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [item.id, item.status]);           // status changes (e.g. -> done) = fetch the new clean image
  return src;
}

/** Why: the review step. Fix what the AI wrote, or retry a failed photo.
 *  Examples: change title + Save -> PATCH {"title": ...} only; "edited" mark appears
 *            failed photo -> Retry -> status "queued", the page polls again
 *            Save while still processing -> button disabled (the API would say 409) */
export default function ItemCard({ item, onChange }: { item: Item; onChange: (item: Item) => void }) {
  const src = useItemImage(item);
  const [form, setForm] = useState(() => toForm(item));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Concept: COMPARE VALUES, NOT OBJECTS. Polling delivers a NEW item object every
  // 2 s even when nothing changed; reacting to `item` would wipe what the user is
  // typing. Reset the form only when the server's values really change.
  // Example: user edits a title while other photos process -> the edit survives polls
  // Concept: ADJUST STATE WHILE RENDERING (React docs pattern). Remember the last
  // server values; if they changed, reset the form in the SAME render (no effect,
  // no extra render).
  const serverValues = JSON.stringify(toForm(item));
  const [lastServer, setLastServer] = useState(serverValues);
  if (lastServer !== serverValues) {
    setLastServer(serverValues);
    setForm(JSON.parse(serverValues));
  }

  const changes = diff(item, form);
  const edited = (field: string) => item.edited_fields.includes(field);

  async function run(action: () => Promise<Item>) {
    setSaving(true);
    setError(null);
    try { onChange(await action()); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't reach the server."); }
    finally { setSaving(false); }
  }

  return (
    <article className="space-y-3 rounded-xl bg-white p-3 shadow">
      <div className="aspect-square overflow-hidden rounded bg-gray-100">
        {src ? <img src={src} alt={item.title ?? item.original_filename} className="h-full w-full object-contain" />
             : <div className="flex h-full items-center justify-center text-sm text-gray-400">No image</div>}
      </div>

      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="truncate text-gray-500" title={item.original_filename}>{item.original_filename}</span>
        <span className={`rounded px-2 py-0.5 text-xs ${BADGE[item.status]}`}>{item.status.replace("_", " ")}</span>
      </div>
      {item.last_error && <p className="text-sm text-amber-700">{item.last_error}</p>}

      <fieldset disabled={busy(item.status) || saving} className="space-y-2 text-sm disabled:opacity-60">
        <Field label="Title" edited={edited("title")}>
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full rounded border px-2 py-1" />
        </Field>
        <Field label="Description" edited={edited("description")}>
          <textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full rounded border px-2 py-1" />
        </Field>
        <Field label="Category" edited={edited("category")}>
          <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="w-full rounded border px-2 py-1">
            <option value="">(none)</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
        <Field label="Colours (comma separated)" edited={edited("colours")}>
          <input value={form.colours} onChange={(e) => setForm({ ...form, colours: e.target.value })} className="w-full rounded border px-2 py-1" />
        </Field>
        <Field label="Tags (comma separated)" edited={edited("tags")}>
          <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} className="w-full rounded border px-2 py-1" />
        </Field>
      </fieldset>

      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <div className="flex gap-2">
        <button disabled={!Object.keys(changes).length || saving || busy(item.status)}
                onClick={() => run(() => api.updateItem(item.id, changes))}
                className="rounded bg-black px-3 py-1 text-sm text-white disabled:opacity-40">Save</button>
        {(item.status === "failed" || item.status === "needs_review") && (
          <button disabled={saving} onClick={() => run(() => api.retryItem(item.id))}
                  className="rounded border px-3 py-1 text-sm">Retry</button>
        )}
      </div>
    </article>
  );
}

function Field({ label, edited, children }: { label: string; edited: boolean; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-500">{label}{edited && <span className="ml-1 text-blue-600">· edited</span>}</span>
      {children}
    </label>
  );
}

/** The form keeps text; lists become "navy, white" while editing. */
function toForm(item: Item) {
  return {
    title: item.title ?? "", description: item.description ?? "", category: item.category ?? "",
    colours: item.colours.join(", "), tags: item.tags.join(", "),
  };
}

/** Why: send ONLY what changed (PATCH), so untouched fields stay AI-owned.
 *  Example: only the title changed -> {"title": "New"}; nothing changed -> {} (Save stays disabled) */
function diff(item: Item, form: ReturnType<typeof toForm>) {
  const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
  const out: Partial<Pick<Item, "title" | "description" | "category" | "colours" | "tags">> = {};
  if (form.title !== (item.title ?? "") && form.title.trim()) out.title = form.title.trim();
  if (form.description !== (item.description ?? "")) out.description = form.description;
  if (form.category !== (item.category ?? "") && form.category) out.category = form.category as Category;
  if (form.colours !== item.colours.join(", ")) out.colours = split(form.colours);
  if (form.tags !== item.tags.join(", ")) out.tags = split(form.tags);
  return out;
}
