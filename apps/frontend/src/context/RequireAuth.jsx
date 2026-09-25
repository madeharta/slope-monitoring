import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth, roleSatisfies } from "./AuthContext.jsx";
export default function RequireAuth({ minRole = "viewer" }) {
  const { auth, isAuthenticated } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (!roleSatisfies(auth.role, minRole)) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
