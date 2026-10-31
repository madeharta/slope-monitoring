// Route guard — bungkus route yang butuh login:
//   <Route element={<RequireAuth minRole="operator" />}>...
// React Router v6 nested-route pattern (Outlet).

import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth, roleSatisfies } from "./AuthContext.jsx";

export default function RequireAuth({ minRole = "viewer" }) {
  const { auth, isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    // Simpan lokasi asal supaya Login.jsx bisa redirect balik setelah
    // sukses — belum diimplementasikan di Login.jsx saat ini (redirect
    // selalu ke "/"), state ini disiapkan untuk langkah berikutnya.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (!roleSatisfies(auth.role, minRole)) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
