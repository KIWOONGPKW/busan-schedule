"""헤더 환율 카드용 송금환율(보낼 때, TTS).

하나은행 고시환율 페이지는 robots.txt(Disallow: /*.do$, /*?)로 자동 수집을 막고 있어
한국수출입은행 공식 Open API(AP01, 현재환율)의 TTS로 대신한다. 출처는 "한국수출입은행 기준".

  GET https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON?authkey=KEY&searchdate=YYYYMMDD&data=AP01
      -> JSON 배열 [{result, cur_unit, tts, ttb, deal_bas_r, ...}]
      비영업일·당일 고시 전(대략 11시 전)에는 빈 배열 -> 날짜를 거슬러 올라가 직전 영업일 값을 쓴다
  인증키는 환경변수 KEXIM_KEY (GitHub Secrets). 하루 1,000회 제한.

갱신: 영업일(월~금) 09:30~16:00 사이에만 API를 부르고, 그 밖의 시간이나 키가 없을 때는
scripts/fx_cache.json(마지막으로 받은 값)을 그대로 쓴다.
"""
import http.cookiejar
import json
import os
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from terminals import _fetch, _opener

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "fx_cache.json"
URL = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"
WANT = [("USD", "USD", ["USD"]), ("EUR", "EUR", ["EUR"]),
        ("CNY", "CNY", ["CNH", "CNY"]), ("JPY", "JPY(100엔)", ["JPY(100)"])]


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def _day(key, day):
    q = urllib.parse.urlencode({"authkey": key, "searchdate": day.strftime("%Y%m%d"), "data": "AP01"})
    # 수출입은행 서버가 쿠키 없으면 리다이렉트를 반복하는 경우가 있어 쿠키를 받는다
    raw = _fetch(f"{URL}?{q}", opener=_opener(http.cookiejar.CookieJar()))
    rows = json.loads(raw or "[]")
    if rows and rows[0].get("result") not in (1, "1"):
        raise RuntimeError(f"수출입은행 API result={rows[0].get('result')} (2:코드오류 3:인증키 오류 4:일일 제한)")
    by = {r.get("cur_unit"): _num(r.get("tts")) for r in rows}
    return {code: next((by[u] for u in units if by.get(u)), None) for code, _, units in WANT} if rows else None


def _fresh(key, now):
    days, d = [], now.date()
    for _ in range(14):  # 연휴가 길어도 직전 두 영업일은 나온다
        got = _day(key, d)
        if got and any(got.values()):
            days.append((d, got))
            if len(days) == 2:
                break
        d -= timedelta(days=1)
    if not days:
        raise RuntimeError("최근 14일 고시 환율이 없어요")
    (d0, cur), prev = days[0], (days[1][1] if len(days) > 1 else {})
    prev_date = days[1][0].isoformat() if len(days) > 1 else None
    rates = [{"code": code, "label": label, "tts": cur.get(code),
              "diff": round(cur[code] - prev[code], 2) if cur.get(code) and prev.get(code) else None}
             for code, label, _ in WANT]
    return {"date": d0.isoformat(), "prev_date": prev_date, "source": "한국수출입은행", "rates": rates,
            "fetched_at": now.strftime("%Y-%m-%d %H:%M")}


def fetch_fx(now=None, force=False):
    """(환율 dict 또는 None, 오류 문자열). force=True면 시간과 관계없이 now 날짜 기준으로 받아온다."""
    now = now or datetime.now()
    try:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cached = None
    key = os.environ.get("KEXIM_KEY", "").strip()
    in_hours = now.weekday() < 5 and "09:30" <= now.strftime("%H:%M") <= "16:00"
    err = ""
    if key and (force or in_hours or not cached):
        try:
            data = _fresh(key, now)
            CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            cached = data
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:160]
    elif not key:
        err = "KEXIM_KEY 없음"
    return cached, err


if __name__ == "__main__":
    # 날짜 지정 수동 실행: KEXIM_KEY=... python scripts/fx.py 20261106  (그날 고시 + 직전 영업일과 비교)
    import sys
    at = datetime.strptime(sys.argv[1], "%Y%m%d").replace(hour=23, minute=59) if len(sys.argv) > 1 else None
    print(json.dumps(fetch_fx(at, force=bool(at)), ensure_ascii=False, indent=1))
