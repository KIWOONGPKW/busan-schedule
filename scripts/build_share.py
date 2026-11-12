"""공유용 HTML 만들기: 터미널 일정을 지금 시점으로 모아 한 파일에 담는다.

실행: python build_share.py  ->  share/busan-vessel-schedule.html
(화주 등 내부 데이터는 넣지 않고, 터미널이 공개한 선석배정 일정만 담는다)
"""
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import empties
import fx
import incheon
import kcci
import news
import terminals

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "share" / "busan-vessel-schedule.html"


# 부산 8개 + 인천 4개 터미널을 한 목록으로 (화면 검색·필터·요약이 그대로 함께 동작)
FETCHERS = {**terminals.FETCHERS, **incheon.FETCHERS}
TERMINALS = {**terminals.TERMINALS, **incheon.TERMINALS}


def main():
    rows, errors = [], {}

    def grab(code):
        try:
            return code, FETCHERS[code]()
        except Exception as e:  # noqa: BLE001
            errors[code] = f"{type(e).__name__}: {e}"[:160]
            return code, []

    with ThreadPoolExecutor(max_workers=len(FETCHERS)) as ex:
        for code, found in ex.map(grab, FETCHERS):
            rows += [{"t": code, **r} for r in found]

    try:  # 뉴스가 막혀도 스케줄은 나가야 한다
        articles, news_errors = news.fetch_news()
    except Exception as e:  # noqa: BLE001
        articles, news_errors = [], {"쉬핑가제트": str(e), "부산항만공사": str(e)}

    try:  # 공컨 현황이 막혀도 스케줄은 나가야 한다
        yards, empty_errors = empties.fetch_empties({r["operator"] for r in rows if r["t"] == "HJNC" and r["operator"]})
    except Exception as e:  # noqa: BLE001
        yards, empty_errors = [], {k: str(e)[:160] for k in ("HJNC", "BPTC", "HJIT", "E1CT")}

    def load(name, key):  # 사용자가 고치는 표: 잘못 고쳐도 페이지는 나가야 한다
        try:
            return json.loads((ROOT / name).read_text(encoding="utf-8"))[key], ""
        except Exception as e:  # noqa: BLE001
            return ({} if key == "routes" else []), f"{name} 읽기 실패: {e}"[:160]

    transit, transit_err = load("transit_times.json", "ports")
    routes, routes_err = load("routes.json", "routes")
    carriers, cc_err = load("carrier_codes.json", "carriers")
    if cc_err:
        carriers = {}
    regions, rg_err = load("regions.json", "regions")
    if rg_err:
        regions = {}
    try:
        cities = {k: v for k, v in json.loads((ROOT / "city_ports.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    except Exception:  # noqa: BLE001
        cities = {}
    port_carriers, pc_err = load("port_carriers.json", "ports")
    if pc_err:
        port_carriers = {}
    # 선명 → IMO(7자리)/MMSI(9자리). 사용자가 직접 넣는 간단한 표 (VesselFinder는 링크만, 긁어 오지 않음)
    vessel_ids, vessels_err = {}, ""
    try:
        raw = json.loads((ROOT / "vessels_imo.json").read_text(encoding="utf-8"))
        for name, num in raw.items():
            num = str(num).strip()
            if name.startswith("_") or not num.isdigit():
                continue
            if len(num) == 7:
                vessel_ids[name] = {"imo": num}
            elif len(num) == 9:
                vessel_ids[name] = {"mmsi": num}
    except Exception as e:  # noqa: BLE001
        vessels_err = f"vessels_imo.json 읽기 실패: {e}"[:160]

    try:
        fx_data, fx_err = fx.fetch_fx()
    except Exception as e:  # noqa: BLE001
        fx_data, fx_err = None, str(e)[:160]

    try:
        kcci_data, kcci_err = kcci.fetch_kcci()
    except Exception as e:  # noqa: BLE001
        kcci_data, kcci_err = None, str(e)[:160]

    proxy_routes, proxy_err = [], ""
    try:  # KCCI 미발표 항구 -> 가까운 KCCI 항로 연결표 (사용자 편집)
        raw = json.loads((ROOT / "proxy_routes.json").read_text(encoding="utf-8"))
        for p in raw.get("ports", []):
            if p.get("port") and p.get("route") in kcci.WANT:
                proxy_routes.append({k: p.get(k, "") for k in ("port", "group", "route", "note")})
            else:
                proxy_err = f"proxy_routes.json: {p.get('port') or '?'} 항로 코드 확인 필요 ({'·'.join(kcci.WANT)}만 가능)"
    except Exception as e:  # noqa: BLE001
        proxy_err = f"proxy_routes.json 읽기 실패: {e}"[:160]

    try:  # 인천발 목적지 검색 표 (사용자 편집)
        incheon_dest = json.loads((ROOT / "incheon_transit_times.json").read_text(encoding="utf-8"))
        incheon_dest.pop("_안내", None)
        incheon_dest_err = ""
    except Exception as e:  # noqa: BLE001
        incheon_dest, incheon_dest_err = {}, f"incheon_transit_times.json 읽기 실패: {e}"[:160]

    data = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "transit": transit, "routes": routes, "port_carriers": port_carriers, "carriers": carriers, "regions": regions, "cities": cities,
            "ports_v": hashlib.md5((ROOT.parent / "ports.json").read_bytes()).hexdigest()[:10] if (ROOT.parent / "ports.json").exists() else "",
            "dest_error": " · ".join(filter(None, [transit_err, routes_err, pc_err, cc_err, rg_err])),
            "vessel_ids": vessel_ids, "vessel_error": vessels_err,
            "terminals": TERMINALS, "incheon": list(incheon.TERMINALS),
            "incheon_dest": incheon_dest, "incheon_dest_error": incheon_dest_err, "errors": errors, "rows": rows,
            "news": articles, "news_error": ", ".join(news_errors),
            "empties": yards, "empty_error": ", ".join(empty_errors),
            "fx": fx_data, "fx_error": fx_err, "fx_hist": fx.rates_history(), "kcci": kcci_data, "kcci_error": kcci_err, "proxy_routes": proxy_routes, "proxy_error": proxy_err}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (ROOT / "share_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT}  ({len(rows)}건, 뉴스 {len(articles)}건, "
          f"실패: {list(errors) or '없음'}, {OUT.stat().st_size // 1024}KB)")

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
