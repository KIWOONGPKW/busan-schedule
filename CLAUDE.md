# 부산·인천 스케줄 대시보드 작업 규칙

## 색 규칙 (항상 지킬 것)
- 부산 행 = 연한 녹색 (`--zbs-*`, `--open-*`) — 합계 칸 포함
- 인천 행 = 연한 파랑 (`--ic-*`; 로그인 필요·정보 미제공 행은 아주 연한 파랑 `--ic-off`) — 합계 칸 포함
- 머리글 · 전체 합계 행 = 연한 보라 (`--sum-*`, 배경은 머리글과 같은 `--head`)
  - 장비 현황표 "공개 터미널 전체" 행: 행 전체 연한 보라 배경, 위쪽 구분선 보라, 글씨·숫자 굵게 진한 보라, 합계 칸 숫자는 한 단계 더 굵게
  - 합계 열: 배경을 따로 주지 않고 그 행 색을 그대로 따른다(행 색 = 합계 칸 색). 보라는 머리글 "합계" 칸과 전체 합계 행에만. 합계 숫자는 다른 칸보다 굵게
- 경고 = 노랑
- 색은 `scripts/share_template.html` 맨 위 `:root` 토큰(★ 주석)에서 바꾼다. 개별 규칙에 색을 직접 쓰지 않는다.

## 표
- 고정 머리글(`position: sticky`)은 불투명 배경 + `z-index`로 아래 행 글자가 비치지 않게 한다.

## 빌드·배포
- 작업 전 `git pull`.
- 화면은 `scripts/share_template.html`, 데이터는 `scripts/build_share.py`가 넣는다.
- `cd scripts && python build_share.py` → `scripts/share/부산항_선박스케줄.html`을 `index.html`로 복사 → 커밋·push → `gh workflow run update.yml`.
