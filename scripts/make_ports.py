"""항구 목록 갱신:
  curl -L -o code-list.csv https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv
  python scripts/make_ports.py code-list.csv ports.json

UN/LOCODE code-list.csv -> ports.json (해상 항구만: Function 첫 자리가 '1')
형식: {"v": 출처, "p": [[코드, 영문명, 국가, 지역], ...]}  — 페이지가 검색창을 처음 쓸 때만 불러 쓰는 목록
지역은 scripts/regions.json의 countries(국가 → 지역)로 정하고, 미국·캐나다·러시아는 좌표로 나눈다.
"""
import csv
import json
import re
import sys
from pathlib import Path

src, out = sys.argv[1], sys.argv[2]
COUNTRIES = json.loads((Path(__file__).resolve().parent / "regions.json").read_text(encoding="utf-8"))["countries"]


def coords(s):
    """'4058N 02842E' -> (40.97, 28.70)"""
    m = re.match(r"(\d{2})(\d{2})([NS])\s+(\d{3})(\d{2})([EW])", s or "")
    if not m:
        return None
    lat = (int(m[1]) + int(m[2]) / 60) * (1 if m[3] == "N" else -1)
    lon = (int(m[4]) + int(m[5]) / 60) * (1 if m[6] == "E" else -1)
    return lat, lon


def region(cc, sub, c):
    r = COUNTRIES.get(cc, "")
    if cc == "US":
        if sub in ("AK", "HI", "CA", "OR", "WA") or (c and c[1] < -115):
            return "미주 서안"
        if sub in ("TX", "LA", "MS", "AL") or (c and c[0] < 31 and -98 < c[1] < -82):
            return "미주 걸프"
        return "미주 동안"
    if cc == "CA":
        return "미주 서안" if sub == "BC" or (c and c[1] < -110) else "미주 동안"
    if cc == "RU":
        if sub in ("PRI", "KHA", "SAK", "KAM", "MAG", "CHU", "SA", "AMU") or (c and c[1] > 100):
            return "러시아 극동"
        if sub in ("KDA", "ROS", "AD") or (c and c[0] < 48 and 30 < c[1] < 50):
            return "흑해"
        if c or sub:
            return "유럽"
        return ""  # 좌표·지역 정보가 없으면 모름 (아래 RU_FAR_EAST로 보완)
    return r


# 좌표가 빠진 러시아 극동 주요 항구
RU_FAR_EAST = {"RUVVO", "RUNJK", "RUVYP", "RUKOR", "RUPKC", "RUMAG", "RUVNN", "RUZRB"}
ports, seen = [], set()
with open(src, encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        if (r.get("Change") or "").strip() == "X":  # 삭제 표시된 코드
            continue
        if not (r.get("Function") or "").startswith("1"):
            continue
        cc = r["Country"].strip().upper()
        code = (cc + r["Location"]).strip().upper()
        if len(code) != 5 or code in seen:
            continue
        seen.add(code)
        name = (r.get("NameWoDiacritics") or r.get("Name") or "").strip().upper()
        reg = region(cc, (r.get("Subdivision") or "").strip().upper(), coords(r.get("Coordinates")))
        if code in RU_FAR_EAST:
            reg = "러시아 극동"
        ports.append([code, name, cc, reg])
ports.sort()
data = {"v": "UN/LOCODE (UNECE) via github.com/datasets/un-locode, Function=1 (port)", "p": ports}
open(out, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
print(len(ports), "ports,", sum(1 for p in ports if p[3]), "with region")
