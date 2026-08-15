// Two looks, toggled from the top bar:
//  - editorial: warm coffee palette, full-bleed sepia map, floating overlays.
//  - mono:      ISA-101 high-performance HMI (neutral grey, colour = abnormal only).
export const PALETTES = {
  editorial: {
    line: {
      rainfall: "#E8833A", soil_moisture: "#c9a227", moisture: "#c9a227",
      suction: "#b5838d", pore_pressure: "#b5838d", tilt: "#f0b429",
      // field-sensor set: GNSS creep + components, two tilt axes, derived motion
      displacement: "#F5EEE4", disp_e: "#c9a227", disp_n: "#b5838d", disp_u: "#8d7d6d",
      tilt_x: "#f0b429", tilt_y: "#cbb79f", vibration: "#6f5a44",
      velocity: "#F5EEE4", acceleration: "#8d7d6d",
    },
    lineDefault: "#cbb79f",
    rainBar: "#8a5a34",
    marker: { bahaya: "#ef4444", siaga: "#f0b429", normal: "#a08a72" },
    spark: { stroke: "#E8833A", fill: "rgba(232,131,58,0.16)", end: "#f5eee4" },
    band: { siaga: "rgba(240,180,41,0.13)", bahaya: "rgba(239,68,68,0.15)" },
    bandLine: { siaga: "rgba(240,180,41,0.55)", bahaya: "rgba(239,68,68,0.6)" },
    area: true,
  },
  mono: {
    line: {
      rainfall: "#3a3a46", soil_moisture: "#cfd0d6", moisture: "#cfd0d6",
      suction: "#a9aab3", pore_pressure: "#a9aab3", tilt: "#e9e9ee",
      // field-sensor set: GNSS creep + components, two tilt axes, derived motion
      displacement: "#e9e9ee", disp_e: "#a9aab3", disp_n: "#8b8c96", disp_u: "#6b6c76",
      tilt_x: "#e9e9ee", tilt_y: "#a9aab3", vibration: "#55555f",
      velocity: "#e9e9ee", acceleration: "#8b8c96",
    },
    lineDefault: "#b7b8c0",
    rainBar: "#3a3a46",
    marker: { bahaya: "#ef4d54", siaga: "#eea23c", normal: "#8b8c96" },
    spark: { stroke: "#9a9ba4", fill: "rgba(139,140,150,0.10)", end: "#cfd0d6" },
    band: { siaga: "rgba(238,162,60,0.10)", bahaya: "rgba(239,77,84,0.10)" },
    bandLine: { siaga: "rgba(238,162,60,0.5)", bahaya: "rgba(239,77,84,0.55)" },
    area: false,
  },
};

export const getPalette = (v) => PALETTES[v] || PALETTES.editorial;
