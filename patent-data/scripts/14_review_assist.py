"""替 T3_REVIEW 清單產生「建議裁決」，供人工逐筆確認。

**這支腳本一樣不下最終判斷。** 它只是把 4804 筆待審縮到可讀的規模，並把判斷
理由攤開來，讓人工複核時看的是證據而不是直覺。最終決定寫進
config/assignee_manual.csv，再由 11_verify_manual.py 驗回字典。

判斷的核心：T3 之所以是偽陽性溫床，是因為「第一個詞相同」太便宜。
  GEN DYNAMICS  vs GEN ELECTRIC      -> 兩家毫不相干
  AMAZON COM    vs AMAZON TECH       -> 同一家（Amazon 的專利持有實體）
兩者的差別不在字串距離，而在**第一個詞是不是該公司獨有的品牌詞**。

所以用兩個資料驅動的訊號，不憑記憶：

  1. head_firms  名冊裡有幾家公司的核心名以這個詞開頭。
     GEN -> GD/GIS/GM/SYMC/GE 共 5 家，是共用詞，第二個詞才是品牌，必須完全相同。
     AMAZON -> 只有 AMZN 一家，是獨有品牌詞。

  2. head_orgs   字典裡有幾個「不同的核心名」以這個詞開頭。
     數字大代表這個詞被無數不相干的機構共用（UNIV、NAT、KOREA…）。

再加上 FUNCTIONAL：企業內部功能詞（TECH、RES、DEV、IP、LICENSING…）。
「品牌詞 + 功能詞」幾乎一定是同一集團的持有實體；「品牌詞 + 另一個實詞」
則可能是另一家獨立公司（TOYOTA JIDOSHOKKI 是另外上市的豐田自動織機），
這種一律丟回人工，不自動放行。
"""

import collections
import csv
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 檔名以數字開頭，只能用 importlib 載入
_spec = importlib.util.spec_from_file_location(
    "m10", pathlib.Path(__file__).resolve().parent / "10_match_assignees.py")
m10 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m10)

# 企業功能/地理詞：接在品牌詞後面時，幾乎都是同集團的持有或營運實體
FUNCTIONAL = {
    "TECH", "RES", "DEV", "IP", "LICENSING", "SOLUTIONS", "PRODUCTS", "SERVICES",
    "SYS", "LAB", "GLOBAL", "INT", "ENTPR", "HOLDING", "HOLDINGS", "GROUP",
    "DIGITAL", "VENTURES", "INVESTMENTS", "OPERATIONS", "MFG", "ENG", "DESIGN",
    "SOFTWARE", "NETWORKS", "SEMICONDUCTOR", "MICROELECTRONICS", "INSTR",
    "AMERICA", "AMERICAS", "NORTH", "EUROPE", "ASIA", "JAPAN", "CHINA", "KOREA",
    "USA", "US", "UK", "DEUTSCHLAND", "FRANCE", "CANADA", "INDIA", "SINGAPORE",
    "COM", "ONLINE", "INTERACTIVE", "ENTERTAINMENT", "MEDIA", "STUDIOS",
}

MIN_PUB = 100      # 件數門檻：>=100 的 266 筆已涵蓋未裁決量的 87%


def main():
    roster = m10.load_roster()
    # roster 的結構由 10_ 決定，這裡只取需要的欄位
    heads_firm = collections.defaultdict(set)
    for r in roster:
        c = m10.core(r["primary_name"])      # core() 回傳 token list
        if c:
            heads_firm[c[0]].add(r["primary_ticker"])

    rev = list(csv.DictReader(open(ROOT / "out" / "assignee_match_review.csv",
                                   encoding="utf-8")))
    heads_org = collections.Counter()
    for r in rev:
        c = r["assignee_core"]
        if c:
            heads_org[c.split()[0]] += 1

    done = {(r["ticker"], r["assignee_name"])
            for r in csv.DictReader(open(ROOT / "config" / "assignee_manual.csv",
                                         encoding="utf-8"))}

    out = []
    for r in rev:
        if (r["primary_ticker"], r["assignee_name"]) in done:
            continue
        n = int(r["n_publications"])
        if n < MIN_PUB:
            continue
        p = (r["matched_from_name"] or "").split()
        a = (r["assignee_core"] or "").split()
        if not p or not a:
            continue
        head = p[0]
        nf, no = len(heads_firm.get(head, ())), heads_org.get(head, 0)
        rest = a[len(p):] if a[:len(p)] == p else None

        if a[0] != head:
            why, sug = "首詞不同", "EXCLUDE"
        elif nf > 1:
            # 共用首詞，品牌在第二個詞：必須整串前綴相同才可能是同一家
            if rest is not None:
                why, sug = f"首詞{head}為{nf}家共用，但完整前綴相符", "CHECK"
            else:
                why, sug = f"首詞{head}為{nf}家共用，第二詞不同", "EXCLUDE"
        elif rest is None:
            why, sug = "首詞獨有，但非完整前綴", "CHECK"
        elif not rest:
            why, sug = "核心名完全相同", "INCLUDE"
        elif all(t in FUNCTIONAL or t in m10.LEGAL for t in rest):
            why, sug = f"品牌詞獨有 + 功能詞 {' '.join(rest)}", "INCLUDE"
        else:
            why, sug = f"品牌詞獨有，但多出實詞 {' '.join(rest)}", "CHECK"

        out.append({**r, "n": n, "suggest": sug, "why": why,
                    "head_firms": nf, "head_orgs": no})

    out.sort(key=lambda x: (x["suggest"], -x["n"]))
    p = ROOT / "out" / "assignee_review_suggest.csv"
    cols = ["suggest", "why", "primary_ticker", "primary_name", "matched_from_name",
            "assignee_name", "assignee_core", "n_publications", "first_filing_year",
            "last_filing_year", "head_firms", "head_orgs", "permco"]
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    c = collections.Counter(x["suggest"] for x in out)
    print(f"待審且件數 >= {MIN_PUB} 的有 {len(out)} 筆")
    for k in ("INCLUDE", "CHECK", "EXCLUDE"):
        rows = [x for x in out if x["suggest"] == k]
        print(f"  {k:<8}{c[k]:>4} 筆，涉及 {sum(x['n'] for x in rows):>7,} 件 publication")
    print(f"\n寫入 {p}")


if __name__ == "__main__":
    main()
