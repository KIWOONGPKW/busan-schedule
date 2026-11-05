"""컨테이너 번호로 적재 선박·선적 여부 추적.

containers.txt(저장소 맨 위)에 적힌 컨테이너를 터미널 컨테이너 조회 화면으로 찾고,
적재(예정) 선박을 선석배정 일정과 이어 붙여 출항 여부까지 낸다.

  DGT  : POST /DGT/container/containers -> JSON (세션 쿠키 + CSRF), out.vvd = 'OYDJ-001/2026'
  BNCT : GET  /esvc/cntr/cntrSrch/search -> JSON (세션 쿠키), OUT_VVD + OUT_VVD_YEAR
  HJNC : GET  /esvc/cntr/info/data -> JSON (세션 쿠키), info.X_VSL / X_VOYAGE / X_ATD
         (못 찾으면 {} 를 준다)

화주·B/L·부킹 번호는 공개 페이지에 싣지 않는다.
"""
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from terminals import TIMEOUT, UA, _dt, _fetch, _opener

LIST_FILE = Path(__file__).resolve().parent.parent / "containers.txt"
CNTR_RE = re.compile(r"^[A-Z]{4}\d{7}$")
RECENT_DAYS = 45  # 이보다 오래된 기록은 '예전 기록'으로 본다
SUPPORTED = ["DGT", "BNCT", "HJNC"]


def read_list():
    """containers.txt -> [(컨테이너, 메모)]. '#' 뒤는 주석, 줄 끝 메모는 공백 뒤에 적는다."""
    if not LIST_FILE.exists():
        return []
    out, seen = [], set()
    for line in LIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        no, _, memo = line.partition(" ")
        no = re.sub(r"[^A-Z0-9]", "", no.upper())
        if CNTR_RE.match(no) and no not in seen:
            seen.add(no)
            out.append((no, memo.strip()[:40]))
    return out


# ---------------------------------------------------------------- 터미널별 조회

def _dgt_session():
    base = "https://www.dgtbusan.com/DGT"
    op = _opener(http.cookiejar.CookieJar())
    page = _fetch(f"{base}/esvc/cntr/cntrInfo", opener=op)
    token = re.search(r'name="_csrf" content="([^"]+)"', page).group(1)
    header = re.search(r'name="_csrf_header" content="([^"]+)"', page).group(1)

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={
            "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest", header: token})
        with op.open(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    return post


def track_dgt(nos):
    post = _dgt_session()
    res = post("/container/containers", {"filter": {"cntrNos": nos, "stamp": ["B", "Y", "O"]}})
    out = {}
    for c in res.get("containers") or []:
        o, i = c.get("out") or {}, c.get("in") or {}
        loaded = o.get("mode") == "S" and bool(o.get("outDate"))
        hit = {"t": "DGT", "voy": o.get("vvd") or "", "loaded": loaded,
               "loaded_at": _dt(o.get("outDate")) if loaded else "", "in_at": _dt(i.get("inDate")),
               "gone_by_truck": o.get("mode") == "T" and bool(o.get("outDate")),
               "pod": c.get("pod") or "", "fe": c.get("fullEmpty") or "", "state": c.get("stamp") or ""}
        hit["last"] = max(hit["loaded_at"], hit["in_at"], _dt(o.get("outDate")))
        cur = out.get(c["cntrNo"])
        if cur is None or hit["last"] > cur["last"]:
            out[c["cntrNo"]] = hit
    return out


def track_bnct(nos):
    base = "https://info.bnctkorea.com/esvc/cntr/cntrSrch"
    op = _opener(http.cookiejar.CookieJar())
    _fetch(base, opener=op)
    out = {}
    for no in nos:
        q = urllib.parse.urlencode({"CNTR_NO": no, "CNTR_SEQ": "", "TML_OUT_DTE": "", "TML_OUT_HOUR": "", "TML_OUT_MINUTE": ""})
        res = json.loads(_fetch(f"{base}/search?{q}", opener=op, headers={
            "Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": base}))
        info = (res.get("cntrInfo") or [None])[0]
        if not info:
            continue
        loaded = info.get("OUT_MODE") == "SHIP" and bool(info.get("TML_OUT_DTE"))
        voy = info.get("OUT_VVD") or ""
        hit = {"t": "BNCT", "voy": f"{voy}/{info.get('OUT_VVD_YEAR') or ''}" if voy else "", "loaded": loaded,
               "loaded_at": _dt(info.get("TML_OUT_DTE")) if loaded else "", "in_at": _dt(info.get("TML_IN_DTE")),
               "gone_by_truck": info.get("OUT_MODE") == "TRUCK" and bool(info.get("TML_OUT_DTE")),
               "pod": info.get("POD") or "", "fe": info.get("CNTR_FOE") or "", "state": info.get("STS_NM") or ""}
        hit["last"] = max(hit["loaded_at"], hit["in_at"], _dt(info.get("TML_OUT_DTE")))
        out[no] = hit
    return out


def track_hjnc(nos):
    base = "https://www.hjnc.co.kr/esvc/cntr/info"
    op = _opener(http.cookiejar.CookieJar())
    _fetch(base, opener=op)
    out = {}
    for no in nos:
        raw = _fetch(f"{base}/data?{urllib.parse.urlencode({'cntrNo': no})}", opener=op, headers={
            "Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": base})
        info = (json.loads(raw) or {}).get("info") or {}
        if not info:
            continue
        loaded_at = _dt(info.get("OV_DATE"))  # 선적(Out Vessel) 일시
        hit = {"t": "HJNC", "voy": info.get("X_VOYAGE") or "", "vsl": info.get("X_VSL") or "", "loaded": bool(loaded_at),
               "loaded_at": loaded_at, "in_at": _dt(info.get("IT_DATE") or info.get("IV_DATE")),
               "gone_by_truck": bool(_dt(info.get("OT_DATE"))), "atd": _dt(info.get("X_ATD")),
               "pod": info.get("POD") or "", "fe": info.get("FE") or "", "state": info.get("CNTR_STATE") or ""}
        hit["last"] = max(hit["loaded_at"], hit["in_at"], _dt(info.get("OT_DATE")))
        out[no] = hit
    return out


TRACKERS = {"DGT": track_dgt, "BNCT": track_bnct, "HJNC": track_hjnc}


# ---------------------------------------------------------------- 일정과 잇기

def _norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _voy_key(s):
    """'OYDJ-001/2026' / 'OYDJ-1/2026' / 'CMCZ005/2026' -> 숫자 앞 0을 뺀 비교용 키."""
    return re.sub(r"(?<![0-9])0+(?=\d)", "", _norm(s))


def _find_row(rows, hit):
    if not hit["voy"] and not hit.get("vsl"):
        return None
    key = _voy_key(hit["voy"])
    same = [r for r in rows if r["t"] == hit["t"]]
    for r in same:
        if key and any(_voy_key(v) == key for v in r["voyages"] if v):
            return r
    if hit.get("vsl"):  # HJNC: 모선 코드 + 항차가 따로 온다
        for r in same:
            if _norm(hit["vsl"]) in (_norm(r["vessel"]), _norm(r["voyages"][0])[:4]) and \
                    any(_norm(hit["voy"]) and _norm(hit["voy"]) in _norm(v) for v in r["voyages"]):
                return r
    return None


def track(rows):
    """[(컨테이너, 메모)] -> 화면용 추적 결과 목록, {터미널: 오류}."""
    items = read_list()
    if not items:
        return [], {}
    nos = [no for no, _ in items]
    errors, found = {}, {}

    def run(code):
        try:
            return code, TRACKERS[code](nos)
        except Exception as e:  # noqa: BLE001
            errors[code] = f"{type(e).__name__}: {e}"[:160]
            return code, {}

    with ThreadPoolExecutor(max_workers=len(TRACKERS)) as ex:
        for _, hits in ex.map(run, TRACKERS):
            for no, hit in hits.items():
                if no not in found or hit["last"] > found[no]["last"]:
                    found[no] = hit

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    old = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d %H:%M")
    out = []
    for no, memo in items:
        hit = found.get(no)
        if not hit:
            out.append({"no": no, "memo": memo, "result": "none"})
            continue
        row = _find_row(rows, hit)
        etd = (row or {}).get("etd") or hit.get("atd") or ""
        if hit["loaded"]:
            # 일정표에 없는 예전 항차(조회 기간 밖)는 이미 떠난 배로 본다
            gone = (etd and etd <= now) or (row or {}).get("status") == "출항" or (not row and hit["last"] < old)
            result = "departed" if gone else "loaded"
        elif hit["gone_by_truck"]:
            result = "out"
        else:
            result = "yard"
        out.append({"no": no, "memo": memo, "result": result, "old": hit["last"] < old, "t": hit["t"],
                    "vessel": (row or {}).get("vessel") or hit.get("vsl") or "", "voy": hit["voy"],
                    "etb": (row or {}).get("etb") or "", "etd": etd, "berth": (row or {}).get("berth") or "",
                    "loaded_at": hit["loaded_at"], "in_at": hit["in_at"], "pod": hit["pod"],
                    "fe": hit["fe"], "state": hit["state"]})
    return out, errors


if __name__ == "__main__":
    import sys
    import terminals
    if len(sys.argv) > 1:  # 시험용: python tracking.py BEAU4348542 ...
        read_list = lambda: [(n.upper(), "") for n in sys.argv[1:]]  # noqa: E731
    rows = []
    for code in SUPPORTED:
        rows += [{"t": code, **r} for r in terminals.FETCHERS[code]()]
    res, errs = track(rows)
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    print("오류:", errs or "없음")
