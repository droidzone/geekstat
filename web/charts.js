const PAD_LEFT = 58;
const PAD_RIGHT_Y2 = 48;
const PAD_RIGHT = 14;
const PAD_TOP = 28;
const PAD_BOTTOM = 32;

export function createChart(host, spec) {
  const root = document.createElement("div");
  root.className = "chart";
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", spec.label || "chart");
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.hidden = true;
  const legend = document.createElement("div");
  legend.className = "legend";
  root.append(tip, canvas, legend);
  host.append(root);

  const series = spec.series.map((item) => ({ ...item, hidden: Boolean(item.hidden) }));
  let epochs = [];
  let intervals = [];
  let columns = {};
  let hover = null;
  let layout = null;
  let drag = null;
  let destroyed = false;

  for (const item of series) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "legend-item";
    button.setAttribute("aria-pressed", item.hidden ? "false" : "true");
    const swatch = document.createElement("i");
    swatch.style.background = item.color;
    if (item.dash) swatch.style.background = "transparent";
    if (item.dash) {
      swatch.style.borderTop = `2px dashed ${item.color}`;
      swatch.style.height = "0";
    }
    button.append(swatch, document.createTextNode(item.label));
    if (item.hidden) button.classList.add("is-off");
    button.addEventListener("click", () => {
      item.hidden = !item.hidden;
      button.classList.toggle("is-off", item.hidden);
      button.setAttribute("aria-pressed", item.hidden ? "false" : "true");
      draw();
    });
    legend.append(button);
  }

  canvas.addEventListener("pointerdown", (event) => {
    if (!epochs.length || !layout) return;
    canvas.setPointerCapture(event.pointerId);
    drag = { x: event.offsetX, y: event.offsetY, current: event.offsetX };
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!epochs.length || !layout) return;
    if (drag) {
      drag.current = event.offsetX;
      draw();
      return;
    }
    const index = indexAt(event.offsetX);
    if (index == null) return;
    hover = index;
    draw();
    spec.onHover?.(index);
  });
  canvas.addEventListener("pointerup", (event) => {
    if (!drag) return;
    const moved = Math.abs(event.offsetX - drag.x);
    const startX = drag.x;
    const endX = event.offsetX;
    drag = null;
    draw();
    if (moved < 6 || !layout) return;
    const a = epochAt(Math.min(startX, endX));
    const b = epochAt(Math.max(startX, endX));
    if (a != null && b != null && b > a) spec.onSelect?.(a, b);
  });
  canvas.addEventListener("dblclick", () => spec.onReset?.());

  function setData(next) {
    epochs = next.epochs || [];
    intervals = next.intervals || [];
    columns = next.columns || {};
    if (hover != null && (hover < 0 || hover >= epochs.length)) hover = epochs.length ? epochs.length - 1 : null;
    draw();
  }

  function setCursor(index) {
    hover = index == null || index < 0 || index >= epochs.length ? null : index;
    draw();
  }

  function resize() {
    draw();
  }

  function destroy() {
    destroyed = true;
    root.remove();
  }

  function visibleSeries(scale) {
    return series.filter((item) => !item.hidden && (scale == null || item.scale === scale));
  }

  function draw() {
    if (destroyed) return;
    const width = host.clientWidth || root.clientWidth || 640;
    const height = spec.height || 220;
    const dpr = window.devicePixelRatio || 1;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.font = '12px "SF Mono", ui-monospace, monospace';
    ctx.textBaseline = "middle";

    const hasY2 = visibleSeries("y2").length > 0;
    const pad = {
      l: PAD_LEFT,
      r: hasY2 ? PAD_RIGHT_Y2 : PAD_RIGHT,
      t: PAD_TOP,
      b: PAD_BOTTOM,
    };
    const plotW = Math.max(10, width - pad.l - pad.r);
    const plotH = Math.max(10, height - pad.t - pad.b);
    layout = { pad, plotW, plotH, width, height };

    if (!epochs.length) {
      ctx.fillStyle = "#a39888";
      ctx.textAlign = "center";
      ctx.fillText("No samples in this window", width / 2, height / 2);
      tip.hidden = true;
      return;
    }

    const xMin = epochs[0];
    const xMax = epochs[epochs.length - 1];
    const span = Math.max(xMax - xMin, 60);
    const x0 = xMin - span * 0.02;
    const x1 = xMax + span * 0.02;
    layout.x0 = x0;
    layout.x1 = x1;

    const yValues = finiteValues(visibleSeries("y"));
    const yScale = scaleFor(yValues);
    const y2Scale = { max: 100, ticks: [0, 25, 50, 75, 100] };
    layout.yScale = yScale;

    ctx.strokeStyle = "rgba(243, 239, 230, 0.08)";
    ctx.fillStyle = "#a39888";
    ctx.lineWidth = 1;
    ctx.textAlign = "right";
    for (const tick of yScale.ticks) {
      const y = yAt(tick, yScale.max, pad, plotH);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + plotW, y);
      ctx.stroke();
      ctx.fillText(formatTick(tick), pad.l - 8, y);
    }
    if (hasY2) {
      ctx.textAlign = "left";
      for (const tick of y2Scale.ticks) {
        const y = yAt(tick, y2Scale.max, pad, plotH);
        ctx.fillText(String(tick), pad.l + plotW + 8, y);
      }
    }

    const xTicks = chooseXTicks(epochs, x0, x1, plotW);
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const epoch of xTicks) {
      const x = xAt(epoch, x0, x1, pad, plotW);
      ctx.strokeStyle = "rgba(243, 239, 230, 0.05)";
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, pad.t + plotH);
      ctx.stroke();
      ctx.fillStyle = "#a39888";
      ctx.fillText(spec.formatX(epoch, x1 - x0 <= 1800), x, pad.t + plotH + 8);
    }

    ctx.save();
    ctx.beginPath();
    ctx.rect(pad.l, pad.t, plotW, plotH);
    ctx.clip();
    for (const item of [...visibleSeries("y2"), ...visibleSeries("y")]) {
      const scaleMax = item.scale === "y2" ? y2Scale.max : yScale.max;
      strokeSeries(ctx, item, epochs, intervals, columns[item.key] || [], x0, x1, scaleMax, pad, plotW, plotH);
    }
    ctx.restore();

    if (drag) {
      const left = Math.min(drag.x, drag.current);
      const right = Math.max(drag.x, drag.current);
      ctx.fillStyle = "rgba(224, 154, 43, 0.16)";
      ctx.fillRect(left, pad.t, right - left, plotH);
    }

    if (hover != null && epochs[hover] != null) {
      const x = xAt(epochs[hover], x0, x1, pad, plotW);
      ctx.strokeStyle = "#e09a2b";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, pad.t + plotH);
      ctx.stroke();
      for (const item of visibleSeries()) {
        const value = (columns[item.key] || [])[hover];
        if (value == null || Number.isNaN(value)) continue;
        const scaleMax = item.scale === "y2" ? y2Scale.max : yScale.max;
        const y = yAt(value, scaleMax, pad, plotH);
        ctx.fillStyle = "#161410";
        ctx.strokeStyle = item.color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
      const lines = [spec.formatX(epochs[hover], true)];
      for (const item of visibleSeries()) {
        lines.push(`${item.label}  ${item.format((columns[item.key] || [])[hover])}`);
      }
      tip.hidden = false;
      tip.textContent = lines.join("   ");
    }
  }

  function finiteValues(items) {
    const values = [];
    for (const item of items) {
      for (const value of columns[item.key] || []) {
        if (value != null && Number.isFinite(value)) values.push(value);
      }
    }
    return values;
  }

  function epochAt(pixel) {
    if (!layout) return null;
    const ratio = (pixel - layout.pad.l) / layout.plotW;
    return layout.x0 + Math.min(1, Math.max(0, ratio)) * (layout.x1 - layout.x0);
  }

  function indexAt(pixel) {
    const epoch = epochAt(pixel);
    if (epoch == null || !epochs.length) return null;
    let best = 0;
    let bestDist = Infinity;
    for (let index = 0; index < epochs.length; index += 1) {
      const dist = Math.abs(epochs[index] - epoch);
      if (dist < bestDist) {
        bestDist = dist;
        best = index;
      }
    }
    return best;
  }

  return { setData, setCursor, resize, destroy };
}

function strokeSeries(ctx, item, epochs, intervals, values, x0, x1, scaleMax, pad, plotW, plotH) {
  ctx.beginPath();
  ctx.lineWidth = item.width || 1.75;
  ctx.strokeStyle = item.color;
  ctx.setLineDash(item.dash || []);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  let drawing = false;
  const showPoints = epochs.length <= 40;
  for (let index = 0; index < epochs.length; index += 1) {
    const value = values[index];
    const gap = index > 0 && epochs[index] - epochs[index - 1] > gapLimit(intervals, index);
    if (value == null || !Number.isFinite(value) || gap) {
      drawing = false;
      if (value == null || !Number.isFinite(value)) continue;
    }
    const x = xAt(epochs[index], x0, x1, pad, plotW);
    const y = yAt(value, scaleMax, pad, plotH);
    if (!drawing) {
      ctx.moveTo(x, y);
      drawing = true;
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.stroke();
  ctx.setLineDash([]);
  if (showPoints) {
    for (let index = 0; index < epochs.length; index += 1) {
      const value = values[index];
      if (value == null || !Number.isFinite(value)) continue;
      ctx.fillStyle = item.color;
      ctx.beginPath();
      ctx.arc(xAt(epochs[index], x0, x1, pad, plotW), yAt(value, scaleMax, pad, plotH), 2.4, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function gapLimit(intervals, index) {
  const previous = intervals[index - 1] || 300;
  const current = intervals[index] || 300;
  return Math.max(previous, current, 60) * 2.5;
}

function xAt(epoch, x0, x1, pad, plotW) {
  return pad.l + ((epoch - x0) / (x1 - x0)) * plotW;
}

function yAt(value, max, pad, plotH) {
  const top = pad.t + 8;
  const height = plotH - 12;
  const clamped = Math.max(0, value);
  return top + (1 - clamped / max) * height;
}

function scaleFor(values) {
  const dataMax = values.length ? Math.max(...values) : 1;
  const headroom = dataMax <= 0 ? 1 : dataMax * 1.08;
  if (dataMax > 80 && dataMax <= 100) {
    return { max: 100, ticks: [0, 25, 50, 75, 100] };
  }
  const step = niceStep(headroom / 4);
  const ticks = [];
  for (let value = 0; value <= headroom + step * 0.01; value += step) ticks.push(roundTick(value));
  if (ticks[ticks.length - 1] < headroom) ticks.push(roundTick(ticks[ticks.length - 1] + step));
  return { max: ticks[ticks.length - 1] || 1, ticks };
}

function niceStep(raw) {
  if (!(raw > 0)) return 1;
  const exp = Math.floor(Math.log10(raw));
  const pow = 10 ** exp;
  const frac = raw / pow;
  const buckets = [1, 2, 2.5, 5, 10];
  const bucket = buckets.find((item) => frac <= item) || 10;
  return bucket * pow;
}

function roundTick(value) {
  return Math.round(value * 1000) / 1000;
}

function formatTick(value) {
  const abs = Math.abs(value);
  if (abs >= 100) return value.toFixed(0);
  if (abs >= 10) return trim(value.toFixed(1));
  return trim(value.toFixed(2));
}

function trim(text) {
  return text.replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

function chooseXTicks(epochs, x0, x1, plotW) {
  const target = Math.max(2, Math.floor(plotW / 88));
  const step = (x1 - x0) / target;
  const ticks = [];
  for (let epoch = x0; epoch <= x1; epoch += step) ticks.push(epoch);
  if (epochs.length <= 8) return epochs.slice();
  return ticks;
}
