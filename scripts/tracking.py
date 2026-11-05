"""컨테이너 번호로 적재 선박·선적 여부 추적.

containers.txt(저장소 맨 위)에 적힌 컨테이너를 터미널 컨테이너 조회 화면으로 찾고,
적재(예정) 선박을 선석배정 일정과 이어 붙여 출항 여부까지 낸다.

  DGT  : POST /DGT/container/containers -> JSON (세션 쿠키 + CSRF), out.vvd = 'OYDJ-001/2026'
  BNCT : GET  /esvc/cntr/cntrSrch/search -> JSON (세션 쿠키), OUT_VVD + OUT_VVD_YEAR
  HJNC : GET  /esvc/cntr/info/data -> JSON (세션 쿠키), info.X_VSL / X_VOYAGE / X_ATD
         (못 찾으면 {} 를 준다)
  HPNT : POST /infoservice/cntr/cntrSearchList.jsp -> HTML (CSRF 토큰, 조회마다 새로 받음)
  PNIT : HPNT와 같은 시스템 (www.pnitl.com, tmnCod=P)
  PNC  : POST /info/CMS/Container/Info.pnc -> HTML 표, 선적모선 'KKDE - 001/2025'
  BPTC : POST /GetShip_servlet_cg_kr (거쳐 간 모선 목록, 최근 순) -> cntr_out_cg_kr.jsp 상세 (EUC-KR)
  HKTL : POST /jsp/T04/dataio_cntr.jsp -> HTML (EUC-KR), 선명(항차) 'SKY SUNSHINE(KSKN07)'

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

from terminals import TIMEOUT, UA, _cells, _dt, _fetch, _opener, _rows

LIST_FILE = Path(__file__).resolve().parent.parent / "containers.txt"
CNTR_RE = re.compile(r"^[A-Z]{4}\d{7}$")
RECENT_DAYS = 45  # 이보다 오래된 기록은 '예전 기록'으로 본다
SUPPORTED = ["HJNC", "HPNT", "PNC", "DGT", "PNIT", "BNCT", "BPTC", "HKTL"]


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


def _pairs(page, start=0, end=None):
    """'라벨 | 값 | 라벨 | 값' 표 -> [(라벨, 값)] (순서 유지, 같은 라벨이 여러 번 나올 수 있다)."""
    page = re.sub(r"<script.*?</script>", "", page[start:end], flags=re.S | re.I)
    out = []
    for _, row in _rows(page):
        c = [x.replace("\xa0", " ").strip() for x in _cells(row, "t[hd]")]
        out += [(c[i], c[i + 1]) for i in range(0, len(c) - 1, 2)]
    return out


def _hpnt_like(code, host, tmn):
    """HPNT·PNIT(같은 시스템): 양하/적하 모선·Terminal In/Out 칸으로 나뉜 상세 화면."""
    def track_one(nos):
        url = f"https://{host}/infoservice/cntr/cntrSearchList.jsp"
        op = _opener(http.cookiejar.CookieJar())
        out = {}
        for no in nos:
            # 조회마다 CSRF 토큰이 바뀐다 (GET은 무시되고 POST만 받는다)
            token = re.search(r"CSRF_TOKEN', value:'([^']+)'", _fetch(url, opener=op)).group(1)
            page = _fetch(url, opener=op, headers={"Referer": url}, data={
                "CSRF_TOKEN": token, "isSearch": "Y", "page": "1", "URI": "/infoservice/cntr/cntrSearchList.jsp",
                "contNo": "", "tmnCod": tmn, "isEirSearch": "null", "cntrNo": no})
            if "해당 컨테이너를 찾을 수 없습니다" in page:
                continue
            cut = [page.find(s) for s in ("Terminal In 정보", "적하 모선/항차 정보", "Terminal Out 정보")]
            if min(cut) < 0:
                continue
            gen, t_in, ship_out, t_out = (dict(_pairs(page, a, b)) for a, b in
                                          ((0, cut[0]), (cut[0], cut[1]), (cut[1], cut[2]), (cut[2], None)))
            out_at = _dt(t_out.get("터미널 반출 시간"))
            loaded = t_out.get("Out Mode") == "SHIP" and bool(out_at)
            voy = (ship_out.get("항차") or "").split("/")[-1].strip()  # '2026 / YTLN002'
            hit = {"t": code, "voy": voy, "vsl": ship_out.get("모선명") or "", "loaded": loaded,
                   "loaded_at": out_at if loaded else "", "in_at": _dt(t_in.get("터미널 반입 시간")),
                   "gone_by_truck": bool(out_at) and not loaded,
                   "pod": ship_out.get("POD") or "", "fe": (gen.get("FE / TS") or "").split("/")[0].strip()[:1],
                   "state": gen.get("Class") or ""}
            hit["last"] = max(hit["in_at"], out_at)
            out[no] = hit
        return out
    return track_one


def track_pnc(nos):
    url = "https://svc.pncport.com/info/CMS/Container/Info.pnc?mCode=MN002"
    out = {}
    for no in nos:
        page = _fetch(url, data={"CONTNO": no})
        info = dict(_pairs(page))
        if info.get("Container No.") != no:
            continue
        out_at = _dt(info.get("반출시간"))
        loaded = info.get("반출경로") == "Vessel" and bool(out_at)
        voy = re.sub(r"\s+", "", info.get("선적모선") or "")  # 'KKDE - 001/2025'
        hit = {"t": "PNC", "voy": voy, "loaded": loaded, "loaded_at": out_at if loaded else "",
               "in_at": _dt(info.get("반입시간")), "gone_by_truck": bool(out_at) and not loaded,
               "pod": info.get("양하항") or "", "fe": info.get("F/E") or "", "state": info.get("구분") or ""}
        hit["last"] = max(hit["in_at"], out_at)
        out[no] = hit
    return out


def track_bptc(nos):
    # 1단계: 번호로 거쳐 간 모선 목록(최근 순) -> 2단계: 가장 최근 모선으로 상세 조회
    base = "https://info.bptc.co.kr"
    out = {}
    for no in nos:
        page = _fetch(f"{base}/GetShip_servlet_cg_kr", encoding="cp949", data={"v_cntr_no": no, "v_flag": "CNTR_SRCH"},
                      headers={"Referer": f"{base}/content/cg/jsp/cntr_in_cg_kr.jsp"})
        ships = re.findall(r'<OPTION value="([A-Z0-9]+-\d{4}-\d+-[A-Z]+-\d+)"', page, re.I)
        if not ships:
            continue
        page = _fetch(f"{base}/content/cg/jsp/cntr_out_cg_kr.jsp", encoding="cp949", data={
            "v_cntr_no1": no, "v_ship": ships[0], "v_dup_no": ships[0].rsplit("-", 1)[1], "v_from": "in"},
            headers={"Referer": f"{base}/GetShip_servlet_cg_kr"})
        info = dict(_pairs(page))
        loaded_at = _dt(info.get("적하일시"))
        vsl, voy = info.get("선박 코드") or "", (info.get("입항차") or "").lstrip("0")
        hit = {"t": "BPTC", "voy": f"{vsl}-{voy}" if vsl and voy else "", "loaded": bool(loaded_at),
               "loaded_at": loaded_at, "in_at": _dt(info.get("반입일시") or info.get("양하일시")),
               "gone_by_truck": bool(_dt(info.get("반출일시"))), "atd": _dt(info.get("출항일시")) if loaded_at else "",
               "pod": (info.get("양하항") or "").replace(" ", "") if loaded_at else "",
               "fe": (info.get("상태") or "")[2:3], "state": info.get("상태") or ""}
        hit["last"] = max(hit["loaded_at"], hit["in_at"], _dt(info.get("반출일시")))
        out[no] = hit
    return out


def track_hktl(nos):
    url = "https://custom.hktl.com/jsp/T04/dataio_cntr.jsp"
    out = {}
    for no in nos:
        # 년도·항차를 비워야 가장 최근 기록을 준다
        page = _fetch(url, encoding="cp949", data={
            "langType": "K", "terminal": "HBCTLIB", "mainType": "T04", "subType": "01", "optType": "T",
            "pname": "/T04/dataio_cntr.jsp", "ctrno": no, "seq": "", "vvd": "", "year": ""})
        if re.search(r"^\s*noinfo_chk\(\);", page, re.M):
            continue
        info = dict(_pairs(page))
        if info.get("Container Number") != no:
            continue
        m = re.match(r"(.*)\((\w+)\)\s*$", info.get("선명(항차)") or "")  # 'SKY SUNSHINE(KSKN07)'
        vsl, voy = (m.group(1).strip(), m.group(2)) if m else ("", "")
        loaded_at = _dt(info.get("적하일시"))
        hit = {"t": "HKTL", "voy": voy, "vsl": "" if vsl == "null" else vsl, "loaded": bool(loaded_at),
               "loaded_at": loaded_at, "in_at": _dt(info.get("반입일시") or info.get("양하일시")),
               "gone_by_truck": bool(_dt(info.get("반출일시"))),
               "pod": (info.get("양하항") or "") if loaded_at else "",
               "fe": (info.get("Full / Empty") or "")[:1], "state": (info.get("컨테이너 Move") or "").split(":")[-1].strip()}
        hit["last"] = max(hit["loaded_at"], hit["in_at"], _dt(info.get("반출일시")))
        out[no] = hit
    return out


TRACKERS = {"DGT": track_dgt, "BNCT": track_bnct, "HJNC": track_hjnc,
            "HPNT": _hpnt_like("HPNT", "www.hpnt.co.kr", "H"), "PNIT": _hpnt_like("PNIT", "www.pnitl.com", "P"),
            "PNC": track_pnc, "BPTC": track_bptc, "HKTL": track_hktl}


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
