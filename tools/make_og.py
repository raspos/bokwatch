"""공유 미리보기 썸네일(site/og.png, 1200×630) 생성. 로고(site/logo.svg)와 같은 계기판 모양을 그린다.

  python tools/make_og.py

글꼴은 Windows 맑은 고딕을 쓴다. 숫자는 매일 바뀌므로 넣지 않는다.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "og.png"
FONT_B, FONT_R = "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"
NAVY, TRACK, ORANGE, WHITE, MUTED = "#1d2a44", "#3b4a68", "#ec6a2e", "#ffffff", "#aab4c6"


def main() -> None:
    W, H, S = 1200, 630, 2  # 2배로 그려 줄여서 가장자리를 부드럽게
    img = Image.new("RGB", (W * S, H * S), NAVY)
    d = ImageDraw.Draw(img)
    # 계기판: 중심 (250, 360), 반지름 150
    cx, cy, r, w = 250 * S, 360 * S, 150 * S, 30 * S
    box = [cx - r, cy - r, cx + r, cy + r]
    d.arc(box, 180, 360, fill=TRACK, width=w)
    d.arc(box, 180, 306, fill=ORANGE, width=w)  # 70% 지점
    for ang in (180, 306):  # 둥근 끝
        x = cx + (r - w / 2) * math.cos(math.radians(ang))
        y = cy + (r - w / 2) * math.sin(math.radians(ang))
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=ORANGE if ang in (180, 306) else TRACK)
    x2 = cx + (r - w / 2) * math.cos(math.radians(360))
    y2 = cy + (r - w / 2) * math.sin(math.radians(360))
    d.ellipse([x2 - w / 2, y2 - w / 2, x2 + w / 2, y2 + w / 2], fill=TRACK)
    # 바늘과 축
    nx = cx + 112 * S * math.cos(math.radians(306))
    ny = cy + 112 * S * math.sin(math.radians(306))
    d.line([cx, cy, nx, ny], fill=WHITE, width=16 * S)
    d.ellipse([nx - 8 * S, ny - 8 * S, nx + 8 * S, ny + 8 * S], fill=WHITE)
    d.ellipse([cx - 20 * S, cy - 20 * S, cx + 20 * S, cy + 20 * S], fill=WHITE)
    d.rounded_rectangle([cx - 124 * S, cy + 46 * S, cx + 124 * S, cy + 60 * S], radius=8 * S, fill=TRACK)
    # 글자
    title = ImageFont.truetype(FONT_B, 112 * S)
    sub = ImageFont.truetype(FONT_R, 38 * S)
    small = ImageFont.truetype(FONT_R, 28 * S)
    tx = 470 * S
    d.text((tx, 180 * S), "BOK워치", font=title, fill=WHITE)
    d.text((tx, 330 * S), "한국은행 금통위 금리 결정 모니터", font=sub, fill=WHITE)
    d.text((tx, 392 * S), "모형 추정 확률 · 총재 발언 · 의사록 · 전문가 전망", font=small, fill=MUTED)
    d.text((tx, 438 * S), "매일 오전 10시 갱신", font=small, fill=ORANGE)
    img.resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
