import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import L from "leaflet";
import { useStore } from "../store";
import { getPalette } from "../theme";

const LABEL = { bahaya: "Bahaya", siaga: "Siaga", normal: "Normal", unknown: "Belum terverifikasi" };
const DEVICE_STATUS = {
  online: { label: "Online", color: "#41c87a" },
  stale: { label: "Stale", color: "#d7a93f" },
  offline: { label: "Offline", color: "#6f737e" },
  unknown: { label: "Unknown", color: "#9b9da5" },
};

function fmt(v) {
  return typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) : v;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? esc(value) : esc(d.toLocaleString());
}

export default function SiteMap({ slopes, devices = [] }) {
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

    const legend = L.control({ position: "bottomright" });
    legend.onAdd = () => {
      const div = L.DomUtil.create("div");
      div.style.cssText = "background:rgba(17,18,24,.88);color:#ececf2;padding:8px 10px;border:1px solid rgba(255,255,255,.13);border-radius:6px;font:11px/1.5 system-ui,sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.25)";
      div.innerHTML =
        '<div style="font-weight:700;margin-bottom:3px">Device telemetry</div>' +
        Object.values(DEVICE_STATUS).map((s) => `<div><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${s.color};margin-right:6px"></span>${s.label}</div>`).join("") +
        '<div style="margin-top:4px;color:#aeb1bc">Pin hanya muncul jika posisi GNSS/reference tersedia.</div>';
      return div;
    };
    legend.addTo(map);

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
        radius: s.status === "bahaya" ? 9 : 6.5,
        color: variant === "vibrant" ? "#0a0b12" : "#0b0b0e",
        weight: 2,
        fillColor: col,
        fillOpacity: 1,
      }).addTo(layer);
      const r = s.reading;
      const rtxt = r
        ? `<div class="popreading"><span class="val">${fmt(r.value)} ${esc(r.unit)}</span> · ${esc(r.quantity)}${r.depth_cm != null ? ` @ ${fmt(r.depth_cm)}cm` : ""}</div>`
        : "";
      m.bindPopup(
        `<div class="popname">${esc(s.name)}</div>` +
          `<span class="badge ${esc(s.status)}"><span class="pip"></span>${esc(LABEL[s.status])}</span>` +
          `<div class="popaction">${esc(s.action)}</div>` + rtxt +
          `<button class="popbtn" data-site="${esc(s.site_id)}">Open detail →</button>`,
        { closeButton: true }
      );
      m.on("popupopen", (e) => {
        const btn = e.popup.getElement().querySelector(".popbtn");
        if (btn) btn.addEventListener("click", () => navigate(`/sites/${s.site_id}`));
      });
    });

    devices.forEach((d) => {
      if (!d.position || typeof d.position.lat !== "number" || typeof d.position.lon !== "number") return;
      const state = DEVICE_STATUS[d.connectivity_status] || DEVICE_STATUS.unknown;
      const m = L.circleMarker([d.position.lat, d.position.lon], {
        radius: 5,
        color: "#f4f4f7",
        weight: 1.5,
        fillColor: state.color,
        fillOpacity: 1,
      }).addTo(layer);
      const accuracy = typeof d.position.h_acc_m === "number" ? `${fmt(d.position.h_acc_m)} m` : "—";
      m.bindTooltip(`${d.label || d.device_id} · ${state.label}`, { direction: "top", offset: [0, -5] });
      m.bindPopup(
        `<div class="popname">${esc(d.label || d.device_id)}</div>` +
        `<div class="popreading"><b>${esc(state.label)}</b> · telemetry freshness</div>` +
        `<div class="popaction">Device: ${esc(d.device_id)}<br/>Site: ${esc(d.site_id)}<br/>Last activity: ${fmtTime(d.last_activity)}<br/>Position source: ${esc(d.position.source || "unknown")}<br/>Position time: ${fmtTime(d.position.time)}<br/>GNSS h-acc: ${esc(accuracy)}<br/>Position validation: ${esc(d.position.validation_status || "unknown")}</div>` +
        `<button class="popbtn" data-site="${esc(d.site_id)}">Open site →</button>`,
        { closeButton: true }
      );
      m.on("popupopen", (e) => {
        const btn = e.popup.getElement().querySelector(".popbtn");
        if (btn) btn.addEventListener("click", () => navigate(`/sites/${d.site_id}`));
      });
    });
  }, [slopes, devices, navigate, variant, pal]);

  return <div ref={ref} style={{ width: "100%", height: "100%" }} />;
}
