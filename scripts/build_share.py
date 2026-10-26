"""공유용 HTML 만들기: 6개 터미널 일정을 지금 시점으로 모아 한 파일에 담는다.

실행: python build_share.py  ->  share/busan-vessel-schedule.html
(화주 등 내부 데이터는 넣지 않고, 터미널이 공개한 선석배정 일정만 담는다)
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import terminals

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "share" / "busan-vessel-schedule.html"


def main():
    rows, errors = [], {}

    def grab(code):
        try:
            return code, terminals.FETCHERS[code]()
        except Exception as e:  # noqa: BLE001
            errors[code] = f"{type(e).__name__}: {e}"[:160]
            return code, []

    with ThreadPoolExecutor(max_workers=6) as ex:
        for code, found in ex.map(grab, terminals.FETCHERS):
            rows += [{"t": code, **r} for r in found]

    data = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "terminals": terminals.TERMINALS, "errors": errors, "rows": rows}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (ROOT / "share_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT}  ({len(rows)}건, 실패: {list(errors) or '없음'}, {OUT.stat().st_size // 1024}KB)")

    # 로그인 없이 더블클릭으로 여는 단독 파일 (카톡·메일·USB로 전달용) -> 바탕화면에도 복사
    standalone = ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
                  '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                  + page.replace("</style>", "</style>\n</head>\n<body>", 1) + "\n</body>\n</html>\n")
    stamp = datetime.now().strftime("%m%d_%H%M")
    targets = [ROOT / "share" / "부산항_선박스케줄.html"]
    if "--no-desktop" not in sys.argv:  # 자동 갱신(publish_pages.py) 때는 바탕화면에 쌓지 않음
        targets.append(Path.home() / "Desktop" / f"부산항_선박스케줄_{stamp}.html")
    for target in targets:
        target.write_text(standalone, encoding="utf-8")
        print(target)


if __name__ == "__main__":
    main()
