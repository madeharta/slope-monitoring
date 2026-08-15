import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useStore } from "../store";

// One configurable ECharts panel used by every analytics chart on the slope
// detail page. Series colour carries QUANTITY; status is shown only as shaded
// bands behind the series (ISA-101 — see charts.css). Charts never animate.
//
// Props:
//   series : [{ name, type:"line"|"bar", data:[[isoTime, value]], color,
//               width, dash, area, axis:0|1, opacity, barWidth, z }]
//   left   : { name, min, max } | null   (left y-axis)
//   right  : { name, min, max } | null   (right y-axis)
//   bands  : [{ from, to, color, axis }]  horizontal shaded regions
//   hlines : [{ y, color, label, axis }]  horizontal dashed threshold lines
//   vlines : [{ x:isoTime, color, label }] vertical anomaly markers
const TXT = "#8a8b95", GRID = "#1c1c22", RULE = "#26262d", AXLBL = "#7c7d87";

export default function PanelChart({
  height = 260, series = [], left = null, right = null,
  bands = [], hlines = [], vlines = [],
}) {
  const ref = useRef(null);
  const chartRef = useRef(null);
  // re-theme when the variant flips (values are read straight from series props,
  // but subscribing keeps the panel in step with the rest of the console)
  const variant = useStore((s) => s.variant);

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

    const axisBase = (a) => ({
      type: "value", name: a?.name, min: a?.min, max: a?.max,
      nameTextStyle: { color: TXT, fontSize: 9.5, align: "left" }, nameGap: 8,
      axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { color: AXLBL, fontSize: 9.5, fontFamily: "ui-monospace,monospace" },
    });
    const yAxis = [left ? { ...axisBase(left), position: "left" } : { show: false }];
    yAxis.push(right ? { ...axisBase(right), position: "right" } : { show: false, position: "right" });

    const es = series.map((s) => {
      const op = s.opacity ?? 1;
      const common = { name: s.name, type: s.type || "line", data: s.data, yAxisIndex: s.axis || 0, z: s.z || 2 };
      if (s.type === "bar") {
        return { ...common, itemStyle: { color: s.color, opacity: op }, barWidth: s.barWidth || "55%" };
      }
      return {
        ...common, showSymbol: false,
        lineStyle: { color: s.color, width: s.width || 1.8, type: s.dash || "solid", opacity: op },
        areaStyle: s.area ? { color: s.color, opacity: 0.08 * op } : undefined,
      };
    });

    // markArea (bands) + horizontal threshold lines attach to the first series
    // on the matching axis so the y-coordinates map correctly.
    const maData = series.map(() => []);
    const mlData = series.map(() => []);
    [0, 1].forEach((axis) => {
      const idx = series.findIndex((s) => (s.axis || 0) === axis);
      if (idx < 0) return;
      bands.filter((b) => (b.axis || 0) === axis).forEach((b) =>
        maData[idx].push([{ yAxis: b.from, itemStyle: { color: b.color } }, { yAxis: b.to }]));
      hlines.filter((h) => (h.axis || 0) === axis).forEach((h) =>
        mlData[idx].push({
          yAxis: h.y,
          lineStyle: { color: h.color, type: "dashed", width: 1.4 },
          label: { formatter: () => h.label, color: h.color, fontSize: 9, position: "insideEndTop", fontFamily: "ui-monospace,monospace" },
        }));
    });
    // vertical anomaly markers ride on the first series (x-axis coordinate)
    if (es.length) vlines.forEach((v) =>
      mlData[0].push({
        xAxis: v.x,
        lineStyle: { color: v.color, type: "dashed", width: 1 },
        label: { formatter: () => v.label, color: v.color, fontSize: 9, position: "insideStartTop", fontFamily: "ui-monospace,monospace" },
      }));

    es.forEach((s, i) => {
      if (maData[i].length) s.markArea = { silent: true, data: maData[i] };
      if (mlData[i].length) s.markLine = { silent: true, symbol: "none", data: mlData[i] };
    });

    c.setOption({
      animation: false, backgroundColor: "transparent",
      grid: { left: 54, right: right ? 52 : 20, top: 16, bottom: 24 },
      xAxis: {
        type: "time", axisLine: { lineStyle: { color: RULE } },
        axisLabel: { color: TXT, fontSize: 9.5, hideOverlap: true, fontFamily: "ui-monospace,monospace" },
        splitLine: { show: true, lineStyle: { color: GRID } }, axisTick: { show: false },
      },
      yAxis,
      series: es,
      tooltip: {
        trigger: "axis", backgroundColor: "rgba(9,9,11,.95)", borderColor: RULE,
        textStyle: { color: "#e9e9ee", fontSize: 12 }, axisPointer: { lineStyle: { color: RULE } },
      },
    }, true);
  }, [series, left, right, bands, hlines, vlines, variant]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
