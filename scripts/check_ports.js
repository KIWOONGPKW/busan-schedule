// 부산발 목적지 검색 전수 점검: ports.json의 모든 항구를 페이지 검색 로직으로 하나씩 검색해 본다.
//   node scripts/check_ports.js [index.html] [ports.json] [보고서.md]
// 결과마다: ① 노선 연결 배 / ② 환적 가능(예상) 배 / ③ 선사 공식 스케줄 링크 중 무엇이 나왔는지 센다.
// ①②③ 중 하나도 없는 항구(빈 화면·정보 준비 중·못 찾음)는 문제 항구 → 보고서에 목록, 종료 코드 1.
// 정기 서비스가 없다는 사유(남극·북한 등)를 보여주는 항구는 '운항 불가 안내'로 따로 센다(문제 아님).
const fs = require("fs");
const [page = "index.html", portsFile = "ports.json", out = "port_check.md"] = process.argv.slice(2);
const html = fs.readFileSync(page, "utf8");
const js = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).pop();

// 브라우저 없이 돌리기 위한 최소한의 화면 대역
const els = {};
const el = (id) => els[id] || (els[id] = { id, innerHTML: "", textContent: "", hidden: false, value: "", src: "", href: "",
  classList: { toggle() {}, remove() {}, add() {} }, addEventListener() {}, setAttribute() {}, scrollIntoView() {}, dataset: {} });
global.document = { querySelector: el, querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => null, setItem() {} };
global.Audio = function () { return { addEventListener() {}, set src(v) {} }; };
global.location = { hash: "" };
global.fetch = () => Promise.resolve({ json: () => Promise.resolve(JSON.parse(fs.readFileSync(portsFile, "utf8"))) });

const run = new Function(js + `
return loadAllPorts().then(() => {
  const res = { total: 0, route: 0, ts: 0, linkOnly: 0, none: 0, problems: [] };
  for (const p of allPorts()) {
    res.total++;
    renderDest(p.code);
    const m = destUi.mode;
    if (m === "route" && destUi.rows) res.route++;
    else if (m === "ts" && destUi.rows) res.ts++;
    else if (m === "none") res.none++;
    else if (destUi.links) res.linkOnly++;
    else res.problems.push({ code: p.code, name: p.name, country: p.country, region: p.region || "", mode: m || "빈 화면" });
  }
  return res;
});`);

run().then((r) => {
  const byCountry = {};
  r.problems.forEach((p) => { byCountry[p.country] = (byCountry[p.country] || 0) + 1; });
  const now = new Date().toISOString().slice(0, 16).replace("T", " ");
  const lines = [
    `# 부산발 목적지 검색 전수 점검 (${now} UTC)`, "",
    `| 구분 | 항구 수 |`, `|---|---:|`,
    `| 전체 | ${r.total} |`,
    `| ① 노선 연결 배 | ${r.route} |`,
    `| ② 환적 가능 (예상) 배 | ${r.ts} |`,
    `| ③ 선사 공식 스케줄 링크만 | ${r.linkOnly} |`,
    `| 운항 불가 안내 (남극·북한 등, 사유 표시) | ${r.none} |`,
    `| **문제 항구 (①②③ 모두 없음)** | **${r.problems.length}** |`, "",
  ];
  if (r.problems.length) {
    lines.push("## 국가별 문제 항구", "", "| 국가 | 수 |", "|---|---:|",
      ...Object.entries(byCountry).sort((a, b) => b[1] - a[1]).map(([c, n]) => `| ${c} | ${n} |`), "",
      "## 문제 항구 목록 (최대 300개)", "", "| 코드 | 항구 | 국가 | 지역 | 상태 |", "|---|---|---|---|---|",
      ...r.problems.slice(0, 300).map((p) => `| ${p.code} | ${p.name} | ${p.country} | ${p.region || "-"} | ${p.mode} |`),
      "", "→ scripts/regions.json의 countries(국가 → 지역)에 국가를 추가하면 해결돼요.");
  }
  fs.writeFileSync(out, lines.join("\n") + "\n");
  console.log(lines.slice(2, 10).join("\n"));
  process.exit(r.problems.length ? 1 : 0);
}).catch((e) => { console.error(e); process.exit(2); });
