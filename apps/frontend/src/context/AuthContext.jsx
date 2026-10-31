// Kontrak backend (apps/api/routers/v1/auth.py, common/security.py):
//   POST /api/v1/auth/login {email, password} -> {access_token, refresh_token, role}
//   POST /api/v1/auth/refresh {refresh_token} -> {access_token, refresh_token} (ROTATED)
//   access_token: JWT, expired 15 menit; refresh_token: 7 hari.
//
// Silent token refresh (2026-09-20, sebelumnya TIDAK ADA — item pending
// sejak awal proyek): authFetch() sekarang otomatis coba refresh SEKALI
// kalau dapat 401, lalu ulangi request aslinya dengan token baru. Kalau
// refresh JUGA gagal (refresh token juga kadaluwarsa/invalid), logout
// paksa — user harus login ulang, tidak ada infinite retry loop.

import { createContext, useContext, useState, useCallback, useRef } from "react";

const AuthContext = createContext(null);

const STORAGE_KEY = "slope_auth"; // sessionStorage, bukan localStorage —
// sengaja hilang saat tab ditutup, sesuai konvensi dashboard keselamatan
// (operator tidak boleh "lupa logout" di komputer bersama)

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
  const refreshingRef = useRef(null); // in-flight refresh promise — cegah beberapa authFetch() yang 401 bersamaan memicu banyak refresh sekaligus

  const login = useCallback(async (email, password) => {
    const r = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const body = await r.json();
    if (!r.ok) {
      // Backend selalu balas envelope {"ok": false, "error": "...", "detail": "..."}
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
    if (refreshingRef.current) return refreshingRef.current; // sudah ada refresh berjalan, tunggu itu saja
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

// Role hierarchy kumulatif — HARUS sama persis dengan common/security.py
// ROLE_RANK di backend. Duplikasi ini disengaja (frontend tidak boleh
// import Python), tapi berarti kalau backend berubah, ini WAJIB ikut diubah.
const ROLE_RANK = { viewer: 0, operator: 1, admin: 2 };

export function roleSatisfies(actualRole, minRole) {
  return (ROLE_RANK[actualRole] ?? -1) >= (ROLE_RANK[minRole] ?? 99);
}
