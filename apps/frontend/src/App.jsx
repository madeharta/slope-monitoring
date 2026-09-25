import { useEffect } from "react";
import { Routes, Route } from "react-router-dom";
import { useStore } from "./store";
import TopBar from "./components/TopBar.jsx";
import Overview from "./pages/Overview.jsx";
import SlopeDetail from "./pages/SlopeDetail.jsx";
import Login from "./pages/Login.jsx";
import PanduanPenggunaan from "./pages/PanduanPenggunaan.jsx";
import AdminSites from "./pages/AdminSites.jsx";
import Devices from "./pages/Devices.jsx";
import Settings from "./pages/Settings.jsx";
import AuditLogPage from "./pages/AuditLogPage.jsx";
import Sites from "./pages/Sites.jsx";
import Users from "./pages/Users.jsx";
import MFAEnroll from "./pages/MFAEnroll.jsx";
import RequireAuth from "./context/RequireAuth.jsx";
import { useAuth } from "./context/AuthContext.jsx";
function AuthenticatedApp() {
  const connect = useStore((s) => s.connect);
  useEffect(() => {
    connect();
  }, [connect]);
  return (
    <div className="app">
      <div className="stage">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/sites/:id" element={<SlopeDetail />} />
          <Route path="/panduan" element={<PanduanPenggunaan />} />
          <Route path="/admin/sites" element={<AdminSites />} />
          <Route path="/devices" element={<Devices />} />
          <Route path="/sites" element={<Sites />} />
          <Route path="/users" element={<Users />} />
          <Route path="/mfa/enroll" element={<MFAEnroll />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/audit-log" element={<AuditLogPage />} />
        </Routes>
      </div>
      <TopBar />
    </div>
  );
}
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth minRole="viewer" />}>
        <Route path="/*" element={<AuthenticatedApp />} />
      </Route>
    </Routes>
  );
}
