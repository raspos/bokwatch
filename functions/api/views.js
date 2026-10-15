// 조회수 카운터(Cloudflare Pages Functions + KV). Pages 프로젝트 설정에서 KV 네임스페이스를 변수 이름 VIEWS로 연결해야 동작한다.
// GET  /api/views → {total, today}
// POST /api/views → 1 올린 뒤 {total, today}. 같은 브라우저 세션에서는 화면이 한 번만 POST 한다.
// KV는 원자적 증가가 아니라 동시에 들어온 요청은 일부 빠질 수 있다(대략치).
const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});

export async function onRequest({ request, env }) {
  if (!env.VIEWS) return json({ error: "VIEWS 연결 없음" }, 503);
  if (!["GET", "POST"].includes(request.method)) return json({ error: "method" }, 405);
  const today = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10); // KST 날짜
  const dayKey = `d:${today}`;
  let [total, day] = await Promise.all([env.VIEWS.get("total"), env.VIEWS.get(dayKey)]);
  total = parseInt(total || "0", 10);
  day = parseInt(day || "0", 10);
  if (request.method === "POST") {
    total += 1;
    day += 1;
    await Promise.all([
      env.VIEWS.put("total", String(total)),
      env.VIEWS.put(dayKey, String(day), { expirationTtl: 60 * 60 * 24 * 40 }),
    ]);
  }
  return json({ total, today: day });
}
