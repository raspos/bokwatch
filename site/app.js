/* BOK워치 — 단일 페이지. 외부 요청은 같은 출처 data/*.json 뿐. */
(function () {
  "use strict";

  // ------------------------------------------------------------ 유틸
  const $ = (s, el = document) => el.querySelector(s);
  const D = {};                 // 로드된 데이터
  const S = { tab: "market", d: null, s: "0", chip: "", spk: "", ven: "", dot: "", q: "", sort: "", qf: "", qd: "" };
  const TABS = ["market", "guidance", "minutes", "news", "qual", "method"];

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

  // 갱신 상태: 지난 시간과 색(26시간 안 초록, 50시간 안 노랑, 그 뒤 빨강)
  const ageH = (iso) => iso ? (Date.now() - new Date(iso.length <= 10 ? iso + "T18:00+09:00" : iso).getTime()) / 3600e3 : null;
  const freshCls = (iso, failed) => failed ? "bad" : iso == null ? "" : ageH(iso) <= 26 ? "ok" : ageH(iso) <= 50 ? "late" : "bad";
  const rel = (iso) => {
    const a = ageH(iso);
    if (a == null) return "";
    if (a < 1) return `${Math.max(1, Math.round(a * 60))}분 전`;
    if (a < 48) return `${Math.round(a)}시간 전`;
    return `${Math.round(a / 24)}일 전`;
  };
  const stamp = (iso) => iso ? iso.slice(5, 16).replace("T", " ").replace("-", "/") : "–";
  const asofLine = (text, iso, failed) => h("div", { class: "asof" }, h("i", { class: `fdot ${freshCls(iso, failed)}` }), text);
  const busy = (on) => { const b = $("#busy"); if (b) b.classList.toggle("on", on); };
  function flash(el) { if (!el) return; el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }

  const more = (label, ...kids) => h("details", { class: "more" }, h("summary", {}, label), ...kids.filter(Boolean));

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
    const [meta, status, guidance, reports, minutes, news, backtest, hist, events, qual, plog, decision, cdshort, kois] = await Promise.all([
      getJSON("data/meta.json"), getJSON("data/status.json"), getJSON("data/guidance.json"),
      getJSON("data/reports.json"), getJSON("data/minutes.json"), getJSON("data/news.json"),
      getJSON("data/backtest.json"), getText("data/history.csv"),
      getJSON("data/events.json"), getJSON("data/qual.json"), getJSON("data/prob_log.json"), getJSON("data/decision.json"),
      getJSON("data/cd_short.json"), getJSON("data/kofr_ois.json"),
    ]);
    Object.assign(D, { meta: meta || {}, status: status || {}, guidance: guidance || { meetings: [], dotplots: [], speeches: [] },
      reports: reports || { reports: [], consensus: { by_meeting: {} } }, minutes: minutes || { meetings: [] },
      news: news || { items: [], chips: [] }, backtest, hist: hist ? parseCSV(hist) : [],
      events: events || { upcoming: [], recent: [], all: [], indicators: {} }, qual, plog: plog || [], decision, cdshort, kois });
    D.snaps = {};
  }
  async function snapshot(date) {
    if (!date) return null;
    if (!(date in D.snaps)) D.snaps[date] = await getJSON(`data/snapshots/${date}.json`);
    return D.snaps[date];
  }
  const prevDate = (date) => { const ix = D.meta.snapshots || []; const i = ix.indexOf(date); return i > 0 ? ix[i - 1] : null; };

  // ------------------------------------------------------------ 헤더·경고
  const SRC_NAMES = { ecos: "ECOS 시장금리", cdcurve: "금투협 CD 단기물", krx: "KRX KOFR 선물", bok: "한은 홈페이지", news: "연합뉴스 RSS",
    naver: "네이버 뉴스", events: "경제지표 일정", ai: "AI 정성 판단", decision: "결정 예측 모형" };
  function freshPill(built) {
    const st = D.status || {};
    const failed = Object.values(st).some((v) => v && v.ok === false);
    const lines = Object.entries(SRC_NAMES).filter(([k]) => st[k]).map(([k, n]) =>
      `${st[k].ok === false ? "✕" : "✓"} ${n}: ${st[k].last_success ? stamp(st[k].last_success) : "성공 기록 없음"}${st[k].ok === false ? " (최근 시도 실패)" : ""}`);
    return h("span", { class: "fresh", title: `매일 오전 10시 자동 갱신\n${lines.join("\n")}`, tabindex: 0 },
      h("i", { class: `fdot ${freshCls(built, failed)}` }), "갱신 ", h("b", {}, stamp(built)), h("span", { class: "rel" }, rel(built)),
      failed ? h("span", { class: "badge warn" }, "일부 실패") : "");
  }

  function renderHeader(snap) {
    const m = D.meta;
    $("#banner").hidden = !m.banner;
    const today = todayKST();
    const next = (m.upcoming || [])[0];
    const kids = [
      h("span", {}, "데이터 기준 ", h("b", {}, ymd(snap ? snap.asof : m.latest))),
      freshPill(m.built),
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
    void fresh;
    // 경고 문구는 머리말에 띄우지 않는다(산출 중단 사유는 확률 게이지 자리, 상세는 투입 금리 아래 설명에 나온다)
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
  function renderStrip(snap, staleFrom) {
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
    const nTop = nxt && nxt.method === "kofr_ois" ? outcomes(nxt).reduce((a, b) => (b.p > a.p ? b : a)) : null;
    tiles.push(h("div", { class: "tile" }, h("div", { class: "tgt" }, nextDate ? `대상: ${dmon(nextDate)} 회의` : "대상: 다음 회의"),
      h("div", { class: "k" }, nTop ? `모형 추정(KOFR OIS)${staleFrom ? ` · ${ymd(staleFrom)} 기준` : ""}`
      : `모형 추정(CD) · ${nextDate ? mon(nextDate) + " 회의" : "다음 회의"} 인상 확률${staleFrom ? ` · ${ymd(staleFrom)} 기준` : ""}`),
      h("div", { class: "v" }, nTop ? `${nTop.name} ${pct(nTop.p)}` : nxt ? (nxt.range && nxt.range.direction === "hike" ? `최고 ${pct(nxt.range.max)}` : pct(nxt.p_hike)) : "–"),
      nTop ? h("div", { class: "s" }, outcomes(nxt).filter((o) => o.bp !== nTop.bp).map((o) => `${o.name} ${pct(o.p)}`).join(" · ")) : "",
      nxt && nxt.range ? h("div", { class: "s" }, `가능 범위 ${pct(nxt.range.min, 0)}~${pct(nxt.range.max, 0)}`) : "",
      h("div", { class: "s" }, ms[1] ? (ms[1].method === "kofr_ois"
        ? `${mon(ms[1].date)} ${(() => { const t = outcomes(ms[1]).reduce((a, b) => (b.p > a.p ? b : a)); return `${t.name} ${pct(t.p)}`; })()} · 인상 ${pct(ms[1].p_hike)}`
        : `${mon(ms[1].date)} ${pct(ms[1].p_hike)} · 기대금리 ${fx(ms[1].expected)}%`) : "")));
    // 한은 점도표
    tiles.push(h("div", { class: "tile" }, h("div", { class: "tgt" }, "대상: 6개월 뒤"),
      h("div", { class: "k" }, `한은 점도표 중간값(${dp ? md(dp.date) : "–"})`),
      h("div", { class: "v" }, dp ? fx(dp.median) + "%" : "–"),
      h("div", { class: "s" }, dp && r0 != null ? `현 ${fx(r0)}% 대비 위 ${dots(dp, r0).above} · 같음 ${dots(dp, r0).at} · 아래 ${dots(dp, r0).below}` : "")));
    // 전문가
    tiles.push(h("div", { class: "tile" }, h("div", { class: "tgt" }, `대상: ${nextDate ? mon(nextDate) : "다음"} 회의${ms[1] ? ` · ${mon(ms[1].date)} 회의` : ""}`),
      h("div", { class: "k" }, `전문가 전망`),
      h("div", { class: "v" }, c && c.n ? `${consTop(c).name} ${pct(consTop(c).n / c.n, 0)}` : "–"),
      h("div", { class: "s" }, c && c.n ? `${consTop(c).n}/${c.n}곳` + (Object.keys(c.counts).length > 1 ? " · " + Object.entries(c.counts).filter(([k]) => k !== consTop(c).name).map(([k, v]) => `${k} ${v}곳`).join(" · ") : "") : ""),
      h("div", { class: "s" }, secondCons(ms[1]))));
    // 엇갈림: 방향 신호가 다르면 강조
    // 점도표는 6개월 뒤 전망이라 '다음 회의' 신호와 비교하지 않는다(10월 동결·이후 인상은 일관된 경로)
    const sig = [nxt ? nxt.p_hike >= 0.5 : null, null, c && c.n ? c.hike_share >= 0.5 : null];
    const known = sig.filter((x) => x != null);
    const diverge = known.length >= 2 && known.some((x) => x !== known[0]);
    if (diverge) {
      sig.forEach((x, i) => { if (x != null && x !== majority(known)) tiles[i].classList.add("diverge"); });
      const lbl = ["모형 추정", "점도표", "전문가"].map((n, i) => sig[i] == null ? null : `${n} ${sig[i] ? "인상 쪽" : "동결 쪽"}`).filter(Boolean).join(" · ");
      tiles.push(h("div", { class: "strip-note" }, `엇갈림 — ${lbl} (둘 다 다음 회의 기준)`));
    }
    const Q = D.qual && D.qual.synthesis;
    const pr = D.qual && D.qual.pressure;
    tiles.splice(3, 0, h("div", { class: "tile ref" }, h("div", { class: "tgt" }, "대상: 다음 회의 · 최근 기사"), h("div", { class: "k" }, "AI 정성 판단(참고)"),
      h("div", { class: "v" }, Q ? LEAN[Q.lean] : "–"),
      h("div", { class: "s" }, Q ? Q.headline : "네이버 뉴스·OpenAI API 연결 후 표시",
        pr && pr.index != null ? ` · 압력지수 ${pr.index >= 0 ? "+" : ""}${pr.index.toFixed(2)}` : "")));
    // 카드마다 '무엇을, 언제 기준으로' 보여 주는지
    const st = D.status || {};
    const ko = snap && snap.components && snap.components.kofr_ois;
    const cdDate = ko && ko.curve && ko.curve.m1 ? ko.curve.m1.cd_date : snap && snap.asof;
    const marks = [
      [nxt && nxt.method === "kofr_ois" ? `CD ${md(cdDate)} 공시값 · 갱신 ${stamp(D.meta.built)}` : `시장금리 ${md(snap ? snap.asof : D.meta.latest)} · 갱신 ${stamp(D.meta.built)}`,
        D.meta.built, st.ecos && st.ecos.ok === false || st.cdcurve && st.cdcurve.ok === false],
      [dp ? `${md(dp.date)} 회의 점도표` + (D.guidance.next_dotplot ? ` · 다음 ${md(D.guidance.next_dotplot)}` : "") : "점도표 없음", null, false],
      [`보고서 ${D.reports.asof ? md(D.reports.asof) : "–"} 기준 · 기사 수집 ${stamp((st.naver || {}).last_success)}`, (st.naver || {}).last_success, st.naver && st.naver.ok === false],
      [null, null, false],
    ];
    if (D.qual) marks[3] = [`AI 판단 ${stamp(D.qual.updated)} · 최근 ${D.qual.window_hours || 72}시간 기사`, D.qual.updated, st.ai && st.ai.ok === false];
    tiles.filter((x) => x.classList.contains("tile")).forEach((el, i) => {
      const mk = marks[i];
      if (mk && mk[0]) el.append(asofLine(mk[0], mk[1], mk[2]));
    });
    const strip = $("#strip");
    const changed = strip.dataset.key && strip.dataset.key !== `${S.d}|${S.s}`;
    strip.dataset.key = `${S.d}|${S.s}`;
    strip.removeAttribute("aria-busy");
    strip.replaceChildren(...tiles);
    if (changed) tiles.forEach(flash);
  }
  const LEAN = { "-2": "강한 인하 압력", "-1": "인하 압력", "0": "중립", "1": "인상 압력", "2": "강한 인상 압력" };
  const majority = (arr) => arr.filter(Boolean).length * 2 >= arr.length;
  // 전망 기관이 가장 많이 고른 결정
  function consTop(c) {
    const [name, n] = Object.entries(c.counts || {}).sort((a, b) => b[1] - a[1])[0] || ["–", 0];
    return { name, n };
  }
  function secondCons(m2) {
    if (!m2) return "";
    const c = (D.reports.consensus.by_meeting || {})[m2.date];
    if (!c || !c.n) return "";
    const t = consTop(c);
    return `${mon(m2.date)} ${t.name} ${pct(t.n / c.n, 0)} (${t.n}/${c.n}곳)`;
  }
  function dots(dp, r0) {
    let above = 0, at = 0, below = 0;
    for (const [lv, n] of Object.entries(dp.dist)) { const v = +lv; if (v > r0 + 1e-9) above += n; else if (v < r0 - 1e-9) below += n; else at += n; }
    return { above, at, below };
  }

  // ------------------------------------------------------------ 탭 1 시장
  // p: 바늘 위치(가능 범위 최고값). lo가 있으면 [lo, p] 구간을 진하게, 그 아래는 옅게 칠한다.
  function gaugeSVG(p, lo = null, label = "인상 확률") {
    const W = 250, H = 132, cx = W / 2, cy = 116, R = 92, T = 16;
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", `인상 확률 ${pct(p)}`);
    const arc = d3.arc().innerRadius(R - T).outerRadius(R).cornerRadius(3);
    const a0 = -Math.PI / 2, a1 = Math.PI / 2, ap = a0 + (a1 - a0) * Math.max(0, Math.min(1, p || 0));
    svg.append("path").attr("transform", `translate(${cx},${cy})`).attr("d", arc({ startAngle: a0, endAngle: a1 })).attr("fill", "var(--surface-2)").attr("stroke", "var(--line)");
    const al = lo == null ? a0 : a0 + (a1 - a0) * Math.max(0, Math.min(1, lo));
    if (lo != null && lo > 0) svg.append("path").attr("transform", `translate(${cx},${cy})`).attr("d", arc({ startAngle: a0, endAngle: al })).attr("fill", "var(--hike)").attr("opacity", 0.35);
    if (p > 0) svg.append("path").attr("transform", `translate(${cx},${cy})`).attr("d", arc({ startAngle: al, endAngle: ap })).attr("fill", "var(--hike)");
    for (const t of [0, 25, 50, 75, 100]) {
      const a = a0 + (a1 - a0) * t / 100, s = Math.sin(a), c = -Math.cos(a);
      svg.append("line").attr("x1", cx + s * (R + 2)).attr("y1", cy + c * (R + 2)).attr("x2", cx + s * (R + 7)).attr("y2", cy + c * (R + 7)).attr("stroke", "var(--ink-3)");
      svg.append("text").attr("x", cx + s * (R + 15)).attr("y", cy + c * (R + 15) + 4).attr("text-anchor", "middle").attr("font-size", 9).attr("fill", "var(--ink-3)").text(t);
    }
    const s = Math.sin(ap), c = -Math.cos(ap);
    svg.append("line").attr("x1", cx).attr("y1", cy).attr("x2", cx + s * (R - 22)).attr("y2", cy + c * (R - 22)).attr("stroke", "var(--ink)").attr("stroke-width", 2.5).attr("stroke-linecap", "round");
    svg.append("circle").attr("cx", cx).attr("cy", cy).attr("r", 5).attr("fill", "var(--ink)");
    svg.append("text").attr("x", cx).attr("y", cy - 26).attr("text-anchor", "middle").attr("font-size", 26).attr("font-weight", 700).attr("fill", "var(--ink)").text(pct(p));
    svg.append("text").attr("x", cx).attr("y", cy - 10).attr("text-anchor", "middle").attr("font-size", 10).attr("fill", "var(--ink-3)").text(label);
    return svg.node();
  }

  // 회의별 결정 결과(이동폭별 확률) — 가장 높은 결정을 크게
  function outcomes(m) {
    const name = (bp) => bp === 0 ? "동결" : `${Math.abs(bp)}bp ${bp > 0 ? "인상" : "인하"}`;
    const cls = (bp) => bp === 0 ? "hold" : bp > 0 ? (bp > 25 ? "hike2" : "hike") : (bp < -25 ? "cut2" : "cut");
    const mv = m.moves && Object.keys(m.moves).length ? m.moves : { 0: m.p_hold, 25: m.p_hike, "-25": m.p_cut };
    return Object.entries(mv).map(([k, v]) => ({ bp: +k, p: +v || 0, name: name(+k), cls: cls(+k) }))
      .filter((o) => o.p > 0.0005).sort((a, b) => a.bp - b.bp);
  }
  const dmon = (s) => `${+s.slice(5, 7)}월 ${+s.slice(8, 10)}일`;

  // 반원 게이지: 왼쪽부터 인하 | 동결 | 인상 비율로 호를 나누고, 가운데에 가장 높은 결정을 크게
  function decisionGaugeSVG(os, top, rest) {
    const W = 250, H = 140, cx = W / 2, cy = 120, R = 98, T = 22;
    const color = { hold: "var(--hold)", hike: "var(--hike)", hike2: "var(--hike)", cut: "var(--cut)", cut2: "var(--cut)" };
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", os.map((o) => `${o.name} ${pct(o.p)}`).join(", "));
    const arc = d3.arc().innerRadius(R - T).outerRadius(R);
    const a0 = -Math.PI / 2, span = Math.PI;
    svg.append("path").attr("transform", `translate(${cx},${cy})`).attr("d", arc({ startAngle: a0, endAngle: a0 + span })).attr("fill", "var(--surface-2)");
    let a = a0;
    for (const o of os) {
      const b = a + span * o.p;
      svg.append("path").attr("transform", `translate(${cx},${cy})`).attr("d", arc({ startAngle: a, endAngle: b }))
        .attr("fill", color[o.cls]).attr("opacity", o.cls.endsWith("2") ? 0.65 : 1).attr("stroke", "var(--surface)").attr("stroke-width", 1.5)
        .append("title").text(`${o.name} ${pct(o.p)}`);
      if (o.p >= 0.08) {
        const mid = (a + b) / 2, rr = R + 10;
        svg.append("text").attr("x", cx + Math.sin(mid) * rr).attr("y", cy - Math.cos(mid) * rr + 3)
          .attr("text-anchor", Math.sin(mid) > 0.3 ? "start" : Math.sin(mid) < -0.3 ? "end" : "middle")
          .attr("font-size", 10).attr("fill", "var(--ink-3)").text(pct(o.p, 0));
      }
      a = b;
    }
    const tc = top.bp === 0 ? "var(--ink)" : top.bp > 0 ? "var(--hike)" : "var(--cut)";
    svg.append("text").attr("x", cx).attr("y", cy - 32).attr("text-anchor", "middle").attr("font-size", 15).attr("font-weight", 600).attr("fill", tc).text(top.name);
    svg.append("text").attr("x", cx).attr("y", cy - 4).attr("text-anchor", "middle").attr("font-size", 30).attr("font-weight", 700).attr("fill", tc).text(pct(top.p));
    return svg.node();
  }

  function decisionCard(m, pm, pd, snapForParts) {
    const os = outcomes(m);
    const top = os.reduce((a, b) => (b.p > a.p ? b : a), os[0] || { name: "동결", p: 1, cls: "hold" });
    const rest = os.filter((o) => o !== top).sort((a, b) => b.p - a.p);
    const ch = pm ? m.p_hike - pm.p_hike : null;
    const cls = ch == null ? "flat" : ch > 0.0005 ? "up" : ch < -0.0005 ? "down" : "flat";
    const cand = ["동결", ...os.filter((o) => o.bp !== 0).map((o) => o.name)].filter((x, i, a) => a.indexOf(x) === i);
    const tailNote = "";
    return h("div", { class: "gauge decision" },
      h("span", { class: `badge chg ${cls}`, title: pm ? `전일(${ymd(pd)}) 대비 인상 확률 변화` : "전일 데이터 없음" }, ch == null ? "전일 –" : "인상 전일 " + pp(ch)),
      h("h4", {}, `${dmon(m.date)} 금리 결정 전망`),
      decisionGaugeSVG(os, top, rest),
      h("div", { class: "dlegend" }, ...os.map((o) => h("span", {}, h("i", { class: o.cls }), `${o.name} ${pct(o.p)}`))),
      h("div", { class: "sub" }, `회의 뒤 기대 금리 ${fx(m.expected, 3)}%`),
      more("근거",
        h("div", { class: "sub" }, `자체 합성 KOFR OIS(${m.ois_source}) 모형 추정 · ${cand.join(" 또는 ")} 가정${tailNote}`),
        m.cd91 && m.cd91.range ? h("div", { class: "sub range" }, `참고 — CD 91일 가능 범위: 인상 ${pct(m.cd91.range.min)}~${pct(m.cd91.range.max)}`) : null,
        h("div", { class: "sub parts" }, partsLine(snapForParts, m.date))));
  }

  // 기본 추정치가 멈춘 날이면 마지막으로 산출된 날의 스냅샷을 쓴다
  async function defaultView(snap) {
    if (!snap || snap.default_ok !== false) return { view: snap, staleFrom: null };
    for (const dd of (D.meta.snapshots || []).filter((x) => x < snap.asof).sort().reverse().slice(0, 15)) {
      const s2 = await snapshot(dd);
      if (s2 && s2.default_ok !== false && s2.scenarios[S.s].meetings.some((m) => m.in_range)) return { view: s2, staleFrom: dd };
    }
    return { view: snap, staleFrom: null };
  }

  async function renderMarket(snap) {
    document.querySelectorAll("#spreadToggle button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.s === S.s));
    if (!snap) {
      $("#gauges").replaceChildren(h("div", { class: "empty" }, "시장금리 데이터가 없습니다. ECOS 수집(daily.yml) 또는 data/manual 수동 입력 후 표시됩니다."));
      ["#probTable", "#inputTable"].forEach((s) => $(s).replaceChildren());
      renderTrend(); return;
    }
    // 기본 추정치가 멈춘 날이면 마지막으로 산출된 날의 값으로 게이지를 그리고 그 날짜를 밝힌다
    const live = snap;
    const dv = await defaultView(snap);
    snap = dv.view;
    const staleFrom = dv.staleFrom;
    $("#staleNote").textContent = staleFrom
      ? `${ymd(live.asof)} 기본 추정치 산출 중단(CD 만기가 확정된 금통위 일정 밖). 아래 게이지·표는 마지막 산출일 ${ymd(staleFrom)} 기준이다. 2027년 금통위 일정이 공지되면 다시 매일 갱신된다.`
      : "";
    const asm = (snap.assumed_meetings || []);
    if (!staleFrom && asm.length)
      $("#staleNote").textContent = `다음 해 금통위 일정 미공지: CD 만기 안의 ${asm.map(ymd).join("·")} 회의를 가정해 계산했다(최근 4년 1월 회의 중 가장 이른 날). KOFR OIS 3개월물 계산에서는 이 회의를 변화 없음으로 둔다. CD 91일 가능 범위의 최고값은 이 가정과 무관하다. 일정이 공지되면 실제 날짜로 바꾼다.`;
    $("#staleNote").hidden = !staleFrom && !asm.length;
    const scen = snap.scenarios[S.s];
    const pd = prevDate(snap.asof);
    const prev = pd ? await snapshot(pd) : null;
    const ms = scen.meetings.filter((m) => m.in_range);
    const cards = ms.slice(0, 3).map((m) => {
      const pm = prev && prev.scenarios[S.s].meetings.find((x) => x.date === m.date && x.in_range);
      // 전일 변화는 게이지 숫자와 같은 값(가능 범위 최고)끼리 비교한다
      const top = (x) => x.range && x.range.direction === "hike" ? x.range.max : x.p_hike;
      const ch = pm ? top(m) - top(pm) : null;
      const cls = ch == null ? "flat" : ch > 0.0005 ? "up" : ch < -0.0005 ? "down" : "flat";
      if (m.method === "kofr_ois") return decisionCard(m, pm, pd, staleFrom ? live : snap);
      return h("div", { class: "gauge" },
        h("span", { class: `badge chg ${cls}`, title: pm ? `전일(${ymd(pd)}) 대비` : "전일 데이터 없음" }, ch == null ? "전일 –" : "전일 " + pp(ch)),
        h("h4", {}, `${ymd(m.date)} 금통위`),
        m.range && m.range.direction === "hike" ? gaugeSVG(m.range.max, m.range.min, "인상 확률 최고(가능 범위)")
          : gaugeSVG(m.p_hike, null, m.method === "kofr_ois" ? "인상 확률(KOFR OIS)" : "인상 확률"),
        m.method === "kofr_ois" ? h("div", { class: "sub" }, `동결 ${pct(m.p_hold)} · 인상 ${pct(m.p_hike)}` + (m.p_cut > 0 ? ` · 인하 ${pct(m.p_cut)}` : "")
          + ` · 회의 뒤 기대 금리 ${fx(m.expected, 3)}% (${m.ois_source})`) : "",
        m.method === "kofr_ois" && m.cd91 && m.cd91.range ? h("div", { class: "sub range" }, `참고 — CD 91일 같은 금리로 가능한 범위: 인상 ${pct(m.cd91.range.min)}~${pct(m.cd91.range.max)}`) : "",
        m.method === "kofr_ois" ? "" : h("div", { class: "sub" }, `점추정(최소 인상 경로): 동결 ${pct(m.p_hold)} · 인상 ${pct(m.p_hike)}` + (m.p_cut > 0 ? ` · 인하 ${pct(m.p_cut)}` : "")
          + ` · 회의 뒤 기대 금리 ${fx(m.expected, 3)}%`),
        more("근거",
          m.range ? h("div", { class: "sub range" }, `같은 금리로 가능한 범위: ${m.range.direction === "cut" ? "인하" : "인상"} ${pct(m.range.min)}~${pct(m.range.max)}.`
            + ` 각 회의를 따로 본 최고값이라 여러 회의의 최고값이 동시에 성립하지는 않는다(가까운 회의부터 배정 ${pct(m.range.early)}, 늦은 회의부터 배정 ${pct(m.range.late)})`) : null,
          h("div", { class: "sub parts" }, partsLine(staleFrom ? live : snap, m.date))),
        h("div", { class: "method-tag" }, m.source || ({ bootstrap: "부트스트래핑", min_hike: "최소 인상 경로", lsq: "비음수 최소제곱" }[m.method] || m.method)));
    });
    const out = scen.meetings.filter((m) => !m.in_range).map((m) => md(m.date));
    // 정상 스프레드 버튼 설명: 그날 실제 가정값과 회의별 확률 범위
    const u0 = snap.inputs.find((i) => i.used);
    if (u0) {
      const bp = Math.round(u0.spread * 100);
      const cdc = (snap.components || {}).cd || {};
      const rng = ms.map((m) => {
        const ps = ["-5", "0", "5"].map((k) => ((cdc[k] || {}).meetings || []).find((x) => x.date === m.date && x.range)).filter(Boolean).map((x) => x.range.max);
        return ps.length ? `${md(m.date)} ${pct(Math.min(...ps))}~${pct(Math.max(...ps))}` : null;
      }).filter(Boolean);
      $("#spreadNote").textContent = `CD 91일 모형: ${u0.label} 금리에서 역산한 값이다. 검증된 시장 내재확률이 아니다. `
        + `정상 스프레드는 금리 변화 기대가 없을 때도 ${u0.label} 금리가 기준금리보다 높게 붙는 폭(은행 자금사정·신용 웃돈)이다. `
        + `기본 ${bp}bp(${u0.spread_how}), −5bp는 ${bp - 5}bp, +5bp는 ${bp + 5}bp로 계산한 결과다. 스프레드를 작게 잡을수록 인상확률이 높게 나온다. `
        + `버튼별 인상확률 최고값: ${rng.join(", ") || "–"}. 만기 안에 회의가 둘 이상이라 회의 사이 배분이 정해지지 않아 범위로만 낸다.`;
    } else $("#spreadNote").textContent = "";
    if (!cards.length) {
      const kf = (snap.components || {}).kofr_futures;
      cards.push(h("div", { class: "empty" }, snap.default_ok === false
        ? "기본 추정치(CD 91일 모형) 산출 중단: CD 만기가 확정된 금통위 일정 밖이다. "
          + (kf ? "KOFR 선물 실험값: " + kf.meetings.map((m) => `${md(m.date)} 인상 ${pct(m.p_hike)}`).join(", ") + "." : "")
        : "투입 상품 만기 안에 금통위가 없습니다."));
    }
    $("#gauges").replaceChildren(...cards);

    // 회의 뒤 기대 기준금리표(분포가 아니라 기대값). 누적 분포는 회의별 확률만으로 정해지지 않아 가능 범위로 따로 보인다.
    const bp = (x) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}bp`;
    const thead = h("thead", {}, h("tr", {}, ...["회의", "기대 기준금리", "현재 대비", "직전 회의 대비", "결정 확률", "계산"].map((x, i) => h("th", { class: i === 5 ? "l" : null }, x))));
    let prevE = snap.r0;
    const rows = ms.map((m) => {
      const ex = m.method === "kofr_ois" ? m.expected : (m.range && m.range.max_expected != null ? m.range.max_expected : m.expected);
      const os = outcomes(m);
      const r = h("tr", {}, h("td", {}, ymd(m.date)), h("td", {}, fx(ex, 3) + "%"), h("td", {}, bp(ex - snap.r0)), h("td", {}, bp(ex - prevE)),
        h("td", {}, os.map((o) => `${o.name} ${pct(o.p)}`).join(" · ")),
        h("td", { class: "l" }, m.method === "kofr_ois" ? m.ois_source.replace(" OIS", "").replace(" + ", "·") + " OIS" : "CD 91일"));
      prevE = ex;
      return r;
    });
    $("#probTable").replaceChildren(thead, h("tbody", {}, rows));
    // 두 회의 누적 결과: 회의별 확률(동결·같은 방향 25bp)만 주어지면 '두 번 모두 변경' 확률은 [max(0, p1+p2−1), min(p1, p2)] 사이 어디든 가능하다
    const notes = [];
    if (ms.length >= 2 && ms[0].method === "kofr_ois" && ms[1].method === "kofr_ois") {
      const o1 = outcomes(ms[0]).filter((o) => o.bp), o2 = outcomes(ms[1]).filter((o) => o.bp);
      const one = (os) => os.length === 0 || (os.length === 1 && Math.abs(os[0].bp) === 25);
      if (one(o1) && one(o2) && (!o1.length || !o2.length || Math.sign(o1[0].bp) === Math.sign(o2[0].bp))) {
        const sgn = (o1[0] || o2[0] || { bp: 25 }).bp > 0 ? 1 : -1;
        const p1 = o1.length ? o1[0].p : 0, p2 = o2.length ? o2[0].p : 0;
        const lo = Math.max(0, p1 + p2 - 1), hi = Math.min(p1, p2);
        const lv = (k) => fx(snap.r0 + sgn * 0.25 * k, 2) + "%";
        notes.push(`${md(ms[1].date)} 회의 뒤 기준금리 분포는 하나로 정해지지 않는다. 회의별 확률(${md(ms[0].date)} ${pct(p1)}, ${md(ms[1].date)} ${pct(p2)})만으로는 두 번 모두 ${sgn > 0 ? "인상" : "인하"}할 확률을 알 수 없어서다. `
          + `가능 범위: ${lv(0)} ${pct(1 - p1 - p2 + lo)}~${pct(1 - p1 - p2 + hi)} · ${lv(1)} ${pct(p1 + p2 - 2 * hi)}~${pct(p1 + p2 - 2 * lo)} · ${lv(2)} ${pct(lo)}~${pct(hi)}. 기대 기준금리(${fx(ms[1].expected, 3)}%)는 어느 경우에나 같다.`);
      }
    }
    $("#probNote").textContent = notes.join(" ");
    // FedWatch 방식: 회의별 이동 확률을 곱해 회의 뒤 기준금리 분포를 잇는다(독립 가정). OIS로 낸 회의까지만.
    const fwMs = [];
    for (const m of ms) { if (m.method !== "kofr_ois") break; fwMs.push(m); }
    if (fwMs.length) {
      let dist = { [snap.r0.toFixed(2)]: 1 };
      const rowsFw = fwMs.map((m) => {
        const next = {};
        for (const [lv, p0] of Object.entries(dist)) for (const o of outcomes(m)) {
          const k = (+lv + o.bp / 100).toFixed(2);
          next[k] = (next[k] || 0) + p0 * o.p;
        }
        dist = next;
        return [m.date, { ...dist }];
      });
      const lvls = [...new Set(rowsFw.flatMap(([, d]) => Object.keys(d)))].sort((a, b) => a - b);
      $("#fwTable").replaceChildren(h("thead", {}, h("tr", {}, h("th", {}, "회의 뒤"), ...lvls.map((l) => h("th", {}, l + "%")))),
        h("tbody", {}, ...rowsFw.map(([d, dd]) => h("tr", {}, h("td", {}, ymd(d)), ...lvls.map((l) => h("td", { class: dd[l] ? null : "zero" }, pct(dd[l] || 0)))))));
    } else $("#fwTable").replaceChildren();

    // OIS 계산 근거·민감도
    const ko = (live.components || {}).kofr_ois;
    if (ko && ko.curve) {
      const C = ko.curve, k = (ko.path || [])[0] ? ko.path[0].kofr_base : null;
      const use = { w1: "참고(곡선)", w2: "참고(곡선)", m1: "다음 회의 계산", m3: "그다음 회의 계산" };
      $("#oisTable").replaceChildren(
        h("thead", {}, h("tr", {}, ...["만기", "CD", "기준일", "스프레드(CD − 실제 KOFR 복리, 중앙값)", "자체 합성 OIS", "쓰임"].map((x) => h("th", {}, x)))),
        h("tbody", {}, ...["w1", "w2", "m1", "m3"].filter((x) => C[x]).map((x) => h("tr", {}, h("td", {}, C[x].label), h("td", {}, fx(C[x].cd, 2) + "%"),
          h("td", {}, ymd(C[x].cd_date)), h("td", {}, `${(C[x].spread * 100).toFixed(1)}bp (${C[x].n_obs}일)`), h("td", {}, fx(C[x].ois, 3) + "%"), h("td", {}, use[x])))));
      const sens = (ko.path || []).map((n) => {
        const T = n.tenor_days || 30, post = n.post_days;
        if (!post) return null;
        const per = T / post / 25; // CD(또는 스프레드) 1bp → 회의 확률 변화
        return `${md(n.meeting)}: ${n.source.startsWith("1개월") ? "CD 1개월" : "CD 91일"} 1bp 변화 → 그 회의 변경 확률 약 ${(per * 100).toFixed(1)}%p`;
      }).filter(Boolean);
      $("#oisNote").textContent = [`KOFR − 기준금리 보정 ${k != null ? (k * 100).toFixed(1) + "bp" : "–"}(${ko.kofr_base_how || "60일 중앙값"}).`,
        `민감도 — ${sens.join(" · ")}. CD 공시값이 1bp 단위(소수 둘째 자리 버림)라 이 정도 오차가 늘 있다. 다음 회의 값이 바뀌면 그다음 회의 값은 반대 방향으로 움직인다.`,
        "스프레드 ±1bp, KOFR 보정 ±1bp도 같은 크기로 움직인다."].join(" ");
    } else { $("#oisTable").replaceChildren(); $("#oisNote").textContent = "자체 합성 OIS 자료 없음 — CD 91일 값으로 표시한다."; }

    // CD 91일 참고 범위(버튼 결과가 바로 보이는 표)
    const cdc0 = (snap.components || {}).cd || {};
    const cdRows = ms.map((m) => {
      const cells = ["-5", "0", "5"].map((kk) => { const x = ((cdc0[kk] || {}).meetings || []).find((z) => z.date === m.date && z.range); return x ? `${pct(x.range.min)}~${pct(x.range.max)}` : "–"; });
      return h("tr", {}, h("td", {}, ymd(m.date)), ...cells.map((c, i) => h("td", { class: ["-5", "0", "5"][i] === S.s ? "max" : null }, c)));
    });
    $("#cdRangeTable").replaceChildren(h("thead", {}, h("tr", {}, h("th", {}, "회의"), ...["스프레드 −5bp", "기본", "+5bp"].map((x) => h("th", {}, `${x} 인상 확률 범위`)))), h("tbody", {}, cdRows));

    // 투입 금리표
    const ih = h("thead", {}, h("tr", {}, ...["상품", "금리", "기준일", "기준금리 대비", "전일 대비", "스프레드", "쓰임", "출처"].map((t, i) => h("th", { class: i === 7 ? "l" : null }, t))));
    const vb = (x) => x == null ? "–" : (x >= 0 ? "+" : "") + x + "bp";
    const useOf = (i) => i.id === "cd91" ? "3개월 OIS · CD 91일 참고 범위" : i.id === "kofr" ? "OIS 스프레드·KOFR 보정" : "참고";
    const ib = snap.inputs.map((i) => h("tr", {},
      h("td", {}, i.label), h("td", {}, fx(i.rate, 3) + "%"), h("td", {}, ymd(i.date)), h("td", {}, vb(i.vs_base_bp)), h("td", {}, vb(i.chg_bp)),
      h("td", { title: i.spread_how }, i.id === "cd91" && ko && ko.curve && ko.curve.m3
        ? `OIS ${(ko.curve.m3.spread * 100).toFixed(1)}bp · 참고 범위 ${(i.spread * 100 + (i.used ? +S.s : 0)).toFixed(0)}bp` : i.used ? (i.spread * 100 + +S.s).toFixed(0) + "bp" : "–"),
      h("td", {}, useOf(i)), h("td", { class: "l" }, i.source)));
    if (ko && ko.curve) {
      for (const x of ["w1", "w2", "m1"].filter((z) => ko.curve[z])) {
        const c = ko.curve[x];
        ib.push(h("tr", {}, h("td", {}, `CD ${c.label}(AAA 평가)`), h("td", {}, fx(c.cd, 2) + "%"), h("td", {}, ymd(c.cd_date)),
          h("td", {}, vb(Math.round((c.cd - snap.r0) * 1000) / 10)), h("td", {}, "–"), h("td", {}, `OIS ${(c.spread * 100).toFixed(1)}bp`),
          h("td", {}, x === "m1" ? "1개월 OIS(다음 회의)" : "OIS 곡선(참고)"), h("td", { class: "l" }, "금융투자협회 CD시가평가수익률 5사 평균")));
      }
      const k0 = (ko.path || [])[0];
      if (k0) ib.push(h("tr", {}, h("td", {}, "KOFR − 기준금리 보정"), h("td", {}, (k0.kofr_base * 100).toFixed(1) + "bp"), h("td", {}, "–"), h("td", {}, "–"), h("td", {}, "–"),
        h("td", {}, "–"), h("td", {}, "OIS → 기준금리 환산"), h("td", { class: "l" }, ko.kofr_base_how || "60일 중앙값")));
    }
    $("#inputTable").replaceChildren(ih, h("tbody", {}, ib));
    const used = snap.inputs.find((i) => i.used);
    $("#marketNote").textContent = [`기준금리 ${fx(snap.r0)}% (${snap.r0_source}).`,
      used ? `CD 91일 참고 범위의 정상 스프레드: ${used.label} ${(used.spread * 100).toFixed(0)}bp — ${used.spread_how}${S.s !== "0" ? `, 화면은 ${S.s > 0 ? "+" : ""}${S.s}bp 가정` : ""}.` : "",
      ms.some((m) => m.method !== "kofr_ois") ? `CD 91일로 낸 회의 계산 방식: ${scen.method.replace("min_hike", "최소 인상 경로").replace("bootstrap", "부트스트래핑").replace("lsq", "비음수 최소제곱")}.` : "기본값 계산: 자체 합성 KOFR OIS(1개월·3개월물 부트스트래핑).",
      out.length ? `만기 밖이라 계산하지 않은 회의: ${out.join(", ")}.` : "",
      ...(snap.warnings || [])].filter(Boolean).join(" ");
    renderFutures(live);
    renderTrend();
    renderEvents();
    renderLog();
  }

  // 회의별 두 방식 값 한 줄
  function partsLine(snap, date) {
    const c = snap.components || {};
    const kf = c.kofr_futures && c.kofr_futures.meetings.find((x) => x.date === date);
    const bl = c.blend_experimental && c.blend_experimental.meetings.find((x) => x.date === date);
    const qm = c.qual_mix && c.qual_mix.meeting === date ? c.qual_mix : null;
    return "실험값 — " + [kf ? `KOFR 선물 ${pct(kf.p_hike)}` : "KOFR 선물 –", bl ? `혼합 ${pct(bl.p_hike)}` : "혼합 –",
      ...(qm ? [`AI 정성 ${pct(qm.qual.p_hike)}`, qm.w10 ? `기본+정성10% ${pct(qm.w10.p_hike)}` : ""] : [])].filter(Boolean).join(" · ");
  }

  function renderFutures(snap) {
    const kf = snap && snap.components && snap.components.kofr_futures;
    if (!kf) { $("#futTable").replaceChildren(); $("#futNote").textContent = "KOFR 선물 가격 없음(KRX 수집 전 또는 기준일 근처 자료 없음)."; return; }
    const head = h("thead", {}, h("tr", {}, ...["결제월", "기준기간", "정산가격", "내재 금리", "지난 날/남은 날", "거래량", "미결제약정"].map((x) => h("th", {}, x))));
    const body = kf.used.map((u) => h("tr", {}, h("td", {}, u.month), h("td", {}, `${ymd(u.start)}~${ymd(u.end)}`), h("td", {}, (+u.price).toFixed(3)),
      h("td", {}, fx(u.rate, 3) + "%"), h("td", {}, `${u.past_days}/${u.future_days}일`), h("td", { class: u.volume ? null : "zero" }, u.volume), h("td", {}, u.oi)));
    $("#futTable").replaceChildren(head, h("tbody", {}, body));
    const nz = kf.used.filter((u) => !u.volume).length;
    $("#futNote").textContent = `가격일 ${ymd(kf.price_date)} · KOFR−기준금리 차이 ${(kf.spread * 100).toFixed(1)}bp(${kf.spread_how}). `
      + `기준기간이 확정 일정 밖인 결제월은 뺐다(${kf.skipped.map((s) => s.month).join(", ") || "없음"}). `
      + (nz ? `거래량 0인 결제월 ${nz}개의 정산가격은 체결로 확인된 가격이 아니다(거래소가 이론가격·호가 등으로 정함). ` : "")
      + "KOFR 선물 결과는 실험값이며 기본 추정치에 섞지 않는다.";
  }

  // 날짜별 확률 기록(prob_log.json): 재계산하지 않는 당일 기록
  function renderLog() {
    const L = D.plog || [];
    const days = [...new Set(L.map((r) => r.date))].sort().reverse().slice(0, 60);
    const meets = [...new Set(L.filter((r) => r.status === "산출" && days.includes(r.date)).map((r) => r.meeting))].sort();
    if (!days.length) {
      $("#logTable").replaceChildren();
      $("#logNote").textContent = "아직 기록이 없습니다. 매일 10시 일일 갱신(run_daily.py) 때부터 하루 한 줄씩 쌓입니다.";
      return;
    }
    const head = h("thead", {}, h("tr", {}, h("th", {}, "기록일"), h("th", {}, "금리 기준일"),
      ...meets.map((m) => h("th", {}, `${md(m)} 인상`)), h("th", {}, "기준"), h("th", { class: "l" }, "비고")));
    const body = days.map((dd) => {
      const rs = L.filter((r) => r.date === dd);
      const r0 = rs[0];
      const stop = r0.status !== "산출";
      return h("tr", { class: dd.length > 10 ? "extra" : null }, h("td", {}, ymd(dd) + (dd.length > 10 ? ` ${dd.slice(11, 16)} 추가` : "")), h("td", {}, ymd(r0.asof)),
        ...meets.map((m) => { const r = rs.find((x) => x.meeting === m); return h("td", {}, r && r.p_hike !== "" ? pct(+r.p_hike) : "–"); }),
        h("td", {}, stop ? "–" : r0.instrument),
        h("td", { class: "l" }, stop ? "산출 중단: " + r0.note : rs.map((r) => `${md(r.meeting)} ${r.note}`).filter((x) => x.trim()).join(" / ")));
    });
    $("#logTable").replaceChildren(head, h("tbody", {}, body));
    $("#logNote").textContent = "기록일 아침 10시에 그 전 영업일 종가로 계산해 화면에 낸 값이다. 이후 가정이 바뀌어도 고치지 않는다. '추가' 줄은 정기 기록 밖에서 모형을 바꾼 시점의 값이다.";
  }

  function renderEvents() {
    const E = D.events;
    const flag = { US: "미국", KR: "한국" };
    const ind = Object.values(E.indicators || {});
    const tiles = ind.length ? ind.map((x) => h("div", { class: "tile" }, h("div", { class: "k" }, `${x.label} · ${x.month} 전년동월비`),
      h("div", { class: "v" }, fx(x.yoy, 1) + "%"),
      h("div", { class: "s" }, (x.prev_yoy != null ? `전월 ${fx(x.prev_yoy, 1)}%` : "") + (x.core_yoy != null ? ` · 근원 ${fx(x.core_yoy, 1)}%` : "")
        + (x.prev_core_yoy != null ? `(전월 ${fx(x.prev_core_yoy, 1)}%)` : "")),
      x.mom != null ? h("div", { class: "s" }, `전월비 ${x.mom >= 0 ? "+" : ""}${fx(x.mom, 1)}%` + (x.core_mom != null ? ` · 근원 ${x.core_mom >= 0 ? "+" : ""}${fx(x.core_mom, 1)}%` : "") + " (계절조정)") : "",
      x.consensus ? h("div", { class: "s" }, `예상 ${fx(x.consensus.yoy, 1)}%` + (x.consensus.core_yoy != null ? ` · 근원 예상 ${fx(x.consensus.core_yoy, 1)}%` : "") + " → "
        + [x.yoy - x.consensus.yoy, x.core_yoy != null && x.consensus.core_yoy != null ? x.core_yoy - x.consensus.core_yoy : null]
          .map((d, i) => d == null ? "" : `${i ? "근원 " : ""}${d > 0.04 ? "상회" : d < -0.04 ? "하회" : "부합"}`).filter(Boolean).join(" · ")) : "",
      h("div", { class: "note" }, x.source, x.consensus ? [" · 예상치: ", x.consensus.link ? ext(x.consensus.link, x.consensus.source) : x.consensus.source] : ""))) : [h("p", { class: "note" }, "지표 실제치 수집 전 (FRED·ECOS)")];
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
    // 다가오는 회의만, 최신값과 변화폭을 한 줄로. 미니 추이선은 최근 20영업일.
    const el = $("#trend");
    const key = (v) => v instanceof Date ? v.toISOString().slice(0, 10) : String(v);
    const rows = D.hist.filter((r) => String(r.scenario) === S.s).map((r) => ({ d: key(r.date), m: key(r.meeting), p: +r.p_hike }));
    if (!rows.length) { el.replaceChildren(h("div", { class: "empty" }, "추이 데이터 없음")); return; }
    const last = rows.reduce((a, r) => (r.d > a ? r.d : a), "");
    const meets = [...new Set(rows.filter((r) => r.m > last).map((r) => r.m))].sort().slice(0, 3);
    if (!meets.length) { el.replaceChildren(h("div", { class: "empty" }, "다가오는 회의의 추이 데이터 없음")); return; }
    const days = [...new Set(rows.map((r) => r.d))].sort();
    const back = (n) => days[Math.max(0, days.length - 1 - n)];
    const at = (m, d) => { const r = rows.find((x) => x.m === m && x.d === d); return r ? r.p : null; };
    const chg = (a, b) => a == null || b == null ? "–" : (a - b >= 0.0005 ? "+" : a - b <= -0.0005 ? "−" : "±") + (Math.abs(a - b) * 100).toFixed(1) + "%p";
    const spark = (m) => {
      const pts = days.slice(-20).map((d) => at(m, d)).filter((v) => v != null);
      if (pts.length < 2) return "–";
      const W = 120, H = 26, xs = (k) => 2 + (k * (W - 4)) / (pts.length - 1), ys = (v) => H - 3 - v * (H - 6);
      const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H).attr("role", "img").attr("aria-label", `${md(m)} 회의 최근 추이`);
      svg.append("path").attr("d", d3.line().x((v, k) => xs(k)).y(ys)(pts)).attr("fill", "none").attr("stroke", "var(--ink-2)").attr("stroke-width", 1.5);
      svg.append("circle").attr("cx", xs(pts.length - 1)).attr("cy", ys(pts[pts.length - 1])).attr("r", 2.5).attr("fill", "var(--hike)");
      return svg.node();
    };
    const head = h("thead", {}, h("tr", {}, ...["회의", `최신(${ymd(last)})`, "전일 대비", "1주 전 대비", "1개월 전 대비", "최근 20영업일"].map((x) => h("th", {}, x))));
    const body = meets.map((m) => {
      const now = at(m, last);
      return h("tr", {}, h("td", {}, `${ymd(m)} 금통위`), h("td", {}, now == null ? "–" : pct(now)),
        h("td", {}, chg(now, at(m, back(1)))), h("td", {}, chg(now, at(m, back(5)))), h("td", {}, chg(now, at(m, back(21)))), h("td", {}, spark(m)));
    });
    el.replaceChildren(h("div", { class: "tbl-wrap" }, h("table", { class: "grid trend-table" }, head, h("tbody", {}, body))));
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
          ""),
        dl);
    });
    $("#meetCards").replaceChildren(...cards);

    // 타임라인
    const fill = (selEl, vals, cur, all) => selEl.replaceChildren(h("option", { value: "" }, all), ...vals.map((v) => h("option", { value: v, selected: v === cur }, v)));
    // 기본은 총재 발언만. '발언자 전체'를 고르면 부총재·위원 발언도 함께
    const isGov = (s) => / 총재$/.test(s) && !s.includes("부총재");
    $("#spkSel").replaceChildren(h("option", { value: "" }, "총재"), h("option", { value: "*", selected: S.spk === "*" }, "발언자 전체"),
      ...(G.speakers || []).filter((v) => !isGov(v)).map((v) => h("option", { value: v, selected: v === S.spk }, v)));
    fill($("#venSel"), G.venues || [], S.ven, "장소 전체");
    const tn = { hawk: "매파", dove: "비둘기", neutral: "중립" };
    const sp = (G.speeches || []).filter((s) => (!S.spk ? isGov(s.speaker) : S.spk === "*" || s.speaker === S.spk) && (!S.ven || s.venue === S.ven));
    $("#timeline").replaceChildren(...sp.map((s) => h("li", { class: s.tone },
      h("div", { class: "when" }, `${ymd(s.date)} · ${s.venue} · ${s.speaker}`, h("span", { class: `tag ${s.tone}` }, tn[s.tone] || s.tone)),
      h("div", {}, "“" + s.quote + "”", s.note ? h("small", {}, s.note) : ""),
      h("div", { class: "note" }, s.link ? ext(s.link, "인용 기사") : ""),
      (s.articles || []).length ? more(`관련 기사 ${s.articles.length}건`, h("ul", { class: "rel" }, ...s.articles.map((a) =>
        h("li", {}, `${a.published.slice(5, 16).replace("T", " ").replace("-", "/")} · ${a.press} `, ext(a.link, a.title))))) : null)));
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
      svg.node(), more("설명", h("div", { class: "note" }, "통방문·간담회 문장을 config 사전으로 센 값(문장당 점수). 자동 산출 · 참고용 — 문맥(부정·조건)을 읽지 못합니다.")));
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
        ? "한은 홈페이지 수집 전입니다. 공개 예정일은 '회의일 + 14일 이후 첫 화요일' 규칙 계산값이며 한은 공지가 우선합니다."
        : "위원별 의견을 추출한 의사록이 없습니다."));
      return;
    }
    const v = withV.views;
    const t = v.totals;
    $("#views").replaceChildren(
      h("p", {}, `${ymd(withV.date)} 회의 의사록 · 위원별 의견 ${v.paragraphs.length}건: 인상 ${t["인상"] || 0} · 동결 ${t["동결"] || 0} · 인하 ${t["인하"] || 0}`
        + (v.result ? ` · 결정 ${v.result}` : "")
        + (v.dissent && v.dissent.length ? ` · 소수의견 ${v.dissent.map((x) => `${x.name}(${x.view || "–"})`).join(", ")}` : "") + " · ", ext(v.source, "원문 PDF")),
      h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
        h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "입장"), h("th", { class: "l" }, "첫 문장"))),
        h("tbody", {}, v.paragraphs.map((p, i) => h("tr", {}, h("td", {}, i + 1), h("td", {}, p.lean), h("td", { class: "l" }, p.excerpt)))))),
      more("설명", h("p", { class: "note" }, "입장은 위원별 의견 개진(본회의) 단락의 첫 문장으로 자동 판정합니다. 의사록은 위원을 익명으로 적고, 소수의견 실명은 의결문 단서에서 옮깁니다.")));
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
    // 기사 목록은 뺐다(총재 발언은 가이던스 탭 타임라인의 기사 링크로 본다)
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
      if (c.k === "source") return h("td", { class: "l" }, r.link ? ext(r.link, r.source) : r.source || "–");
      if (c.k === "published") return h("td", {}, ymd(r.published), (D.reports.new || []).includes(r.institution) ? h("span", { class: "badge new" }, "새") : "");
      return h("td", { class: c.l ? "l" : null }, r[c.k] || "–");
    })));
    $("#repTable").replaceChildren(thead, h("tbody", {}, tb));

    renderConsensus();
    const K = D.reports.kofia || [];
    const pc = (v) => v == null ? "–" : v + "%";
    $("#kofia").replaceChildren(K.length ? h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ...["월", "상태", "조사기간", "응답자", "동결", "인상", "인하", "출처"].map((t, i) => h("th", { class: i === 7 ? "l" : null }, t)))),
      h("tbody", {}, K.slice().reverse().map((k) => h("tr", {}, h("td", {}, k.month), h("td", {}, k.status || "–"), h("td", {}, k.period || "–"), h("td", {}, k.respondents ?? "–"),
        h("td", {}, pc(k.hold)), h("td", {}, pc(k.hike)), h("td", {}, pc(k.cut)), h("td", { class: "l" }, k.source || (k.status === "미발표" ? "10월 금통위 대상 설문은 '11월 채권시장지표'로 발표(작년 10/21)" : "–")))))))
      : h("p", { class: "note" }, "금투협 설문 미입력"));
  }

  async function renderConsensus() {
    const dv = await defaultView(await snapshot(S.d));
    const snap = dv.view;
    const scen = snap && snap.scenarios[S.s];
    const asof = dv.staleFrom ? ` · ${ymd(dv.staleFrom)} 기준` : "";
    const cons = D.reports.consensus;
    const cards = (D.meta.upcoming || []).slice(0, 2).map((m) => {
      const c = cons.by_meeting[m] || { counts: {}, n: 0 };
      const mk0 = scen && scen.meetings.find((x) => x.date === m && x.in_range);
      // 게이지와 같은 기준: 그 회의 인상확률을 가능 범위 최고로 둔 경로
      const mk = mk0 && mk0.range && mk0.range.direction === "hike"
        ? { ...mk0, p_hike: mk0.range.max, p_hold: 1 - mk0.range.max, p_cut: 0 } : mk0;
      const order = [["인상", "var(--hike)"], ["동결", "var(--hold)"], ["인하", "var(--cut)"]];
      const other = c.n - order.reduce((s, [k]) => s + (c.counts[k] || 0), 0);
      const bar = h("div", { class: "cbar", role: "img", "aria-label": "전망 기관 수" },
        ...order.filter(([k]) => c.counts[k]).map(([k, col]) => h("span", { style: `flex:${c.counts[k]};background:${col}`, title: `${k} ${c.counts[k]}곳` }, `${k} ${c.counts[k]}`)),
        other > 0 ? h("span", { style: `flex:${other};background:var(--ink-3)` }, `기타 ${other}`) : "");
      const mbar = mk ? h("div", { class: "cbar", role: "img", "aria-label": "모형 추정 확률" },
        mk.p_hike > 0.005 ? h("span", { style: `flex:${mk.p_hike};background:var(--hike)` }, mk.p_hike > 0.12 ? `인상 ${pct(mk.p_hike, 0)}` : "") : "",
        mk.p_hold > 0.005 ? h("span", { style: `flex:${mk.p_hold};background:var(--hold)` }, mk.p_hold > 0.12 ? `동결 ${pct(mk.p_hold, 0)}` : "") : "",
        mk.p_cut > 0.005 ? h("span", { style: `flex:${mk.p_cut};background:var(--cut)` }, "인하") : "") : h("div", { class: "note" }, "모형 추정치 없음");
      return h("div", { class: "tile" }, h("div", { class: "k" }, `${ymd(m)} 회의`),
        h("div", { class: "s" }, `전문가 ${c.n}곳 — 인상 ${pct(c.hike_share, 0)}`), bar,
        h("div", { class: "s" }, `모형 추정(${mk0 && mk0.method === "kofr_ois" ? "KOFR OIS" : "CD"}) — 인상 ${mk ? (mk0.range ? "최고 " : "") + pct(mk.p_hike) : "–"}${mk ? asof : ""}`), mbar);
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
      el.replaceChildren(h("div", { class: "empty" }, "AI 정성 판단 데이터가 없습니다. GitHub Secrets에 NAVER_CLIENT_ID·NAVER_CLIENT_SECRET·OPENAI_API_KEY를 넣으면 매일 10시 갱신 때 생성됩니다."));
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
        ...((S_.event_checks || []).length ? [h("h4", {}, "사건 분류와 요약 대조"), h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
          h("thead", {}, h("tr", {}, ...["사건", "최종 분류", "요약의 해석", "일치", "설명"].map((x, i) => h("th", { class: i === 4 ? "l" : null }, x)))),
          h("tbody", {}, ...S_.event_checks.map((c) => h("tr", {}, h("td", { class: "l" }, c.event), h("td", {}, c.classified), h("td", {}, c.summary_reading),
            h("td", { class: c.consistent ? null : "mixed" }, c.consistent ? "일치" : "다름"), h("td", { class: "l" }, c.note || "–"))))))] : []),
        h("h4", {}, "주요 요인"),
        h("ul", { class: "drivers" }, ...(S_.drivers || []).map((d) => h("li", {},
          h("span", { class: `tag ${dirCls[d.direction]}` }, d.direction), " ", h("b", {}, d.factor), " — ", d.point, " ",
          ...d.article_ids.filter((i) => byId[i]).map((i, k) => h("span", {}, k ? ", " : "[", ext(byId[i].link, byId[i].press || "기사"), k === d.article_ids.filter((j) => byId[j]).length - 1 ? "]" : ""))))),
        (S_.counterpoints || []).length ? [h("h4", {}, "반대 근거"), h("ul", {}, ...S_.counterpoints.map((c) => h("li", {}, c)))] : "",
        (S_.watch || []).length ? [h("h4", {}, "관전 포인트"), h("ul", {}, ...S_.watch.map((c) => h("li", {}, c)))] : ""));
    } else kids.push(h("p", { class: "note" }, "종합 판단 없음 (하루 1회 daily.yml에서 생성)"));

    // 다음 회의 관련 신호(사건 단위, 근거 기사)
    if (Q.signals) {
      const order = ["추가 인상 신호", "높은 금리 유지", "이번 회의 동결 신호", "인하 신호", "중기 경로", "배경 요인"];
      kids.push(h("h3", {}, "다음 회의 관련 신호 ", h("small", {}, `최근 ${Q.signals_window_days}일 · 같은 사건은 한 번 · AI 분류라 근거 기사 원문 확인`)));
      kids.push(h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
        h("thead", {}, h("tr", {}, h("th", {}, "신호"), h("th", {}, "사건 수"), h("th", { class: "l" }, "대표 근거"))),
        h("tbody", {}, ...order.map((s) => {
          const x = Q.signals[s] || { events: 0, examples: [] };
          return h("tr", {}, h("td", {}, s), h("td", {}, x.events),
            h("td", { class: "l" }, ...(x.examples.length ? x.examples.map((e, i) => h("div", {}, `${e.published.slice(5, 10)} ${e.press} `, ext(e.link, e.title),
              e.reports > 1 ? ` (보도 ${e.reports}건)` : "", h("small", {}, ` — ${e.reason}`))) : ["–"])));
        })))));
      kids.push(more("설명", h("p", { class: "note" }, "'높은 금리 유지'(긴축 기조 유지)는 이번 회의 동결과도 양립한다. '중기 경로'는 다음 회의가 아닌 시점(예: 6개월 뒤 점도표)에 관한 신호다.")));
    }

    // 압력지수 + 요인
    kids.push(h("h3", {}, `뉴스 태그 압력지수 `, h("small", {}, P.unit === "사건"
      ? `최근 ${Q.window_hours}시간 관련 기사 ${P.n_articles}건 → 같은 사건끼리 묶어 ${P.n}건으로 계산 · +1 인상 압력 ~ −1 인하 압력`
      : `최근 ${Q.window_hours}시간 관련 기사 ${P.n || 0}건 · +1 인상 압력 ~ −1 인하 압력 · 태그 단순 합산`)));
    kids.push(h("div", { class: "qgrid" }, h("div", { class: "tile" }, h("div", { class: "k" }, "현재"), h("div", { class: "v" }, P.index == null ? "–" : (P.index >= 0 ? "+" : "") + P.index.toFixed(2)),
      h("div", { class: "s" }, `태깅 ${Q.counts.tagged}/${Q.counts.total}건 · 관련 ${Q.counts.relevant}건`)), h("div", { id: "qualTrend", class: "chart" })));
    kids.push(h("h3", {}, P.unit === "사건" ? "요인별 사건 수 " : "요인별 기사 수 ", h("small", {}, `주황=인상 압력, 파랑=인하 압력, ${P.unit === "사건" ? "사건" : "기사"} 수 기준`)), factorBars(P.factors || []));
    if ((Q.events || []).length) {
      kids.push(h("h3", {}, "많이 보도된 사건 ", h("small", {}, "같은 사건 보도는 지수에 한 번만 들어가고, 보도 수는 가중치로 최대 2배까지만 반영")));
      kids.push(h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
        h("thead", {}, h("tr", {}, ...["사건", "보도 수", "대표 요인", "기사별 방향", "대상", "시점", "대표 방향"].map((x) => h("th", {}, x)))),
        h("tbody", {}, ...Q.events.slice(0, 12).map((g) => {
          const M = g.mix || {}, dd = M.direction || {};
          const rep = g.direction > 0.2 ? "인상 압력" : g.direction < -0.2 ? "인하 압력" : "중립";
          const tg = M.target || {}, hz = M.horizon || {};
          return h("tr", {}, h("td", { class: "l" }, g.label), h("td", {}, g.n_reports), h("td", {}, g.factor || "–"),
            h("td", {}, M.n ? `인상 ${dd["인상 압력"] || 0} · 인하 ${dd["인하 압력"] || 0} · 중립 ${dd["중립"] || 0}` : "–"),
            h("td", { title: M.target_basis ? `대상 판정: ${M.target_basis}` : "" }, M.n ? `해외 ${tg["해외(연준 등)"] || 0} · 국내 ${tg["국내·한은"] || 0}` : "–"),
            h("td", {}, M.n ? `다음 회의 ${hz["다음 회의"] || 0} · 중기·배경 ${hz["중기·배경"] || 0}` : "–"),
            h("td", { class: M.mixed ? "mixed" : null, title: M.mixed ? "기사별 방향이 엇갈려 하나로 줄이기 어렵다" : "" },
              M.mixed ? `혼재(가중 평균 ${rep})` : `${rep} (가중 평균 ${(g.direction >= 0 ? "+" : "") + g.direction.toFixed(2)})`));
        })))));
      kids.push(more("설명", h("p", { class: "note" }, "대표 방향 = 기사별 방향을 강도로 가중 평균한 값(+0.2 넘으면 인상 압력, −0.2 밑이면 인하 압력). 인상·인하 기사가 함께 많으면(가장 많은 쪽이 60% 미만이거나 적은 쪽이 25% 이상) '혼재'로 표시한다. "
        + "대상은 AI가 기사마다 고른 주된 중앙은행(한은/연준/기타 해외)으로 센다. 이 구분이 생기기 전 태그는 요인('미 연준·글로벌 금리' = 해외)으로 센다. 방향은 한은 기준금리에 주는 함의만이다(연준 영향은 따로 분류). 시점은 AI 신호 태그 기준이다(추가 인상·높은 금리 유지·이번 회의 동결·인하 신호 = 다음 회의, 나머지 = 중기·배경).")));
    }

    // 기사 목록
    const facs = [...new Set((Q.articles || []).map((a) => a.factor))];
    const sel = h("select", { "aria-label": "요인", onchange: (e) => setS({ qf: e.target.value }) }, h("option", { value: "" }, "요인 전체"), ...facs.map((f) => h("option", { value: f, selected: S.qf === f }, f)));
    const dsel = h("select", { "aria-label": "방향", onchange: (e) => setS({ qd: e.target.value }) }, h("option", { value: "" }, "방향 전체"), ...Object.keys(dirCls).map((f) => h("option", { value: f, selected: S.qd === f }, f)));
    // 태깅된 기사: 접어 두고 누르면 연다(필터를 바꿔 다시 그려도 열린 상태 유지)
    const arts = (Q.articles || []).filter((a) => (!S.qf || a.factor === S.qf) && (!S.qd || a.direction === S.qd)).slice(0, 100);
    const tagBox = h("details", { class: "cdref", open: tagOpen, ontoggle: (e) => { tagOpen = e.target.open; } },
      h("summary", {}, `태깅된 기사 ${(Q.articles || []).length}건`), h("div", { class: "row-head" }, h("span", {}), h("div", { class: "filters" }, sel, dsel)));
    kids.push(tagBox);
    tagBox.append(h("ul", { class: "news" }, ...(arts.length ? arts.map((a) => h("li", {},
      h("div", { class: "m" }, `${a.published.slice(5, 16).replace("T", " ")} · ${a.press}${a.dup_press && a.dup_press.length ? ` 외 ${a.dup_press.length}곳` : ""} · ${a.origin === "yna" ? "연합 RSS" : "네이버"}${a.event_n > 1 ? ` · 같은 사건 보도 ${a.event_n}건: ${a.event}` : ""}`),
      h("div", { class: "t" }, ext(a.link, a.title)),
      h("div", { class: "sum" }, h("span", { class: `tag ${dirCls[a.direction]}` }, `${a.direction} ${"▮".repeat(a.strength)}`), " ", h("b", {}, a.factor), a.signal ? ` · ${a.signal}` : "", " · ", a.reason))) : [h("li", { class: "empty" }, "해당 기사 없음")])));
    if ((Q.errors || []).length) kids.push(h("p", { class: "note" }, "마지막 실행 오류: " + Q.errors.join("; ")));
    el.replaceChildren(...kids.flat());
    qualTrend();
  }

  let tagOpen = false;
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

  // ------------------------------------------------------------ 방법·검증
  function renderMethod() {
    const B = D.backtest || {};
    const C = B.compare || null;
    const W = C && C.walk_forward;
    const el = $("#method");
    el.className = "method";
    const sec = (title, ...kids) => [h("h2", {}, title), ...kids];
    const sub = (title, ...kids) => [h("h3", {}, title), ...kids];
    const p = (...k) => h("p", {}, ...k);
    const li = (...k) => h("li", {}, ...k);
    const code = (s) => h("code", {}, s);
    const table = (head, rows) => h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ...head.map((x) => h("th", {}, x)))), h("tbody", {}, ...rows.map((r) => h("tr", {}, ...r.map((x) => h("td", {}, x)))))));
    const actK = { hike: "인상", hold: "동결", cut: "인하" };
    const ox = (b) => b ? "○" : "×";

    const cmpTable = C ? table(["방식", "적중", "적중률", "Brier(낮을수록 좋음)"], [
      ["CD 91일 모형 (기본)", `${Math.round(C.cd.hit_rate * C.n)}/${C.n}`, pct(C.cd.hit_rate), C.cd.brier.toFixed(3)],
      ["KOFR 선물 모형 (실험)", `${Math.round(C.kofr.hit_rate * C.n)}/${C.n}`, pct(C.kofr.hit_rate), C.kofr.brier.toFixed(3)],
      ["혼합 KOFR 50% (실험)", `${Math.round(C.blend.hit_rate * C.n)}/${C.n}`, pct(C.blend.hit_rate), C.blend.brier.toFixed(3)],
      ["과거 결정 빈도 (비교 기준)", `${Math.round(C.base_rate.hit_rate * C.n)}/${C.n}`, pct(C.base_rate.hit_rate), C.base_rate.brier.toFixed(3)],
      ["항상 동결 (비교 기준)", `${Math.round(C.always_hold.hit_rate * C.n)}/${C.n}`, pct(C.always_hold.hit_rate), C.always_hold.brier.toFixed(3)],
    ]) : p(h("span", { class: "note" }, "KOFR 선물 이력 수집 전이라 비교표 없음"));
    const HB = C && C.hits_by_actual;
    const byActTable = HB ? table(["실제 결정", "회의 수", "CD 모형", "KOFR 선물", "혼합", "과거 결정 빈도", "항상 동결"],
      ["hold", "hike", "cut"].map((a) => [actK[a], HB[a].n, ...["cd", "kofr", "blend", "base_rate", "always_hold"].map((k) => `${HB[a][k]}/${HB[a].n}`)])) : "";
    const wfTable = W && W.n ? table(["방식", "적중", "Brier"], [
      ["혼합(비율을 그때까지의 회의로만 선택)", `${W.mix.hits}/${W.n}`, W.mix.brier.toFixed(3)],
      ["CD 91일 모형", `${W.cd.hits}/${W.n}`, W.cd.brier.toFixed(3)],
      ["항상 동결", `${W.always_hold.hits}/${W.n}`, "–"],
    ]) : "";
    const oisBy = Object.fromEntries(((D.kois && D.kois.rows) || []).map((r) => [r.meeting, r.ois]));
    const rowsTable = B.n ? h("div", { class: "tbl-wrap" }, h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ...["회의", "관측일", "실제", "OIS(현재 기본) 인상·동결·인하", "적중", "CD 91일 인상·동결·인하", "적중", "KOFR 선물 인상·동결·인하", "적중", "혼합 인상·동결·인하", "적중"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...B.rows.map((r) => h("tr", {}, h("td", {}, ymd(r.meeting)), h("td", {}, ymd(r.obs_date)),
        h("td", {}, actK[r.actual] + (r.move_bp ? ` ${r.move_bp > 0 ? "+" : ""}${r.move_bp}bp` : "")),
        ...(() => { const o = oisBy[r.meeting]; return o ? [h("td", {}, `${pct(o.p_hike, 0)}·${pct(o.p_hold, 0)}·${pct(o.p_cut, 0)}`), h("td", {}, ox(o.hit))] : [h("td", {}, "–"), h("td", {}, "–")]; })(),
        h("td", {}, `${pct(r.p_hike, 0)}·${pct(r.p_hold, 0)}·${pct(r.p_cut, 0)}`), h("td", {}, ox(r.hit)),
        h("td", {}, r.kofr ? `${pct(r.kofr.p_hike, 0)}·${pct(r.kofr.p_hold, 0)}·${pct(r.kofr.p_cut, 0)}` : "–"), h("td", {}, r.kofr ? ox(r.kofr.hit) : "–"),
        h("td", {}, r.blend ? `${pct(r.blend.p_hike, 0)}·${pct(r.blend.p_hold, 0)}·${pct(r.blend.p_cut, 0)}` : "–"), h("td", {}, r.blend ? ox(r.blend.hit) : "–")))))) : "";
    const excl = [...(B.excluded || []).map((e) => `${ymd(e.meeting)}: ${e.why}`),
      ...(C && C.excluded_before ? [`${C.excluded_before.map(ymd).join(", ")}: KOFR 선물 상장(2022-03-28) 전이거나 선물 계산 불가 — CD만 평가`] : [])];

    el.replaceChildren(
      ...sec("무엇을 보여 주나",
        p("화면의 확률은 '모형 추정치'다. 시장금리에서 거꾸로 계산한 값이며, 검증된 시장 내재확률이 아니다. 숫자를 인용할 때는 기준일·기준 금리·정상 스프레드 가정을 함께 밝힌다."),
        table(["구분", "내용", "상태"], [
          ["기본 추정치", "자체 산출 KOFR OIS(1개월·3개월물로 푸는 회의). 풀리지 않는 회의는 CD 91일 모형", "화면 게이지·날짜별 기록에 쓰는 값(2026-10-15 교체)"],
          ["실험값 1", "KOFR 3개월 선물 모형(한국거래소 정산가격)", "따로 표시·기록, 기본값에 섞지 않음"],
          ["실험값 2", "CD 모형과 KOFR 선물 모형 가중평균(KOFR 50%)", "따로 표시·기록, 채택 기준 충족 전까지 실험"],
        ])),
      ...sec("1. CD 91일 모형 (OIS로 풀리지 않는 회의의 기본값·참고 범위)",
        ...sub("가정",
          h("ul", {},
            li("기준일 종가 금리는 다음 날(결제일)부터 만기까지 [시작, 시작+91일) 구간을 덮는다."),
            li("CD 금리에서 정상 스프레드 s를 빼면 그 구간의 평균 기대 기준금리가 된다."),
            li("금통위 결정은 회의 당일부터 적용한다. 회의 사이에는 기준금리가 바뀌지 않는다."),
            li("기준금리는 0.25%p 단위로 움직인다."))),
        ...sub("계산식",
          p(code("91 × (y − s) = Σ E_k × (구간 k의 일수)"), " — E_0 = 현재 기준금리 r0, E_k = 회의 k 뒤 기대 기준금리."),
          h("ul", {},
            li("만기 구간에 회의가 하나면 E_1을 바로 푼다(부트스트래핑)."),
            li("회의가 둘 이상이면 미지수가 식보다 많다. '최소 인상 경로'로 나눈다: 늦은 회의부터 0.25%p 격자 상한까지 채우고 남는 부분을 앞 회의에 둔다. 이 규칙은 가까운 회의 확률을 낮게 잡는 쪽으로 기운다."),
            li("회의별 Δ_k = E_k − E_(k−1). 0 < Δ < 25bp면 인상확률 = Δ ÷ 25bp. Δ ≥ 25bp면 25bp 인상 확정에 초과분을 50bp 확률로 둔다(인상확률 합 100%). 음수는 인하로 대칭."),
            li("회의 뒤 목표금리 분포는 기대금리를 맞추는 인접 두 격자점으로 표시한다. 회의별 결과를 독립 확률나무로 잇는 CME FedWatch와 달리 분포를 좁게 보이게 한다(예: 두 회의 각 50%면 실제 누적 결과는 0·25·50bp가 25·50·25%이지만 '25bp 100%'로 표시)."),
          li("CD 한 금리로는 회의 사이 배분이 정해지지 않는다. 화면의 '같은 금리로 가능한 범위'는 동결·한 방향 25bp만 허용할 때 이 금리와 양립하는 회의별 확률의 최소·최대다. 예: 10/13 CD 3.24%, 스프레드 18bp → 83×p(10월)+48×p(11월)=21.84 → 10월 0~26.3%, 11월 0~45.5%. 화면의 'CD 91일 참고 범위'는 이 최소~최대다(2026-10-15 전에는 게이지 숫자가 그중 최고값이었다). 회의별 최고값은 다른 회의 날짜와 무관하다."))),
        ...sub("계산 예시 (검산 고정값)",
          p("기준일 2026-10-13, 기준금리 3.00%, CD 91일 3.24%, 정상 스프레드 10bp, 회의 10/22·11/26(만기 안 회의가 둘뿐이라고 둔 검산용 예시. 현재 화면 계산은 2027년 1/11 가정 회의를 더한다)."),
          table(["단계", "값"], [
            ["구간", "결제일 10/14 ~ 만기 2027-01-13(91일): 10/14~10/21 8일(3.00%), 10/22~11/25 35일(E1), 11/26~1/12 48일(E2)"],
            ["좌변", "91 × (3.24 − 0.10 − 3.00) = 12.74 (%p·일)"],
            ["최소 인상 경로", "늦은 11월부터: 48일 × 0.25 = 12.00 → 남은 0.74를 10월 35일에: Δ1 = 0.74 ÷ 35 = 0.0211"],
            ["확률", "10월 인상 = 2.11 ÷ 25 = 8.5%, 11월 인상 = (25 − 2.11) ÷ 25 = 91.5%"],
            ["같은 입력, 스프레드 18bp", "좌변 91 × 0.06 = 5.46 → 11월 Δ = 5.46 ÷ 48 = 0.1138 → 10월 0%, 11월 45.5%"],
          ]),
          p(h("span", { class: "note" }, "tests/test_model.py가 이 숫자를 매번 확인한다."))),
        ...sub("정상 스프레드",
          p("기준금리가 오래 묶여 있던 기간(config.model.hold_windows, 현재 2023-02-24~2024-08-21, 3.50% 동결)의 'CD − 기준금리' 중앙값. 동결 구간별 값은 2021년 +20bp, 2023년 +25bp, 2024년 +10bp, 2025년 하반기 +6bp, 2026년 상반기 +32bp로 크게 흔들린다. 그래서 −5bp·+5bp 결과를 함께 보여 준다."))),
      ...koisSection(sec, sub, p, li, table),
      ...cdShortSection(sec, sub, p, li, table),
      ...sec("2. KOFR 3개월 선물 모형 (실험값)",
        h("ul", {},
          li("상품: 한국거래소 3개월무위험금리 선물. 정산가격 = 100 − 기준기간 KOFR 일별 복리금리. 기준기간은 결제월 셋째 수요일 3개월 전 ~ 결제월 셋째 수요일(SOFR 3개월 선물과 같은 구조로 놓음)."),
          li(code("N × 평균KOFR = Σ(지난 날 공시 KOFR) + Σ(남은 날 기대 기준금리 + d)"), " — 복리를 단순평균으로 바꾸고(365/N·ln(1+R·N/365)), 지난 날은 ECOS의 KOFR 공시값을 쓴다."),
          li("d = KOFR − 기준금리 정상 차이: 기준일 앞 60일 중앙값. 동결 구간별 +2~6bp로 CD(+6~32bp)보다 안정적이다."),
          li("기준기간이 확정 일정 안에 끝나는 결제월 여러 개를 최소제곱으로 동시에 풀어 회의별 E_k를 구하고, Δ_k를 CD 모형과 같은 규칙으로 확률로 바꾼다."),
          li("한계: 거래가 드물다. 거래가 없는 결제월의 정산가격은 체결로 확인된 가격이 아니다. 결제월이 적거나 가격이 어긋나면 회의 사이 배정이 흔들린다(예: 2026-10-13 가격은 10월 인상 100%, 11월 하락을 가리켰다). Δ가 25bp를 넘으면 인상확률이 100%가 되는 것은 변환 규칙 때문이며 불확실성이 없다는 뜻이 아니다."))),
      ...sec("3. 혼합 (실험값)",
        p("회의별로 CD 모형과 KOFR 선물 모형의 인상·동결·인하 확률과 기대금리를 가중평균한다(KOFR 50%). 두 모형이 모두 계산된 회의만 낸다.")),
      ...sec("3-1. AI 정성 확률과 기본+정성 (실험값)",
        h("ul", {},
          li("하루 1회 AI(OpenAI)가 뉴스 사건 태그·점도표·한은 발언·지표만 보고 다음 금통위의 인상·동결·인하 확률을 직접 낸다. 같은 정보를 두 번 세지 않도록 시장금리로 계산한 확률은 입력에서 뺀다."),
          li("기본+정성 10%·20% = (1 − w) × 화면 기본값(2026-10-15부터 KOFR OIS, 그 전 CD 91일) + w × AI 정성 확률. 다음 회의 하나만 낸다."),
          li("과거 기사로 거꾸로 만들 수 없어 백테스트가 없다. 날짜별 기록에 쌓고 '5. 기본값 교체 기록과 기준'과 같은 규칙으로 평가한다. AI 출력은 같은 입력에도 조금씩 달라 재현되지 않는다."))),
      ...sec("4. 검증",
        ...sub("백테스트 결과 요약", ...(C ? [
          table(["방식", "적중", "Brier", `금리 바뀐 회의 ${C.by_outcome.n_change}회: 실제 결과에 준 확률 평균`, `동결 회의 ${C.by_outcome.n_hold}회: 동결에 준 확률 평균`], [
            ["CD 91일 모형 (10/15 전 기본)", `${Math.round(C.cd.hit_rate * C.n)}/${C.n}`, C.cd.brier.toFixed(3), pct(C.by_outcome.cd.change, 0), pct(C.by_outcome.cd.hold, 0)],
            ["KOFR 선물 모형 (실험)", `${Math.round(C.kofr.hit_rate * C.n)}/${C.n}`, C.kofr.brier.toFixed(3), pct(C.by_outcome.kofr.change, 0), pct(C.by_outcome.kofr.hold, 0)],
            ["혼합 KOFR 50% (실험)", `${Math.round(C.blend.hit_rate * C.n)}/${C.n}`, C.blend.brier.toFixed(3), pct(C.by_outcome.blend.change, 0), pct(C.by_outcome.blend.hold, 0)],
            ["항상 동결 (비교 기준)", `${Math.round(C.always_hold.hit_rate * C.n)}/${C.n}`, C.always_hold.brier.toFixed(3), "0%", "100%"],
          ]),
          h("ul", {},
            li(`CD 모형은 동결을 잘 맞히지만(동결 회의에 평균 ${pct(C.by_outcome.cd.hold, 0)}) 금리 변경을 놓친다(변경 회의에 평균 ${pct(C.by_outcome.cd.change, 0)}).`),
            li(`KOFR 선물 모형은 반대다. 변경 회의에 평균 ${pct(C.by_outcome.kofr.change, 0)}를 줬지만 동결 회의에서 헛신호가 많다(동결에 평균 ${pct(C.by_outcome.kofr.hold, 0)}).`),
            li(`CD 모형의 Brier ${C.cd.brier.toFixed(3)}는 '과거 결정 빈도'(${C.base_rate.brier.toFixed(3)})보다 ${C.cd.brier < C.base_rate.brier ? "낮다(낫다)" : "높다(못하다)"}. 금리 변경 ${HB.hike.n + HB.cut.n}회 중 CD가 맞힌 것은 ${HB.hike.cd + HB.cut.cd}회다.`),
            li("백테스트의 정상 스프레드는 회의마다 그 시점 이전 자료로만 다시 추정했다(미래정보 제거). 처음 공개한 성적(CD 27/36·Brier 0.461)은 2023~24년 구간으로 구한 18bp를 2021~22년 예측에도 쓴 값이라 실제보다 좋게 나왔다."),
            li("결론: CD 91일·KOFR 선물·혼합은 단순 비교 기준보다 낫다는 근거가 없다. 현재 기본값인 자체 합성 KOFR OIS는 같은 회의에서 CD 91일보다 Brier가 낮지만(1-1절), '항상 동결'과의 차이는 확실하지 않다. 금리에 반영된 기대를 가늠하는 참고치로 쓰고, 단정적인 확률로 인용하지 않는다."))] : [p("KOFR 선물 이력 수집 전")])),
        ...sub("결과별 적중", byActTable, p(h("span", { class: "note" }, "전체 적중률은 동결이 많은 표본에서 높게 나온다. 금리 변경(인상·인하) 포착률을 따로 본다."))),
        ...sub("방법",
          h("ul", {},
            li("각 회의 3영업일 전 종가로 계산한 확률과 실제 결정을 비교한다."),
            li("적중: 가장 높은 확률을 준 결과(인상·동결·인하)가 실제와 같으면 적중. 최고 확률이 둘 이상 같으면(예: 인상 50%·동결 50%) 동률로 보고 적중으로 치지 않는다."),
            li("Brier 점수: 세 결과의 (확률 − 실제 0/1)² 합의 평균. 0이 완벽, 낮을수록 좋다. 적중률보다 확률의 질을 잘 잰다."),
            li("비교 기준 '항상 동결': 이 표본에서 동결이 많아 적중률이 높게 나온다. 모형이 이를 넘지 못하면 예측력이 있다고 보기 어렵다."),
            li("비교 기준 '과거 결정 빈도': 그 회의 이전 결정들의 인상·동결·인하 비율(각 +1 보정)을 확률로 쓴다. 정보 없이 낼 수 있는 확률이라, 모형은 최소한 이보다 Brier가 낮아야 한다."),
            li("미래정보 제거: 정상 스프레드는 관측일 전날까지 자료 중 기준금리가 120일 넘게 바뀌지 않은 날의 (CD − 기준금리) 중앙값(최근 2년)으로 회의마다 다시 구한다. KOFR 실제치·회의 일정도 관측일 이전 값만 쓴다."))),
        ...sub(`세 방식 비교 ${C ? `(두 모형 모두 계산된 회의 ${C.n}회, ${ymd(C.first)}부터)` : ""}`, cmpTable,
          p(h("span", { class: "note" }, "혼합 비율 50%는 같은 표본을 보고 정한 값이라 이 표의 혼합 성적은 실제보다 좋게 나올 수 있다."))),
        ...sub("순차 검증 (비율을 미리 알 수 없다고 놓고 다시 잼)",
          p(W && W.n ? `처음 ${W.start_after}회로 KOFR 비율(0~100%, 10%p 간격)을 Brier 최소로 고르고, 다음 회의를 그 비율로 예측한다. 회의를 하나씩 넘기며 반복해 ${W.n}회를 예측했다.` : "자료 부족"),
          wfTable,
          p(W && W.n ? `결과: 혼합 Brier ${W.mix.brier.toFixed(3)}, CD ${W.cd.brier.toFixed(3)}. 적중은 혼합 ${W.mix.hits}/${W.n}, CD ${W.cd.hits}/${W.n}, 항상 동결 ${W.always_hold.hits}/${W.n}. 표본이 작고 금리 변경 사례가 적어 어느 쪽 우위도 확정할 수 없다. 혼합은 실험값으로 기록만 한다.` : "")),
        ...sub("평가에서 뺀 회의", excl.length ? h("ul", {}, ...excl.map((x) => li(x))) : p("없음")),
        ...sub(`회의별 예측 (${B.n || 0}회)`, B.n ? p(B.rule) : p(h("span", { class: "note" }, B.note || "백테스트 결과 없음")),
          p(h("span", { class: "note" }, "OIS 열은 금융투자협회 CD 단기물 공시(2023-01-09부터)와 스프레드 관측 60일이 쌓인 2023-05 회의부터 있다. OIS 성적 요약은 1-1절.")), rowsTable)),
      ...decisionSection(sec, sub, p, li, table),
      ...sec("5. 기본값 교체 기록과 기준",
        h("ul", {},
          li("2026-10-15 교체: 기본값을 CD 91일 모형에서 자체 산출 KOFR OIS로 바꿨다. 근거: 같은 회의 백테스트 Brier 다음 회의 0.394 대 0.557(27회), 그다음 회의 0.465 대 0.665(26회). 한계: 인상 2회·인하 4회로 표본이 작고, 같은 자료로 CD 단기물 방식 3개를 먼저 시험했다. '항상 동결'과의 차이는 확실하지 않다(다음 회의 0.394 대 0.444, 그다음 0.465 대 0.462)."),
          li("OIS로 풀리지 않는 회의(1개월물 안에 회의가 없고 3개월물 안에 회의가 둘 이상인 날 등)는 CD 91일 모형 가능 범위를 쓴다."),
          li("2026-10-22 회의부터 날짜별 확률 기록(data/prob_log.csv)의 회의 3영업일 전 값으로 순차 평가한다. 8회 뒤 OIS의 평균 Brier가 CD 91일 모형이나 '항상 동결'보다 높으면 교체를 다시 검토한다."),
          li("실험값(KOFR 선물·혼합·AI 정성)은 같은 기록으로 평가한다. 금통위 8회 동안 평균 Brier가 기본값(OIS)과 '항상 동결'보다 모두 낮을 때만 교체를 검토한다. KOFR 선물은 거래 반영 조건(거래 빈도·거래량·미결제약정)을 따로 본다."),
          li("앞으로 판정 기준은 결과를 본 뒤 바꾸지 않는다. 바꿀 때는 날짜와 이유를 이 절에 남긴다."))),
      ...sec("6. 한계",
        h("ul", {},
          li("자체 합성 KOFR OIS는 거래된 OIS 금리가 아니다. CD 평가금리에서 과거 'CD − 실제 KOFR' 차이의 중앙값을 뺀 추정치라, 그 차이가 지금 평소와 다르면 확률이 치우친다. CD 공시값이 1bp 단위라 회의 확률에 5~7%p 안팎 오차가 늘 있다."),
          li("OIS로는 회의별 확률만 나온다. 두 회의 이상 누적 분포(예: 두 번 모두 인상)는 정해지지 않아 가능 범위로만 보인다."),
          li("CD 금리에는 은행 자금사정과 신용 웃돈이 섞이고, 그 폭이 시기마다 크게 다르다(CD 91일 참고 범위의 한계)."),
          li("CD 91일 참고 범위의 '최소 인상 경로'는 한 만기 안의 회의 사이 배정을 가정으로 정한다. 2026-08-27 인상처럼 가까운 회의를 놓칠 수 있다."),
          li("2027년 금통위 일정이 공지되지 않아 1월 회의를 1/11로 가정한다(config assumed_meetings). KOFR OIS 3개월물 계산에서는 이 회의를 동결로 두고, CD 91일 참고 범위의 최고값은 이 가정과 무관하다. CD 만기가 가정 범위(2027-02-21)를 넘는 날부터는 CD 91일 참고 범위가 멈춘다."),
          li("보도 인용 값(기관 전망·발언)은 원문 대조가 필요하다. 매파·비둘기 점수와 의사록 입장 분류는 자동 산출이다."),
          li("AI 정성 판단은 기사 제목·검색 요약만 보고 내린 자동 판단이다. 기본 확률 계산에 넣지 않는다."))),
      ...sec("AI 정성 판단 방식",
        h("ul", {},
          li("네이버 뉴스 검색 API(NAVER API HUB)와 연합뉴스 RSS 기사를 OpenAI 모델이 하나씩 태깅: 관련성, 요인 10종, 다루는 중앙은행(한은/연준/기타 해외), 한은에 주는 방향과 연준에 주는 방향(따로), 강도 1~3, 다음 회의와의 관계 신호, 근거 한 줄."),
          li("한은 방향은 기사에 한국으로 이어지는 경로(환율·한미 금리차·국내 물가)가 적혀 있을 때만 인상·인하로 둔다. 연준 인상 신호는 연준 방향에만 적는다(2026-10-15부터, 최근 7일 기사 다시 분류)."),
          li("같은 사건 보도는 AI가 묶어 사건 하나로 센다. 압력지수 = Σ(사건 방향×강도×보도 수 가중, 최대 2배) ÷ Σ(강도×가중). 최근 72시간 관련 기사만. 사건 표에는 기사별 방향 분포를 함께 보이고, 엇갈리면 '혼재'로 표시한다."),
          li("종합 판단은 하루 1회: 사건별 대표 기사 태그 + 점도표·한은 발언·지표를 넣고 다음 금통위 기준 방향(−2~+2), 근거, 반대 근거, 관전 포인트를 받는다. 보도가 많은 사건은 최종 분류와 요약의 해석을 대조해 '사건 분류와 요약 대조' 표로 보인다."))),
      ...sec("데이터 출처", h("ul", {}, ...(D.meta.sources || []).map((s) => li(s.url ? ext(s.url, s.name) : s.name, ` — ${s.what}`)))),
      ...sec("수집 상태", h("ul", {}, ...Object.entries(D.status || {}).map(([k, v]) => li(h("i", { class: `fdot ${freshCls(v.last_success, v.ok === false)}` }), " ",
        `${SRC_NAMES[k] || k}: ${!v.ok ? "실패" : (v.message || "").startsWith("일부 실패") ? "일부 실패" : "정상"} · 마지막 시도 ${stamp(v.last_attempt)} · 마지막 성공 ${v.last_success ? stamp(v.last_success) : "없음"} · ${v.message || ""}`)),
        Object.keys(D.status || {}).length ? "" : li("수집 기록 없음"))),
    );
  }

  // 결정 예측 모형(실험): 회의 1건 = 표본 1개, 순서형 로지스틱
  function koisSection(sec, sub, p, li, table) {
    const X = D.kois;
    const cur = X && X.current;
    const code = (s) => h("code", {}, s);
    const actK = { hike: "인상", hold: "동결", cut: "인하" };
    const kids = [
      p("한국예탁결제원은 'KOFR OIS 추정금리'를 KOFR OIS = CD − 스프레드로 산출해 공시했으나 2025-10-24 이후 공시가 없다. 같은 산식으로 직접 계산한다(자체 산출 추정치). 2026-10-15부터 화면 기본값이다."),
      h("ul", {},
        li("CD: 1주(7일)·2주(15일)·1개월 = 금융투자협회 CD 시가평가수익률(AAA 5사 평균), 3개월 = CD 91일(ECOS)."),
        li("스프레드(만기별) = 과거 각 날짜의 'CD − 그 기간 실제 KOFR 일복리' 중앙값(ISDA 방식, 최대 5년). 그날까지 기간이 끝나고 KOFR가 공시된 관측만 쓴다. KOFR 이력이 2021-11부터라 아직 5년을 채우지 못했다."),
        li("그다음 회의: 3개월 OIS 식 91 × OIS = Σ 구간 일수 × (그 구간 기준금리 + k)에 1개월물로 푼 다음 회의 뒤 금리를 넣고 남은 회의 뒤 금리를 푼다(부트스트래핑). 만기 직전 7일 이내 회의는 변화 없음으로 둔다. 미지수가 둘 이상 남으면 내지 않는다."),
        li(code("30 × OIS(1개월) = 회의 전 일수 × (r0 + k) + 회의 뒤 일수 × (E + k)"), " — k = KOFR − 기준금리 정상 차이(60일 중앙값). 1개월 안 회의가 하나뿐이라 다음 회의 뒤 기대 기준금리 E를 바로 푼다. Δ = E − r0를 CD 91일 모형과 같은 규칙으로 확률로 바꾼다."),
        li("예탁원 공시값(2025-04-14~2025-10-24, 129일)과 비교: 자체 산출이 평균 1주 +3.5bp, 2주 +3.6bp, 1개월 +2.5bp, 3개월 +1.6bp 높다(스프레드 관측 기간이 짧은 탓으로 보인다). 예탁원 값은 재배포 금지라 화면에 싣지 않는다."),
        li("한계: CD 시가평가수익률은 소수 둘째 자리(버림)라 1bp 단위다. 1개월물 1bp는 회의 확률 약 5%p다. 평가금리라 체결 금리가 아니다. 공시가 18시 이후라 오전 갱신에는 전 영업일 값이 들어간다.")),
    ];
    if (cur && cur.curve) {
      const C = cur.curve;
      kids.push(table(["만기", "CD", "스프레드", "KOFR OIS(자체)"], ["w1", "w2", "m1", "m3"].filter((k) => C[k]).map((k) =>
        [C[k].label, `${fx(C[k].cd, 2)}% (${ymd(C[k].cd_date)})`, `${(C[k].spread * 100).toFixed(1)}bp (${C[k].n_obs}일)`, `${fx(C[k].ois, 3)}%`])));
      for (const n of (cur.path || [])) kids.push(p(h("b", {}, `${ymd(n.meeting)} 회의(${n.source}): `),
        (n.pre_days != null ? `회의 전 ${n.pre_days}일·뒤 ${n.post_days}일, ` : "") + `KOFR−기준금리 ${(n.kofr_base * 100).toFixed(1)}bp → 회의 뒤 기대 ${fx(n.expected, 3)}%(직전 대비 Δ ${n.delta_bp.toFixed(1)}bp) → 인상 ${pct(n.p_hike)} · 동결 ${pct(n.p_hold)}${n.p_cut > 0 ? ` · 인하 ${pct(n.p_cut)}` : ""}`
        + (n.tail_assumed && n.tail_assumed.length ? ` (만기 직전 ${n.tail_assumed.map(ymd).join("·")} 회의는 뒤 구간이 짧아 변화 없음으로 둠)` : "")));
    }
    if (X && X.n) {
      const S = X.summary, B = S.same_as_cd91;
      const line = (name, s) => [name, `${s.hits}/${X.n}`, s.brier.toFixed(3), ...["hike", "cut"].map((a) => `${s.by_actual[a].hits}/${s.by_actual[a].n}`),
        ...["hike", "hold", "cut"].map((a) => s.by_actual[a].p_actual == null ? "–" : pct(s.by_actual[a].p_actual))];
      kids.push(h("h3", {}, `백테스트 (${X.first} 이후 ${X.n}회, ${X.rule})`),
        table(["방식", "적중", "Brier", "인상 포착", "인하 포착", "인상 때 준 확률", "동결 때", "인하 때"],
          [line("KOFR OIS(자체) 1개월", S.ois), line("과거 결정 빈도", S.base_rate), line("항상 동결", S.always_hold)]));
      if (B) kids.push(p(`같은 회의 ${B.n}회: KOFR OIS ${B.ois.brier.toFixed(3)} · CD 91일 모형 ${B.cd91.brier.toFixed(3)} · 과거 빈도 ${B.base_rate.brier.toFixed(3)} · 항상 동결 ${B.always_hold.brier.toFixed(3)}.`));
      kids.push(table(["회의", "관측일", "실제", "CD 1개월 → OIS", "Δ", "인상 / 인하", "CD 91일 인상 / 인하"],
        X.rows.map((r) => [ymd(r.meeting), ymd(r.obs_date), `${actK[r.actual]}${r.move_bp ? ` ${r.move_bp > 0 ? "+" : ""}${r.move_bp}bp` : ""}`,
          `${fx(r.ois.cd_1m, 2)}% → ${fx(r.ois.ois_1m, 3)}%`, `${r.ois.delta_bp.toFixed(1)}bp`, `${pct(r.ois.p_hike)} / ${pct(r.ois.p_cut)}`,
          r.cd91 ? `${pct(r.cd91.p_hike)} / ${pct(r.cd91.p_cut)}` : "–"])),
        ...(X.second && X.second.n ? [h("h3", {}, `그다음 회의 예측 (${X.second.n}회, 같은 관측일)`),
          p(`KOFR OIS Brier ${X.second.ois.brier.toFixed(3)}(적중 ${X.second.ois.hits}/${X.second.n}) · 항상 동결 ${X.second.always_hold.brier.toFixed(3)}(적중 ${X.second.always_hold.hits}/${X.second.n})`
            + (X.second.same_as_cd91 ? ` · 같은 ${X.second.same_as_cd91.n}회 CD 91일 모형 ${X.second.same_as_cd91.cd91.toFixed(3)}` : "") + "."),
          table(["관측일", "회의", "실제", "Δ", "OIS 인상 / 인하", "CD 91일 인상 / 인하"], X.second.rows.map((r) => [ymd(r.obs_date), ymd(r.meeting),
            `${actK[r.actual]}${r.move_bp ? ` ${r.move_bp > 0 ? "+" : ""}${r.move_bp}bp` : ""}`, `${r.ois.delta_bp.toFixed(1)}bp`,
            `${pct(r.ois.p_hike)} / ${pct(r.ois.p_cut)}`, r.cd91 ? `${pct(r.cd91.p_hike)} / ${pct(r.cd91.p_cut)}` : "–"]))] : []),
        p(h("span", { class: "note" }, "표본이 작다(인상 2회·인하 4회). 같은 자료로 CD 단기물 직접 역산 방식 3개(1-2절)를 먼저 시험한 뒤 이 방식을 시험했다. 산식은 예탁원 공시 방식을 따른 것으로 결과를 보고 고르지 않았다. 2026-10-15 기본값으로 바꿨고, 회의 3영업일 전 기록 8회로 다시 판정한다(5절).")));
    }
    kids.push(h("h3", {}, "CME FedWatch 방식과의 차이"),
      table(["항목", "CME FedWatch", "BOK워치"], [
        ["입력 가격", "30일 연방기금 선물(ZQ) 체결 가격 → 그달 평균 실효금리(EFFR)", "자체 합성 KOFR OIS(금투협 CD 평가금리 − 스프레드). 거래 가격이 아니고 1bp 단위"],
        ["회의 전후 나누기", "회의 있는 달을 회의 전 N일·뒤 M일로 나눠 그달 시작·끝 금리를 역산", "1개월·3개월 OIS 기간을 회의 전·뒤 일수로 나눠 회의 뒤 기대 금리를 역산(같은 원리)"],
        ["시작점", "회의 없는 달(기준월) 선물로 앞뒤 달의 시작·끝 금리를 이어 붙임", "회의 전 구간은 '현재 기준금리 + KOFR−기준금리 차이'로 둠. 1개월물로 다음 회의, 3개월물로 그다음 회의"],
        ["회의별 확률", "Δ/25bp를 정수와 소수로 나눠 두 결과(예: 50bp 10%·75bp 90%)", "같음(Δ = 그 회의 뒤 기대 금리 − 직전 회의 뒤 기대 금리)"],
        ["정책금리와 시장금리 차이", "EFFR이 목표금리 변화에 비례해 움직인다고 가정", "KOFR − 기준금리 차이(60일 중앙값)가 일정하다고 가정"],
        ["여러 회의 누적 분포", "회의별 확률을 곱함(이진 확률 트리, 회의 사이 독립 가정)", "회의별 확률만으로는 정해지지 않아 가능 범위로 보이고, 독립 가정(FedWatch 방식) 값을 함께 보인다"],
      ]),
      p(h("span", { class: "note" }, "출처: CME Group 'Understanding the CME Group FedWatch Tool Methodology'(2025-01-23). BOK워치는 CME Group과 관계없다.")));
    return sec("1-1. 자체 산출 KOFR OIS (기본 추정치, 2026-10-15부터)", ...kids);
  }

  function cdShortSection(sec, sub, p, li, table) {
    const X = D.cdshort;
    const cur = X && X.current;
    const code = (s) => h("code", {}, s);
    const actK = { hike: "인상", hold: "동결", cut: "인하" };
    const kids = [
      p("CD 91일은 만기 안에 금통위가 둘 이상 들어가 회의 사이 배분을 가정으로 정해야 한다. 금융투자협회가 공시하는 CD 시가평가수익률(AAA, 평가사 5사 평균)의 1개월물·15일물은 만기 안 회의가 하나뿐이라 다음 회의 뒤 기대 기준금리를 바로 푼다."),
      h("ul", {},
        li(code("T × (y − s) = 회의 전 일수 × r0 + 회의 뒤 일수 × E"), " — T = 30일(1개월) 또는 15일, y = 그날 CD 금리, r0 = 현재 기준금리."),
        li("s(정상 스프레드) = 그날 이전 1년 안에서 만기 안에 회의가 없던 날의 'CD − 기준금리' 중앙값. 회의가 없으면 기준금리 변화 기대가 없으므로 그 차이는 신용·기간 웃돈만 남는다. 미래 정보는 쓰지 않는다."),
        li("Δ = E − r0를 CD 91일 모형과 같은 규칙으로 인상·동결·인하 확률로 바꾼다."),
        li("한계: 공시값이 소수 둘째 자리(버림)라 1bp 단위다. 1개월물에서 1bp는 회의 확률 약 4~5%p다. 평가사 평가금리라 체결 금리가 아니다. 공시가 18시 이후라 오전 갱신에는 전 영업일 값이 들어간다.")),
    ];
    if (cur && cur.m1) {
      const r = (x) => `${x.label} ${fx(x.rate, 2)}% − 스프레드 ${(x.spread * 100).toFixed(1)}bp(${x.spread_how}) → 회의 전 ${x.pre_days}일·뒤 ${x.post_days}일 → 기대 ${fx(x.expected, 3)}%(Δ ${x.delta_bp.toFixed(1)}bp) → ${ymd(x.meeting)} 인상 ${pct(x.p_hike)}${x.p_cut > 0 ? ` · 인하 ${pct(x.p_cut)}` : ""}`;
      kids.push(h("p", {}, h("b", {}, `현재(${ymd(cur.curve_date)} 공시값): `), r(cur.m1)), ...(cur.d15 ? [p(r(cur.d15))] : []));
    }
    if (X && X.n) {
      const S = X.summary, B = S.same_as_cd91;
      const line = (name, s) => [name, `${s.hits}/${X.n}`, s.brier.toFixed(3), ...["hike", "cut"].map((a) => `${s.by_actual[a].hits}/${s.by_actual[a].n}`),
        ...["hike", "hold", "cut"].map((a) => s.by_actual[a].p_actual == null ? "–" : pct(s.by_actual[a].p_actual))];
      kids.push(h("h3", {}, `백테스트 (${X.first} 이후 ${X.n}회, ${X.rule})`),
        table(["방식", "적중", "Brier", "인상 포착", "인하 포착", "인상 때 준 확률", "동결 때", "인하 때"],
          [line("CD 1개월", S.m1), line("CD 15일", S.d15), line("과거 결정 빈도", S.base_rate), line("항상 동결", S.always_hold)]));
      if (B) kids.push(p(`같은 회의 ${B.n}회만 비교: CD 1개월 Brier ${B.m1.brier.toFixed(3)} · CD 15일 ${B.d15.brier.toFixed(3)} · CD 91일 모형 ${B.cd91.brier.toFixed(3)} · 과거 빈도 ${B.base_rate.brier.toFixed(3)} · 항상 동결 ${B.always_hold.brier.toFixed(3)}.`));
      kids.push(table(["회의", "관측일", "실제", "CD 1개월 금리·스프레드", "1개월 인상/인하", "15일 인상/인하", "CD 91일 인상"],
        X.rows.map((r) => [ymd(r.meeting), ymd(r.obs_date), `${actK[r.actual]}${r.move_bp ? ` ${r.move_bp > 0 ? "+" : ""}${r.move_bp}bp` : ""}`,
          `${fx(r.m1.rate, 2)}% · ${r.m1.spread_bp}bp`, `${pct(r.m1.p_hike)} / ${pct(r.m1.p_cut)}`, `${pct(r.d15.p_hike)} / ${pct(r.d15.p_cut)}`,
          r.cd91 ? pct(r.cd91.p_hike) : "–"])));
      kids.push(h("h3", {}, "판정"),
        p("CD 1개월·15일 모두 '항상 동결'보다 Brier가 높다(나쁘다). 회의가 없던 기간의 'CD − 기준금리'가 −10bp~+27bp로 흔들려 25bp 결정 기대보다 크기 때문이다. 단기 CD로는 다음 회의 기대를 가려내지 못했다."),
        p("시험한 스프레드 방식(2026-10-15, 같은 28회): A 1년 중앙값(처음 정한 방식) 0.614 · B 최근 10일 중앙값 0.510 · D 7일물과 1개월물을 함께 풀어 그날 스프레드 추정 1.038. 과거 빈도 0.535, 항상 동결 0.429. B·D는 A 결과를 본 뒤 시험해 채택 근거로 쓰지 않는다. 화면 실험값은 처음 정한 A다."),
        p(h("span", { class: "note" }, "실험값이다. 화면 기본값(CD 91일 가능 범위)에 섞지 않고 날짜별 기록 비고에 남긴다. 2023-01-09 이전은 5사 평균 공시가 없어 평가하지 않았다.")));
    }
    return sec("1-2. CD 단기물(1개월·15일) 직접 역산 (실험값)", ...kids);
  }

  function decisionSection(sec, sub, p, li, table) {
    const X = D.decision;
    if (!X || !X.models) return sec("4-1. 결정 예측 모형 (실험)", p(h("span", { class: "note" }, "아직 산출 전")));
    const actK = { hike: "인상", hold: "동결", cut: "인하" };
    const names = { m1: "M1 순서형 (변수 3개)", m2: "M2 순서형 (M1 + 직전 변경 방향)", m3: "M3 다항 (M1과 같은 변수)" };
    const rows = [];
    for (const [k, m] of Object.entries(X.models)) {
      const s = m.walk_forward.summary.model, b = s.by_actual;
      rows.push([names[k] || k, `${s.hits}/${m.walk_forward.n}`, s.brier.toFixed(4), `${b.hike.hits}/${b.hike.n}`, `${b.cut.hits}/${b.cut.n}`,
        m.next ? `인상 ${pct(m.next.probs.hike)} · 동결 ${pct(m.next.probs.hold)} · 인하 ${pct(m.next.probs.cut)}` : "–"]);
    }
    const s0 = Object.values(X.models)[0].walk_forward;
    for (const [lab, key] of [["과거 결정 빈도", "base_rate"], ["항상 동결", "always_hold"]]) {
      const s = s0.summary[key], b = s.by_actual;
      rows.push([lab, `${s.hits}/${s0.n}`, s.brier.toFixed(4), `${b.hike.hits}/${b.hike.n}`, `${b.cut.hits}/${b.cut.n}`, "–"]);
    }
    const xin = X.inputs_today || {};
    return sec("4-1. 결정 예측 모형 (실험)",
      p(`가격에서 확률을 역산하는 대신, 과거 금통위 결정과 당시 자료의 관계를 학습한다. 정례회의 ${X.n_meetings}회(${ymd(X.span[0])}~${ymd(X.span[1])}, `
        + `동결 ${X.class_counts.hold}·인상 ${X.class_counts.hike}·인하 ${X.class_counts.cut})를 회의 1건 = 표본 1개로 쓴다.`),
      h("ul", {},
        li("모형: 순서형 로지스틱(인하 < 동결 < 인상), L2 규제 λ=" + X.lambda + ". 입력은 회의 3영업일 전에 알 수 있던 값만 쓴다(근원물가는 발표 시점 기준)."),
        li("M1 변수: CD 91일 − 기준금리, CD 20영업일 변화, 근원물가(식료품·에너지 제외) − 물가목표. M2는 직전 기준금리 변경 방향을 더한다(순서형). M3는 M1과 같은 변수로 인상·인하에 서로 다른 계수를 주는 다항 로지스틱이다(2026-10-15 추가). 시험한 후보는 이 셋이다."),
        li(`순차 검증: 처음 ${X.start_n}회로 학습을 시작해, 회의마다 그 이전 회의로만 다시 학습하고 다음 회의를 예측했다.`),
        li(`채택 기준: '과거 결정 빈도'보다 Brier가 5% 이상 낮고(현재 통과선 ${Object.values(X.models)[0].threshold_brier}) '항상 동결'보다도 낮을 것. 5%는 통계적 유의성이 아니라 실무상 최소 개선 기준이고, 첫 결과(2026-10-15)를 본 뒤 정했다.`),
        li("지금까지의 146회는 모형 개발·비교에 쓴 자료로 취급한다. 시험한 후보 수(현재 3개)를 기록하고, 앞으로는 바꾸지 않은 규칙으로 새 회의마다 3영업일 전 예측(data/decision_log.csv)을 쌓아 평가한다."),
        li("규제·표준화: 음의 로그우도 합계 + λ·Σβ²(절편·경계 제외). 표준화는 학습 구간 평균·표준편차로만. 물가목표는 당시 목표(2016년부터 2.0%, 그 전 범위 목표의 가운데 3.0%). 직전 변경 방향은 직전 회의 결정이 아니라 270일 안 가장 최근 실제 변경(임시회의 포함)의 방향.")),
      table(["모형", "적중", "Brier", "인상 포착", "인하 포착", `다음 회의 예측(실험)`], rows),
      h("h3", {}, "결과별 분해 ", h("small", {}, "실제 결과에 준 평균 확률 · 그 회의들의 평균 Brier(낮을수록 좋음)")),
      table(["실제 결정", ...Object.keys(X.models).map((k) => names[k] || k), "과거 결정 빈도"],
        ["hike", "hold", "cut"].map((a) => {
          const s0b = s0.summary.base_rate.by_actual[a];
          return [`${actK[a]} ${s0b.n}회`, ...Object.values(X.models).map((m) => {
            const b = m.walk_forward.summary.model.by_actual[a];
            return `${pct(b.p_actual)} · ${b.brier.toFixed(3)}`;
          }), `${pct(s0b.p_actual)} · ${s0b.brier.toFixed(3)}`];
        })),
      p(h("b", {}, "판정: "), X.verdict),
      p(h("span", { class: "note" }, `다음 회의 예측 읽는 법: 현재 입력이 과거 결정 비율(${["hike", "hold", "cut"].map((k) => `${actK[k]} ${pct(X.class_counts[k] / X.n_meetings)}`).join("·")}, ${X.n_meetings}회)보다 어느 쪽으로 기울었는지만 보여 준다. 결정 확률을 정확히 내는 능력은 검증되지 않았다. 모형별 값을 평균하거나 범위로 묶어 쓰지 않는다. 검증 성적은 회의 3영업일 전 기준이라 그 전 날짜의 예측에는 그대로 적용되지 않는다.`)),
      p(h("span", { class: "note" }, `오늘 입력: CD−기준금리 ${xin.spread_bp ?? "–"}bp · CD 20영업일 변화 ${xin.cd_chg_bp ?? "–"}bp · `
        + `근원물가−목표 ${xin.core_gap ?? "–"}%p(${xin.cpi_month || "–"}분) · 직전 변경 ${xin.last_move === 1 ? "인상" : xin.last_move === -1 ? "인하" : "없음"}`)));
  }

  // ------------------------------------------------------------ 공통 렌더
  function tabStamps() {
    const sp = (D.guidance.speeches || [])[0];
    const nw = (D.news.items || []).map((x) => x.published).sort().pop();
    return { market: D.meta.built, guidance: sp ? sp.date + "T18:00+09:00" : null, minutes: D.minutes.updated,
      news: D.reports.asof ? D.reports.asof + "T18:00+09:00" : nw, qual: D.qual && D.qual.updated, method: D.meta.built };
  }
  function renderTabs() {
    const seen = store("bokwatch.lastVisit");
    const ts = tabStamps();
    const label = { market: "확률 추정", guidance: "가이던스", minutes: "의사록", news: "보고서", qual: "정성 판단(AI)", method: "방법·검증" };
    document.querySelectorAll("#tabs button").forEach((b) => {
      const t = b.dataset.tab, iso = ts[t];
      const isNew = t !== S.tab && t !== "method" && iso && seen && iso.slice(0, 16) > seen
        || (t === "minutes" && (D.meta.new_minutes || []).length && t !== S.tab);
      b.replaceChildren(label[t] || b.textContent, ...(isNew ? [h("i", { class: "tnew", "aria-label": "새 내용" })] : []));
      b.title = !iso ? "" : t === "guidance" ? `최근 발언 ${md(iso.slice(0, 10))}` : `갱신 ${stamp(iso)} (${rel(iso)})`;
    });
    document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === S.tab));
    for (const t of TABS) $("#tab-" + t).hidden = t !== S.tab;
  }

  async function renderAll() {
    busy(true);
    try { await renderAllInner(); } finally { busy(false); }
  }
  async function renderAllInner() {
    renderTabs();
    const snap = await snapshot(S.d);
    renderHeader(snap);
    const dv = await defaultView(snap);
    renderStrip(dv.view, dv.staleFrom);
    await renderMarket(snap);
    renderGuidance();
    renderMinutes();
    renderNews();
    renderQual();
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
    watchUpdates();
    showViews();
  })();

  // 조회수(하단): 세션당 한 번만 센다. 서버 함수가 없거나 실패하면 표시하지 않는다.
  async function showViews() {
    const el = $("#views");
    if (!el || location.protocol === "file:") return;
    let counted = false;
    try { counted = sessionStorage.getItem("bokwatch.counted") === "1"; } catch (e) { /* 사생활 보호 모드 등 */ }
    try {
      const r = await fetch("api/views", { method: counted ? "GET" : "POST", cache: "no-store" });
      if (!r.ok) return;
      const v = await r.json();
      if (typeof v.total !== "number") return;
      try { sessionStorage.setItem("bokwatch.counted", "1"); } catch (e) { /* 무시 */ }
      el.textContent = `조회수 오늘 ${v.today.toLocaleString("ko-KR")} · 누적 ${v.total.toLocaleString("ko-KR")}`;
      el.hidden = false;
    } catch (e) { /* 표시 안 함 */ }
  }

  function watchUpdates() {
    const check = async () => {
      const m = await getJSON("data/meta.json");
      if (!m || !m.built || m.built === D.meta.built) return;
      const t = $("#toast");
      t.replaceChildren(h("span", {}, `새 데이터가 반영됐습니다 (${stamp(m.built)} 갱신)`),
        h("button", { type: "button", onclick: () => location.reload() }, "새로고침"),
        h("button", { type: "button", "aria-label": "닫기", onclick: () => { t.hidden = true; } }, "닫기"));
      t.hidden = false;
    };
    setInterval(check, 2 * 60e3);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
    // 지난 시간 표시를 1분마다 새로 쓴다
    setInterval(() => { const el = $("#meta .fresh"); if (el) el.replaceWith(freshPill(D.meta.built)); }, 60e3);
  }
})();
