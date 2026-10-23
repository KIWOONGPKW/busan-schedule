"""부산항 4개 터미널 선석배정 현황 조회 모듈.

각 터미널 사이트는 선명 검색 기능이 없고 '기간별 전체 목록'만 제공한다.
그래서 기간(오늘-20일 ~ 오늘+40일) 목록을 한 번 받아온 뒤, 선명/항차로 직접 찾는다.

  PNC  : POST /info/CMS/Ship/Info.pnc  -> HTML 표 (행 색상 class로 상태 구분)
  HJNC : GET  /esvc/vessel/berthScheduleT/data -> JSON (세션 쿠키 필요)
  HPNT : GET  /infoservice/vessel/vslScheduleList.jsp -> HTML 표 (POST는 400)
  BPTC : POST /Berth_status_text_servlet_sw_kr -> HTML 표 (EUC-KR)   [북항]
  HKTL : GET  custom.hktl.com/jsp/T01/sunsuk.jsp -> HTML 표 (EUC-KR, 20건 페이지) [북항]
         (자성대에서 신감만·감만1로 이전한 한국허치슨터미널)
"""
import html
import http.cookiejar
import json
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TIMEOUT = 20
DAYS_BACK, DAYS_AHEAD = 20, 40

TERMINALS = {
    "PNC": "PNC 부산신항만 (신항)",
    "HJNC": "HJNC 한진부산 (신항)",
    "HPNT": "HPNT HMM PSA (신항)",
    "BPTC": "BPTC 신선대·감만 (북항)",
    "HKTL": "HKTL 허치슨 신감만·감만1 (북항)",
}

_SSL_LOOSE = ssl.create_default_context()
_SSL_LOOSE.check_hostname = False
_SSL_LOOSE.verify_mode = ssl.CERT_NONE


def _opener(cookies=None):
    handlers = [urllib.request.HTTPSHandler(context=_SSL_LOOSE)]
    if cookies is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(cookies))
    return urllib.request.build_opener(*handlers)


def _fetch(url, data=None, headers=None, opener=None, encoding="utf-8"):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, **(headers or {})})
    with (opener or _opener()).open(req, timeout=TIMEOUT) as r:
        return r.read().decode(encoding, "replace")


def _cells(row_html, tag="td"):
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", row_html, re.I | re.S)]


def _rows(page):
    page = re.sub(r"\s+", " ", page)
    return re.findall(r"<tr([^>]*)>(.*?)</tr>", page, re.I)


def _dt(s):
    """'2026-10-23 14:00' / '2026/10/23 14:00' -> 'YYYY-MM-DD HH:MM' (없으면 '')."""
    m = re.search(r"(\d{4})[-/.](\d{2})[-/.](\d{2})\s*(\d{2}):?(\d{2})?", s or "")
    if not m:
        return ""
    y, mo, d, h, mi = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi or '00'}"


def _range():
    today = datetime.now().date()
    return today - timedelta(days=DAYS_BACK), today + timedelta(days=DAYS_AHEAD)


# ---------------------------------------------------------------- 터미널별 수집

def fetch_pnc():
    start, end = _range()
    page = _fetch("https://svc.pncport.com/info/CMS/Ship/Info.pnc?mCode=MN014", data={
        "STARTDATE": start.strftime("%Y%m%d"), "ENDDATE": end.strftime("%Y%m%d"),
        "ROUTE": "", "OPERATOR": "", "ROWCOUNT": "1000"})
    status_by_class = {"bgCol1": "출항", "bgCol2": "접안", "bgCol3": "예정"}
    out = []
    for attrs, row in _rows(page):
        c = _cells(row)
        if len(c) < 11 or not c[0].isdigit():
            continue
        cls = re.search(r"bgCol\d", attrs)
        out.append({"vessel": c[1], "voyages": [c[2], c[3]], "operator": c[4],
                    "etb": _dt(c[7]), "etd": _dt(c[8]), "berth": c[9], "yard_open": "", "yard_close": _dt(c[10]),
                    "status": status_by_class.get(cls.group() if cls else "", "예정")})
    return out


def fetch_hjnc():
    base = "https://www.hjnc.co.kr/esvc/vessel/berthScheduleT"
    op = _opener(http.cookiejar.CookieJar())
    _fetch(base, opener=op)  # 세션 쿠키 발급
    start, end = _range()
    # dateType 키가 빠지면 서버가 빈 응답을 준다
    q = urllib.parse.urlencode({"startDate": start.isoformat(), "endDate": end.isoformat(), "sort": "ETB",
                                "dateType": "", "route": "", "oper": "", "amount": "1000", "page": "1"})
    raw = _fetch(f"{base}/data?{q}", opener=op, headers={
        "Accept": "application/json", "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest", "Referer": base})
    status_map = {"done": "출항", "work": "접안", "working": "접안", "plan": "예정"}
    out = []
    for r in json.loads(json.loads(raw)["stringContent"]):
        out.append({"vessel": r.get("VSL_NM") or "", "voyages": [r.get("VOY_NO") or "", r.get("OPR_VOY") or ""],
                    "operator": r.get("PTNR_CODE") or "", "etb": _dt(r.get("ETB") or r.get("ATA")),
                    "etd": _dt(r.get("ATD")), "berth": r.get("BERTH_NO") or "",
                    "yard_open": _dt(r.get("YARD_OPEN")), "yard_close": _dt(r.get("YARD_CLOSE")),
                    "status": status_map.get(r.get("STATUS"), r.get("STATUS") or "예정")})
    return out


def fetch_hpnt():
    url = "https://www.hpnt.co.kr/infoservice/vessel/vslScheduleList.jsp"
    op = _opener(http.cookiejar.CookieJar())
    _fetch(url, opener=op)
    start, end = _range()
    q = urllib.parse.urlencode({"isSearch": "Y", "page": "1", "URI": "", "userID": "", "groupID": "U999",
                                "tmnCod": "H", "strdStDate": start.isoformat(),
                                "strdEdDate": end.isoformat(), "route": ""})
    page = _fetch(f"{url}?{q}", opener=op, headers={"Referer": url})
    status_map = {"DEPARTED": "출항", "ARRIVED": "접안", "PLANNED": "예정"}
    out = []
    for _, row in _rows(page):
        c = _cells(row)
        if len(c) < 15:
            continue
        out.append({"vessel": c[4], "voyages": [c[2], c[3]], "operator": c[1],
                    "etb": _dt(c[8]), "etd": _dt(c[9]), "berth": c[0], "yard_open": _dt(c[6]), "yard_close": _dt(c[7]),
                    "status": status_map.get(c[14].upper(), c[14] or "예정")})
    return out


def fetch_bptc():
    start, end = _range()
    page = _fetch("https://info.bptc.co.kr/Berth_status_text_servlet_sw_kr", encoding="cp949", data={
        "v_time": "term", "YEAR1": start.year, "MONTH1": f"{start.month:02d}", "DAY1": f"{start.day:02d}",
        "YEAR2": end.year, "MONTH2": f"{end.month:02d}", "DAY2": f"{end.day:02d}",
        "ROCD": "ALL", "v_oper_cd": "", "ORDER": "item2", "v_gu": "A"},
        headers={"Referer": "https://info.bptc.co.kr/content/sw/frame/berth_status_text_frame_sw_kr.jsp"})
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = []
    for _, row in _rows(page):
        c = _cells(row)
        if len(c) < 11 or not _dt(c[6]):
            continue
        ata, atc, etd = _dt(c[7]), _dt(c[8]), _dt(c[9])
        # 상태 열이 없어 입항/작업완료/출항 시각으로 추정
        status = "출항" if (atc and etd and etd <= now) else "접안" if ata and ata <= now else "예정"
        out.append({"vessel": c[3], "voyages": [c[2]], "operator": c[5],
                    "etb": ata or _dt(c[6]), "etd": etd, "berth": f"{c[0]} {c[1]}",
                    "yard_open": "", "yard_close": _dt(c[10]),
                    "status": status})
    return out


def fetch_hktl():
    # 시작일부터 약 11일치만, 20건씩 페이지로 준다 -> 10일 간격 구간 x 페이지를 돌며 모은다
    url = "https://custom.hktl.com/jsp/T01/sunsuk.jsp"
    status_by_color = {"#CCCCCC": "출항", "#FFFF99": "접안", "#CCFFFF": "예정"}
    today = datetime.now().date()
    seen, out = set(), []
    for offset in range(-10, DAYS_AHEAD, 10):
        day = today + timedelta(days=offset)
        for page_no in range(1, 20):
            q = urllib.parse.urlencode({"langType": "K", "mainType": "T01", "subType": "01", "optType": "T",
                                        "terminal": "HBCTLIB", "year": day.year, "month": f"{day.month:02d}",
                                        "day": f"{day.day:02d}", "currentPage": page_no, "startPage": 1})
            page = re.sub(r"\s+", " ", _fetch(f"{url}?{q}", encoding="cp949"))
            rows = re.findall(r'<tr bgcolor="(#\w+)"(.*?)</tr>', page, re.I)
            for color, row in rows:
                c = _cells(row)
                if len(c) < 14 or (c[0], c[4]) in seen:
                    continue
                seen.add((c[0], c[4]))
                out.append({"vessel": c[11], "voyages": [c[0], c[1].strip("/ ")], "operator": c[12],
                            "etb": _dt(c[4]), "etd": _dt(c[6]), "berth": c[2], "yard_open": "", "yard_close": _dt(c[7]),
                            "status": status_by_color.get(color.upper(), "예정")})
            if len(rows) < 20:
                break
    return out


FETCHERS = {"PNC": fetch_pnc, "HJNC": fetch_hjnc, "HPNT": fetch_hpnt, "BPTC": fetch_bptc, "HKTL": fetch_hktl}


# ---------------------------------------------------------------- 선박 매칭

def _norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def search_vessel(rows, query):
    """선명으로 찾는다. 완전 일치가 없으면 일부 일치(예: 'EMERALD' -> 'HMM EMERALD').
    같은 배가 여러 번 기항하면, 아직 출항 안 한 가장 가까운 기항 하나만 남긴다
    (전부 출항했으면 가장 최근 기항)."""
    name = _norm(query)
    if not name:
        return []
    cands = [r for r in rows if _norm(r["vessel"]) == name]
    if not cands:
        cands = [r for r in rows if name in _norm(r["vessel"])]
    cutoff = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M")
    best = {}
    for r in cands:
        key = _norm(r["vessel"])
        cur = best.get(key)
        upcoming = r["etd"] >= cutoff
        if cur is None:
            best[key] = r
        elif upcoming and (cur["etd"] < cutoff or r["etd"] < cur["etd"]):
            best[key] = r
        elif not upcoming and cur["etd"] < cutoff and r["etd"] > cur["etd"]:
            best[key] = r
    return list(best.values())


if __name__ == "__main__":
    for code, fn in FETCHERS.items():
        try:
            rows = fn()
            print(code, len(rows), rows[:1], rows[-1:] if rows else "")
        except Exception as e:  # noqa: BLE001
            print(code, "ERROR", repr(e))
