"""안전운임 고시 엑셀 -> 페이지 조회용 safe_freight.json (저장소 맨 위, GitHub Pages가 그대로 내려줌).

고시가 바뀔 때만 손으로 한 번 실행한다 (Actions에서는 돌리지 않음):
  python scripts/safe_freight.py "<왕복.xlsx>" "<편도.xlsx>"
  (인자를 생략하면 내려받기 폴더의 '(별첨)_수출입_컨테이너_품목_기점별_운임(왕복/편도).xlsx')

엑셀 구조 (헤더 2줄, 데이터는 3번째 줄부터)
  왕복: 기점 시트 14개 / 시도|시군구|행정동|거리(km)|40FT 안전위탁·운수사업자 간·안전운송|20FT 같은 3개
  편도: 부산신항·부산북항·광양항↔의왕ICD 3개 / 시도|시군구|행정동|구간거리|적컨거리|공컨거리|40FT 3종|20FT 3종

JSON (용량을 줄이려고 주소는 한 번만, 왕복 운임은 기점별 '거리 -> 운임' 표로 저장)
  A: ["시도|시군구|행정동", ...]                       14개 시트 주소 목록이 모두 같아 한 번만
  R: {기점: {"d": [주소 순서대로 거리], "t": {거리: [20위탁, 20운수, 20안전, 40위탁, 40운수, 40안전]}}}
  O: {"부산신항↔의왕ICD": [[주소번호, 구간, 적컨, 공컨, 20위탁, 20운수, 20안전, 40위탁, 40운수, 40안전], ...]}
"""
import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "safe_freight.json"
DL = Path.home() / "Downloads"


def _rows(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    return {sn: [r for r in wb[sn].iter_rows(min_row=3, values_only=True) if r and r[0]] for sn in wb.sheetnames}


def build(rt_path, ow_path):
    rt, ow = _rows(rt_path), _rows(ow_path)
    first = next(iter(rt.values()))
    addr = [f"{r[0]}|{r[1]}|{r[2]}" for r in first]
    idx = {a: i for i, a in enumerate(addr)}
    R = {}
    for sheet, rows in rt.items():
        if [f"{r[0]}|{r[1]}|{r[2]}" for r in rows] != addr:
            raise RuntimeError(f"{sheet}: 주소 목록이 다른 시트와 달라요")
        t = {}
        for r in rows:  # 엑셀은 40FT가 먼저 -> 20FT 먼저로 바꿔 저장
            v = [r[7], r[8], r[9], r[4], r[5], r[6]]
            if t.setdefault(str(r[3]), v) != v:
                raise RuntimeError(f"{sheet}: 같은 거리 {r[3]}km인데 운임이 달라요")
        R[sheet] = {"d": [r[3] for r in rows], "t": t}
    O = {sheet: [[idx[f"{r[0]}|{r[1]}|{r[2]}"], r[3], r[4], r[5], r[9], r[10], r[11], r[6], r[7], r[8]] for r in rows]
         for sheet, rows in ow.items()}
    data = {"src": [Path(rt_path).name, Path(ow_path).name], "A": addr, "R": R, "O": O}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(addr), len(R), len(O)


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else DL / "(별첨)_수출입_컨테이너_품목_기점별_운임(왕복).xlsx"
    b = sys.argv[2] if len(sys.argv) > 2 else DL / "(별첨)_수출입_컨테이너_품목_기점별_운임(편도).xlsx"
    n, r, o = build(a, b)
    print(f"{OUT} 주소 {n}곳 · 왕복 기점 {r}개 · 편도 {o}개 · {OUT.stat().st_size // 1024}KB")
