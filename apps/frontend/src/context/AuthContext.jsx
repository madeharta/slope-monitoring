import { createContext, useContext, useState, useCallback, useRef } from "react";
const AuthContext = createContext(null);
const STORAGE_KEY = "slope_auth";
function loadStored() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(loadStored);
  const refreshingRef = useRef(null);
  const login = useCallback(async (email, password) => {
    const r = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const body = await r.json();
    if (!r.ok) {
      throw new Error(body.detail || "Login gagal");
    }
    const next = { accessToken: body.access_token, refreshToken: body.refresh_token, role: body.role, email };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    setAuth(next);
    return next;
  }, []);
  const logout = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    setAuth(null);
  }, []);
  const doRefresh = useCallback(async () => {
    if (refreshingRef.current) return refreshingRef.current;
    refreshingRef.current = (async () => {
      const stored = loadStored();
      if (!stored?.refreshToken) throw new Error("tidak ada refresh token tersimpan");
      const r = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: stored.refreshToken }),
      });
      if (!r.ok) throw new Error("refresh gagal — refresh token juga kadaluwarsa/invalid");
      const body = await r.json();
      const next = { ...stored, accessToken: body.access_token, refreshToken: body.refresh_token };
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      setAuth(next);
      return next;
    })();
    try {
      return await refreshingRef.current;
    } finally {
      refreshingRef.current = null;
    }
  }, []);
  const authFetch = useCallback(
    async (url, options = {}) => {
      if (!auth) throw new Error("authFetch dipanggil tanpa sesi aktif");
      const doFetch = (token) =>
        fetch(url, { ...options, headers: { ...options.headers, Authorization: `Bearer ${token}` } });
      let r = await doFetch(auth.accessToken);
      if (r.status === 401) {
        try {
          const refreshed = await doRefresh();
          r = await doFetch(refreshed.accessToken);
        } catch {
          logout();
          throw new Error("Sesi Anda berakhir — silakan login ulang.");
        }
      }
      return r;
    },
    [auth, doRefresh, logout]
  );
  return (
    <AuthContext.Provider value={{ auth, login, logout, authFetch, isAuthenticated: !!auth }}>
      {children}
    </AuthContext.Provider>
  );
}
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth dipanggil di luar <AuthProvider>");
  return ctx;
}
const ROLE_RANK = { viewer: 0, operator: 1, admin: 2 };
export function roleSatisfies(actualRole, minRole) {
  return (ROLE_RANK[actualRole] ?? -1) >= (ROLE_RANK[minRole] ?? 99);
}
