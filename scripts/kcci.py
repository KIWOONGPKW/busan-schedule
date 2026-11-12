"""하단 '운임 추이' 그래프용 (미주 서안·동안, 중동, 지중해) KCCI 주간 운임 (부산항 선적, USD/FEU, 40ft Dry, 부대 Surcharge 포함).

출처: 한국해양진흥공사 KCCI (KOBC Container Composite Index) 공개 시계열 화면
  POST https://www.kobc.or.kr/ebz/shippinginfo/timeseries/gridList.do?mId=0304000000
       sDay=YYYY-MM-DD&eDay=YYYY-MM-DD  -> 표: 날짜 | KCCI | KUWI | KUEI | KNEI | KMDI | KMEI | ...
  robots.txt: 일반 수집기는 제한 없음 (Googlebot만 검색·게시판 제외)
항로 정의 (KCCI 표준기술서 /ebz/common/file/KCCI_Standards.pdf):
  KMEI 중동  = 부산 → 제벨알리, 담만, 제다
  KMDI 지중해 = 부산 → 발렌시아, 바르셀로나, 제노아, 나폴리 (이집트 항구 아님)
  KUWI 미주서안 · KUEI 미주동안 = 부산 → 미국 서안 · 동안 (표의 KUWI·KUEI 열)
매주 월요일 14시(한국 시간) 발표 -> 월요일 14시가 지나고 캐시에 그 주 값이 없을 때만 받는다
(공휴일이면 화요일에 나오기도 해서 새 주 값이 보일 때까지 1시간 간격으로 다시 시도). 그 밖에는 scripts/kcci_cache.json.
Actions(update.yml)는 TZ=Asia/Seoul이라 datetime.now()가 한국 시간.
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from terminals import _cells, _fetch, _rows

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "kcci_cache.json"
URL = "https://www.kobc.or.kr/ebz/shippinginfo/timeseries/gridList.do?mId=0304000000"
START = "2026-01-01"
WANT = {"KUWI": "미주서안", "KUEI": "미주동안", "KMEI": "중동", "KMDI": "지중해"}
RETRY = timedelta(hours=1)


def _last_release(now):
    """now 이전 가장 최근의 '월요일 14:00' (한국 시간)."""
    monday = (now - timedelta(days=now.weekday())).replace(hour=14, minute=0, second=0, microsecond=0)
    return monday if now >= monday else monday - timedelta(days=7)


def _download(now):
    page = _fetch(URL, data={"page": "1", "sDay": START, "eDay": now.date().isoformat()})
    head = None
    weeks = []
    for _, tr in _rows(page):
        th = _cells(tr, "th")
        if "KMEI" in th:
            head = th
            continue
        td = _cells(tr)
        if head and td and re.fullmatch(r"\d{4}-\d{2}-\d{2}", td[0]):
            # td: 날짜, KCCI, 그 뒤로 head 순서의 항로
            vals = dict(zip(head, td[2:]))
            row = {"date": td[0]}
            for code in WANT:
                try:
                    row[code] = int(vals[code].replace(",", ""))
                except (KeyError, ValueError):
                    row[code] = None
            weeks.append(row)
    weeks = sorted({w["date"]: w for w in weeks if w["date"] >= START}.values(), key=lambda w: w["date"])
    if len(weeks) < 4:
        raise RuntimeError(f"KCCI 시계열을 읽지 못했어요 ({len(weeks)}주)")
    return {"source": "한국해양진흥공사 KCCI", "url": URL, "unit": "USD/FEU",
            "routes": WANT, "weeks": weeks, "fetched_at": now.strftime("%Y-%m-%d %H:%M")}


def fetch_kcci(now=None, force=False):
    """(data, error) — 실패하면 캐시 값과 오류 문구. force=True면 일정과 상관없이 새로 받음."""
    now = now or datetime.now()
    cached = None
    if CACHE.exists() and not force:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        at = datetime.strptime(cached.get("fetched_at", "2000-01-01 00:00"), "%Y-%m-%d %H:%M")
        newest = (cached.get("weeks") or [{}])[-1].get("date", "")
        due = _last_release(now)
        # 이번 발표(월요일 날짜 이후) 값이 이미 있거나, 방금(1시간 안) 시도했으면 캐시 그대로
        # (항로를 새로 추가해 캐시에 그 열이 없으면 바로 다시 받음)
        complete = all(k in (cached.get("weeks") or [{}])[-1] for k in WANT)
        if complete and (newest >= due.date().isoformat() or now - at < RETRY):
            return cached, ""
    try:
        data = _download(now)
    except Exception as e:  # noqa: BLE001
        return cached, f"KCCI 조회 실패: {e}"[:160]
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data, ""


if __name__ == "__main__":
    d, err = fetch_kcci(force=True)  # 손으로 실행하면 바로 새로 받음
    print(err or f"{len(d['weeks'])}주, {d['weeks'][0]['date']} ~ {d['weeks'][-1]['date']}, 최근 {d['weeks'][-1]}")
