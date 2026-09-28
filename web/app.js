import { createChart } from "/charts.js";

const dateSelect = document.querySelector("#date");
const fromInput = document.querySelector("#from");
const toInput = document.querySelector("#to");
const statusEl = document.querySelector("#status");
const errorEl = document.querySelector("#error");
const warningsEl = document.querySelector("#warnings");
const identityEl = document.querySelector("#identity");
const cursorCard = document.querySelector("#cursor-card");
const pinCard = document.querySelector("#pin-card");
const peaksEl = document.querySelector("#peaks");
const chartsEl = document.querySelector("#charts");
const tableWrap = document.querySelector("#table-wrap");

const state = {
  catalog: null,
  dates: [],
  date: "",
  day: null,
  samples: [],
  view: [],
  idx: null,
  hovering: false,
  pinned: null,
  disk: "all",
  net: "all",
  tableOpen: null,
};

let chartApis = [];
let chartSig = "";
let builtKey = "";
let loadToken = 0;
let tableRows = [];
let ui = defaultUi();

const COLORS = {
  user: "#6aa6ff",
  nice: "#c4b5fd",
  system: "#e09a2b",
  iowait: "#e15b45",
  steal: "#d07ad6",
  idle: "#b7aa9a",
  used: "#e15b45",
  free: "#8d8376",
  avail: "#6fbfa3",
  pct: "#e09a2b",
  l1: "#6aa6ff",
  l5: "#e09a2b",
  l15: "#6fbfa3",
  cpus: "#c8bba8",
  read: "#6fbfa3",
  write: "#e15b45",
  rx: "#6aa6ff",
  tx: "#e09a2b",
};

document.querySelector("#prev").addEventListener("click", () => stepDate(-1));
document.querySelector("#next").addEventListener("click", () => stepDate(1));
document.querySelector("#refresh").addEventListener("click", refresh);
dateSelect.addEventListener("change", () => {
  state.date = dateSelect.value;
  setFullDayInputs();
  loadDay(state.date, false);
});
fromInput.addEventListener("change", () => {
  applyWindow();
  writeUrl();
});
toInput.addEventListener("change", () => {
  applyWindow();
  writeUrl();
});
document.addEventListener("keydown", (event) => {
  if (event.target.closest("input, select, textarea, button")) return;
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  if (!state.view.length) return;
  event.preventDefault();
  const delta = event.key === "ArrowRight" ? 1 : -1;
  const current = state.idx == null ? state.view.length - 1 : state.idx;
  focusIndex(Math.max(0, Math.min(state.view.length - 1, current + delta)), true, true);
});

new ResizeObserver(() => {
  for (const item of chartApis) item.api.resize();
}).observe(chartsEl);

boot();

async function boot() {
  try {
    await loadSettings();
    statusEl.textContent = "Reading the sysstat file list…";
    await loadCatalog(false);
    const params = new URLSearchParams(location.search);
    if (params.get("date") && state.dates.includes(params.get("date"))) state.date = params.get("date");
    else if (state.dates.length) state.date = state.dates[state.dates.length - 1];
    dateSelect.value = state.date;
    if (params.get("start")) fromInput.value = ensureSeconds(params.get("start"));
    if (params.get("end")) toInput.value = ensureSeconds(params.get("end"));
    syncDateButtons();
    if (state.date) await loadDay(state.date, false);
    else statusEl.textContent = "No sa files are available.";
  } catch (error) {
    showError(error.message);
    statusEl.textContent = "";
  }
}

async function refresh() {
  clearError();
  await loadCatalog(true);
  if (state.date && !state.dates.includes(state.date)) state.date = state.dates[state.dates.length - 1] || "";
  dateSelect.value = state.date;
  if (state.date) await loadDay(state.date, true);
}

async function loadCatalog(force) {
  state.catalog = await getJSON(`/api/catalog${force ? "?refresh=1" : ""}`);
  state.dates = state.catalog.dates;
  identityEl.textContent = `${state.catalog.host} · ${state.catalog.timezone} (UTC${state.catalog.utc_offset})`;
  dateSelect.replaceChildren();
  for (const day of state.dates) {
    const option = document.createElement("option");
    option.value = day;
    option.textContent = `${weekday(day)} ${day}`;
    dateSelect.append(option);
  }
  if (!state.dates.length) showError("No sa files were found in /var/log/sysstat.");
}

async function loadDay(date, force) {
  const token = ++loadToken;
  statusEl.textContent = "Loading samples…";
  setBusy(true);
  try {
    const day = await getJSON(`/api/day?date=${encodeURIComponent(date)}${force ? "&refresh=1" : ""}`);
    if (token !== loadToken) return;
    state.day = day;
    state.samples = day.samples;
    chartSig = "";
    applyWindow();
    writeUrl();
  } catch (error) {
    if (token !== loadToken) return;
    showError(error.message);
  } finally {
    if (token === loadToken) setBusy(false);
  }
}

function applyWindow() {
  const bounds = windowBounds(fromInput.value, toInput.value);
  if (!bounds) {
    showError("The end time is before the start time.");
    return;
  }
  clearError();
  state.view = state.samples.filter((sample) => {
    const clock = tod(sample.iso);
    return clock >= bounds[0] && clock <= bounds[1];
  });
  state.idx = state.view.length ? state.view.length - 1 : null;
  state.hovering = false;
  render();
}

async function loadSettings() {
  try {
    const payload = await getJSON("/api/settings");
    ui = {
      title: payload.title,
      charts: payload.charts,
      hideIdle: payload.hide_idle,
      from: payload.default_from,
      to: payload.default_to,
      ranges: payload.ranges,
      hotUser: payload.hot_user,
      hotIowait: payload.hot_iowait,
      hotRam: payload.hot_ram,
      hotSwap: payload.hot_swap,
      tableOpenBelow: payload.table_open_below,
    };
  } catch {
    ui = defaultUi();
  }
  const custom = Boolean(ui.title) && ui.title !== "Geekstat";
  document.title = custom ? `${ui.title} · Geekstat` : "Geekstat";
  const instance = document.querySelector("#instance");
  if (instance) {
    instance.hidden = !custom;
    instance.textContent = custom ? ui.title : "";
  }
  fromInput.value = ui.from;
  toInput.value = ui.to;
  const group = document.querySelector(".chips");
  group.replaceChildren();
  for (const range of ui.ranges) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.span = String(range.span);
    button.textContent = range.label;
    button.addEventListener("click", () => onSpan(String(range.span)));
    group.append(button);
  }
}

function onSpan(span) {
  if (span === "day") {
    setFullDayInputs();
    applyWindow();
    writeUrl();
    return;
  }
  applyLast(Number(span));
}

function defaultUi() {
  return {
    title: "Geekstat",
    charts: ["cpu", "memory", "swap", "load", "disk", "network"],
    hideIdle: true,
    from: "00:00:00",
    to: "23:59:00",
    ranges: [
      { label: "15m", span: "900" },
      { label: "1h", span: "3600" },
      { label: "6h", span: "21600" },
      { label: "Full day", span: "day" },
    ],
    hotUser: 50,
    hotIowait: 5,
    hotRam: 80,
    hotSwap: 10,
    tableOpenBelow: 24,
  };
}

function applyLast(seconds) {
  if (!state.samples.length) return;
  const end = tod(state.samples[state.samples.length - 1].iso);
  const start = Math.max(0, end - seconds);
  fromInput.value = formatHMS(start);
  toInput.value = formatHMS(end);
  applyWindow();
  writeUrl();
}

function render() {
  renderStatus();
  renderWarnings();
  renderPeaks();
  renderCharts();
  const key = viewKey();
  if (key !== builtKey) {
    renderTable();
    builtKey = key;
  }
  paintCursor();
}

function renderStatus() {
  const day = state.day;
  if (!day) return;
  const count = state.view.length;
  const interval = formatInterval(medianInterval(state.view));
  const cpus = cpuLabel(state.view);
  const files = (day.files || []).map((file) => `${file.name} ${file.source === "ssh" ? "decoded" : "cached"}`).join(", ");
  const bits = [
    `${weekday(day.date)} ${day.date}`,
    `${day.timezone} (UTC${day.utc_offset})`,
    `${count} raw sample${count === 1 ? "" : "s"}`,
    interval ? `median interval ${interval}` : "",
    cpus,
    networkText(day.network),
    files ? `files ${files}` : "",
    day.idle_disks?.length ? `idle disks hidden: ${day.idle_disks.join(", ")}` : "",
    day.restarts?.length ? `restart ${day.restarts.map((item) => item.iso.slice(11, 19)).join(", ")}` : "",
  ].filter(Boolean);
  statusEl.textContent = bits.join(" · ");
}

function renderWarnings() {
  const warnings = state.day?.warnings || [];
  warningsEl.hidden = warnings.length === 0;
  warningsEl.textContent = warnings.join(" ");
}

function renderPeaks() {
  peaksEl.replaceChildren();
  const items = [
    ["Peak user", peak(state.view, (sample) => sample.cpu.user), (value) => pct(value)],
    ["Peak iowait", peak(state.view, (sample) => sample.cpu.iowait), (value) => pct(value)],
    ["Peak RAM", peak(state.view, (sample) => sample.mem.used_pct), (value) => pct(value)],
    ["Peak load", peak(state.view, (sample) => sample.load.l1), (value) => num(value)],
  ];
  for (const [label, found, format] of items) {
    if (!found) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${label} ${format(found.value)} at ${found.sample.iso.slice(11, 19)}`;
    button.addEventListener("click", () => focusSample(found.sample));
    peaksEl.append(button);
  }
}

function renderCharts() {
  const next = signature();
  if (next !== chartSig) {
    for (const item of chartApis) item.api.destroy();
    chartApis = [];
    chartsEl.replaceChildren();
    buildCharts();
    chartSig = next;
  }
  const epochs = state.view.map((sample) => sample.epoch);
  const intervals = state.view.map((sample) => sample.interval || 0);
  for (const item of chartApis) item.api.setData({ epochs, intervals, columns: item.columns(state.view) });
}

function buildCharts() {
  const hooks = {
    formatX,
    onHover: (index) => focusIndex(index, true, false),
    onSelect: (start, end) => {
      fromInput.value = formatX(Math.min(start, end), true);
      toInput.value = formatX(Math.max(start, end), true);
      applyWindow();
      writeUrl();
    },
    onReset: () => {
      setFullDayInputs();
      applyWindow();
      writeUrl();
    },
  };
  const idleNote = ui.hideIdle
    ? "Each point is one sar sample. Idle starts off so a spike stays visible. Click idle in the legend to bring it back."
    : "Each point is one sar sample.";
  const panels = {
    cpu() {
      addPanel("CPU", idleNote, hooks, [
        series("user", "user", COLORS.user, pct, false),
        series("nice", "nice", COLORS.nice, pct, false),
        series("system", "system", COLORS.system, pct, false),
        series("iowait", "iowait", COLORS.iowait, pct, false),
        series("steal", "steal", COLORS.steal, pct, false),
        series("idle", "idle", COLORS.idle, pct, ui.hideIdle),
      ], (samples) => ({
        user: column(samples, (sample) => sample.cpu.user),
        nice: column(samples, (sample) => sample.cpu.nice),
        system: column(samples, (sample) => sample.cpu.system),
        iowait: column(samples, (sample) => sample.cpu.iowait),
        steal: column(samples, (sample) => sample.cpu.steal),
        idle: column(samples, (sample) => sample.cpu.idle),
      }), 250);
    },
    memory() {
      addPanel("Memory", "Used, free, and available are sar's own figures, in GiB. The dashed line is percent used.", hooks, [
        series("used", "used", COLORS.used, gib, false),
        series("free", "free", COLORS.free, gib, false),
        series("available", "available", COLORS.avail, gib, false),
        series("used_pct", "% used", COLORS.pct, pct, false, "y2", [5, 4]),
      ], (samples) => ({
        used: column(samples, (sample) => toGib(sample.mem.used_kb)),
        free: column(samples, (sample) => toGib(sample.mem.free_kb)),
        available: column(samples, (sample) => toGib(sample.mem.avail_kb)),
        used_pct: column(samples, (sample) => sample.mem.used_pct),
      }), 230);
    },
    swap() {
      addPanel("Swap", "Used space, with percent used on the right axis.", hooks, [
        series("used", "used", COLORS.steal, gib, false),
        series("used_pct", "% used", COLORS.pct, pct, false, "y2", [5, 4]),
      ], (samples) => ({
        used: column(samples, (sample) => toGib(sample.swap.used_kb)),
        used_pct: column(samples, (sample) => sample.swap.used_pct),
      }), 180);
    },
    load() {
      addPanel("Load average", "1, 5, and 15 minute load. The dashed line is the CPU count recorded with each sample.", hooks, [
        series("l1", "1 min", COLORS.l1, num, false),
        series("l5", "5 min", COLORS.l5, num, false),
        series("l15", "15 min", COLORS.l15, num, false),
        series("cpus", "CPUs", COLORS.cpus, (value) => (value == null ? "—" : String(value)), false, "y", [5, 4]),
      ], (samples) => ({
        l1: column(samples, (sample) => sample.load.l1),
        l5: column(samples, (sample) => sample.load.l5),
        l15: column(samples, (sample) => sample.load.l15),
        cpus: column(samples, (sample) => sample.cpu_count),
      }), 190);
    },
    disk() {
      const disks = deviceNames(state.samples, "disk");
      const diskSeries = state.disk === "all"
        ? [series("read", "read", COLORS.read, rate, false), series("write", "write", COLORS.write, rate, false)]
        : [
            series("read", "read", COLORS.read, rate, false),
            series("write", "write", COLORS.write, rate, false),
            series("util", "% util", COLORS.pct, pct, false, "y2", [5, 4]),
          ];
      addPanel(
        "Disk I/O",
        state.disk === "all" ? "Sum of read and write throughput. Loop devices are omitted." : `${state.disk} throughput and utilization.`,
        hooks,
        diskSeries,
        (samples) => state.disk === "all"
          ? {
              read: column(samples, (sample) => sum(sample, "disk", "read_kb_s")),
              write: column(samples, (sample) => sum(sample, "disk", "write_kb_s")),
            }
          : {
              read: column(samples, (sample) => sample.disk[state.disk]?.read_kb_s ?? null),
              write: column(samples, (sample) => sample.disk[state.disk]?.write_kb_s ?? null),
              util: column(samples, (sample) => sample.disk[state.disk]?.util_pct ?? null),
            },
        200,
        deviceSelect("Disk", disks, state.disk, (value) => {
          state.disk = value;
          chartSig = "";
          render();
        }),
      );
    },
    network() {
      const ifaces = deviceNames(state.samples, "net");
      addPanel(
        "Network",
        state.net === "all" ? "Sum of receive and transmit, excluding loopback." : `${state.net} receive and transmit.`,
        hooks,
        [series("rx", "receive", COLORS.rx, rate, false), series("tx", "transmit", COLORS.tx, rate, false)],
        (samples) => state.net === "all"
          ? {
              rx: column(samples, (sample) => sum(sample, "net", "rx_kb_s")),
              tx: column(samples, (sample) => sum(sample, "net", "tx_kb_s")),
            }
          : {
              rx: column(samples, (sample) => sample.net[state.net]?.rx_kb_s ?? null),
              tx: column(samples, (sample) => sample.net[state.net]?.tx_kb_s ?? null),
            },
        200,
        deviceSelect("Network interface", ifaces, state.net, (value) => {
          state.net = value;
          chartSig = "";
          render();
        }),
      );
    },
  };
  for (const name of ui.charts) {
    if (panels[name]) panels[name]();
  }
}

function addPanel(title, note, hooks, seriesList, columns, height, extra) {
  const section = document.createElement("section");
  section.className = "panel";
  const head = document.createElement("div");
  head.className = "panel-head";
  const heading = document.createElement("h2");
  heading.textContent = title;
  const copy = document.createElement("p");
  copy.className = "panel-note";
  copy.textContent = note;
  head.append(heading);
  if (extra) head.append(extra);
  const host = document.createElement("div");
  host.className = "chart-host";
  section.append(head, copy, host);
  chartsEl.append(section);
  const api = createChart(host, { ...hooks, series: seriesList, height, label: title });
  chartApis.push({ api, columns });
}

function deviceSelect(label, names, current, onChange) {
  if (!names.length) return null;
  const select = document.createElement("select");
  select.setAttribute("aria-label", label);
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = "All active";
  select.append(all);
  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.append(option);
  }
  select.value = names.includes(current) || current === "all" ? current : "all";
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

function renderTable() {
  tableWrap.replaceChildren();
  tableRows = [];
  const details = document.createElement("details");
  details.className = "samples";
  if (state.tableOpen == null) state.tableOpen = state.view.length > 0 && state.view.length <= ui.tableOpenBelow;
  details.open = state.tableOpen;
  details.addEventListener("toggle", () => {
    state.tableOpen = details.open;
  });
  const summary = document.createElement("summary");
  summary.textContent = `Raw samples in this window (${state.view.length})`;
  const scroller = document.createElement("div");
  scroller.className = "table-scroll";
  const table = document.createElement("table");
  const caption = document.createElement("caption");
  caption.textContent = "Original sar samples for the selected window. Values are not averaged or rolled up.";
  const head = document.createElement("thead");
  const labels = ["Time", "User", "System", "Iowait", "Steal", "Idle", "RAM %", "Used", "Free", "Available", "Swap %", "Load", "Disk read", "Disk write", "Net rx", "Net tx"];
  const headRow = document.createElement("tr");
  for (const label of labels) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    headRow.append(cell);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  state.view.forEach((sample, index) => {
    const row = document.createElement("tr");
    const timeCell = document.createElement("td");
    const jump = document.createElement("button");
    jump.type = "button";
    jump.className = "time-jump";
    jump.textContent = sample.iso.slice(11, 19);
    jump.addEventListener("click", () => focusIndex(index, true, false));
    timeCell.append(jump);
    row.append(
      timeCell,
      cell(pct(sample.cpu.user)),
      cell(pct(sample.cpu.system)),
      cell(pct(sample.cpu.iowait)),
      cell(pct(sample.cpu.steal)),
      cell(pct(sample.cpu.idle)),
      cell(pct(sample.mem.used_pct)),
      cell(gibText(sample.mem.used_kb)),
      cell(gibText(sample.mem.free_kb)),
      cell(gibText(sample.mem.avail_kb)),
      cell(pct(sample.swap.used_pct)),
      cell(num(sample.load.l1)),
      cell(rate(sum(sample, "disk", "read_kb_s"))),
      cell(rate(sum(sample, "disk", "write_kb_s"))),
      cell(rate(sum(sample, "net", "rx_kb_s"))),
      cell(rate(sum(sample, "net", "tx_kb_s"))),
    );
    body.append(row);
    tableRows.push(row);
  });
  table.append(caption, head, body);
  scroller.append(table);
  details.append(summary, scroller);
  tableWrap.append(details);
}

function renderReadouts() {
  fillCard(cursorCard, state.view[state.idx] ?? null, state.hovering ? "At cursor" : "Latest in window", true);
  fillCard(pinCard, state.pinned, "Pinned", false);
}

function fillCard(node, sample, title, isCursor) {
  node.replaceChildren();
  const head = document.createElement("div");
  head.className = "card-head";
  const heading = document.createElement("h2");
  heading.textContent = title;
  head.append(heading);
  const action = document.createElement("button");
  action.type = "button";
  if (isCursor) {
    action.textContent = "Pin this moment";
    action.disabled = !sample;
    action.addEventListener("click", () => {
      state.pinned = sample;
      renderReadouts();
    });
  } else {
    action.textContent = "Clear pin";
    action.disabled = !sample;
    action.addEventListener("click", () => {
      state.pinned = null;
      renderReadouts();
    });
  }
  head.append(action);
  const when = document.createElement("p");
  when.className = "when";
  if (!sample) {
    when.textContent = isCursor ? "Hover a chart, or use the arrow keys." : "Pin the cursor to keep one moment beside another.";
    node.append(head, when);
    return;
  }
  when.textContent = `${sample.iso.slice(0, 10)}  ${sample.iso.slice(11, 19)}`;
  const grid = document.createElement("div");
  grid.className = "metrics";
  const ramHot = (sample.mem.used_pct ?? 0) >= ui.hotRam;
  grid.append(
    metric("User", pct(sample.cpu.user), (sample.cpu.user ?? 0) >= ui.hotUser),
    metric("System", pct(sample.cpu.system), false),
    metric("Iowait", pct(sample.cpu.iowait), (sample.cpu.iowait ?? 0) >= ui.hotIowait),
    metric("Steal", pct(sample.cpu.steal), false),
    metric("Idle", pct(sample.cpu.idle), false),
    metric("RAM used", pct(sample.mem.used_pct), ramHot),
    metric("Used", gibText(sample.mem.used_kb), ramHot),
    metric("Free", gibText(sample.mem.free_kb), false),
    metric("Available", gibText(sample.mem.avail_kb), false),
    metric("Nice", pct(sample.cpu.nice), false),
    metric("Swap", pct(sample.swap.used_pct), (sample.swap.used_pct ?? 0) >= ui.hotSwap),
    metric("Load 1 / 5 / 15", `${num(sample.load.l1)}  ${num(sample.load.l5)}  ${num(sample.load.l15)}`, (sample.load.l1 ?? 0) >= (sample.cpu_count || 1)),
    metric("Disk read", rate(sum(sample, "disk", "read_kb_s")), false),
    metric("Disk write", rate(sum(sample, "disk", "write_kb_s")), false),
    metric("Net receive", rate(sum(sample, "net", "rx_kb_s")), false),
  );
  node.append(head, when, grid);
}

function paintCursor() {
  for (const item of chartApis) item.api.setCursor(state.idx);
  renderReadouts();
  tableRows.forEach((row, index) => row.classList.toggle("is-current", index === state.idx));
}

function focusIndex(index, hovering, scroll) {
  state.idx = index;
  state.hovering = hovering;
  paintCursor();
  if (scroll && tableRows[index]) tableRows[index].scrollIntoView({ block: "nearest" });
}

function focusSample(sample) {
  const index = state.view.indexOf(sample);
  if (index >= 0) focusIndex(index, true, true);
}

function stepDate(delta) {
  const index = state.dates.indexOf(state.date);
  const next = state.dates[index + delta];
  if (!next) return;
  state.date = next;
  dateSelect.value = next;
  setFullDayInputs();
  syncDateButtons();
  loadDay(next, false);
}

function syncDateButtons() {
  const index = state.dates.indexOf(state.date);
  document.querySelector("#prev").disabled = index <= 0;
  document.querySelector("#next").disabled = index < 0 || index >= state.dates.length - 1;
}

function setFullDayInputs() {
  fromInput.value = ui.from;
  toInput.value = ui.to;
}

function writeUrl() {
  if (!state.date) return;
  const url = new URL(location.href);
  url.searchParams.set("date", state.date);
  url.searchParams.set("start", fromInput.value);
  url.searchParams.set("end", toInput.value);
  history.replaceState(null, "", url);
  syncDateButtons();
}

function signature() {
  return [state.disk, state.net, deviceNames(state.samples, "disk").join(","), deviceNames(state.samples, "net").join(",")].join("|");
}

function viewKey() {
  if (!state.view.length) return `${state.date}:empty:${fromInput.value}:${toInput.value}`;
  const first = state.view[0];
  const last = state.view[state.view.length - 1];
  return [state.date, fromInput.value, toInput.value, state.view.length, first.epoch, last.epoch].join("|");
}

function series(key, label, color, format, hidden, scale = "y", dash = null) {
  return { key, label, color, format, hidden, scale, dash };
}

function column(samples, getter) {
  return samples.map((sample) => {
    const value = getter(sample);
    return value == null || Number.isNaN(value) ? null : value;
  });
}

function sum(sample, group, field) {
  let total = 0;
  let any = false;
  for (const device of Object.values(sample[group] || {})) {
    if (device[field] == null) continue;
    any = true;
    total += device[field];
  }
  return any ? total : null;
}

function deviceNames(samples, group) {
  const names = new Set();
  for (const sample of samples) Object.keys(sample[group] || {}).forEach((name) => names.add(name));
  return [...names].sort();
}

function toGib(kb) {
  return kb == null ? null : kb / 1048576;
}

function pct(value) {
  return value == null || Number.isNaN(value) ? "—" : `${Number(value).toFixed(2)}%`;
}

function num(value) {
  return value == null || Number.isNaN(value) ? "—" : Number(value).toFixed(2);
}

function gib(value) {
  return value == null || Number.isNaN(value) ? "—" : `${Number(value).toFixed(2)} GiB`;
}

function gibText(kb) {
  return gib(toGib(kb));
}

function rate(value) {
  if (value == null || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1024) return `${(value / 1024).toFixed(2)} MB/s`;
  return `${Number(value).toFixed(1)} kB/s`;
}

function metric(label, value, hot) {
  const node = document.createElement("div");
  node.className = hot ? "metric hot" : "metric";
  const strong = document.createElement("b");
  strong.textContent = value;
  const caption = document.createElement("span");
  caption.textContent = label;
  node.append(strong, caption);
  return node;
}

function cell(value) {
  const node = document.createElement("td");
  node.textContent = value;
  return node;
}

function networkText(network) {
  if (network === "demo") return "demo data, no SSH";
  if (network === "decode") return "decoded with sadf and cached locally";
  if (network === "catalog") return "file list checked over SSH, samples from local cache";
  return "local cache, server not contacted";
}

function cpuLabel(samples) {
  const counts = [...new Set(samples.map((sample) => sample.cpu_count).filter((value) => value != null))].sort((a, b) => a - b);
  if (!counts.length) return "";
  if (counts.length === 1) return `${counts[0]} CPU${counts[0] === 1 ? "" : "s"}`;
  return `${counts[0]}–${counts[counts.length - 1]} CPUs`;
}

function medianInterval(samples) {
  const values = samples.map((sample) => sample.interval).filter((value) => value > 0).sort((a, b) => a - b);
  if (!values.length) return null;
  return values[Math.floor(values.length / 2)];
}

function formatInterval(seconds) {
  if (seconds == null) return "";
  const minutes = seconds / 60;
  if (Math.abs(minutes - Math.round(minutes)) < 0.2) return `${Math.round(minutes)} min`;
  return `${Math.round(seconds)} s`;
}

function weekday(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
}

function tod(iso) {
  const [hour, minute, second] = iso.slice(11, 19).split(":").map(Number);
  return hour * 3600 + minute * 60 + second;
}

// Same window rule as sarview/window.py: an end time on the minute includes that minute's sample.
function windowBounds(start, end) {
  const from = parseClock(start);
  const to = parseClock(end);
  if (!from || !to) return null;
  const startSec = from.h * 3600 + from.m * 60 + from.s;
  let endSec = to.h * 3600 + to.m * 60 + to.s;
  if (to.s === 0) endSec += 59;
  if (endSec < startSec) return null;
  return [startSec, endSec];
}

function parseClock(text) {
  const parts = String(text || "").trim().split(":").map(Number);
  if (parts.length < 2 || parts.length > 3 || parts.some((value) => Number.isNaN(value))) return null;
  if (parts.length === 2) parts.push(0);
  const [hour, minute, second] = parts;
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) return null;
  return { h: hour, m: minute, s: second };
}

function formatHMS(total) {
  const hour = Math.floor(total / 3600);
  const minute = Math.floor((total % 3600) / 60);
  const second = Math.floor(total % 60);
  return [hour, minute, second].map((value) => String(value).padStart(2, "0")).join(":");
}

function ensureSeconds(value) {
  const parsed = parseClock(value);
  if (!parsed) return value;
  return formatHMS(parsed.h * 3600 + parsed.m * 60 + parsed.s);
}

function formatX(epoch, withSeconds) {
  const offset = state.day?.offset_minutes || 0;
  const shifted = new Date((epoch + offset * 60) * 1000);
  const hour = String(shifted.getUTCHours()).padStart(2, "0");
  const minute = String(shifted.getUTCMinutes()).padStart(2, "0");
  const second = String(shifted.getUTCSeconds()).padStart(2, "0");
  return withSeconds ? `${hour}:${minute}:${second}` : `${hour}:${minute}`;
}

function peak(samples, getter) {
  let best = null;
  for (const sample of samples) {
    const value = getter(sample);
    if (value == null || Number.isNaN(value)) continue;
    if (!best || value > best.value) best = { value, sample };
  }
  return best;
}

async function getJSON(url) {
  const response = await fetch(url);
  let body = {};
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function showError(message) {
  errorEl.hidden = false;
  errorEl.textContent = message;
}

function clearError() {
  errorEl.hidden = true;
  errorEl.textContent = "";
}

function setBusy(busy) {
  dateSelect.disabled = busy;
  document.querySelector("#refresh").disabled = busy;
  document.body.setAttribute("aria-busy", busy ? "true" : "false");
}
