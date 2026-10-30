# BOK워치 PC 예약 갱신: 매일 오전 Windows 작업 스케줄러가 실행한다(Cloudflare 크론 대신).
# 순서: 최신 코드 받기 → 전체 갱신(run_daily.py) → data·site 변경만 커밋 → 푸시(푸시하면 사이트가 배포된다).
# 오늘 기록이 이미 있으면(GitHub 예약 실행이 먼저 돈 경우 등) run_daily.py가 건너뛰므로 AI 비용이 두 번 들지 않는다.
# 키는 저장소 루트의 .env에서 읽는다(.gitignore에 있어 커밋되지 않는다). 이 스크립트에는 키가 없다.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$logDir = Join-Path $env:LOCALAPPDATA "bokwatch"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("local_daily_{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$py = "C:\Users\kimwo\AppData\Local\Programs\Python\Python312\python.exe"
$env:PYTHONIOENCODING = "utf-8"
$env:SKIP_IF_DONE_TODAY = "1"

function Say($m) { Add-Content -Path $log -Encoding UTF8 -Value ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) }
function Keep($x) { $t = ($x | Out-String); if ($t.Trim()) { Add-Content -Path $log -Encoding UTF8 -Value $t } }

Say "시작"
Keep (git pull --rebase --autostash origin main 2>&1)
Keep (& $py run_daily.py 2>&1)
Say "run_daily.py 종료 코드 $LASTEXITCODE"

git add -A data site
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Say "변경 없음(건너뜀 또는 이미 갱신됨)"; exit 0 }
Keep (git commit -m ("daily(local): {0} KST" -f (Get-Date -Format "yyyy-MM-dd HH:mm")) 2>&1)
for ($i = 1; $i -le 4; $i++) {
    Keep (git pull --rebase --autostash origin main 2>&1)
    Keep (git push origin HEAD:main 2>&1)
    if ($LASTEXITCODE -eq 0) { Say "푸시 완료"; exit 0 }
    Start-Sleep -Seconds ([math]::Pow(2, $i))
}
Say "푸시 실패 — 로그 확인 필요"
exit 1
