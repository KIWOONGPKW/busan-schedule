"""인천항 4개 컨테이너 터미널 선석배정 현황 조회 모듈 (부산 terminals.py와 같은 행 모양).

  SNCT : GET  snct.sun-kwang.co.kr/infoservice/webpage/vessel/vslScheduleText.jsp -> HTML 표 (EUC-KR) [인천신항]
         행 class: row-d 출항 · row-b 접안 · 없음 예정, 괄호 친 시각은 예정
  HJIT : POST esvc2.hjit.co.kr/HJIT/berth/vesselSchedule -> JSON (세션 쿠키 + CSRF, 부산 DGT와 같은 시스템) [인천신항]
         반입 마감 시각은 공개 안 함 -> ableGateIn(Y/N)을 gate_in으로 넘김
  ICT  : GET  service.psa-ict.co.kr/vessel/schedule -> Next.js 페이지에 실린 JSON [인천남항]
         사이트가 어제~7일 뒤만 보여 줘서 그 범위만 나옴 (기간 지정 불가)
  E1CT : POST www.e1ct.co.kr/info/terminal/berthText -> HTML 표 (CSRF, 50건씩 페이지) [인천남항]
         괄호 친 시각은 예정

장치장 코드(출처: forwarder.kr 터미널 표)는 화면(share_template.html BOND)에 있음.
경인항 HSIT(SM상선 경인터미널, 02006024)는 공개 선석 일정이 없어 넣지 않음.
"""
import html
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime

from terminals import TIMEOUT, UA, _dt, _fetch, _opener, _range

TERMINALS = {
    "SNCT": "SNCT 선광신컨테이너터미널 (인천신항)",
    "HJIT": "HJIT 한진인천컨테이너터미널 (인천신항)",
    "ICT": "ICT PSA 인천컨테이너터미널 (인천남항)",
    "E1CT": "E1CT E1컨테이너터미널 (인천남항)",
}


def _parts(cell_html):
    """<br>로 나뉜 칸 -> ['윗줄', '아랫줄'] (태그·&nbsp; 정리)."""
    out = []
    for p in re.split(r"<br\s*/?>", cell_html, flags=re.I):
        t = html.unescape(re.sub(r"<[^>]+>", "", p)).replace("\xa0", " ").strip()
        out.append(re.sub(r"\s+", " ", t))
    return out


def _planned(s):
    """'(2026-11-13 14:00)' -> ('2026-11-13 14:00', True) / 괄호 없으면 실제 시각."""
    return _dt(s), "(" in (s or "")


def _status(etb_actual, etd_actual, etd):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if etd_actual and etd and etd <= now:
        return "출항"
    return "접안" if etb_actual else "예정"


def fetch_snct():
    url = "http://snct.sun-kwang.co.kr/infoservice/webpage/vessel/vslScheduleText.jsp"
    start, end = _range()
    q = urllib.parse.urlencode({"isSearch": "Y", "page": "1", "strdStDate": start.isoformat(),
                                "strdEdDate": end.isoformat(), "ROUTE": "*"})
    page = re.sub(r"\s+", " ", _fetch(f"{url}?{q}", encoding="cp949"))
    status_by_class = {"row-d": "출항", "row-b": "접안"}
    out = []
    for cls, row in re.findall(r'<tr class="([^"]*)"[^>]*>(.*?)</tr>', page, re.I):
        c = [_parts(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.I)]
        # NO | 선석 | 모선항차/선사항차 | 년도 | 항로 | 선명/Bitt | 접안 | 반입시작 | 반입마감 | 출항 | 선사 | 양하 | 적하 | Shift
        if len(c) < 14 or not _dt(c[6][0]):
            continue
        out.append({"vessel": c[5][0], "voyages": [f"{c[2][0]}/{c[3][0]}", c[2][1] if len(c[2]) > 1 else ""],
                    "operator": c[10][0], "etb": _dt(c[6][0]), "etd": _dt(c[9][0]), "berth": c[1][0],
                    "yard_open": _dt(c[7][0]), "yard_close": _dt(c[8][0]), "route": c[4][0],
                    "status": status_by_class.get(cls.strip(), "예정")})
    return out


def fetch_hjit():
    base = "https://esvc2.hjit.co.kr/HJIT"
    op = _opener(http.cookiejar.CookieJar())
    page = _fetch(f"{base}/esvc/vessel/berthScheduleT", opener=op)  # 세션 쿠키 + CSRF 토큰
    token = re.search(r'name="_csrf" content="([^"]+)"', page).group(1)
    header = re.search(r'name="_csrf_header" content="([^"]+)"', page).group(1)
    start, end = _range()
    body = json.dumps({"fromDate": start.strftime("%Y%m%d"), "toDate": end.strftime("%Y%m%d"),
                       "vessel": "", "voyage": ""}).encode()
    req = urllib.request.Request(f"{base}/berth/vesselSchedule", data=body, headers={
        "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/esvc/vessel/berthScheduleT", header: token})
    with op.open(req, timeout=TIMEOUT) as r:
        rows = json.loads(r.read().decode("utf-8", "replace"))["vesselSchedules"]
    status_map = {"DEPARTURED": "출항", "DEPARTED": "출항", "WORKING": "접안", "ARRIVED": "접안", "PLANNED": "예정"}
    out = []
    for r in rows:
        out.append({"vessel": r.get("vesselName") or "",
                    "voyages": [f"{r.get('vesselCode')}-{r.get('voyageSeq')}/{r.get('voyageYear')}",
                                "/".join(dict.fromkeys(v for v in (r.get("inVoyage"), r.get("outVoyage")) if v))],
                    "operator": r.get("carrier") or r.get("operator") or "", "etb": _dt(r.get("atb") or r.get("etb")),
                    "etd": _dt(r.get("atd") or r.get("etd")), "berth": f"{r.get('berthNo') or ''}",
                    "yard_open": "", "yard_close": _dt(r.get("cctDate")), "gate_in": r.get("ableGateIn") or "",
                    "route": r.get("serviceLane") or "",
                    "status": status_map.get((r.get("status") or "").upper(), r.get("status") or "예정")})
    return out


def fetch_ict():
    page = _fetch("https://service.psa-ict.co.kr/vessel/schedule")
    # Next.js(App Router)가 self.__next_f.push([1,"..."]) 조각으로 데이터를 싣는다
    payload = "".join(json.loads(c) for c in re.findall(r'self\.__next_f\.push\(\[1,(".*?")\]\)', page, re.S))
    status_map = {"D": "출항", "B": "접안", "W": "접안", "A": "접안", "P": "예정"}
    seen, out = set(), []
    for m in re.finditer(r'\{"vslvvd":', payload):
        obj, _ = json.JSONDecoder().raw_decode(payload, m.start())
        key = obj.get("vslvvd")
        if not obj.get("vslName") or key in seen:
            continue
        seen.add(key)
        out.append({"vessel": obj["vslName"],
                    "voyages": [key or "", "/".join(dict.fromkeys(v for v in (obj.get("operVslvvdIn"), obj.get("operVslvvdOut")) if v))],
                    "operator": obj.get("operator") or obj.get("operVsl") or "",
                    "etb": _dt(obj.get("atbDate") or obj.get("etbDate")), "etd": _dt(obj.get("atdDate") or obj.get("etdDate")),
                    "berth": obj.get("berthNo") or "", "yard_open": "", "yard_close": _dt(obj.get("cutOffDate")),
                    "route": obj.get("outService") or obj.get("inService") or "",
                    "status": status_map.get((obj.get("vslState") or "").upper(), "예정")})
    if not out:
        raise RuntimeError("일정 데이터를 찾지 못함 (페이지 구조 변경?)")
    return out


def fetch_e1ct():
    url = "https://www.e1ct.co.kr/info/terminal/berthText"
    op = _opener(http.cookiejar.CookieJar())
    token = re.search(r'name="_csrf" value="([^"]+)"', _fetch(url, opener=op)).group(1)
    start, end = _range()
    out, page_no, total, size = [], 0, None, 50
    while total is None or page_no * size < total:
        page = _fetch(url, opener=op, headers={"Referer": url}, data={
            "_csrf": token, "searchStartDt": start.strftime("%Y%m%d"), "searchEndDt": end.strftime("%Y%m%d"),
            "number": str(page_no)})
        # paging("#paging", 전체 건수, 페이지당 건수, 페이지 번호, 폼)
        m = re.search(r'paging\(\s*"#paging",\s*(\d+),\s*(\d+)', page)
        total, size = (int(m.group(1)), int(m.group(2)) or 50) if m else (0, 50)
        body = re.sub(r"\s+", " ", page.split("<tbody>", 1)[-1].split("</tbody>", 1)[0])
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.I):
            # 닫는 </td>가 빠진 칸이 있어 <td 기준으로 자른다
            c = [_parts(x.split(">", 1)[-1].split("</td>")[0]) for x in re.split(r"<td", row, flags=re.I)[1:]]
            # No | 선석 | 모선항차/선사항차 | 연도 | 선명/Bitt | 접안 | 반입마감(작업완료) | 출항 | 선사 | 양하 | 적하 | Shift
            if len(c) < 9:
                continue
            etb, etb_plan = _planned(c[5][0])
            etd, etd_plan = _planned(c[7][0])
            if not etb and not etd:
                continue
            out.append({"vessel": c[4][0], "voyages": [f"{c[2][0].replace(' ', '')}/{c[3][0]}", c[2][1] if len(c[2]) > 1 else ""],
                        "operator": c[8][0], "etb": etb, "etd": etd, "berth": c[1][0],
                        "yard_open": "", "yard_close": _dt(c[6][0]), "route": "",
                        "status": _status(not etb_plan, not etd_plan, etd)})
        page_no += 1
        if page_no > 20:
            break
    return out


FETCHERS = {"SNCT": fetch_snct, "HJIT": fetch_hjit, "ICT": fetch_ict, "E1CT": fetch_e1ct}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for code, fn in FETCHERS.items():
        try:
            rows = fn()
            print(code, len(rows), rows[:1], rows[-1:] if rows else "")
        except Exception as e:  # noqa: BLE001
            print(code, "ERROR", repr(e))
