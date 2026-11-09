"""헤더 환율 카드용 송금환율(보낼 때, TTS).

1순위: 하나은행 고시환율 '송금 보낼 때' 당일 1회차(최초 고시, 평일 08:2x 무렵).
  GET https://www.kebhana.com/cms/rate/wpfxd651_01i_01.do?inqKindCd=1&inqStrDt=YYYYMMDD&pbldDvCd=N
      pbldDvCd 3: 현재(날짜와 상관없이 최신 회차) / 0: 그날 최종 회차 / 1: 그날 최초 회차
      -> HTML 표. 열 순서: 통화 | 현찰 사실때(환율, Spread) | 현찰 파실때(환율, Spread) | 송금 보낼때 | 송금 받을때 | ...
      비영업일을 넣으면 직전 영업일 값이 나온다. 전일 대비는 직전 영업일 1회차와 비교.
      1회차 고시 전·주말·공휴일에는 직전 영업일 1회차를 쓴다 (카드에 "직전 영업일 기준").
  참고: 하나은행 robots.txt가 /*.do$, /*? 를 Disallow 하므로 오늘자 1회차를 받은 뒤엔 다시 부르지 않는다.

2순위(하나은행 실패 + 최근 하나은행 캐시도 없을 때): 한국수출입은행 공식 Open API(AP01, 현재환율)의 TTS.
  GET https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON?authkey=KEY&searchdate=YYYYMMDD&data=AP01
      -> JSON 배열 [{result, cur_unit, tts, ttb, deal_bas_r, ...}]
      비영업일·당일 고시 전(대략 11시 전)에는 빈 배열 -> 날짜를 거슬러 올라가 직전 영업일 값을 쓴다
  인증키는 환경변수 KEXIM_KEY (GitHub Secrets). 하루 1,000회 제한.
  영업일(월~금) 09:30~16:00 사이에만 API를 부르고, 그 밖의 시간에는 scripts/fx_cache.json을 그대로 쓴다.

3순위: 위 둘 다 없으면 ECB(유럽중앙은행) 기준환율로 대신한다 (참고용).
  GET https://api.frankfurter.dev/v1/{시작일}..?base=EUR&symbols=KRW,USD,CNY,JPY  (무료·키 없음, ECB 공개 데이터)
  ECB는 영업일 16:00 CET(한국 밤 0시 무렵) 고시 -> 원화 환산(KRW/통화) 기준환율이며 은행 송금환율(TTS)이 아니다.
"""
import http.cookiejar
import json
import os
import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from terminals import _cells, _fetch, _opener, _rows

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "fx_cache.json"
HIST = ROOT / "rates_history.json"  # 날짜별 하나은행 1회차 송금 보낼 때 (카드 날짜 조회용)
URL = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"
ECB_URL = "https://api.frankfurter.dev/v1/"
HANA_URL = "https://www.kebhana.com/cms/rate/wpfxd651_01i_01.do"
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


def _hana(day, kind="1"):
    """하나은행 고시환율 한 번 조회 -> (기준일 date, 회차 int, 고시시각 "HH:MM", {코드: 송금 보낼 때}).
    kind "1"=그날 최초(1회차), "0"=그날 최종, "3"=현재 최신. 비영업일을 넣으면 직전 영업일 값이 나온다."""
    q = urllib.parse.urlencode({"ajax": "true", "inqKindCd": "1", "inqStrDt": day.strftime("%Y%m%d"), "pbldDvCd": kind})
    page = _fetch(f"{HANA_URL}?{q}")
    m = re.search(r"기준일\s*:\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?고시일시\s*:\s*\d{4}년\s*\d{1,2}월\s*\d{1,2}일\s*"
                  r"(\d{1,2})시\s*(\d{1,2})분.*?\((\d+)회차\)", re.sub(r"<[^>]+>", " ", page), re.S)
    if not m:
        raise RuntimeError("하나은행 응답에 기준일/회차가 없어요")
    base = datetime(int(m[1]), int(m[2]), int(m[3])).date()
    by = {}
    for _, row in _rows(page):
        c = _cells(row)
        parts = c[0].split() if c else []
        if len(c) >= 6 and len(parts) >= 2:  # "미국 USD", "일본 JPY (100)" / 6번째 열 = 송금 보낼 때
            by[parts[1]] = _num(c[5])
    rates = {code: by.get(code) for code, _, _ in WANT}
    if not any(rates.values()):
        raise RuntimeError("하나은행 환율 표를 못 읽었어요")
    return base, int(m[6]), f"{int(m[4]):02d}:{int(m[5]):02d}", rates


def rates_history():
    """날짜별 1회차 송금 보낼 때 기록 {"YYYY-MM-DD": {"t": "HH:MM", "USD": .., "EUR": .., "CNY": .., "JPY": ..}}."""
    try:
        return json.loads(HIST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_history(entries):
    """entries: [(date, "HH:MM", {코드: 값})] 를 기록에 더해 날짜순으로 저장 (한 줄에 하루)."""
    hist = rates_history()
    for d, tm, rates in entries:
        if any(rates.values()):
            hist[d.isoformat()] = {"t": tm, **{k: v for k, v in rates.items() if v}}
    lines = [f' "{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in sorted(hist.items())]
    HIST.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def backfill(start):
    """start(date)부터 오늘까지 평일마다 1회차를 받아 기록에 채운다 (이미 있는 날은 건너뜀). 처음 한 번 손으로 실행."""
    import time
    have, d, got = rates_history(), start, []
    while d <= datetime.now().date():
        if d.weekday() < 5 and d.isoformat() not in have:
            try:
                bd, _, tm, rates = _hana(d)
                if bd == d:  # 공휴일이면 직전 영업일 값이 나오므로 버린다
                    got.append((bd, tm, rates))
            except Exception as e:  # noqa: BLE001
                print(d, "실패", e)
            time.sleep(0.7)
        d += timedelta(days=1)
    _save_history(got)
    return len(got)


def _hana_fresh(now):
    """now 날짜의 1회차(최초) 고시. 아직 고시 전(08:2x 전)·비영업일이면 직전 영업일 1회차.
    전일 대비는 그 직전 영업일 1회차와 비교. 받은 값은 rates_history.json에도 쌓는다."""
    d, last = now.date(), None
    for _ in range(3):  # 오늘 1회차 고시 전엔 응답이 비어 있을 수 있어 하루씩 거슬러 본다
        try:
            d0, rnd, tm, cur = _hana(d)
            break
        except RuntimeError as e:
            last, d = e, d - timedelta(days=1)
    else:
        raise last
    prev, prev_date, d, entries = {}, None, d0 - timedelta(days=1), [(d0, tm, cur)]
    for _ in range(3):
        try:
            pd, _, ptm, got = _hana(d)
        except RuntimeError:
            d -= timedelta(days=1)
            continue
        if pd < d0:
            prev, prev_date = got, pd.isoformat()
            entries.append((pd, ptm, got))
            break
        d = pd - timedelta(days=1)
    try:
        _save_history(entries)
    except Exception:  # noqa: BLE001  기록 저장 실패는 카드 표시에 영향 없게
        pass
    rates = [{"code": code, "label": label, "tts": cur.get(code),
              "diff": round(cur[code] - prev[code], 2) if cur.get(code) and prev.get(code) else None}
             for code, label, _ in WANT]
    return {"date": d0.isoformat(), "prev_date": prev_date, "source": "하나은행", "round": rnd, "time": tm,
            "rates": rates, "fetched_at": now.strftime("%Y-%m-%d %H:%M")}


def _ecb(now):
    """ECB 기준환율을 원화로 환산 (최근 고시일 + 직전 고시일 비교)."""
    start = (now.date() - timedelta(days=14)).isoformat()
    end = now.date().isoformat()
    raw = json.loads(_fetch(f"{ECB_URL}{start}..{end}?base=EUR&symbols=KRW,USD,CNY,JPY"))
    days = sorted(raw.get("rates", {}).items())
    if not days:
        raise RuntimeError("ECB 기준환율이 없어요")

    def krw(r):  # EUR 기준 표 -> 통화 1단위(JPY는 100엔)당 원화
        k = r["KRW"]
        return {"USD": k / r["USD"], "EUR": k, "CNY": k / r["CNY"], "JPY": k / r["JPY"] * 100}
    cur = krw(days[-1][1])
    prev = krw(days[-2][1]) if len(days) > 1 else {}
    rates = [{"code": code, "label": label, "tts": round(cur[code], 2),
              "diff": round(round(cur[code], 2) - round(prev[code], 2), 2) if prev else None}
             for code, label, _ in WANT]
    return {"date": days[-1][0], "prev_date": days[-2][0] if len(days) > 1 else None, "source": "ECB",
            "rates": rates, "fetched_at": now.strftime("%Y-%m-%d %H:%M")}


def fetch_fx(now=None, force=False):
    """(환율 dict 또는 None, 오류 문자열). force=True면 시간과 관계없이 now 날짜 기준으로 받아온다."""
    # Actions 수동 실행에서 고시일(FX_DATE=YYYYMMDD)을 지정하면 그날 1회차로 고정 (최신값으로 덮어쓰지 않게)
    fx_date = os.environ.get("FX_DATE", "").strip()
    if now is None and fx_date:
        now, force = datetime.strptime(fx_date, "%Y%m%d").replace(hour=23, minute=59), True
    now = now or datetime.now()
    try:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cached = None
    # 1순위 하나은행 (당일 1회차 송금 보낼 때). 1회차는 하루 한 번 고시되고 바뀌지 않으므로
    # 오늘 이미 오늘자 1회차를 받았거나(주말·공휴일엔 오늘 한 번 받았으면) 다시 부르지 않는다
    if (not force and cached and cached.get("source") == "하나은행" and cached.get("round") == 1
            and cached.get("fetched_at", "")[:10] == now.strftime("%Y-%m-%d")
            and (cached.get("date") == now.date().isoformat() or now.weekday() >= 5)):
        return cached, ""
    try:
        data = _hana_fresh(now)
        CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return data, ""
    except Exception as e:  # noqa: BLE001
        hana_err = f"하나은행 {type(e).__name__}: {e}"[:160]
    # 하나은행이 잠깐 안 될 때: 3일 안에 받은 하나은행 캐시가 있으면 그걸 그대로 쓴다
    if not force and cached and cached.get("source") == "하나은행":
        try:
            recent = now - datetime.strptime(cached.get("fetched_at", ""), "%Y-%m-%d %H:%M") <= timedelta(days=3)
        except ValueError:
            recent = False
        if recent:
            return cached, hana_err
        cached = None  # 오래된 하나은행 캐시는 버리고 아래 대체 경로로
    key = os.environ.get("KEXIM_KEY", "").strip()
    in_hours = now.weekday() < 5 and "09:30" <= now.strftime("%H:%M") <= "16:00"
    err = ""
    if key and (force or in_hours or not cached or cached.get("source") != "한국수출입은행"):
        try:
            data = _fresh(key, now)
            CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            cached = data
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:160]
    elif not key:
        err = "KEXIM_KEY 없음"
    # 수출입은행 값이 없으면(키 없음·실패) ECB 기준환율로 대신 (수출입은행 캐시가 있으면 그걸 우선)
    if not cached or cached.get("source") == "ECB":
        try:
            data = _ecb(now)
            CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            cached = data
        except Exception as e:  # noqa: BLE001
            err = " · ".join(filter(None, [err, f"ECB {type(e).__name__}: {e}"[:120]]))
    return cached, " · ".join(filter(None, [hana_err, err]))


if __name__ == "__main__":
    # 날짜 지정 수동 실행: python scripts/fx.py 20261106  (그날 1회차 + 직전 영업일 1회차와 비교)
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--backfill":  # python scripts/fx.py --backfill 20260101
        print(backfill(datetime.strptime(sys.argv[2], "%Y%m%d").date()), "일 추가")
        sys.exit()
    at = datetime.strptime(sys.argv[1], "%Y%m%d").replace(hour=23, minute=59) if len(sys.argv) > 1 else None
    print(json.dumps(fetch_fx(at, force=bool(at)), ensure_ascii=False, indent=1))
