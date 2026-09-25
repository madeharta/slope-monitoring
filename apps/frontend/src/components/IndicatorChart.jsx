import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useStore } from "../store";
import { getPalette } from "../theme";
const TXT = "#8a8b95", GRID = "#1c1c22", RULE = "#26262d";
export default function IndicatorChart({ quantity, unit, points, live, threshold }) {
  const ref = useRef(null);
  const chartRef = useRef(null);
  const variant = useStore((s) => s.variant);
  const pal = getPalette(variant);
  useEffect(() => {
    const c = echarts.init(ref.current, null, { renderer: "canvas" });
    chartRef.current = c;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); c.dispose(); chartRef.current = null; };
  }, []);
  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    const pts = points.map((p) => [p[0], p[1]]);
    for (const ev of live || []) if (ev.quantity === quantity && ev.value != null) pts.push([ev.t, ev.value]);
    pts.sort((a, b) => new Date(a[0]) - new Date(b[0]));
    const vals = pts.map((p) => p[1]).filter((v) => v != null);
    let ymin = vals.length ? Math.min(...vals) : 0;
    let ymax = vals.length ? Math.max(...vals) : 1;
    if (threshold) {
      ymin = Math.min(ymin, threshold.siaga, threshold.bahaya);
      ymax = Math.max(ymax, threshold.siaga, threshold.bahaya);
    }
    const pad = (ymax - ymin) * 0.15 || 1;
    ymin -= pad; ymax += pad;
    let markArea;
    if (threshold) {
      const { dir, siaga, bahaya } = threshold;
      markArea = { silent: true, data: dir === "high"
        ? [
            [{ yAxis: siaga, itemStyle: { color: pal.band.siaga } }, { yAxis: bahaya }],
            [{ yAxis: bahaya, itemStyle: { color: pal.band.bahaya } }, { yAxis: ymax }],
          ]
        : [
            [{ yAxis: bahaya, itemStyle: { color: pal.band.siaga } }, { yAxis: siaga }],
            [{ yAxis: ymin, itemStyle: { color: pal.band.bahaya } }, { yAxis: bahaya }],
          ] };
    }
    const color = pal.line[quantity] || pal.lineDefault;
    const isRain = quantity === "rainfall";
    const series = isRain
      ? { type: "bar", data: pts, itemStyle: { color: pal.rainBar, borderRadius: 1 }, barWidth: "55%", markArea }
      : { type: "line", data: pts, showSymbol: false, lineStyle: { color, width: 2 },
          areaStyle: pal.area ? { color, opacity: 0.08 } : undefined, markArea };
    c.setOption({
      animation: false, backgroundColor: "transparent",
      grid: { left: 46, right: 16, top: 12, bottom: 22 },
      xAxis: { type: "time", axisLine: { lineStyle: { color: RULE } },
        axisLabel: { color: TXT, fontSize: 9, hideOverlap: true }, splitLine: { show: true, lineStyle: { color: GRID } }, axisTick: { show: false } },
      yAxis: { min: ymin, max: ymax, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { show: false }, axisLabel: { color: "#7c7d87", fontSize: 9 } },
      series: [series],
      tooltip: { trigger: "axis", backgroundColor: "rgba(9,9,11,.95)", borderColor: RULE, textStyle: { color: "#e9e9ee", fontSize: 12 } },
    }, true);
  }, [points, live, threshold, quantity, variant]);
  return <div ref={ref} style={{ width: "100%", height: "100%" }} />;
}
