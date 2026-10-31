"use strict";
const $ = id => document.getElementById(id);
const state = { points: [], histories: new Map(), controller: null, generation: 0 };
const time = value => new Date(value).toLocaleString();
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function request(url, signal) {
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`查詢失敗（HTTP ${response.status}）`);
  return response.json();
}
// 探索清單分頁讀取，不把 API 預設的第一頁當成全部設備／點位。
async function list(url, signal) {
  const result = [];
  for (let offset = 0; ; offset += 1000) {
    const page = await request(`${url}?limit=1000&offset=${offset}`, signal);
    result.push(...page);
    if (page.length < 1000) return result;
  }
}
function options(select, values, key, label, previous) {
  select.replaceChildren(...values.map(value => {
    const option = element("option", label(value)); option.value = value[key]; return option;
  }));
  if (values.some(value => value[key] === previous)) select.value = previous;
  select.disabled = !values.length;
}
function renderCards() {
  $("cards").replaceChildren();
  for (const point of state.points) {
    const latest = state.histories.get(point.point_id).readings[0];
    const card = element("article", undefined, "card");
    card.append(element("h3", point.name), element("p", point.code, "timestamp"));
    const value = element("p", latest ? latest.value : "尚無資料", "value");
    value.append(element("span", ` ${point.unit}`, "unit")); card.append(value);
    if (latest) card.append(element("p", `採集：${time(latest.acquired_at)}`, "timestamp"));
    $("cards").append(card);
  }
  if (!state.points.length) $("cards").append(element("p", "此設備尚未設定感測點。", "empty"));
}
function renderHistory() {
  const history = state.histories.get($("point").value);
  $("chart").replaceChildren(); $("readings").replaceChildren();
  if (!history || !history.readings.length) {
    $("range").textContent = "尚無量測資料。";
    $("chart").append(element("p", "等待資料入庫", "empty")); return;
  }
  const rows = history.readings;
  $("range").textContent = `最近 ${rows.length} 筆 · ${time(rows.at(-1).acquired_at)} — ${time(rows[0].acquired_at)}`;
  for (const row of rows) {
    const tr = element("tr");
    tr.append(element("td", time(row.acquired_at)), element("td", `${row.value} ${history.point.unit}`), element("td", time(row.received_at)));
    $("readings").append(tr);
  }
  // 原始十進位字串供卡片／表格顯示；只在繪圖時轉成 Number。
  const samples = [...rows].reverse().map(row => ({ x: Date.parse(row.acquired_at), y: Number(row.value) }));
  if (samples.some(p => !Number.isFinite(p.x) || !Number.isFinite(p.y))) {
    $("chart").append(element("p", "數值超出圖表可顯示範圍，請查看量測資料。", "empty")); return;
  }
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 920 280"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${history.point.name}，最近 ${rows.length} 筆量測趨勢，單位 ${history.point.unit}`);
  function draw(tag, attributes, text) {
    const node = document.createElementNS(svg.namespaceURI, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    svg.append(node); return node;
  }
  const xmin = samples[0].x, xmax = samples.at(-1).x;
  let ymin = Math.min(...samples.map(p => p.y)), ymax = Math.max(...samples.map(p => p.y));
  const pad = (ymax - ymin) * .12 || Math.max(Math.abs(ymin) * .01, .1);
  ymin -= pad; ymax += pad;
  const x = v => 85 + (xmax === xmin ? .5 : (v - xmin) / (xmax - xmin)) * 810;
  const y = v => 225 - (v - ymin) / (ymax - ymin) * 200;
  for (let i = 0; i <= 4; i++) {
    const value = ymin + (ymax - ymin) * i / 4, position = y(value);
    draw("line", { x1: 85, x2: 895, y1: position, y2: position, stroke: "#e4ebef" });
    draw("text", { x: 75, y: position + 4, "text-anchor": "end" }, Number(value.toPrecision(6)).toString());
  }
  draw("text", { x: 85, y: 15 }, history.point.unit);
  draw("polyline", { points: samples.map(p => `${x(p.x)},${y(p.y)}`).join(" "), fill: "none", stroke: "#167d74", "stroke-width": 2.5 });
  for (const sample of samples) {
    const dot = draw("circle", { cx: x(sample.x), cy: y(sample.y), r: 3, fill: "#167d74" });
    const title = document.createElementNS(svg.namespaceURI, "title");
    title.textContent = `${time(sample.x)} · ${sample.y} ${history.point.unit}`; dot.append(title);
  }
  draw("text", { x: 85, y: 255 }, time(xmin));
  draw("text", { x: 895, y: 255, "text-anchor": "end" }, time(xmax));
  $("chart").append(svg);
}
async function refresh(discover = false) {
  // 切換設備時取消舊查詢，避免較慢的舊回應覆蓋新設備。
  state.controller?.abort();
  const controller = new AbortController(); state.controller = controller;
  const generation = ++state.generation;
  const timeout = setTimeout(() => controller.abort(), 15000);
  $("refresh").disabled = true; $("error").hidden = true;
  $("status").textContent = "查詢中…";
  try {
    if (discover) {
      const devices = await list("/devices", controller.signal);
      options($("device"), devices, "device_id", d => `${d.name} (${d.device_id})`, $("device").value);
    }
    const deviceId = $("device").value;
    const points = deviceId ? await list(`/devices/${encodeURIComponent(deviceId)}/points`, controller.signal) : [];
    const histories = new Map();
    // 依序查詢，避免點位增加時一次開出大量 DB 請求。
    for (const point of points) histories.set(point.point_id, await request(`/points/${encodeURIComponent(point.point_id)}/readings?limit=100`, controller.signal));
    if (generation !== state.generation) return;
    state.points = points; state.histories = histories;
    options($("point"), points, "point_id", p => `${p.name} (${p.unit})`, $("point").value);
    renderCards(); renderHistory();
    $("status").textContent = deviceId ? `查詢成功：${new Date().toLocaleTimeString()} · 每 5 秒更新` : "尚無設備，等待設備初始化。";
  } catch (error) {
    if (generation !== state.generation) return;
    $("status").textContent = "此次更新失敗";
    $("error").textContent = `${error.name === "AbortError" ? "查詢逾時" : error.message}；若有先前資料，仍保留顯示，並非新量測。`;
    $("error").hidden = false;
  } finally {
    clearTimeout(timeout);
    if (generation === state.generation) { state.controller = null; $("refresh").disabled = false; }
  }
}
$("device").addEventListener("change", () => {
  state.points = []; state.histories.clear(); $("cards").replaceChildren();
  options($("point"), [], "point_id", p => p.name); renderHistory(); refresh();
});
$("point").addEventListener("change", renderHistory);
$("refresh").addEventListener("click", () => refresh(true));
refresh(true);
setInterval(() => { if (!state.controller && !document.hidden) refresh(true); }, 5000);
