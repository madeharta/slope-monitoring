import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import L from "leaflet";
import { useStore } from "../store";
import { getPalette } from "../theme";
const LABEL = { bahaya: "Bahaya", siaga: "Siaga", normal: "Normal", unknown: "Belum terverifikasi" };
function fmt(v) {
  return typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) : v;
}
export default function SiteMap({ slopes }) {
  const ref = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const navigate = useNavigate();
  const variant = useStore((s) => s.variant);
  const pal = getPalette(variant);
  useEffect(() => {
    const map = L.map(ref.current, { zoomControl: false, attributionControl: false }).setView(
      [-6.72, 106.95], 9
    );
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 16 }
    ).addTo(map);
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 16, opacity: 0.16 }
    ).addTo(map);
    L.control.attribution({ prefix: false }).addAttribution("© Esri").addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);
  useEffect(() => {
    const map = mapRef.current, layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    slopes.forEach((s) => {
      const col = s.status === "unknown" ? "#8b8c96" : (pal.marker[s.status] || pal.marker.normal);
      if (s.status !== "normal") {
        L.circleMarker([s.lat, s.lon], {
          radius: 17, stroke: false, fillColor: col, fillOpacity: 0.18, className: "slope-halo",
        }).addTo(layer);
      }
      const m = L.circleMarker([s.lat, s.lon], {
        radius: s.status === "bahaya" ? 9 : 6.5, color: variant === "vibrant" ? "#0a0b12" : "#0b0b0e", weight: 2,
        fillColor: col, fillOpacity: 1,
      }).addTo(layer);
      const r = s.reading;
      const rtxt = r
        ? `<div class="popreading"><span class="val">${fmt(r.value)} ${r.unit}</span> · ${r.quantity}${r.depth_cm != null ? ` @ ${r.depth_cm}cm` : ""}</div>`
        : "";
      m.bindPopup(
        `<div class="popname">${s.name}</div>` +
          `<span class="badge ${s.status}"><span class="pip"></span>${LABEL[s.status]}</span>` +
          `<div class="popaction">${s.action}</div>` + rtxt +
          `<button class="popbtn" data-site="${s.site_id}">Open detail →</button>`,
        { closeButton: true }
      );
      m.on("popupopen", (e) => {
        const btn = e.popup.getElement().querySelector(".popbtn");
        if (btn) btn.addEventListener("click", () => navigate(`/sites/${s.site_id}`));
      });
    });
  }, [slopes, navigate, variant]);
  return <div ref={ref} style={{ width: "100%", height: "100%" }} />;
}
