# 부산·인천 스케줄 대시보드 작업 규칙

## 색 규칙 (항상 지킬 것)
- 부산 = 연한 녹색 (`--zbs-*`, `--open-*`)
- 인천 = 연한 파랑 (`--ic-*`)
- 전체 합계 행 · 합계 열 = 연한 보라 (`--sum-*`, 배경은 머리글과 같은 `--head`)
  - 장비 현황표 "공개 터미널 전체" 행: 행 전체 연한 보라 배경, 위쪽 구분선 보라, 글씨·숫자 굵게 진한 보라
  - 합계 열: 머리글부터 맨 아래까지 모든 칸 연한 보라, 숫자는 다른 칸보다 조금 굵게
- 경고 = 노랑
- 색은 `scripts/share_template.html` 맨 위 `:root` 토큰(★ 주석)에서 바꾼다. 개별 규칙에 색을 직접 쓰지 않는다.

## 표
- 고정 머리글(`position: sticky`)은 불투명 배경 + `z-index`로 아래 행 글자가 비치지 않게 한다.

## 빌드·배포
- 작업 전 `git pull`.
- 화면은 `scripts/share_template.html`, 데이터는 `scripts/build_share.py`가 넣는다.
- `cd scripts && python build_share.py` → `scripts/share/부산항_선박스케줄.html`을 `index.html`로 복사 → 커밋·push → `gh workflow run update.yml`.
