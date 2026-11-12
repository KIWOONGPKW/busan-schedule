"""터미널별 픽업 가능한 공컨테이너(Empty) 수량.

로그인 없이 공개된 곳만 모은다.
  HJNC : GET /esvc/onDock/emptyStatus/data?shippingCode=선사 -> JSON (세션 쿠키, 선사별로만 조회됨)
         + /dataCMS (값이 있으면 같은 TYPE·SIZE 수량을 덮어씀 — 화면과 같은 방식)
  BPTC : GET /content/od/frame/yard_new_empty_frame_od_kr.jsp -> HTML 표 (EUC-KR, 신선대·감만 선사별)
  HJIT : POST esvc2.hjit.co.kr/HJIT/eslip/ondock/getEmptyOutList -> JSON (세션 쿠키 + CSRF)  [인천신항]
  E1CT : GET  www.e1ct.co.kr/info/terminal/emptyContainer -> HTML 표 (선사 | 20GP | 40GP | 40HQ | 45GP | 합계) [인천남항]
PNC·DGT·BNCT·HPNT·PNIT·HKTL·SNCT·ICT는 공컨 현황이 로그인(회원) 전용이거나 공개 화면이 없어 뺀다.
"""
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from terminals import UA, _cells, _fetch, _opener, _rows

SIZES = ["20", "40", "40HC", "45", "특수"]  # 특수 = 냉동·OT·FR/PL·SR 등
PRIVATE = ["PNC", "DGT", "BNCT", "HPNT", "PNIT", "HKTL", "SNCT", "ICT"]
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


def fetch_hjit():
    base = "https://esvc2.hjit.co.kr/HJIT"
    op = _opener(http.cookiejar.CookieJar())
    page = _fetch(f"{base}/esvc/yard/emptyStatus", opener=op)
    token = re.search(r'name="_csrf" content="([^"]+)"', page).group(1)
    req = urllib.request.Request(f"{base}/eslip/ondock/getEmptyOutList", data=b'{"operator":""}', headers={
        "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest", "X-CSRF-TOKEN": token, "Referer": f"{base}/esvc/yard/emptyStatus"})
    with op.open(req, timeout=20) as r:
        rows = json.loads(r.read().decode("utf-8", "replace") or "[]")
    sizes = {"ge20": "20", "ge40": "40", "ge40h": "40HC", "ge45": "45"}  # 나머지(rf·fr·ot·tk)는 특수
    lines = {}
    for r in rows:
        box = {}
        for k, v in r.items():
            if k != "opr" and isinstance(v, (int, float)):
                _add(box, sizes.get(k, "특수"), int(v))
        if r.get("opr") and box:
            lines[r["opr"]] = box
    return [{"name": "HJIT 한진인천", "area": "인천신항", "lines": lines}]


def fetch_e1ct():
    page = _fetch("https://www.e1ct.co.kr/info/terminal/emptyContainer")
    cols = ["20", "40", "40HC", "45"]
    lines = {}
    for _, row in _rows(page):
        c = _cells(row)
        if len(c) != 6 or not all(x.replace(",", "").isdigit() for x in c[1:]):
            continue
        box = {}
        for size, v in zip(cols, c[1:5]):
            _add(box, size, int(v.replace(",", "")))
        if box:
            lines[c[0]] = box
    return [{"name": "E1CT E1컨테이너", "area": "인천남항", "lines": lines}]


def fetch_empties(hjnc_lines=()):
    """-> ([{name, area, lines: {선사: {사이즈: 수량}}}], {출처: 오류})"""
    out, errors = [], {}
    for code, fn in (("HJNC", lambda: fetch_hjnc(hjnc_lines)), ("BPTC", fetch_bptc), ("HJIT", fetch_hjit), ("E1CT", fetch_e1ct)):
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
