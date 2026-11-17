import { useEffect, useState } from "react";
import { api, ApiError, type BatchSummary, type Progress } from "../api";
import Upload from "../components/Upload";

/** Why: one look tells how far a batch is.
 *  Example: done 3, needs_review 1, failed 1, total 10 -> green 30%, amber 10%, red 10% */
export function ProgressBar({ p }: { p: Progress }) {
  const pct = (n: number) => `${p.total ? (n / p.total) * 100 : 0}%`;
  return (
    <div className="flex h-2 overflow-hidden rounded bg-gray-200" title={`${p.done} done · ${p.needs_review} review · ${p.failed} failed · ${p.total} total`}>
      <div className="bg-green-500" style={{ width: pct(p.done) }} />
      <div className="bg-amber-400" style={{ width: pct(p.needs_review) }} />
      <div className="bg-red-500" style={{ width: pct(p.failed) }} />
    </div>
  );
}

/** Why: the home page. Upload new photos, or open an earlier batch.
 *  States a real user sees: loading, API error, no batches yet, the list. */
export default function Batches() {
  const [batches, setBatches] = useState<BatchSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listBatches()
      .then(setBatches)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Can't reach the server."));
  }, []);

  return (
    <div className="space-y-6">
      <Upload onUploaded={(b) => { window.location.hash = `#/batches/${b.id}`; }} />

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Your batches</h2>
        {error && <p role="alert" className="text-red-600">{error}</p>}
        {!batches && !error && <p className="text-gray-500">Loading…</p>}
        {batches?.length === 0 && <p className="text-gray-500">No batches yet. Upload some photos above.</p>}
        {batches?.map((b) => (
          <a key={b.id} href={`#/batches/${b.id}`} className="block space-y-2 rounded-xl bg-white p-4 shadow hover:bg-gray-50">
            <div className="flex justify-between text-sm">
              <span>{new Date(b.created_at).toLocaleString()}</span>
              <span className="text-gray-500">{b.progress.done}/{b.progress.total} done</span>
            </div>
            <ProgressBar p={b.progress} />
          </a>
        ))}
      </section>
    </div>
  );
}
