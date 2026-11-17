import { useEffect, useState } from "react";
import { useAuth } from "./auth";
import BatchDetail from "./pages/BatchDetail";
import Batches from "./pages/Batches";
import Login from "./pages/Login";

/** Why: the address bar decides the page, so Back/Forward and refresh work.
 *  Concept: HASH ROUTING. "#/batches/abc" never reaches the server; no router
 *  library needed for 2 pages.
 *  Example: "#/batches/3f9c..." -> batch page; anything else -> batch list */
function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);   // cleanup on unmount
  }, []);
  return hash;
}

export default function App() {
  const { user, loading, logout } = useAuth();
  const hash = useHashRoute();

  if (loading) return <p className="p-8 text-gray-500">Loading…</p>;
  if (!user) return <Login />;

  const batchId = hash.match(/^#\/batches\/([0-9a-f-]+)$/)?.[1];
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between border-b bg-white px-4 py-3">
        <a href="#/" className="font-semibold">AI Catalog Assistant</a>
        <div className="flex items-center gap-3 text-sm">
          <span className="hidden text-gray-500 sm:inline">{user.email}</span>
          <button onClick={logout} className="underline">Log out</button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl p-4">
        {/* key={batchId}: a fresh page (state reset) when switching batches */}
        {batchId ? <BatchDetail key={batchId} id={batchId} /> : <Batches />}
      </main>
    </div>
  );
}
