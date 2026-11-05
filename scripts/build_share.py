"""공유용 HTML 만들기: 터미널 일정을 지금 시점으로 모아 한 파일에 담는다.

실행: python build_share.py  ->  share/busan-vessel-schedule.html
(화주 등 내부 데이터는 넣지 않고, 터미널이 공개한 선석배정 일정만 담는다)
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import empties
import news
import terminals
import tracking

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

    with ThreadPoolExecutor(max_workers=len(terminals.FETCHERS)) as ex:
        for code, found in ex.map(grab, terminals.FETCHERS):
            rows += [{"t": code, **r} for r in found]

    try:  # 뉴스가 막혀도 스케줄은 나가야 한다
        articles, news_errors = news.fetch_news()
    except Exception as e:  # noqa: BLE001
        articles, news_errors = [], {"쉬핑가제트": str(e), "부산항만공사": str(e)}

    try:  # 컨테이너 조회가 막혀도 스케줄은 나가야 한다
        tracked, track_errors = tracking.track(rows)
    except Exception as e:  # noqa: BLE001
        tracked, track_errors = [], {"추적": str(e)[:160]}

    try:  # 공컨 현황이 막혀도 스케줄은 나가야 한다
        yards, empty_errors = empties.fetch_empties({r["operator"] for r in rows if r["t"] == "HJNC" and r["operator"]})
    except Exception as e:  # noqa: BLE001
        yards, empty_errors = [], {"HJNC": str(e)[:160], "BPTC": str(e)[:160]}

    def load(name, key):  # 사용자가 고치는 표: 잘못 고쳐도 페이지는 나가야 한다
        try:
            return json.loads((ROOT / name).read_text(encoding="utf-8"))[key], ""
        except Exception as e:  # noqa: BLE001
            return ({} if key == "routes" else []), f"{name} 읽기 실패: {e}"[:160]

    transit, transit_err = load("transit_times.json", "ports")
    routes, routes_err = load("routes.json", "routes")
    vessel_ids, vessels_err = load("vessels.json", "vessels")
    if vessels_err:
        vessel_ids = {}

    data = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "transit": transit, "routes": routes, "dest_error": " · ".join(filter(None, [transit_err, routes_err])),
            "vessel_ids": vessel_ids, "vessel_error": vessels_err,
            "terminals": terminals.TERMINALS, "errors": errors, "rows": rows,
            "news": articles, "news_error": ", ".join(news_errors),
            "tracking": tracked, "track_terminals": [t for t in tracking.SUPPORTED if t not in track_errors], "track_error": ", ".join(track_errors),
            "empties": yards, "empty_error": ", ".join(empty_errors)}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (ROOT / "share_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT}  ({len(rows)}건, 뉴스 {len(articles)}건, 컨테이너 {len(tracked)}개, "
          f"실패: {list(errors) + list(track_errors) or '없음'}, {OUT.stat().st_size // 1024}KB)")

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
