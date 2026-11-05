"""터미널별 픽업 가능한 공컨테이너(Empty) 수량.

로그인 없이 공개된 곳만 모은다.
  HJNC : GET /esvc/onDock/emptyStatus/data?shippingCode=선사 -> JSON (세션 쿠키, 선사별로만 조회됨)
         + /dataCMS (값이 있으면 같은 TYPE·SIZE 수량을 덮어씀 — 화면과 같은 방식)
  BPTC : GET /content/od/frame/yard_new_empty_frame_od_kr.jsp -> HTML 표 (EUC-KR, 신선대·감만 선사별)
PNC·DGT·BNCT·HPNT·PNIT·HKTL은 공컨 현황이 로그인(회원) 전용이라 뺀다.
"""
import http.cookiejar
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from terminals import _cells, _fetch, _opener, _rows

SIZES = ["20", "40", "40HC", "45", "특수"]  # 특수 = 냉동·OT·FR/PL·SR 등
PRIVATE = ["PNC", "DGT", "BNCT", "HPNT", "PNIT", "HKTL"]
# HJNC는 선사 코드를 넣어야만 보여줘서, 일정표 선사 + 자주 오는 선사를 차례로 묻는다
HJNC_LINES = ["HMM", "ONE", "MSC", "MSK", "CMA", "HLC", "EMC", "YML", "ZIM", "COS", "OOL", "KMD", "SKR", "HAS",
              "PCL", "PIL", "WHL", "TSL", "SIT", "DJS", "DYS", "NSS", "CKL", "ESL", "RCL", "SML", "KFC", "CUL", "BEN", "EMA", "RSA"]


def _add(box, size, n):
    if n:
        box[size] = box.get(size, 0) + n


def fetch_hjnc(lines=()):
    base = "https://www.hjnc.co.kr/esvc/onDock/emptyStatus"
    op = _opener(http.cookiejar.CookieJar())
    _fetch(base, opener=op)
    hdr = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": base}

    def one(line):
        q = urllib.parse.urlencode({"shippingCode": line})
        rows = json.loads(_fetch(f"{base}/data?{q}", opener=op, headers=hdr) or "[]")
        cms = json.loads(_fetch(f"{base}/dataCMS?{urllib.parse.urlencode({'PTNR_CODE': line})}", opener=op, headers=hdr) or "[]")
        fix = {(r["CON_TYPE"], r["CON_SIZE"]): int(r["CNT"] or 0) for r in cms}
        box = {}
        for r in rows:
            t, s = r["CON_TYPE"], r["CON_SIZE"]
            n = fix.get((t, s), int(r["CNT"] or 0))
            _add(box, s if t == "G" and s in ("20", "40", "40HC", "45") else "특수", n)
        return line, box

    with ThreadPoolExecutor(max_workers=4) as ex:
        found = dict(ex.map(one, dict.fromkeys([*HJNC_LINES, *lines])))
    return [{"name": "HJNC 한진부산", "area": "신항", "lines": {k: v for k, v in found.items() if v}}]


def fetch_bptc():
    page = _fetch("https://info.bptc.co.kr/content/od/frame/yard_new_empty_frame_od_kr.jsp"
                  "?p_id=EMPT_NE_KR&snb_num=8&snb_div=service&pop_ok=Y", encoding="cp949")
    # 한 줄에 [선사, GP20, GP40, OT20, OT40, FL20, FL40, HQ20, HQ40, HQ45] x (신선대, 감만)
    cols = ["20", "40", "특수", "특수", "특수", "특수", "20", "40HC", "45"]
    yards = [{"name": "BPTC 신선대", "area": "북항", "lines": {}}, {"name": "BPTC 감만", "area": "북항", "lines": {}}]
    for _, row in _rows(page):
        c = _cells(row)
        if len(c) != 20:
            continue
        for yard, part in zip(yards, (c[:10], c[10:])):
            box = {}
            for size, v in zip(cols, part[1:]):
                _add(box, size, int(v) if v.isdigit() else 0)
            if part[0] and box:
                yard["lines"][part[0]] = box
    return yards


def fetch_empties(hjnc_lines=()):
    """-> ([{name, area, lines: {선사: {사이즈: 수량}}}], {출처: 오류})"""
    out, errors = [], {}
    for code, fn in (("HJNC", lambda: fetch_hjnc(hjnc_lines)), ("BPTC", fetch_bptc)):
        try:
            out += fn()
        except Exception as e:  # noqa: BLE001
            errors[code] = f"{type(e).__name__}: {e}"[:160]
    return out, errors


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    yards, errs = fetch_empties()
    for y in yards:
        tot = {s: sum(b.get(s, 0) for b in y["lines"].values()) for s in SIZES}
        print(y["name"], len(y["lines"]), "선사", tot)
    print("오류:", errs or "없음")
