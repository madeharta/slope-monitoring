import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useStore } from "../store";
import { getPalette } from "../theme";

const TXT = "#8a8b95", GRID = "#1c1c22", RULE = "#26262d";

// registry-driven lane assignment: rainfall on top, tilt (banded) at the bottom,
// every other quantity shares the middle lane. Bands live ONLY in the tilt lane.
function laneOf(q) {
  if (q === "rainfall") return "rain";
  if (q.startsWith("tilt")) return "tilt";
  return "mid";
}

export default function CombinedChart({ series, live, thresholds }) {
  const ref = useRef(null);
  const chartRef = useRef(null);
  const variant = useStore((s) => s.variant);
  const pal = getPalette(variant);

  useEffect(() => {
    const chart = echarts.init(ref.current, null, { renderer: "canvas" });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // merge historical + live points per quantity
    const byQ = {};
    for (const s of series) byQ[s.quantity] = { unit: s.unit, pts: s.points.map((p) => [p[0], p[1]]) };
    for (const ev of live || []) {
      if (ev.value == null) continue;
      byQ[ev.quantity] = byQ[ev.quantity] || { unit: ev.unit, pts: [] };
      byQ[ev.quantity].pts.push([ev.t, ev.value]);
    }
    for (const q in byQ) byQ[q].pts.sort((a, b) => new Date(a[0]) - new Date(b[0]));

    const has = (lane) => Object.keys(byQ).some((q) => laneOf(q) === lane);
    const g = {}; // grid indices per lane
    let gi = 0, top = 20;
    const grids = [], xAxes = [], yAxes = [];
    const addLane = (lane, h, label) => {
      if (!has(lane)) return;
      g[lane] = gi;
      grids.push({ left: 56, right: 62, top, height: h });
      xAxes.push({
        gridIndex: gi, type: "time",
        axisLine: { lineStyle: { color: RULE } },
        axisLabel: { color: TXT, fontSize: 10, hideOverlap: true, show: lane === lastLane() },
        splitLine: { show: true, lineStyle: { color: GRID } },
        axisTick: { show: false },
      });
      // yAxes added by caller
      xAxes[xAxes.length - 1]._label = label;
      top += h + 14;
      gi++;
    };
    function lastLane() {
      const order = ["rain", "mid", "tilt"].filter(has);
      return order[order.length - 1];
    }
    addLane("rain", 62, "Rainfall (mm/h)");
    addLane("mid", 104, "Moisture (%) · Suction (kPa)");
    addLane("tilt", 108, "Tilt (°)");

    const yStyle = (extra = {}) => ({
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: false }, axisLabel: { color: "#7c7d87", fontSize: 9 },
      nameTextStyle: { color: TXT, fontSize: 10, align: "left" }, nameGap: 6, ...extra,
    });

    const yIndex = {};
    if (has("rain")) { yIndex.rain = yAxes.length; yAxes.push(yStyle({ gridIndex: g.rain, inverse: true, name: "mm/h", nameLocation: "start" })); }
    const midQs = Object.keys(byQ).filter((q) => laneOf(q) === "mid");
    midQs.forEach((q, i) => { yIndex[q] = yAxes.length; yAxes.push(yStyle({ gridIndex: g.mid, position: i === 0 ? "left" : "right", name: q === "suction" ? "kPa" : "%" })); });
    let tiltMax = 2;
    if (has("tilt")) {
      const tq = Object.keys(byQ).find((q) => laneOf(q) === "tilt");
      const dmax = Math.max(2, ...byQ[tq].pts.map((p) => p[1] || 0));
      tiltMax = Math.ceil(dmax * 1.1);
      yIndex.tilt = yAxes.length;
      yAxes.push(yStyle({ gridIndex: g.tilt, min: 0, max: tiltMax, name: "°" }));
    }

    const seriesOpt = [];
    for (const q in byQ) {
      const lane = laneOf(q);
      if (lane === "rain") {
        seriesOpt.push({ name: q, type: "bar", xAxisIndex: g.rain, yAxisIndex: yIndex.rain,
          data: byQ[q].pts, itemStyle: { color: pal.rainBar, borderRadius: 1 }, barWidth: "60%" });
      } else if (lane === "tilt") {
        const th = thresholds?.[q] || { siaga: 1.0, bahaya: 1.5 };
        const tc = pal.line[q] || pal.line.tilt || "#e9e9ee";
        seriesOpt.push({
          name: q, type: "line", xAxisIndex: g.tilt, yAxisIndex: yIndex.tilt, data: byQ[q].pts,
          showSymbol: false, lineStyle: { color: tc, width: 2.4 }, z: 3,
          areaStyle: pal.area ? { color: tc, opacity: 0.08 } : undefined,
          markArea: { silent: true, data: [
            [{ yAxis: th.siaga, itemStyle: { color: pal.band.siaga } }, { yAxis: th.bahaya }],
            [{ yAxis: th.bahaya, itemStyle: { color: pal.band.bahaya } }, { yAxis: tiltMax }],
          ] },
          markLine: { silent: true, symbol: "none", label: { color: TXT, fontSize: 9, formatter: (p) => (p.value === th.siaga ? "SIAGA" : "BAHAYA") },
            data: [
              { yAxis: th.siaga, lineStyle: { color: pal.bandLine.siaga, type: "dashed" } },
              { yAxis: th.bahaya, lineStyle: { color: pal.bandLine.bahaya, type: "dashed" } },
            ] },
        });
      } else {
        const lc = pal.line[q] || pal.lineDefault;
        seriesOpt.push({ name: q, type: "line", xAxisIndex: g.mid, yAxisIndex: yIndex[q], data: byQ[q].pts,
          showSymbol: false, lineStyle: { color: lc, width: 1.8, type: q === "suction" ? "dashed" : "solid" },
          areaStyle: pal.area ? { color: lc, opacity: 0.07 } : undefined });
      }
    }

    // lane labels (top-left of each grid)
    const graphic = xAxes.map((x, i) => ({
      type: "text", left: 56, top: grids[i].top - 14,
      style: { text: x._label, fill: TXT, font: "10.5px ui-sans-serif,system-ui" },
    }));

    chart.setOption({
      animation: false, backgroundColor: "transparent",
      grid: grids, xAxis: xAxes, yAxis: yAxes, series: seriesOpt, graphic,
      tooltip: { trigger: "axis", backgroundColor: "rgba(9,9,11,.95)", borderColor: RULE,
        textStyle: { color: "#e9e9ee", fontSize: 12 }, axisPointer: { lineStyle: { color: RULE } } },
    }, true);
  }, [series, live, thresholds, variant]);

  return <div ref={ref} style={{ width: "100%", height: "100%" }} />;
}
