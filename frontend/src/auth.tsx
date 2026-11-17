// Concept: REACT CONTEXT. Login state lives in ONE place; any page can read it
// with useAuth() instead of passing it down through every component.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setOnSessionExpired, tokenStore, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;                 // true while checking a saved token on page load
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // No saved token = nothing to check, so we start "not loading" (no extra render)
  const [loading, setLoading] = useState(() => tokenStore.get() !== null);

  const logout = () => { tokenStore.clear(); setUser(null); };

  useEffect(() => {
    // An expired token anywhere in the app -> back to the login page
    setOnSessionExpired(() => setUser(null));
    // Page reload: is the saved token still valid? Ask the server, don't assume.
    // Example: token from yesterday (expired) -> /auth/me 401 -> show login
    if (!tokenStore.get()) return;
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    await api.login(email, password);
    setUser(await api.me());
  };

  // Register, then log straight in (one step for the user)
  const register = async (email: string, password: string) => {
    await api.register(email, password);
    await login(email, password);
  };

  return <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>;
}

/** Example: const { user, logout } = useAuth(); */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
