import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Batch, type Item } from "../api";
import ItemCard from "../components/ItemCard";
import { ProgressBar } from "./Batches";

/** Why: the batch page. Watch photos finish live, review them, download the results.
 *  Concept: POLLING (Decision Q6). Ask the server every 2 s while anything is
 *  queued/processing; stop when all are finished. Simpler than WebSockets.
 *  Examples: 5 photos processing -> page refreshes itself every 2 s
 *            all done            -> polling stops (no wasted requests)
 *            tab in background   -> skips polls until you come back
 *            Bob opens Alice's batch link -> "Batch not found." */
export default function BatchDetail({ id }: { id: string }) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.getBatch(id)
      .then((b) => { setBatch(b); setError(null); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Can't reach the server. Retrying…"));
  }, [id]);

  useEffect(load, [load]);

  const working = batch?.items.some((i) => i.status === "queued" || i.status === "processing") ?? false;
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => { if (!document.hidden) load(); }, 2000);
    return () => clearInterval(timer);       // Concept: cleanup, so no polling after leaving the page
  }, [working, load]);

  // After a Save or Retry, swap in the updated item right away (no full reload)
  const replace = (updated: Item) =>
    setBatch((b) => b && { ...b, items: b.items.map((i) => (i.id === updated.id ? updated : i)) });

  if (error && !batch) return <p role="alert" className="text-red-600">{error}</p>;
  if (!batch) return <p className="text-gray-500">Loading…</p>;

  const p = batch.progress;
  const short = batch.id.slice(0, 8);
  return (
    <div className="space-y-4">
      <a href="#/" className="text-sm underline">← All batches</a>
      <section className="space-y-2 rounded-xl bg-white p-4 shadow">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="font-semibold">Batch of {p.total} photo{p.total === 1 ? "" : "s"}</h1>
          <div className="flex gap-2 text-sm">
            <button onClick={() => api.download(`/batches/${batch.id}/export.csv`, `catalog-${short}.csv`).catch((e) => setError(e.message))}
                    className="rounded border px-3 py-1">Download CSV</button>
            <button disabled={!p.done && !p.needs_review}
                    onClick={() => api.download(`/batches/${batch.id}/images.zip`, `images-${short}.zip`).catch((e) => setError(e.message))}
                    className="rounded border px-3 py-1 disabled:opacity-40">Download images</button>
          </div>
        </div>
        <ProgressBar p={p} />
        <p className="text-sm text-gray-500">
          {p.done} done · {p.needs_review} need review · {p.failed} failed · {p.queued + p.processing} in progress
          {working && " · updating live"}
        </p>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      </section>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {batch.items.map((item) => <ItemCard key={item.id} item={item} onChange={(u) => { replace(u); if (u.status === "queued") load(); }} />)}
      </div>
    </div>
  );
}
