import { useState, type FormEvent } from "react";
import { ApiError } from "../api";
import { useAuth } from "../auth";

/** Why: one page for both "log in" and "create account" (a toggle), because
 *  new users shouldn't have to hunt for a sign-up page.
 *  Examples: wrong password  -> "Incorrect email or password."  (from the API)
 *            email taken     -> "An account with this email already exists."
 *            API not running -> "Can't reach the server..." */
export default function Login() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();                 // stop the browser's full-page form submit
    setError(null);
    setBusy(true);                      // Concept: disable while busy, so a double-click can't send twice
    try {
      await (mode === "login" ? login(email, password) : register(email, password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server. Is the API running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl bg-white p-6 shadow">
        <h1 className="text-xl font-semibold">AI Catalog Assistant</h1>
        <p className="text-sm text-gray-500">{mode === "login" ? "Log in to your catalog" : "Create your account"}</p>

        <input type="email" required autoComplete="email" placeholder="Email"
               value={email} onChange={(e) => setEmail(e.target.value)}
               className="w-full rounded border px-3 py-2" />
        <input type="password" required minLength={8} placeholder="Password (8+ characters)"
               autoComplete={mode === "login" ? "current-password" : "new-password"}
               value={password} onChange={(e) => setPassword(e.target.value)}
               className="w-full rounded border px-3 py-2" />

        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

        <button disabled={busy} className="w-full rounded bg-black py-2 text-white disabled:opacity-50">
          {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
        </button>
        <button type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}
                className="w-full text-sm text-gray-600 underline">
          {mode === "login" ? "New here? Create an account" : "Already have an account? Log in"}
        </button>
      </form>
    </div>
  );
}
