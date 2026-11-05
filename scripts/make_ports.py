"""항구 목록 갱신: curl -L -o code-list.csv https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv && python scripts/make_ports.py code-list.csv ports.json
UN/LOCODE code-list.csv -> ports.json (해상 항구만: Function 첫 자리가 '1')
형식: {"v": 출처, "p": [[코드, 영문명, 국가], ...]}  — 페이지가 필요할 때만 불러 쓰는 검색용 목록
"""
import csv
import json
import sys

src, out = sys.argv[1], sys.argv[2]
ports, seen = [], set()
with open(src, encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        if (r.get("Change") or "").strip() == "X":  # 삭제 표시된 코드
            continue
        fn = r.get("Function") or ""
        if not fn.startswith("1"):
            continue
        code = (r["Country"] + r["Location"]).strip().upper()
        if len(code) != 5 or code in seen:
            continue
        seen.add(code)
        name = (r.get("NameWoDiacritics") or r.get("Name") or "").strip().upper()
        ports.append([code, name, r["Country"].strip().upper()])
ports.sort()
data = {"v": "UN/LOCODE (UNECE) via github.com/datasets/un-locode, Function=1 (port)", "p": ports}
open(out, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
print(len(ports), "ports")
