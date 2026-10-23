// BOK워치 일일 갱신 트리거(Cloudflare Workers 크론).
// GitHub 예약 실행이 매일 4시간 넘게 늦어져(14:20 KST 전후 시작) 이 워커가 daily 워크플로를 직접 호출한다.
// 필요한 비밀 값: GITHUB_TOKEN (세분화된 토큰, 저장소 raspos/bokwatch, 권한 Actions: Read and write). 코드·저장소에 쓰지 않는다.
const REPO = "raspos/bokwatch";
const WORKFLOW = "daily.yml";

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },
  // 외부에서 호출해 갱신을 일으키지 못하도록 요청에는 응답하지 않는다.
  async fetch() {
    return new Response("scheduled only", { status: 404 });
  },
};

async function dispatch(env) {
  if (!env.GITHUB_TOKEN) throw new Error("GITHUB_TOKEN 비밀 값이 없다");
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "bokwatch-cron",
    },
    // 오늘 기록이 이미 있으면 갱신을 건너뛴다(두 번째 호출·GitHub 예약 실행과 겹쳐도 AI 비용이 두 배가 되지 않는다)
    body: JSON.stringify({ ref: "main", inputs: { skip_if_done: "true" } }),
  });
  if (r.status !== 204) throw new Error(`daily 호출 실패 ${r.status} ${await r.text()}`);
}
