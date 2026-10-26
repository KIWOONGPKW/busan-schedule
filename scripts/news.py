"""코리아쉬핑가제트(ksg.co.kr) 최근 기사 중 부산항 화물 스케줄에 영향 줄 만한 소식만 골라낸다.

  파업·기상: 전국 단위여도 부산항 일정이 흔들리니 그대로 싣는다
  사고·운영(적체·장애 등): 부산항 관련 기사일 때만 싣는다

사이트 검색은 본문 전체를 엉성하게 뒤져서 쓸모가 없다 -> 항만·물류·해운·해양종합 목록
최근 몇 페이지(카테고리당 10건/페이지)를 받아 제목+요약으로 직접 분류한다.

  GET /news/news_list.jsp?page=N&bbsID=news&bbsCategory=KSG&categoryCode=XXX -> HTML (<ul class="new_list">)
"""
import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from terminals import _fetch

BASE = "https://www.ksg.co.kr"
CATEGORIES = {"RKC": "항만", "XHJ": "물류", "LPG": "해운", "GOG": "해양/종합"}
PAGES = 4
DAYS, LIMIT = 14, 15

# 경보 태그는 제목으로만 판단 (요약까지 보면 '사고 재판', '3위 추락' 같은 엉뚱한 기사가 섞인다)
TAGS = {
    "파업": ["파업", "화물연대", "운송거부", "운송 거부", "태업", "쟁의", "집단행동", "준법투쟁", "농성"],
    "사고": ["사고", "화재", "충돌", "좌초", "침몰", "폭발", "전복", "기름유출", "유류유출", "인명피해", "사상자", "실종"],
    "기상": ["태풍", "강풍", "풍랑", "호우", "폭우", "폭설", "대설", "해무", "기상악화", "기상 악화", "결항",
           "입출항 통제", "입항 통제", "운항 통제", "피항"],
    "운영": ["적체", "체선", "혼잡", "하역 중단", "작업 중단", "운영 중단", "장비 고장", "크레인 고장", "전산 장애",
           "시스템 장애", "마비", "셧다운", "폐쇄", "봉쇄"],
}
ANYWHERE = {"파업", "기상"}
# 예방·훈련 같은 행사 기사, 해외 항만 파업은 부산항 일정과 무관 -> 뺀다
NOT_EVENT = ["예방", "훈련", "캠페인", "교육", "점검", "맞손", "협약", "MOU", "포상", "시상", "세미나", "포럼"]
FOREIGN = re.compile(r"美|中|日|英|獨|佛|印|濠|미국|중국|일본|대만|홍콩|싱가포르|베트남|인도|유럽|네덜란드|독일|벨기에|프랑스|영국"
                     r"|스페인|이탈리아|그리스|스웨덴|핀란드|덴마크|노르웨이|캐나다|호주|칠레|브라질|멕시코|페루|남아공|이스라엘")
BUSAN = re.compile(r"부산항|부산신항|부산 신항|부산북항|부산 북항|부산항만공사|BPA\b|신항\s*\d|북항\s*\d")


def _list_page(code, page):
    q = f"page={page}&bbsID=news&bbsCategory=KSG&categoryCode={code}"
    s = _fetch(f"{BASE}/news/news_list.jsp?{q}")
    s = s.split('class="new_list"', 1)[-1].split('class="paging"', 1)[0]  # 옆 칸 '많이 본 기사' 등 제외
    out = []
    for m in re.finditer(r'<dt><a href="/news/main_newsView\.jsp\?pNum=(\d+)">(.*?)</a>.*?class="date">([^<]*)<'
                         r'.*?<dd>(.*?)</(?:dd|dl)>', s, re.S):
        pnum, title, date, summary = m.groups()
        clean = lambda x: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x))).strip()
        out.append({"id": pnum, "title": clean(title), "date": date.strip()[:16],
                    "summary": clean(summary)[:140], "cat": CATEGORIES[code],
                    "url": f"{BASE}/news/main_newsView.jsp?pNum={pnum}"})
    return out


def fetch_news():
    jobs = [(c, p) for c in CATEGORIES for p in range(1, PAGES + 1)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        pages = list(ex.map(lambda j: _list_page(*j), jobs))
    seen, picked = set(), []
    now = datetime.now()
    for item in (a for pg in pages for a in pg):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        title = item["title"]
        tags = [t for t, words in TAGS.items() if any(w in title for w in words)]
        if any(w in title for w in NOT_EVENT):
            tags = []
        if "파업" in tags and FOREIGN.search(title):
            tags.remove("파업")
        busan = bool(BUSAN.search(f'{item["title"]} {item["summary"]}'))
        try:
            age = now - datetime.strptime(item["date"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if age > timedelta(days=DAYS) or not (busan or ANYWHERE & set(tags)):
            continue
        if tags:
            picked.append({**item, "tags": tags, "busan": busan})
    picked.sort(key=lambda a: a["date"], reverse=True)
    return picked[:LIMIT]


if __name__ == "__main__":
    for a in fetch_news():
        print(a["date"], a["tags"], "부산" if a["busan"] else "", a["title"])
