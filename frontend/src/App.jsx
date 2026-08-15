import { useEffect } from "react";
import { Routes, Route } from "react-router-dom";
import { useStore } from "./store";
import TopBar from "./components/TopBar.jsx";
import Overview from "./pages/Overview.jsx";
import SlopeDetail from "./pages/SlopeDetail.jsx";

export default function App() {
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
        </Routes>
      </div>
      <TopBar />
    </div>
  );
}
