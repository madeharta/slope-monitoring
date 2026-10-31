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
  axisFontSize = 9.5, xTimeMode = "clock", timeRange = null,
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
      nameTextStyle: { color: TXT, fontSize: 10, align: "center" },
      nameLocation: "middle", nameGap: 44,
      axisLine: { show: true, lineStyle: { color: RULE } },
      axisTick: { show: true }, splitLine: { show: true, lineStyle: { color: GRID, opacity: 0.2 } },
      axisLabel: { color: AXLBL, fontSize: axisFontSize, fontFamily: "ui-monospace,monospace" },
    });
    const yAxis = [left ? { ...axisBase(left), position: "left" } : { show: false }];
    yAxis.push(right ? { ...axisBase(right), position: "right" } : { show: false, position: "right" });

    const es = series.map((s) => {
      const op = s.opacity ?? 1;
      const common = { name: s.name, type: s.type || "line", data: s.data, yAxisIndex: s.axis || 0, z: s.z || 2 };
      if (s.type === "bar") {
        return {
          ...common,
          itemStyle: { color: s.color, opacity: op, borderRadius: s.borderRadius || [2, 2, 0, 0] },
          barWidth: s.barWidth || "55%",
          barMaxWidth: s.barMaxWidth,
          emphasis: { itemStyle: { opacity: Math.min(1, op + 0.18) } },
        };
      }
      const visiblePoints = (s.data || []).reduce((n, p) => n + (p?.[1] != null ? 1 : 0), 0);
      const baseWidth = s.width || 1.8;
      return {
        ...common, showSymbol: s.showSymbol ?? visiblePoints <= 20, symbolSize: s.symbolSize || 5, connectNulls: false,
        lineStyle: { color: s.color, width: baseWidth, type: s.dash || "solid", opacity: op },
        itemStyle: { color: s.color, opacity: op },
        areaStyle: s.area ? { color: s.color, opacity: 0.08 * op } : undefined,
        emphasis: { focus: "series", lineStyle: { width: baseWidth + 1 } },
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

    const firstTime = series.flatMap((s) => (s.data || []).map((p) => Date.parse(p?.[0])))
      .filter(Number.isFinite).reduce((min, v) => Math.min(min, v), Infinity);
    const lastTime = series.flatMap((s) => (s.data || []).map((p) => Date.parse(p?.[0])))
      .filter(Number.isFinite).reduce((max, v) => Math.max(max, v), -Infinity);
    const elapsedMode = xTimeMode === "elapsed" && Number.isFinite(firstTime) && Number.isFinite(lastTime);
    const shortWindow = elapsedMode && (lastTime - firstTime) < 2000;
    const wib = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Jakarta", year: "numeric", month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
    const fromMs = timeRange?.from ? Date.parse(timeRange.from) : NaN;
    const toMs = timeRange?.to ? Date.parse(timeRange.to) : NaN;
    const bounded = Number.isFinite(fromMs) && Number.isFinite(toMs) && fromMs < toMs;
    const wibTick = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Jakarta", day: "2-digit", month: "short",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
    c.setOption({
      animation: false, backgroundColor: "transparent",
      grid: { left: 65, right: right ? 72 : 25, top: 31, bottom: 61, containLabel: false },
      xAxis: {
        type: "time", min: bounded ? fromMs : undefined, max: bounded ? toMs : undefined,
        name: elapsedMode ? "Elapsed time (s)" : "Date & time (WIB)",
        nameLocation: "middle", nameGap: 42,
        nameTextStyle: { color: TXT, fontSize: 11 },
        axisLine: { show: true, lineStyle: { color: RULE } },
        axisLabel: {
          color: TXT, fontSize: axisFontSize, hideOverlap: true, fontFamily: "ui-monospace,monospace",
          formatter: elapsedMode ? (value) => {
            const delta = value - firstTime;
            return shortWindow ? `${Math.round(delta)} ms` : `${(delta / 1000).toFixed(2)} s`;
          } : (value) => wibTick.format(new Date(value)),
        },
        splitLine: { show: true, lineStyle: { color: GRID } }, axisTick: { show: false },
      },
      yAxis,
      series: es,
      tooltip: {
        trigger: "axis", backgroundColor: "rgba(9,9,11,.95)", borderColor: RULE,
        textStyle: { color: "#e9e9ee", fontSize: 12 },
        ...(elapsedMode ? { formatter: (items) => {
          if (!items?.length) return "";
          const timestamp = Number(items[0].axisValue);
          const at = Number.isFinite(timestamp) ? `${wib.format(new Date(timestamp))} WIB` : "Time unavailable";
          const delta = Number.isFinite(timestamp) ? ((timestamp - firstTime) / 1000).toFixed(3) : "—";
          const values = items.map((i) => `${i.marker} ${i.seriesName}: ${i.value?.[1] == null ? "—" : Number(i.value[1]).toFixed(3)} mm/s`).join("<br/>");
          return `${at}<br/>Elapsed ${delta} s<br/>${values}`;
        }} : {}),
        axisPointer: { type: "cross", lineStyle: { color: RULE }, crossStyle: { color: RULE } },
      },
    }, true);
  }, [series, left, right, bands, hlines, vlines, variant, axisFontSize, xTimeMode, timeRange?.from, timeRange?.to]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
