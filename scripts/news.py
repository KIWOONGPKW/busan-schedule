"""코리아쉬핑가제트(ksg.co.kr) 기사, 부산항만공사(busanpa.com) 공지, 인천항만공사(icpa.or.kr) 보도자료 중
부산항·인천항 화물 스케줄에 영향 줄 만한 소식과 두 항만의 주요 소식을 골라낸다. (아래 '부산'은 부산·인천 모두)

  파업·기상: 전국 단위여도 부산항 일정이 흔들리니 그대로 싣는다
  사고·운영·스케줄(기항·노선 변경, 반입 등): 부산 관련 기사일 때만 싣는다
  항로(수에즈·홍해 등 우회·복귀)·시황(한중항로/ 같은 국내 항로 주간 시황): 부산 언급 없어도 싣는다
  주요: 위에 안 걸렸지만 제목에 부산이 나오는 화물·운영 소식 (행사·홍보성 기사는 뺀다)
  자리가 모자라면 경보 > 스케줄·항로 > 시황 > 주요 순으로 채운다

사이트 검색은 본문 전체를 엉성하게 뒤져서 쓸모가 없다 -> 항만·물류·해운·해양종합 목록
최근 몇 페이지(카테고리당 10건/페이지)를 받아 제목+요약으로 직접 분류한다.

  KSG : GET /news/news_list.jsp?page=N&bbsID=news&bbsCategory=KSG&categoryCode=XXX -> HTML (<ul class="new_list">)
  BPA : GET /board/list.bpa?boardId=BBS_XXX&menuCd=DOM_XXX -> HTML (예전 /kor/Board.do 링크는 404)
        선박대피협의회 회의결과는 기상악화 때 선박 대피 결정이라 전부 싣고, 공지·보도자료는 제목으로 거른다
  IPA : GET /article/list.do?menuKey=1400&boardKey=217 -> HTML 표 (인천항만공사 보도자료, 제목으로 거름)
"""
import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from terminals import _fetch

BASE = "https://www.ksg.co.kr"
BPA = "https://www.busanpa.com"
IPA = "https://www.icpa.or.kr"
BPA_BOARDS = {  # boardId: (menuCd, 게시판 이름, 거르지 않고 붙일 태그)
    "BBS_0000029": ("DOM_000000105001003000", "선박대피협의회", ["기상"]),
    "BBS_0000027": ("DOM_000000105001001000", "공지사항", None),
    "BBS_0000031": ("DOM_000000105002001000", "보도자료", None),
}
CATEGORIES = {"RKC": "항만", "XHJ": "물류", "LPG": "해운", "GOG": "해양/종합"}
PAGES = 4
DAYS, LIMIT = 14, 24

# 경보 태그는 제목으로만 판단 (요약까지 보면 '사고 재판', '3위 추락' 같은 엉뚱한 기사가 섞인다)
TAGS = {
    "파업": ["파업", "화물연대", "운송거부", "운송 거부", "태업", "쟁의", "집단행동", "준법투쟁", "농성"],
    "사고": ["사고", "화재", "충돌", "좌초", "침몰", "폭발", "전복", "기름유출", "유류유출", "인명피해", "사상자", "실종"],
    "기상": ["태풍", "강풍", "풍랑", "호우", "폭우", "폭설", "대설", "해무", "기상악화", "기상 악화", "결항",
           "입출항 통제", "입항 통제", "운항 통제", "피항"],
    "운영": ["적체", "체선", "혼잡", "하역 중단", "작업 중단", "운영 중단", "장비 고장", "크레인 고장", "전산 장애",
           "시스템 장애", "마비", "셧다운", "폐쇄", "봉쇄"],
    "스케줄": ["기항", "항로 개설", "항로 신설", "신규 항로", "신규 서비스", "서비스 개설", "서비스 개편", "항로 개편",
            "항로 중단", "서비스 중단", "운항 중단", "블랭크", "임시 결항", "휴항", "스킵", "선복 감축", "지연",
            "반입", "게이트", "터미널 이전", "터미널 통합", "운영 개시", "개장", "선석",
            "노선", "취항", "재개", "개편", "셔틀", "신설", "바닷길"],
    "항로": ["수에즈", "홍해", "파나마운하", "파나마 운하", "희망봉", "후티", "호르무즈", "말라카"],
}
ALERTS = {"파업", "기상", "사고", "운영"}
LANE_REPORT = re.compile(r"^\s*\S{1,8}항로\s*/")  # KSG 주간 시황: '한중항로/ ...', '동남아항로/ ...'
RANK = [ALERTS, {"스케줄", "항로"}, {"시황"}, {"주요"}]
ANYWHERE = {"파업", "기상", "항로", "시황"}
# 예방·훈련 같은 행사 기사, 해외 항만 파업은 부산항 일정과 무관 -> 뺀다
NOT_EVENT = ["예방", "훈련", "캠페인", "교육", "점검", "맞손", "협약", "MOU", "포상", "시상", "세미나", "포럼"]
# 주요 소식: 부산항 기사 중 화물·운영 이야기만 (기관 행사·공고는 뺀다)
MAJOR = ["물동량", "처리량", "컨테이너", "TEU", "환적", "신기록", "최대", "최초", "터미널", "부두", "선사", "얼라이언스",
         "항로", "선박", "입항", "운임", "수출", "수입", "화물", "배후단지", "하역", "크레인", "자동화", "스마트항만",
         "통관", "관세", "냉동", "공컨테이너", "빈 컨테이너", "장치장", "야드", "보안", "규제", "요금", "개정", "시행"]
FLUFF = NOT_EVENT + ["기부", "봉사", "나눔", "후원", "사회공헌", "채용", "모집", "공고", "결과 공개", "용역", "장학", "수상",
                     "감사패", "취임", "인사", "견학", "방문", "내방", "공모", "축제", "체험", "청렴", "윤리", "간담회",
                     "설명회", "워크숍", "페어", "약정", "총회", "헌혈"]
FOREIGN = re.compile(r"美|中|日|英|獨|佛|印|濠|미국|중국|일본|대만|홍콩|싱가포르|베트남|인도|유럽|네덜란드|독일|벨기에|프랑스|영국"
                     r"|스페인|이탈리아|그리스|스웨덴|핀란드|덴마크|노르웨이|캐나다|호주|칠레|브라질|멕시코|페루|남아공|이스라엘")
BUSAN = re.compile(r"부산|진해신항|부산신항|부산 신항|부산북항|부산 북항|부산항만공사|BPA\b|신항\s*\d|북항\s*\d")
INCHEON = re.compile(r"인천|인천항만공사|IPA\b|SNCT|HJIT|E1CT|선광신컨")


def _clean(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x))).strip()


def _tags(title, busan_title=False):
    if any(w in title for w in NOT_EVENT):
        tags = []
    else:
        tags = [t for t, words in TAGS.items() if any(w in title for w in words)]
        if "파업" in tags and FOREIGN.search(title):
            tags.remove("파업")
        if LANE_REPORT.search(title):
            tags = ["시황"] + [t for t in tags if t in ALERTS]
    if (not tags and busan_title and any(w in title for w in MAJOR)
            and not any(w in title for w in FLUFF)):
        tags = ["주요"]
    return tags


def _ksg_page(code, page):
    q = f"page={page}&bbsID=news&bbsCategory=KSG&categoryCode={code}"
    s = _fetch(f"{BASE}/news/news_list.jsp?{q}")
    s = s.split('class="new_list"', 1)[-1].split('class="paging"', 1)[0]  # 옆 칸 '많이 본 기사' 등 제외
    out = []
    for m in re.finditer(r'<dt><a href="/news/main_newsView\.jsp\?pNum=(\d+)">(.*?)</a>.*?class="date">([^<]*)<'
                         r'.*?<dd>(.*?)</(?:dd|dl)>', s, re.S):
        pnum, title, date, summary = m.groups()
        title, summary = _clean(title), _clean(summary)
        tags = _tags(title, bool(BUSAN.search(title) or INCHEON.search(title)))
        busan = bool(BUSAN.search(f"{title} {summary}"))
        incheon = bool(INCHEON.search(f"{title} {summary}"))
        # 사고·운영·스케줄·주요는 부산·인천 기사일 때만, 파업·기상·항로·시황은 언급 없어도
        if tags and (busan or incheon or ANYWHERE & set(tags)):
            out.append({"id": f"ksg{pnum}", "title": title, "date": date.strip()[:16], "busan": busan, "incheon": incheon,
                        "tags": tags,
                        "source": "쉬핑가제트", "cat": CATEGORIES[code],
                        "url": f"{BASE}/news/main_newsView.jsp?pNum={pnum}"})
    return out


def _bpa_board(board_id):
    menu, name, fixed = BPA_BOARDS[board_id]
    s = _fetch(f"{BPA}/board/list.bpa?boardId={board_id}&menuCd={menu}")
    out = []
    # 한 줄: 제목 링크 ... 작성자 ... <span>YYYY-MM-DD</span>
    for m in re.finditer(r'href="/board/view\.bpa\?[^"]*?dataSid=(\d+)"[^>]*>(.*?)</a>'
                         r'((?:(?!view\.bpa).)*?)<span>(\d{4}-\d{2}-\d{2})</span>', s, re.S):
        sid, title, _, date = m.groups()
        title = _clean(title)
        tags = fixed or _tags(title, True)
        if tags:
            out.append({"id": f"bpa{sid}", "title": title, "date": f"{date} 00:00", "busan": True, "tags": tags,
                        "source": "부산항만공사", "cat": name,
                        "url": f"{BPA}/board/view.bpa?boardId={board_id}&menuCd={menu}&dataSid={sid}"})
    return out


def _ipa_board():
    s = _fetch(f"{IPA}/article/list.do?menuKey=1400&boardKey=217")
    out = []
    for m in re.finditer(r'href="view\.do\?articleKey=(\d+)&[^"]*"[^>]*>(.*?)</a>.*?<td>[^<]*</td>\s*<td>(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.',
                         s, re.S):
        key, title, y, mo, d = m.groups()
        title = _clean(title).rstrip(".").rstrip()
        tags = _tags(title, True)
        if tags:
            out.append({"id": f"ipa{key}", "title": title, "date": f"{y}-{int(mo):02d}-{int(d):02d} 00:00",
                        "busan": False, "incheon": True, "tags": tags, "source": "인천항만공사", "cat": "보도자료",
                        "url": f"{IPA}/article/view.do?articleKey={key}&boardKey=217&menuKey=1400"})
    return out


def fetch_news():
    """(기사 목록, {출처: 오류}) - 한쪽 사이트가 막혀도 다른 쪽 소식은 싣는다."""
    jobs = {("쉬핑가제트", f"{c}-{p}"): (_ksg_page, c, p) for c in CATEGORIES for p in range(1, PAGES + 1)}
    jobs.update({("부산항만공사", b): (_bpa_board, b) for b in BPA_BOARDS})
    jobs[("인천항만공사", "보도자료")] = (_ipa_board,)
    items, errors = [], {}

    def run(key):
        fn, *args = jobs[key]
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001
            errors.setdefault(key[0], f"{type(e).__name__}: {e}"[:160])
            return []

    with ThreadPoolExecutor(max_workers=8) as ex:
        for found in ex.map(run, jobs):
            items += found
    cutoff = (datetime.now() - timedelta(days=DAYS)).strftime("%Y-%m-%d %H:%M")
    seen, picked = set(), []
    # 중요한 태그 순으로 자리를 채우고 -> 화면에는 최신순
    rank = lambda a: next((i for i, group in enumerate(RANK) if group & set(a["tags"])), len(RANK))
    for a in sorted(sorted(items, key=lambda a: a["date"], reverse=True), key=rank):
        if a["id"] not in seen and a["date"] >= cutoff:
            seen.add(a["id"])
            picked.append(a)
    return sorted(picked[:LIMIT], key=lambda a: a["date"], reverse=True), errors


if __name__ == "__main__":
    found, errs = fetch_news()
    for a in found:
        print(a["date"], a["source"], a["tags"], "부산" if a["busan"] else "", "인천" if a.get("incheon") else "", a["title"])
    print("오류:", errs or "없음")
