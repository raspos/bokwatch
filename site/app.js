/* 중앙 BOK워치 — 단일 페이지. 외부 요청은 같은 출처 data/*.json 뿐. */
(function () {
  "use strict";

  // ------------------------------------------------------------ 유틸
  const $ = (s, el = document) => el.querySelector(s);
  const D = {};                 // 로드된 데이터
  const S = { tab: "market", d: null, s: "0", chip: "", spk: "", ven: "", dot: "", q: "", sort: "", qf: "", qd: "" };
  const TABS = ["market", "guidance", "minutes", "news", "qual", "memo", "method"];

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
    return el;
  }
  const ext = (href, text, cls) => href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", class: cls }, text) : h("span", { class: cls }, text);
  const pct = (x, n = 1) => x == null || isNaN(x) ? "–" : (x * 100).toFixed(n) + "%";
  const pp = (x) => x == null || isNaN(x) ? "" : (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(1) + "%p";
  const fx = (x, n = 2) => x == null || isNaN(x) ? "–" : Number(x).toFixed(n);
  const md = (s) => { if (!s) return "–"; const [y, m, d] = s.slice(0, 10).split("-").map(Number); return `${m}/${d}`; };
  const ymd = (s) => s ? s.slice(0, 10).replaceAll("-", ".") : "–";
  const mon = (s) => Number(s.slice(5, 7)) + "월";
  const todayKST = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const days = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);

  async function getJSON(path) {
    try { const r = await fetch(path, { cache: "no-cache" }); if (!r.ok) return null; return await r.json(); }
    catch (e) { return null; }
  }
  async function getText(path) {
    try { const r = await fetch(path, { cache: "no-cache" }); return r.ok ? await r.text() : null; } catch (e) { return null; }
  }
  // d3.csvParse는 new Function을 써서 CSP(unsafe-eval 금지)에 막힌다 → 단순 파서
  function parseCSV(text) {
    const [head, ...lines] = text.trim().split(/\r?\n/);
    const keys = head.split(",");
    return lines.filter(Boolean).map((l) => {
      const v = l.split(",");
      const o = {};
      keys.forEach((k, i) => { const x = v[i]; o[k] = x !== "" && !isNaN(+x) && !/^\d{4}-/.test(x) ? +x : x; });
      return o;
    });
  }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  // ------------------------------------------------------------ URL 해시 상태
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    for (const k of Object.keys(S)) if (p.has(k)) S[k] = p.get(k);
    if (!TABS.includes(S.tab)) S.tab = "market";
    if (!["-5", "0", "5"].includes(S.s)) S.s = "0";
  }
  function writeHash() {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(S)) if (v && !(k === "s" && v === "0") && !(k === "tab" && v === "market")) p.set(k, v);
    const str = p.toString();
    history.replaceState(null, "", str ? "#" + str : location.pathname + location.search);
  }

  // ------------------------------------------------------------ 툴팁
  const tip = $("#tip");
  function showTip(ev, html) {
    tip.replaceChildren(...(Array.isArray(html) ? html : [html]).map((t) => h("div", {}, t)));
    tip.hidden = false;
    const x = Math.min(ev.clientX + 12, innerWidth - tip.offsetWidth - 8);
    const y = Math.max(8, ev.clientY - tip.offsetHeight - 10);
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  const hideTip = () => { tip.hidden = true; };

  // ------------------------------------------------------------ 로드
  async function load() {
    const [meta, status, guidance, reports, minutes, news, memo, backtest, hist, events, qual] = await Promise.all([
      getJSON("data/meta.json"), getJSON("data/status.json"), getJSON("data/guidance.json"),
      getJSON("data/reports.json"), getJSON("data/minutes.json"), getJSON("data/news.json"),
      getJSON("data/memo.json"), getJSON("data/backtest.json"), getText("data/history.csv"),
      getJSON("data/events.json"), getJSON("data/qual.json"),
    ]);
    Object.assign(D, { meta: meta || {}, status: status || {}, guidance: guidance || { meetings: [], dotplots: [], speeches: [] },
      reports: reports || { reports: [], consensus: { by_meeting: {} } }, minutes: minutes || { meetings: [] },
      news: news || { items: [], chips: [] }, memo, backtest, hist: hist ? parseCSV(hist) : [],
      events: events || { upcoming: [], recent: [], all: [], indicators: {} }, qual });
    D.snaps = {};
  }
  async function snapshot(date) {
    if (!date) return null;
    if (!(date in D.snaps)) D.snaps[date] = await getJSON(`data/snapshots/${date}.json`);
    return D.snaps[date];
  }
  const prevDate = (date) => { const ix = D.meta.snapshots || []; const i = ix.indexOf(date); return i > 0 ? ix[i - 1] : null; };

  // ------------------------------------------------------------ 헤더·경고
  function renderHeader(snap) {
    const m = D.meta;
    $("#banner").hidden = !m.banner;
    const today = todayKST();
    const next = (m.upcoming || [])[0];
    const kids = [
      h("span", {}, "데이터 기준 ", h("b", {}, ymd(snap ? snap.asof : m.latest))),
      h("span", {}, "갱신 ", h("b", {}, m.built ? m.built.slice(5, 16).replace("T", " ") : "–")),
      h("span", {}, "기준금리 ", h("b", {}, snap ? fx(snap.r0) + "%" : (m.r0 != null ? fx(m.r0) + "%" : "–"))),
      next ? h("span", {}, "다음 금통위 ", h("b", {}, md(next)), " ", h("span", { class: "dday" }, `D-${days(today, next)}`)) : h("span", { class: "badge warn" }, "다음 금통위 일정 미입력"),
    ];
    if (m.next_event) {
      const e = m.next_event;
      kids.push(h("span", {}, "다음 주요 지표 ", h("b", {}, `${md(e.date)}${e.time ? " " + e.time : ""} ${e.label}`)));
    }
    if ((m.new_minutes || []).length) kids.push(h("span", { class: "badge new" }, "새 의사록"));
    if ((m.new_reports || []).length) kids.push(h("span", { class: "badge new", title: m.new_reports.join(", ") }, `새 보고서 ${m.new_reports.length}`));
    const lastVisit = store("bokwatch.lastVisit");
    const mainKw = D.news.main_keyword || "신현송";
    const fresh = D.news.items.filter((x) => x.keywords.includes(mainKw) && (lastVisit ? x.published > lastVisit : (m.new_main_news || []).includes(x.id)));
    if (fresh.length) kids.push(h("span", { class: "badge new" }, `새 ${mainKw} 기사 ${fresh.length}`));
    for (const w of m.warnings || []) kids.push(h("span", { class: "badge warn" }, w));
    $("#meta").replaceChildren(...kids);

    const al = [];
    const names = { ecos: "ECOS 시장금리", news: "연합뉴스 RSS", bok: "한은 홈페이지", events: "경제지표 일정", naver: "네이버 뉴스 API", ai: "AI 정성 판단" };
    for (const [k, v] of Object.entries(D.status || {})) {
      if (v && v.ok === false) al.push(h("div", { class: "alert bad" },
        `갱신 실패 — ${names[k] || k}: ${v.message || "원인 미상"} · 마지막 성공 ${v.last_success ? v.last_success.replace("T", " ") : "없음"}`));
    }
    const never = Object.keys(names).filter((k) => !D.status || !D.status[k]).map((k) => names[k]);
    if (never.length) al.push(h("div", { class: "alert" }, `수집 기록 없음: ${never.join(", ")} (자동 갱신 첫 실행 전)`));
    $("#alerts").replaceChildren(...al);
  }

  // ------------------------------------------------------------ 요약 띠
  function renderStrip(snap) {
    const scen = snap && snap.scenarios[S.s];
    const ms = scen ? scen.meetings.filter((m) => m.in_range) : [];
    const nxt = ms[0];
    const dp = (D.guidance.dotplots || [])[0];
    const r0 = snap ? snap.r0 : D.meta.r0;
    const cons = D.reports.consensus.by_meeting || {};
    const nextDate = nxt ? nxt.date : (D.meta.upcoming || [])[0];
    const c = nextDate ? cons[nextDate] : null;
    const tiles = [];
    // 시장
    tiles.push(h("div", { class: "tile" }, h("div", { class: "k" }, `시장 · ${nextDate ? mon(nextDate) + " 회의" : "다음 회의"} 인상 확률`),
      h("div", { class: "v" }, nxt ? pct(nxt.p_hike) : "–"),
      h("div", { class: "s" }, ms[1] ? `${mon(ms[1].date)} ${pct(ms[1].p_hike)} · 기대금리 ${fx(ms[1].expected)}%` : "")));
    // 한은 점도표
    tiles.push(h("div", { class: "tile" }, h("div", { class: "k" }, `한은 · 최신 점도표(${dp ? ymd(dp.date) : "–"}) 중간값`),
      h("div", { class: "v" }, dp ? fx(dp.median) + "%" : "–"),
      h("div", { class: "s" }, dp && r0 != null ? `현 ${fx(r0)}% 대비 위 ${dots(dp, r0).above} · 같음 ${dots(dp, r0).at} · 아래 ${dots(dp, r0).below}` : "")));
    // 전문가
    tiles.push(h("div", { class: "tile" }, h("div", { class: "k" }, `전문가 · ${nextDate ? mon(nextDate) : ""} '인상' 전망 기관 비율`),
      h("div", { class: "v" }, c && c.n ? pct(c.hike_share, 0) : "–"),
      h("div", { class: "s" }, c && c.n ? `${c.counts["인상"] || 0}/${c.n}곳 · ` + secondCons(ms[1]) : "")));
    // 엇갈림: 방향 신호가 다르면 강조
    const sig = [nxt ? nxt.p_hike >= 0.5 : null, dp && r0 != null ? dp.median > r0 : null, c && c.n ? c.hike_share >= 0.5 : null];
    const known = sig.filter((x) => x != null);
    const diverge = known.length >= 2 && known.some((x) => x !== known[0]);
    if (diverge) {
      sig.forEach((x, i) => { if (x != null && x !== majority(known)) tiles[i].classList.add("diverge"); });
      const lbl = ["시장", "점도표", "전문가"].map((n, i) => sig[i] == null ? null : `${n} ${sig[i] ? "인상 쪽" : "동결 쪽"}`).filter(Boolean).join(" · ");
      tiles.push(h("div", { class: "strip-note" }, `엇갈림 — ${lbl} (점도표는 6개월 뒤 전망, 시장·전문가는 다음 회의 기준)`));
    }
    const Q = D.qual && D.qual.synthesis;
    const pr = D.qual && D.qual.pressure;
    tiles.splice(3, 0, h("div", { class: "tile ref" }, h("div", { class: "k" }, "참고 · AI 정성 판단(뉴스)"),
      h("div", { class: "v" }, Q ? LEAN[Q.lean] : "–"),
      h("div", { class: "s" }, Q ? Q.headline : "네이버 뉴스·Claude API 연결 후 표시",
        pr && pr.index != null ? ` · 압력지수 ${pr.index >= 0 ? "+" : ""}${pr.index.toFixed(2)}` : "")));
    $("#strip").replaceChildren(...tiles);
  }
  const LEAN = { "-2": "강한 인하 압력", "-1": "인하 압력", "0": "중립", "1": "인상 압력", "2": "강한 인상 압력" };
  const majority = (arr) => arr.filter(Boolean).length * 2 >= arr.length;
  function secondCons(m2) {
    if (!m2) return "";
    const c = (D.reports.consensus.by_meeting || {})[m2.date];
    return c && c.n ? `${mon(m2.date)} ${c.counts["인상"] || 0}/${c.n}곳` : "";
  }
  function dots(dp, r0) {
    let above = 0, at = 0, below = 0;
    for (const [lv, n] of Object.entries(dp.dist)) { const v = +lv; if (v > r0 + 1e-9) above += n; else if (v < r0 - 1e-9) below += n; else at += n; }
    return { above, at, below };
  }

  // ------------------------------------------------------------ 탭 1 시장
  function gaugeSVG(p) {
    const W = 250, H = 132, cx = W / 2, cy = 116, R = 92, T = 16;
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", `인상 확률 ${pct(p)}`);
    const arc = d3.arc().innerRadius(R - T).outerRadius(R).cornerRadius(3);
    const a0 = -Math.PI / 2, a1 = Math.PI / 2, ap = a0 + (a1 - a0) * Math.max(0, Math.min(1, p || 0));
    svg.append("path").attr("transform", `translate(${cx},${cy})`).attr("d", arc({ startAngle: a0, endAngle: a1 })).attr("fill", "var(--surface-2)").attr("stroke", "var(--line)");
    if (p > 0) svg.append("path").attr("transform", `translate(${cx},${cy})`).attr("d", arc({ startAngle: a0, endAngle: ap })).attr("fill", "var(--hike)");
    for (const t of [0, 25, 50, 75, 100]) {
      const a = a0 + (a1 - a0) * t / 100, s = Math.sin(a), c = -Math.cos(a);
      svg.append("line").attr("x1", cx + s * (R + 2)).attr("y1", cy + c * (R + 2)).attr("x2", cx + s * (R + 7)).attr("y2", cy + c * (R + 7)).attr("stroke", "var(--ink-3)");
      svg.append("text").attr("x", cx + s * (R + 15)).attr("y", cy + c * (R + 15) + 4).attr("text-anchor", "middle").attr("font-size", 9).attr("fill", "var(--ink-3)").text(t);
    }
    const s = Math.sin(ap), c = -Math.cos(ap);
    svg.append("line").attr("x1", cx).attr("y1", cy).attr("x2", cx + s * (R - 22)).attr("y2", cy + c * (R - 22)).attr("stroke", "var(--ink)").attr("stroke-width", 2.5).attr("stroke-linecap", "round");
    svg.append("circle").attr("cx", cx).attr("cy", cy).attr("r", 5).attr("fill", "var(--ink)");
    svg.append("text").attr("x", cx).attr("y", cy - 26).attr("text-anchor", "middle").attr("font-size", 26).attr("font-weight", 700).attr("fill", "var(--ink)").text(pct(p));
    svg.append("text").attr("x", cx).attr("y", cy - 10).attr("text-anchor", "middle").attr("font-size", 10).attr("fill", "var(--ink-3)").text("인상 확률");
    return svg.node();
  }

  async function renderMarket(snap) {
    document.querySelectorAll("#spreadToggle button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.s === S.s));
    if (!snap) {
      $("#gauges").replaceChildren(h("div", { class: "empty" }, "시장금리 데이터가 없습니다. ECOS 수집(daily.yml) 또는 data/manual 수동 입력 후 표시됩니다."));
      ["#probTable", "#inputTable"].forEach((s) => $(s).replaceChildren());
      renderTrend(); return;
    }
    const scen = snap.scenarios[S.s];
    const pd = prevDate(snap.asof);
    const prev = pd ? await snapshot(pd) : null;
    const ms = scen.meetings.filter((m) => m.in_range);
    const cards = ms.slice(0, 3).map((m) => {
      const pm = prev && prev.scenarios[S.s].meetings.find((x) => x.date === m.date && x.in_range);
      const ch = pm ? m.p_hike - pm.p_hike : null;
      const cls = ch == null ? "flat" : ch > 0.0005 ? "up" : ch < -0.0005 ? "down" : "flat";
      return h("div", { class: "gauge" },
        h("span", { class: `badge chg ${cls}`, title: pm ? `전일(${ymd(pd)}) 대비` : "전일 데이터 없음" }, ch == null ? "전일 –" : "전일 " + pp(ch)),
        h("h4", {}, `${ymd(m.date)} 금통위`),
        gaugeSVG(m.p_hike),
        h("div", { class: "sub" }, `동결 ${pct(m.p_hold)} · 인상 ${pct(m.p_hike)}` + (m.p_cut > 0 ? ` · 인하 ${pct(m.p_cut)}` : "")),
        h("div", { class: "sub" }, `회의 뒤 기대 금리 ${fx(m.expected, 3)}%`),
        h("div", { class: "method-tag" }, { bootstrap: "부트스트래핑", min_hike: "최소 인상 경로", lsq: "비음수 최소제곱" }[m.method] || m.method));
    });
    const out = scen.meetings.filter((m) => !m.in_range).map((m) => md(m.date));
    if (!cards.length) cards.push(h("div", { class: "empty" }, "투입 상품 만기 안에 금통위가 없습니다."));
    $("#gauges").replaceChildren(...cards);

    // 확률표
    const levels = (D.meta.levels || [2.75, 3, 3.25, 3.5, 3.75]).map((x) => (+x).toFixed(2));
    const thead = h("thead", {}, h("tr", {}, h("th", {}, "회의"), ...levels.map((l) => h("th", {}, l + "%")), h("th", {}, "기대금리")));
    const rows = ms.map((m) => {
      const vals = levels.map((l) => m.levels[l] || 0);
      const outside = Object.entries(m.levels).filter(([l]) => !levels.includes(l));
      const mx = Math.max(...Object.values(m.levels));
      return h("tr", {}, h("td", {}, ymd(m.date)),
        ...levels.map((l, i) => h("td", { class: vals[i] === mx && mx > 0 ? "max" : vals[i] === 0 ? "zero" : null }, vals[i] ? pct(vals[i]) : "0.0%")),
        h("td", {}, fx(m.expected, 3) + "%" + (outside.length ? " *" : "")));
    });
    $("#probTable").replaceChildren(thead, h("tbody", {}, rows));

    // 투입 금리표
    const ih = h("thead", {}, h("tr", {}, ...["상품", "금리", "기준일", "기준금리 대비", "전일 대비", "정상 스프레드", "계산 사용", "출처"].map((t, i) => h("th", { class: i === 7 ? "l" : null }, t))));
    const ib = snap.inputs.map((i) => h("tr", {},
      h("td", {}, i.label), h("td", {}, fx(i.rate, 3) + "%"), h("td", {}, ymd(i.date)),
      h("td", {}, i.vs_base_bp == null ? "–" : (i.vs_base_bp >= 0 ? "+" : "") + i.vs_base_bp + "bp"),
      h("td", {}, i.chg_bp == null ? "–" : (i.chg_bp >= 0 ? "+" : "") + i.chg_bp + "bp"),
      h("td", { title: i.spread_how }, (i.spread * 100 + (i.used ? +S.s : 0)).toFixed(0) + "bp"),
      h("td", {}, i.used ? "사용" : "참고"), h("td", { class: "l" }, i.source)));
    $("#inputTable").replaceChildren(ih, h("tbody", {}, ib));
    const used = snap.inputs.find((i) => i.used);
    $("#marketNote").textContent = [`기준금리 ${fx(snap.r0)}% (${snap.r0_source}).`,
      used ? `정상 스프레드: ${used.label} ${(used.spread * 100).toFixed(0)}bp — ${used.spread_how}${S.s !== "0" ? `, 화면은 ${S.s > 0 ? "+" : ""}${S.s}bp 가정` : ""}.` : "",
      `계산 방식: ${scen.method.replace("min_hike", "최소 인상 경로").replace("bootstrap", "부트스트래핑").replace("lsq", "비음수 최소제곱")}.`, out.length ? `만기 밖이라 계산하지 않은 회의: ${out.join(", ")}.` : "",
      ...(snap.warnings || [])].filter(Boolean).join(" ");
    renderTrend();
    renderEvents();
  }

  function renderEvents() {
    const E = D.events;
    const flag = { US: "미국", KR: "한국" };
    const ind = Object.values(E.indicators || {});
    const tiles = ind.length ? ind.map((x) => h("div", { class: "tile" }, h("div", { class: "k" }, `${x.label} · ${x.month} 전년동월비`),
      h("div", { class: "v" }, fx(x.yoy, 1) + "%"),
      h("div", { class: "s" }, (x.prev_yoy != null ? `전월 ${fx(x.prev_yoy, 1)}%` : "") + (x.core_yoy != null ? ` · 근원 ${fx(x.core_yoy, 1)}%` : "")),
      h("div", { class: "note" }, x.source))) : [h("p", { class: "note" }, "지표 실제치 수집 전 (FRED·ECOS)")];
    $("#indicators").replaceChildren(...tiles);
    const imp = (n) => "●".repeat(n) + "○".repeat(3 - n);
    const row = (e) => h("tr", { class: e.status === "오늘" ? "today" : null },
      h("td", {}, ymd(e.date)), h("td", {}, e.time || "–"), h("td", {}, flag[e.country] || e.country),
      h("td", { class: "l" }, e.link ? ext(e.link, e.label) : e.label, e.verify ? h("span", { class: "badge verify" }, "확인 필요") : ""),
      h("td", { title: "중요도" }, imp(e.importance || 1)), h("td", { class: "l" }, e.source));
    const head = h("thead", {}, h("tr", {}, ...["날짜", "시각(KST)", "국가", "이벤트", "중요도", "출처"].map((t, i) => h("th", { class: i === 3 || i === 5 ? "l" : null }, t))));
    const up = (E.upcoming || []).filter((e) => !(e.kind === "bok" && e.date === (D.meta.upcoming || [])[0] && false));
    $("#eventTable").replaceChildren(head, h("tbody", {}, up.length ? up.map(row) : [h("tr", {}, h("td", { colspan: 6 }, "예정 이벤트 없음"))]));
    $("#eventNote").textContent = (E.skeleton ? "경제지표 일정 수집 전 — 금통위·의사록·수기 입력(data/events.yaml)만 표시. " : "") +
      "미국 일정은 BLS·연준 발표 시각(미 동부)을 KST로 바꾼 값. 한국 CPI 등 국내 지표 일정은 data/events.yaml 수기 입력.";
  }

  function renderTrend() {
    const el = $("#trend");
    const rows = D.hist.filter((r) => String(r.scenario) === S.s);
    const meets = [...new Set(rows.map((r) => r.meeting instanceof Date ? r.meeting.toISOString().slice(0, 10) : String(r.meeting)))]
      .filter((m) => m >= todayKST().slice(0, 10) || true).sort().slice(-3);
    if (!rows.length) { el.replaceChildren(h("div", { class: "empty" }, "추이 데이터 없음")); return; }
    const W = Math.max(320, el.clientWidth - 16), H = 240, m = { t: 14, r: 16, b: 26, l: 40 };
    const pDate = (v) => v instanceof Date ? v : new Date(v);
    const key = (v) => v instanceof Date ? v.toISOString().slice(0, 10) : String(v);
    const series = meets.map((mt) => ({ mt, pts: rows.filter((r) => key(r.meeting) === mt).map((r) => ({ d: pDate(r.date), p: r.p_hike })).sort((a, b) => a.d - b.d) }));
    const allD = rows.map((r) => pDate(r.date));
    let [x0, x1] = d3.extent(allD);
    if (+x0 === +x1) { x0 = d3.timeDay.offset(x0, -7); x1 = d3.timeDay.offset(x1, 7); }
    const x = d3.scaleTime().domain([x0, x1]).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, 1]).range([H - m.b, m.t]);
    const colors = ["#2a78d6", "#eb6834", "#1baf7a"];
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "회의별 인상 확률 추이");
    svg.append("g").attr("class", "gridline").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickSize(-(W - m.l - m.r)).tickFormat("")).call((g) => g.select(".domain").remove());
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.min(6, W / 90)).tickFormat(d3.timeFormat("%m/%d")));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickFormat(d3.format(".0%"))).call((g) => g.select(".domain").remove());
    // 세로선
    const marks = [];
    for (const d of [...(D.meta.upcoming || []), ...D.guidance.meetings.map((g) => g.date)]) marks.push({ d, t: "금통위" });
    for (const mm of D.minutes.meetings || []) if (mm.minutes_expected) marks.push({ d: mm.minutes_expected, t: "의사록" });
    const short = { cpi: (e) => (e.country === "US" ? "美" : "韓") + "CPI", fomc: () => "FOMC", jobs: () => "美고용" };
    for (const e of D.meta.events || []) if (short[e.kind]) marks.push({ d: e.date, t: short[e.kind](e) });
    for (const mk of marks) {
      const dx = new Date(mk.d);
      if (dx < x.domain()[0] || dx > x.domain()[1]) continue;
      svg.append("line").attr("x1", x(dx)).attr("x2", x(dx)).attr("y1", m.t).attr("y2", H - m.b).attr("stroke", "var(--ink-3)").attr("stroke-dasharray", mk.t === "금통위" ? null : "3 3").attr("opacity", .6);
      svg.append("text").attr("x", x(dx) + 3).attr("y", m.t + 9).attr("font-size", 10).attr("fill", "var(--ink-3)").text(mk.t);
    }
    series.forEach((s, i) => {
      svg.append("path").datum(s.pts).attr("fill", "none").attr("stroke", colors[i]).attr("stroke-width", 2).attr("d", d3.line().x((d) => x(d.d)).y((d) => y(d.p)));
      svg.selectAll(null).data(s.pts).join("circle").attr("cx", (d) => x(d.d)).attr("cy", (d) => y(d.p)).attr("r", 4).attr("fill", colors[i]).attr("stroke", "var(--surface)").attr("stroke-width", 2);
      const last = s.pts[s.pts.length - 1];
      if (last) svg.append("text").attr("x", Math.min(x(last.d) + 6, W - 60)).attr("y", y(last.p) - 6).attr("font-size", 11).attr("fill", "var(--ink-2)").text(`${mon(s.mt)} ${pct(last.p)}`);
    });
    // 크로스헤어
    const hover = svg.append("line").attr("y1", m.t).attr("y2", H - m.b).attr("stroke", "var(--ink-2)").attr("opacity", 0);
    svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b).attr("fill", "transparent")
      .on("pointermove", (ev) => {
        const [px] = d3.pointer(ev); const dt = x.invert(px);
        const near = d3.least(allD, (d) => Math.abs(d - dt)); if (!near) return;
        hover.attr("x1", x(near)).attr("x2", x(near)).attr("opacity", .5);
        showTip(ev, [d3.timeFormat("%Y.%m.%d")(near), ...series.map((s) => { const p = s.pts.find((q) => +q.d === +near); return `${md(s.mt)} 회의 ${p ? pct(p.p) : "–"}`; })]);
      }).on("pointerleave", () => { hover.attr("opacity", 0); hideTip(); });
    const legend = h("div", { class: "legend" }, ...series.map((s, i) => h("span", {}, h("i", { style: `background:${colors[i]}` }), `${ymd(s.mt)} 회의`)));
    const n = new Set(allD.map((d) => +d)).size;
    el.replaceChildren(legend, svg.node(), n < 2 ? h("div", { class: "note" }, `이력 ${n}일 — 매일 장 마감 뒤 누적됩니다.`) : "");
  }

  // ------------------------------------------------------------ 탭 2 가이던스
  function dotplotSVG(dp, r0, compact) {
    const lv = Object.keys(dp.dist).map(Number);
    const lo = Math.min(...lv, r0) - 0.25, hi = Math.max(...lv, r0) + 0.25;
    const levels = d3.range(Math.round(lo * 4), Math.round(hi * 4) + 1).map((v) => v / 4);
    const maxN = Math.max(...Object.values(dp.dist));
    const W = 340, rowH = compact ? 24 : 28, H = levels.length * rowH + 24, L = 52, gap = Math.min(16, (W - L - 16) / Math.max(maxN, 1));
    const y = (v) => 10 + (hi - v) * 4 * rowH + rowH / 2;
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", `점도표 ${dp.date} 중간값 ${dp.median}%`);
    for (const v of levels) {
      svg.append("line").attr("x1", L).attr("x2", W - 8).attr("y1", y(v)).attr("y2", y(v)).attr("stroke", "var(--line)").attr("stroke-dasharray", "2 3");
      svg.append("text").attr("x", L - 8).attr("y", y(v) + 4).attr("text-anchor", "end").attr("font-size", 11).attr("fill", "var(--ink-3)").text(v.toFixed(2) + "%");
    }
    // 현재 기준금리
    svg.append("line").attr("x1", L).attr("x2", W - 8).attr("y1", y(r0)).attr("y2", y(r0)).attr("stroke", "var(--ink-3)").attr("stroke-width", 1).attr("opacity", .7);
    svg.append("text").attr("x", W - 8).attr("y", y(r0) - 4).attr("text-anchor", "end").attr("font-size", 10).attr("fill", "var(--ink-2)").text(`당시 기준금리 ${fx(r0)}%`);
    for (const [k, n] of Object.entries(dp.dist)) {
      const v = +k;
      for (let i = 0; i < n; i++) {
        svg.append("circle").attr("cx", L + 12 + i * gap).attr("cy", y(v)).attr("r", 6)
          .attr("fill", v > r0 + 1e-9 ? "var(--hike)" : v < r0 - 1e-9 ? "var(--cut)" : "var(--hold)").attr("stroke", "var(--surface)").attr("stroke-width", 2)
          .on("pointermove", (ev) => showTip(ev, `${v.toFixed(2)}% · ${n}명`)).on("pointerleave", hideTip);
      }
      svg.append("text").attr("x", L + 12 + n * gap + 2).attr("y", y(v) + 4).attr("font-size", 11).attr("fill", "var(--ink-2)").text(n);
    }
    // 중간값
    svg.append("path").attr("d", `M${L - 2},${y(dp.median) - 6}L${L + 4},${y(dp.median)}L${L - 2},${y(dp.median) + 6}Z`).attr("fill", "var(--ink)");
    return svg.node();
  }

  function renderGuidance() {
    const G = D.guidance;
    const dps = G.dotplots || [];
    const sel = $("#dotSel");
    sel.replaceChildren(...dps.map((d) => h("option", { value: d.date, selected: d.date === S.dot }, ymd(d.date))));
    if (!dps.length) { $("#dots").replaceChildren(h("div", { class: "empty" }, "점도표 입력 없음")); }
    else {
      const i = Math.max(0, dps.findIndex((d) => d.date === S.dot));
      const a = dps[i], b = dps[i + 1];
      const card = (dp, main) => h("div", { class: "dotcard" + (main ? " main" : "") },
        h("h4", {}, `${ymd(dp.date)} ${main ? (i === 0 ? "최신" : "선택") : "직전"} · 점 ${dp.n}개`),
        h("div", { class: "sub" }, `중간값 ${fx(dp.median)}% · 당시 기준금리 위 ${dp.above} · 같음 ${dp.at} · 아래 ${dp.below}`),
        dotplotSVG(dp, dp.rate, !main));
      $("#dots").replaceChildren(card(a, true), b ? card(b, false) : h("div", { class: "dotcard empty" }, "직전 점도표 없음"));
      const mv = b ? (a.median - b.median) * 100 : null;
      $("#dotNote").textContent = [b ? `중간값 ${fx(b.median)}% → ${fx(a.median)}% ${mv > 0 ? "▲" : mv < 0 ? "▼" : "→"} ${mv >= 0 ? "+" : ""}${mv.toFixed(0)}bp.` : "",
        `점 분포: ${Object.entries(a.dist).map(([k, n]) => `${k}% ${n}개`).join(", ")}.`,
        G.next_dotplot ? `다음 점도표 공개 예정: ${ymd(G.next_dotplot)} 회의.` : "다음 점도표 공개 회의: 일정 미입력.",
        "점 색: 주황=당시 기준금리 위, 회색=같음, 파랑=아래. ◀ 표시는 중간값."].filter(Boolean).join(" ");
    }

    // 회의 카드
    const cards = G.meetings.map((m) => {
      const v = m.vote;
      const dl = h("dl", {});
      const add = (k, ...vv) => dl.append(h("dt", {}, k), h("dd", {}, ...vv));
      add("표결", v ? `${v.for}명 찬성` + (v.dissent && v.dissent.length ? ` · 소수의견: ${v.dissent.map((x) => `${x.name}(${x.view})`).join(", ")}` : " · 만장일치") : "미입력");
      const fg = m.forward_guidance;
      add("포워드 가이던스", fg ? `3개월 내 인상 열어둔 위원 ${fg.hike ?? "–"} · 동결 ${fg.hold ?? "–"} · 인하 ${fg.cut ?? "–"}` : "미입력");
      if (m.press_quotes.length) add("간담회", ...m.press_quotes.map((q) => h("div", {}, `${q.speaker}: “${q.text}”`)));
      if (m.outlook) add("전망", `성장률 2026년 ${m.outlook.gdp_2026}% · 2027년 ${m.outlook.gdp_2027}%`);
      if (m.diff) add("통방문 변화", h("ul", { class: "diff" }, ...m.diff.map((x) => h("li", { class: x.op }, x.text))),
        m.statement_provisional ? h("div", { class: "note" }, "보도 인용 문구만 담은 임시본 — 원문 대조 필요") : "");
      else if (!m.has_statement) add("통방문", "원문 미입력 (data/statements/)");
      const L = m.links || {};
      const doc = (k, label) => L[k] ? ext(L[k].url, label) : null;
      const pdf = (k) => L[k] && L[k].attachments && L[k].attachments[0] ? ext(L[k].attachments[0].url, "PDF") : null;
      add("원문", h("span", { class: "links" }, doc("statement", "결정문") || h("span", { class: "note" }, "결정문 링크 수집 전"), pdf("statement"),
        doc("minutes", "의사록") || h("span", {}, m.minutes_expected ? `의사록 공개 예정 ${ymd(m.minutes_expected)}` : "의사록 –"), pdf("minutes"), doc("press", "기자간담회")));
      return h("article", { class: "mcard" },
        h("header", {}, h("b", {}, ymd(m.date)), h("span", { class: `dec ${m.decision}` }, `${m.decision} ${m.prev_rate != null && m.prev_rate !== m.rate ? fx(m.prev_rate) + "% → " : ""}${fx(m.rate)}%`),
          m.verify ? h("span", { class: "badge verify" }, "보도 인용 · 원문 대조 필요") : ""),
        dl);
    });
    $("#meetCards").replaceChildren(...cards);

    // 타임라인
    const fill = (selEl, vals, cur, all) => selEl.replaceChildren(h("option", { value: "" }, all), ...vals.map((v) => h("option", { value: v, selected: v === cur }, v)));
    fill($("#spkSel"), G.speakers || [], S.spk, "발언자 전체");
    fill($("#venSel"), G.venues || [], S.ven, "장소 전체");
    const tn = { hawk: "매파", dove: "비둘기", neutral: "중립" };
    const sp = (G.speeches || []).filter((s) => (!S.spk || s.speaker === S.spk) && (!S.ven || s.venue === S.ven));
    $("#timeline").replaceChildren(...sp.map((s) => h("li", { class: s.tone },
      h("div", { class: "when" }, `${ymd(s.date)} · ${s.venue} · ${s.speaker}`, h("span", { class: `tag ${s.tone}` }, tn[s.tone] || s.tone)),
      h("div", {}, "“" + s.quote + "”", s.note ? h("small", {}, s.note) : ""),
      h("div", { class: "note" }, s.link ? ext(s.link, "원문") : "원문 링크 미입력", s.verify ? " · 보도 인용, 원문 대조 필요" : ""))));
    if (!sp.length) $("#timeline").replaceChildren(h("li", {}, "해당 발언 없음"));

    renderTone();
  }

  function renderTone() {
    const el = $("#tone");
    const pts = D.guidance.meetings.filter((m) => m.tone).map((m) => ({ d: m.date, s: m.tone.score, h: m.tone.hawk, v: m.tone.dove })).reverse();
    if (!pts.length) { el.replaceChildren(h("div", { class: "empty" }, "통방문·간담회 문장이 입력된 회의가 없습니다.")); return; }
    const W = Math.max(320, el.clientWidth - 16), H = 170, m = { t: 12, r: 12, b: 24, l: 40 };
    const x = d3.scaleBand().domain(pts.map((p) => p.d)).range([m.l, W - m.r]).padding(0.35);
    const ext_ = Math.max(0.5, d3.max(pts, (p) => Math.abs(p.s)));
    const y = d3.scaleLinear().domain([-ext_, ext_]).range([H - m.b, m.t]).nice();
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "매파 비둘기 보조점수");
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4)).call((g) => g.select(".domain").remove());
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).tickFormat(ymd)).call((g) => g.select(".domain").remove());
    svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", "var(--ink-3)");
    const bw = Math.min(x.bandwidth(), 48);
    svg.selectAll(null).data(pts).join("rect").attr("x", (p) => x(p.d) + (x.bandwidth() - bw) / 2).attr("width", bw)
      .attr("y", (p) => Math.min(y(p.s), y(0))).attr("height", (p) => Math.max(1, Math.abs(y(p.s) - y(0)))).attr("rx", 3)
      .attr("fill", (p) => p.s >= 0 ? "var(--hike)" : "var(--cut)")
      .on("pointermove", (ev, p) => showTip(ev, [`${ymd(p.d)} 점수 ${p.s.toFixed(2)}`, `매파 단어 ${p.h} · 비둘기 단어 ${p.v}`])).on("pointerleave", hideTip);
    el.replaceChildren(h("div", { class: "legend" }, h("span", {}, h("i", { style: "background:var(--hike)" }), "매파(+)"), h("span", {}, h("i", { style: "background:var(--cut)" }), "비둘기(−)")),
      svg.node(), h("div", { class: "note" }, "통방문·간담회 문장을 config 사전으로 센 값(문장당 점수). 자동 산출 · 참고용 — 문맥(부정·조건)을 읽지 못합니다."));
  }

  // ------------------------------------------------------------ 탭 3 의사록
  function renderMinutes() {
    const M = D.minutes.meetings || [];
    const head = h("thead", {}, h("tr", {}, ...["회의일", "의사록", "공개(예정)일", "원문", "PDF", "결정문", "간담회"].map((t) => h("th", {}, t))));
    const body = M.map((m) => {
      const mi = m.docs.minutes, st = m.docs.statement, pr = m.docs.press;
      return h("tr", {}, h("td", {}, ymd(m.date), (m.new || []).includes("minutes") ? h("span", { class: "badge new" }, "새") : ""),
        h("td", {}, m.minutes_status), h("td", {}, mi ? ymd(mi.posted) : `${ymd(m.minutes_expected)} 예정`),
        h("td", {}, mi ? ext(mi.url, "원문") : "–"),
        h("td", {}, mi && mi.attachments && mi.attachments[0] ? ext(mi.attachments[0].url, "PDF") : "–"),
        h("td", {}, st ? ext(st.url, "결정문") : "–"), h("td", {}, pr ? ext(pr.url, "자료") : "–"));
    });
    $("#minTable").replaceChildren(head, h("tbody", {}, body));
    const withV = M.find((m) => m.views);
    if (!withV) {
      $("#views").replaceChildren(h("p", { class: "note" }, D.minutes.skeleton
        ? "한은 홈페이지 수집 전입니다. 공개 예정일은 '회의일 + 12일 이후 첫 화요일' 규칙 계산값이며 한은 공지가 우선합니다."
        : "키워드를 추출한 의사록이 없습니다."));
      return;
    }
    const v = withV.views;
    const t = v.totals;
    $("#views").replaceChildren(
      h("p", {}, `${ymd(withV.date)} 회의 의사록 · 위원 발언 단락 ${v.paragraphs.length}개 · 키워드 빈도 인상 ${t["인상"] || 0} / 동결 ${t["동결"] || 0} / 인하 ${t["인하"] || 0} · `, ext(v.source, "원문 PDF")),
      h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
        h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "기울기(자동)"), h("th", {}, "인상·동결·인하"), h("th", { class: "l" }, "발췌"))),
        h("tbody", {}, v.paragraphs.map((p, i) => h("tr", {}, h("td", {}, i + 1), h("td", {}, p.lean), h("td", {}, `${p.counts["인상"]}·${p.counts["동결"]}·${p.counts["인하"]}`), h("td", { class: "l" }, p.excerpt)))))),
      h("p", { class: "note" }, "자동 분류는 참고용입니다. 의사록은 위원을 익명으로 적습니다. 반드시 원문을 확인하세요."));
  }

  // ------------------------------------------------------------ 탭 4 기사·보고서
  function hl(text, kws) {
    const frag = document.createDocumentFragment();
    if (!kws.length) { frag.append(text); return frag; }
    const re = new RegExp("(" + kws.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "g");
    text.split(re).forEach((part, i) => frag.append(i % 2 ? h("mark", {}, part) : part));
    return frag;
  }

  function renderNews() {
    const N = D.news, kw = N.main_keyword || "신현송";
    const items = N.items.filter((x) => x.keywords.includes(kw) && (!S.chip || x.keywords.includes(S.chip)));
    const pool = S.chip ? N.items.filter((x) => x.keywords.includes(S.chip)) : items;
    const today = todayKST();
    const wk = new Date(Date.parse(today) - 6 * 864e5).toISOString().slice(0, 10);
    const all = N.items.filter((x) => x.keywords.includes(kw));
    $("#newsCount").textContent = `오늘 ${all.filter((x) => x.published.slice(0, 10) === today).length}건 · 최근 7일 ${all.filter((x) => x.published.slice(0, 10) >= wk).length}건`;
    $("#chips").replaceChildren(h("button", { class: "chip", "aria-pressed": !S.chip, onclick: () => setS({ chip: "" }) }, `${kw} 전체`),
      ...(N.chips || []).map((c) => h("button", { class: "chip", "aria-pressed": S.chip === c, onclick: () => setS({ chip: S.chip === c ? "" : c }) },
        c, h("small", {}, String(N.items.filter((x) => x.keywords.includes(c)).length)))));
    const list = (S.chip ? pool : items).slice(0, 80);
    const st = D.status.news;
    $("#newsList").replaceChildren(...(list.length ? list.map((x) => h("li", {},
      h("div", { class: "m" }, `${x.published.slice(5, 16).replace("T", " ")} · ${x.feed}`),
      h("div", { class: "t" }, ext(x.link, hl(x.title, [kw, ...(N.chips || [])]))),
      x.summary ? h("div", { class: "sum" }, hl(x.summary, [kw])) : "")) :
      [h("li", { class: "empty" }, st && st.last_success ? `해당 기사 없음 (마지막 수집 ${st.last_success.replace("T", " ")})` : "RSS 수집 전입니다 (news.yml 첫 실행 뒤 표시).")]));

    // 보고서 표
    const meets = (D.meta.upcoming || []).slice(0, 2);
    const cols = [
      { k: "institution", t: "기관" }, { k: "author", t: "작성자" }, { k: "published", t: "발표일" },
      ...meets.map((m) => ({ k: "call:" + m, t: md(m) + " 전망" })),
      { k: "dissent", t: "소수의견" }, { k: "terminal", t: "최종금리" }, { k: "path", t: "경로", l: 1 }, { k: "rationale", t: "근거", l: 1 }, { k: "source", t: "출처", l: 1 },
    ];
    const val = (r, k) => k.startsWith("call:") ? ((r.calls || {})[k.slice(5)] || {}).call || "" : r[k] ?? "";
    let reps = D.reports.reports.filter((r) => !S.q || JSON.stringify(r).includes(S.q));
    const [sk, sd] = (S.sort || "published:desc").split(":");
    reps = reps.slice().sort((a, b) => { const x = val(a, sk), y = val(b, sk); return (x > y ? 1 : x < y ? -1 : 0) * (sd === "asc" ? 1 : -1); });
    const thead = h("thead", {}, h("tr", {}, ...cols.map((c) => h("th", { class: c.l ? "l" : null, "aria-sort": c.k === sk ? (sd === "asc" ? "ascending" : "descending") : null,
      onclick: () => setS({ sort: `${c.k}:${c.k === sk && sd === "desc" ? "asc" : "desc"}` }) }, c.t))));
    const tb = reps.map((r) => h("tr", {}, ...cols.map((c) => {
      if (c.k.startsWith("call:")) { const x = (r.calls || {})[c.k.slice(5)]; return h("td", { class: x ? "call-" + x.call : null, title: x && x.note || null }, x ? x.call + (x.size ? ` ${Math.round(x.size * 100)}bp` : "") + (x.note ? "*" : "") : "–"); }
      if (c.k === "terminal") return h("td", {}, r.terminal != null ? fx(r.terminal) + "%" : "–");
      if (c.k === "source") return h("td", { class: "l" }, r.link ? ext(r.link, r.source) : r.source || "–", r.verify ? h("span", { class: "badge verify" }, "원문 대조 필요") : "");
      if (c.k === "published") return h("td", {}, ymd(r.published), (D.reports.new || []).includes(r.institution) ? h("span", { class: "badge new" }, "새") : "");
      return h("td", { class: c.l ? "l" : null }, r[c.k] || "–");
    })));
    $("#repTable").replaceChildren(thead, h("tbody", {}, tb));

    renderConsensus();
    const K = (D.reports.kofia || []).filter((k) => k.hold != null);
    $("#kofia").replaceChildren(K.length ? h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ...["월", "조사기간", "응답자", "동결", "인상", "인하"].map((t) => h("th", {}, t)))),
      h("tbody", {}, K.map((k) => h("tr", {}, h("td", {}, k.month), h("td", {}, k.period || "–"), h("td", {}, k.respondents ?? "–"), h("td", {}, k.hold + "%"), h("td", {}, k.hike + "%"), h("td", {}, k.cut + "%"))))))
      : h("p", { class: "note" }, (D.reports.kofia || []).map((k) => `${k.month}: ${k.status || "미입력"}`).join(" · ") + " — 발표 시 data/reports.yaml에 입력"));
  }

  async function renderConsensus() {
    const snap = await snapshot(S.d);
    const scen = snap && snap.scenarios[S.s];
    const cons = D.reports.consensus;
    const cards = (D.meta.upcoming || []).slice(0, 2).map((m) => {
      const c = cons.by_meeting[m] || { counts: {}, n: 0 };
      const mk = scen && scen.meetings.find((x) => x.date === m && x.in_range);
      const order = [["인상", "var(--hike)"], ["동결", "var(--hold)"], ["인하", "var(--cut)"]];
      const other = c.n - order.reduce((s, [k]) => s + (c.counts[k] || 0), 0);
      const bar = h("div", { class: "cbar", role: "img", "aria-label": "전망 기관 수" },
        ...order.filter(([k]) => c.counts[k]).map(([k, col]) => h("span", { style: `flex:${c.counts[k]};background:${col}`, title: `${k} ${c.counts[k]}곳` }, `${k} ${c.counts[k]}`)),
        other > 0 ? h("span", { style: `flex:${other};background:var(--ink-3)` }, `기타 ${other}`) : "");
      const mbar = mk ? h("div", { class: "cbar", role: "img", "aria-label": "시장 확률" },
        mk.p_hike > 0.005 ? h("span", { style: `flex:${mk.p_hike};background:var(--hike)` }, mk.p_hike > 0.12 ? `인상 ${pct(mk.p_hike, 0)}` : "") : "",
        mk.p_hold > 0.005 ? h("span", { style: `flex:${mk.p_hold};background:var(--hold)` }, mk.p_hold > 0.12 ? `동결 ${pct(mk.p_hold, 0)}` : "") : "",
        mk.p_cut > 0.005 ? h("span", { style: `flex:${mk.p_cut};background:var(--cut)` }, "인하") : "") : h("div", { class: "note" }, "시장 확률 없음");
      return h("div", { class: "tile" }, h("div", { class: "k" }, `${ymd(m)} 회의`),
        h("div", { class: "s" }, `전문가 ${c.n}곳 — 인상 ${pct(c.hike_share, 0)}`), bar,
        h("div", { class: "s" }, `시장 — 인상 ${mk ? pct(mk.p_hike) : "–"}`), mbar);
    });
    const term = Object.entries(cons.terminal || {});
    cards.push(h("div", { class: "tile" }, h("div", { class: "k" }, "최종금리 전망 분포"),
      term.length ? h("div", {}, ...term.map(([k, n]) => h("div", { class: "s" }, `${k}% — ${n}곳`))) : h("div", { class: "s" }, "입력 없음"),
      h("div", { class: "note" }, `기관 ${cons.institutions}곳(기관별 최신 보고서 기준)`)));
    $("#consensus").replaceChildren(...cards);
  }

  // ------------------------------------------------------------ 탭 정성 판단(AI)
  function renderQual() {
    const el = $("#qualBody");
    const Q = D.qual;
    if (!Q) {
      el.replaceChildren(h("div", { class: "empty" }, "AI 정성 판단 데이터가 없습니다. GitHub Secrets에 NAVER_CLIENT_ID·NAVER_CLIENT_SECRET·ANTHROPIC_API_KEY를 넣으면 news.yml 실행 때 생성됩니다."));
      return;
    }
    const S_ = Q.synthesis, P = Q.pressure || {};
    const dirCls = { "인상 압력": "hawk", "인하 압력": "dove", "중립": "neutral" };
    const byId = Object.fromEntries((Q.articles || []).map((a) => [a.id, a]));
    const kids = [h("p", { class: "note warnline" }, `AI 자동 판단 · 참고용 — ${Q.model} · 기사 제목·검색 요약만 입력 · 근거 기사 원문을 반드시 확인`)];
    if (S_) {
      const scale = h("div", { class: "lean", role: "img", "aria-label": `정성 판단 ${LEAN[S_.lean]}` },
        ...[-2, -1, 0, 1, 2].map((v) => h("span", { class: "lean-cell" + (v === S_.lean ? " on" : "") + (v > 0 ? " up" : v < 0 ? " down" : "") }, LEAN[v])));
      kids.push(h("div", { class: "qcard" },
        h("div", { class: "k" }, `종합 판단 · ${S_.confidence ? "확신도 " + S_.confidence : ""} · ${(Q.synthesis_updated || "").replace("T", " ")}`),
        scale, h("h3", { class: "qhead" }, S_.headline), h("p", {}, S_.summary),
        S_.market_gap ? h("p", { class: "gap" }, "시장과 차이: " + S_.market_gap) : "",
        h("h4", {}, "주요 요인"),
        h("ul", { class: "drivers" }, ...(S_.drivers || []).map((d) => h("li", {},
          h("span", { class: `tag ${dirCls[d.direction]}` }, d.direction), " ", h("b", {}, d.factor), " — ", d.point, " ",
          ...d.article_ids.filter((i) => byId[i]).map((i, k) => h("span", {}, k ? ", " : "[", ext(byId[i].link, byId[i].press || "기사"), k === d.article_ids.filter((j) => byId[j]).length - 1 ? "]" : ""))))),
        (S_.counterpoints || []).length ? [h("h4", {}, "반대 근거"), h("ul", {}, ...S_.counterpoints.map((c) => h("li", {}, c)))] : "",
        (S_.watch || []).length ? [h("h4", {}, "관전 포인트"), h("ul", {}, ...S_.watch.map((c) => h("li", {}, c)))] : ""));
    } else kids.push(h("p", { class: "note" }, "종합 판단 없음 (하루 1회 daily.yml에서 생성)"));

    // 압력지수 + 요인
    kids.push(h("h3", {}, `뉴스 태그 압력지수 `, h("small", {}, `최근 ${Q.window_hours}시간 관련 기사 ${P.n || 0}건 · +1 인상 압력 ~ −1 인하 압력 · 태그 단순 합산`)));
    kids.push(h("div", { class: "qgrid" }, h("div", { class: "tile" }, h("div", { class: "k" }, "현재"), h("div", { class: "v" }, P.index == null ? "–" : (P.index >= 0 ? "+" : "") + P.index.toFixed(2)),
      h("div", { class: "s" }, `태깅 ${Q.counts.tagged}/${Q.counts.total}건 · 관련 ${Q.counts.relevant}건`)), h("div", { id: "qualTrend", class: "chart" })));
    kids.push(h("h3", {}, "요인별 기사 수 ", h("small", {}, "주황=인상 압력, 파랑=인하 압력, 기사 수 기준")), factorBars(P.factors || []));

    // 기사 목록
    const facs = [...new Set((Q.articles || []).map((a) => a.factor))];
    const sel = h("select", { "aria-label": "요인", onchange: (e) => setS({ qf: e.target.value }) }, h("option", { value: "" }, "요인 전체"), ...facs.map((f) => h("option", { value: f, selected: S.qf === f }, f)));
    const dsel = h("select", { "aria-label": "방향", onchange: (e) => setS({ qd: e.target.value }) }, h("option", { value: "" }, "방향 전체"), ...Object.keys(dirCls).map((f) => h("option", { value: f, selected: S.qd === f }, f)));
    kids.push(h("div", { class: "row-head" }, h("h3", {}, "태깅된 기사 ", h("small", {}, "최근 7일 · 관련 기사만")), h("div", { class: "filters" }, sel, dsel)));
    const arts = (Q.articles || []).filter((a) => (!S.qf || a.factor === S.qf) && (!S.qd || a.direction === S.qd)).slice(0, 100);
    kids.push(h("ul", { class: "news" }, ...(arts.length ? arts.map((a) => h("li", {},
      h("div", { class: "m" }, `${a.published.slice(5, 16).replace("T", " ")} · ${a.press}${a.dup_press && a.dup_press.length ? ` 외 ${a.dup_press.length}곳` : ""} · ${a.origin === "yna" ? "연합 RSS" : "네이버"}`),
      h("div", { class: "t" }, ext(a.link, a.title)),
      h("div", { class: "sum" }, h("span", { class: `tag ${dirCls[a.direction]}` }, `${a.direction} ${"▮".repeat(a.strength)}`), " ", h("b", {}, a.factor), " · ", a.reason))) : [h("li", { class: "empty" }, "해당 기사 없음")])));
    if ((Q.errors || []).length) kids.push(h("p", { class: "note" }, "마지막 실행 오류: " + Q.errors.join("; ")));
    el.replaceChildren(...kids.flat());
    qualTrend();
  }

  function factorBars(fs) {
    if (!fs.length) return h("p", { class: "note" }, "관련 기사 없음");
    const mx = Math.max(1, ...fs.map((f) => Math.max(f.up, f.down)));
    return h("div", { class: "fbars" }, ...fs.map((f) => h("div", { class: "frow" },
      h("div", { class: "fside l" }, h("span", { class: "fv" }, f.down || ""), h("span", { class: "fbar down", style: `width:${f.down / mx * 100}%` })),
      h("div", { class: "fname" }, f.factor),
      h("div", { class: "fside" }, h("span", { class: "fbar up", style: `width:${f.up / mx * 100}%` }), h("span", { class: "fv" }, f.up || "")))));
  }

  function qualTrend() {
    const el = $("#qualTrend");
    if (!el) return;
    const pts = (D.qual.history || []).map((r) => ({ d: new Date(r.date), v: r.index, n: r.n }));
    if (pts.length < 2) { el.replaceChildren(h("div", { class: "empty" }, `이력 ${pts.length}일 — 매일 누적`)); return; }
    const W = Math.max(280, el.clientWidth - 16), H = 150, m = { t: 10, r: 10, b: 22, l: 34 };
    const x = d3.scaleTime().domain(d3.extent(pts, (p) => p.d)).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([-1, 1]).range([H - m.b, m.t]);
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "압력지수 추이");
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(5).tickFormat(d3.timeFormat("%m/%d")));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4)).call((g) => g.select(".domain").remove());
    svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", "var(--ink-3)");
    svg.append("path").datum(pts).attr("fill", "none").attr("stroke", "var(--ink-2)").attr("stroke-width", 2).attr("d", d3.line().x((p) => x(p.d)).y((p) => y(p.v)));
    svg.selectAll(null).data(pts).join("circle").attr("cx", (p) => x(p.d)).attr("cy", (p) => y(p.v)).attr("r", 4)
      .attr("fill", (p) => p.v >= 0 ? "var(--hike)" : "var(--cut)").attr("stroke", "var(--surface)").attr("stroke-width", 2)
      .on("pointermove", (ev, p) => showTip(ev, [`${d3.timeFormat("%Y.%m.%d")(p.d)} ${p.v >= 0 ? "+" : ""}${p.v.toFixed(2)}`, `관련 기사 ${p.n}건`])).on("pointerleave", hideTip);
    el.replaceChildren(svg.node());
  }

  // ------------------------------------------------------------ 탭 5·6
  function renderMemo() {
    const m = D.memo;
    $("#memo").textContent = m ? m.text : "메모 없음";
    $("#memoNote").textContent = m ? `자동 초안 ${m.generated.replace("T", " ")} 생성 — 팩트·맥락 재확인 필요.` + (m.lint && m.lint.length ? ` 문체 점검: ${m.lint.join(", ")}` : " 문체 점검 통과.") : "";
  }

  function renderMethod() {
    const B = D.backtest || {};
    const el = $("#method");
    el.className = "method";
    const sec = (t, ...kids) => [h("h2", {}, t), ...kids];
    const bt = B.n ? [h("p", {}, `${B.rule} · 표본 ${B.n}회 · 적중률 ${pct(B.hit_rate)} · Brier ${B.brier}`),
      h("div", { class: "tbl-wrap" }, h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ...["회의", "관측일", "인상", "동결", "인하", "예측", "실제", "적중", "Brier"].map((t) => h("th", {}, t)))),
        h("tbody", {}, B.rows.map((r) => h("tr", {}, h("td", {}, ymd(r.meeting)), h("td", {}, ymd(r.obs_date)), h("td", {}, pct(r.p_hike)), h("td", {}, pct(r.p_hold)), h("td", {}, pct(r.p_cut)),
          h("td", {}, r.pred), h("td", {}, r.actual), h("td", {}, r.hit ? "○" : "×"), h("td", {}, r.brier))))))]
      : [h("p", { class: "note" }, B.note || "백테스트 결과 없음")];
    el.replaceChildren(
      ...sec("계산 방식",
        h("p", {}, "시장금리 y에서 정상 스프레드 s를 빼면 결제일(기준일 다음 날)부터 만기까지의 평균 기대 기준금리가 된다고 본다. ",
          h("code", {}, "T·(y − s) = Σ E_k × 구간 k의 일수"), ". 금통위 결정은 회의 당일부터 적용한다."),
        h("ul", {},
          h("li", {}, "짧은 만기부터 부트스트래핑한다. 만기 구간에 새 회의가 하나면 그대로 풀고, 둘 이상이면 '최소 인상 경로'로 나눈다(늦은 회의부터 0.25%p 격자 상한까지 채움)."),
          h("li", {}, "회의별 Δ_k = E_k − E_(k−1). 0~25bp면 인상 확률 = Δ/25bp. 25bp 이상이면 25bp 확정에 초과분을 50bp 확률로 둔다. 음수는 인하로 대칭."),
          h("li", {}, "회의 뒤 목표금리 분포는 트리 경로를 금리 수준별로 합산한 값으로, 기대금리를 맞추는 인접 두 격자점 분포(FedWatch 수준 방식)다. 회의 간 확률을 독립으로 곱하면 분포가 더 넓어진다."),
          h("li", {}, "정상 스프레드는 장기 동결 국면(config.model.hold_windows) y − 기준금리의 중앙값. 이력이 부족하면 config 기본 가정값. ±5bp 결과를 함께 저장한다."),
          h("li", {}, "KOFR OIS가 있으면 OIS를, 없으면 CD 91일을 쓴다. 만기가 확정 일정 밖이면 계산에서 뺀다."))),
      ...sec("한계",
        h("ul", {},
          h("li", {}, "CD 금리에는 은행 자금사정과 신용 프리미엄이 섞인다. OIS 데이터가 있을 때 가장 정확하다."),
          h("li", {}, "결과는 정상 스프레드 가정에 매우 민감하다. 10월 회의는 ±5bp에 0~60%를 오간다."),
          h("li", {}, "보도 인용 초기값(전망·발언·점도표·통방문 문구)은 원문 대조가 필요하다."),
          h("li", {}, "매파·비둘기 점수와 의사록 키워드 분류는 사전 기반 자동 산출로 참고용이다."),
          h("li", {}, "AI 정성 판단은 기사 제목·검색 요약만 보고 내린 자동 판단이다. 오분류·과대해석이 있을 수 있으니 근거 기사 원문을 확인한다. 기사 텍스트는 분류 대상 데이터로만 모델에 넘기고, 모델이 인용한 기사 id 중 실제 없는 것은 버린다."))),
      ...sec("AI 정성 판단 방식",
        h("ul", {},
          h("li", {}, "네이버 뉴스 검색 API(config.naver.queries)와 연합뉴스 RSS에서 모은 기사를 Claude가 하나씩 태깅: 관련성, 요인, 방향(인상 압력/중립/인하 압력), 강도 1~3, 근거 한 줄."),
          h("li", {}, "압력지수 = Σ(방향×강도×중복보도 가중) ÷ Σ(강도×가중). 최근 72시간, 관련 기사만. 태그를 단순 합산해 재현 가능."),
          h("li", {}, "종합 판단은 하루 1회: 최근 기사 태그 + 시장 확률·점도표·한은 발언·지표를 함께 넣고, 다음 금통위 기준 방향(−2~+2)과 근거·반대 근거·관전 포인트를 받는다."))),
      ...sec("백테스트 (2021~2026, 회의 3영업일 전)", ...bt),
      ...sec("데이터 출처", h("ul", {}, ...(D.meta.sources || []).map((s) => h("li", {}, s.url ? ext(s.url, s.name) : s.name, ` — ${s.what}`)))),
      ...sec("수집 상태", h("ul", {}, ...Object.entries(D.status || {}).map(([k, v]) => h("li", {}, `${k}: ${v.ok ? "정상" : "실패"} · 마지막 시도 ${v.last_attempt || "–"} · 마지막 성공 ${v.last_success || "없음"} · ${v.message || ""}`)),
        Object.keys(D.status || {}).length ? "" : h("li", {}, "수집 기록 없음"))),
    );
  }

  // ------------------------------------------------------------ 공통 렌더
  function renderTabs() {
    document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === S.tab));
    for (const t of TABS) $("#tab-" + t).hidden = t !== S.tab;
  }

  async function renderAll() {
    renderTabs();
    const snap = await snapshot(S.d);
    renderHeader(snap);
    renderStrip(snap);
    await renderMarket(snap);
    renderGuidance();
    renderMinutes();
    renderNews();
    renderQual();
    renderMemo();
    renderMethod();
    writeHash();
  }

  function setS(patch) { Object.assign(S, patch); renderAll(); }

  // ------------------------------------------------------------ 이벤트
  function bind() {
    $("#tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setS({ tab: b.dataset.tab }); });
    $("#tabs").addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      const i = TABS.indexOf(S.tab) + (e.key === "ArrowRight" ? 1 : -1);
      setS({ tab: TABS[(i + TABS.length) % TABS.length] });
      $(`#tabs button[data-tab="${S.tab}"]`).focus();
    });
    $("#spreadToggle").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setS({ s: b.dataset.s }); });
    $("#snapDate").addEventListener("change", (e) => setS({ d: e.target.value }));
    $("#dotSel").addEventListener("change", (e) => setS({ dot: e.target.value }));
    $("#spkSel").addEventListener("change", (e) => setS({ spk: e.target.value }));
    $("#venSel").addEventListener("change", (e) => setS({ ven: e.target.value }));
    let tm; $("#repSearch").addEventListener("input", (e) => { clearTimeout(tm); tm = setTimeout(() => setS({ q: e.target.value.trim() }), 200); });
    $("#copyLink").addEventListener("click", () => copy(location.href, $("#copyLink"), "링크 복사"));
    $("#copyMemo").addEventListener("click", () => copy($("#memo").textContent, $("#copyMemo"), "복사"));
    $("#themeBtn").addEventListener("click", () => {
      const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const nxt = cur === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = nxt; store("bokwatch.theme", nxt);
    });
    addEventListener("hashchange", () => { readHash(); renderAll(); });
    let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { renderTrend(); renderTone(); qualTrend(); }, 150); });
    addEventListener("beforeprint", () => { $("#tab-market").hidden = false; $("#tab-guidance").hidden = false; renderTrend(); });
    addEventListener("afterprint", renderTabs);
    addEventListener("pagehide", () => store("bokwatch.lastVisit", new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16)));
  }

  async function copy(text, btn, label) {
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch (e) {
      const ta = h("textarea", {}, text); document.body.append(ta); ta.select();
      try { ok = document.execCommand("copy"); } catch (e2) { ok = false; } ta.remove();
    }
    btn.textContent = ok ? "복사됨" : "복사 실패"; setTimeout(() => { btn.textContent = label; }, 1500);
  }

  // ------------------------------------------------------------ 시작
  (async function init() {
    const th = store("bokwatch.theme"); if (th) document.documentElement.dataset.theme = th;
    readHash();
    await load();
    const snaps = D.meta.snapshots || [];
    if (!S.d || !snaps.includes(S.d)) S.d = D.meta.latest || snaps[snaps.length - 1] || null;
    $("#snapDate").replaceChildren(...(snaps.length ? snaps.slice().reverse().map((d) => h("option", { value: d, selected: d === S.d }, ymd(d))) : [h("option", {}, "스냅샷 없음")]));
    if (!S.dot && D.guidance.dotplots && D.guidance.dotplots[0]) S.dot = D.guidance.dotplots[0].date;
    bind();
    await renderAll();
  })();
})();
