import { useState, type DragEvent } from "react";
import { api, ApiError, type Batch } from "../api";

const MAX_FILES = 50;
const MAX_MB = 15;

/** Why: instant feedback BEFORE uploading (the server still re-checks everything).
 *  Bad files are SKIPPED, not blocking: the rest still upload (same rule as the server).
 *  Examples: [shirt.jpg, IMG_1.HEIC] -> ok: [shirt.jpg]; skipped: "IMG_1.HEIC: iPhone HEIC..."
 *            20 MB photo             -> skipped: "big.jpg: larger than 15 MB."
 *            51 good files           -> blocked: "Please choose at most 50 photos." */
function precheck(files: File[]): { ok: File[]; skipped: string[]; blocker: string | null } {
  const ok: File[] = [];
  const skipped: string[] = [];
  for (const f of files) {
    if (/\.hei[cf]$/i.test(f.name)) skipped.push(`${f.name}: iPhone HEIC isn't supported. Export as JPEG.`);
    else if (f.size > MAX_MB * 1024 * 1024) skipped.push(`${f.name}: larger than ${MAX_MB} MB.`);
    else ok.push(f);
  }
  const blocker = ok.length > MAX_FILES ? `Please choose at most ${MAX_FILES} photos.` : null;
  return { ok, skipped, blocker };
}

export default function Upload({ onUploaded }: { onUploaded: (batch: Batch) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  // Concept: IDEMPOTENCY KEY per chosen set. Clicking Upload twice, or retrying
  // after a network error, reuses it, so the server returns the SAME batch.
  // Choosing new files makes a new key.
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [messages, setMessages] = useState<string[]>([]);     // errors (red)
  const [result, setResult] = useState<Batch | null>(null);

  function choose(list: FileList | null) {
    const chosen = Array.from(list ?? []);
    setFiles(chosen);
    setKey(crypto.randomUUID());          // new photos = new upload
    setResult(null);
    setMessages([]);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();                   // stop the browser opening the dropped file
    setDragging(false);
    choose(e.dataTransfer.files);
  }

  async function upload() {
    setBusy(true);
    setMessages([]);
    try {
      const batch = await api.upload(check.ok, key);        // only the files that passed
      // Rejected files (e.g. a PDF renamed .jpg) only appear in this response,
      // so show them here; with none, go straight to the batch page
      if (batch.rejected.length) setResult(batch);
      else onUploaded(batch);
      setFiles([]);
    } catch (err) {
      setMessages([err instanceof ApiError ? err.message : "Upload failed. Check your connection and try again."]);
    } finally {
      setBusy(false);
    }
  }

  const check = precheck(files);
  const blocked = check.ok.length === 0 || check.blocker !== null || busy;
  return (
    <section className="space-y-3 rounded-xl bg-white p-4 shadow">
      <label
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`block cursor-pointer rounded-lg border-2 border-dashed p-8 text-center ${dragging ? "border-black bg-gray-50" : "border-gray-300"}`}
      >
        <input type="file" multiple accept="image/jpeg,image/png" className="hidden"
               onChange={(e) => choose(e.target.files)} />
        <p className="font-medium">Drop product photos here, or click to choose</p>
        <p className="text-sm text-gray-500">JPEG or PNG · up to {MAX_FILES} photos · {MAX_MB} MB each</p>
        {files.length > 0 && (
          <p className="mt-2 text-sm">
            {check.ok.length} photo{check.ok.length === 1 ? "" : "s"} ready
            {check.skipped.length > 0 && `, ${check.skipped.length} will be skipped`}
          </p>
        )}
      </label>

      {check.blocker && <p role="alert" className="text-sm text-red-600">{check.blocker}</p>}
      {check.skipped.map((m) => <p key={m} className="text-sm text-amber-700">Skipped: {m}</p>)}

      {messages.map((m) => <p key={m} role="alert" className="text-sm text-red-600">{m}</p>)}

      <button onClick={upload} disabled={blocked} className="rounded bg-black px-4 py-2 text-white disabled:opacity-40">
        {busy ? "Uploading…" : "Upload"}
      </button>

      {result && (
        <div className="rounded bg-amber-50 p-3 text-sm">
          <p className="font-medium">{result.items.length} uploaded, {result.rejected.length} skipped:</p>
          <ul className="list-disc pl-5">
            {result.rejected.map((r) => <li key={r.filename}>{r.filename}: {r.reason}</li>)}
          </ul>
          <button onClick={() => onUploaded(result)} className="mt-2 underline">Open batch →</button>
        </div>
      )}
    </section>
  );
}
