"""把 AI 專利資料對齊 repo 既有的股票與論文資料，輸出公司-年度面板。

輸出 out/patent_stock_paper_annual.csv:
  parent_company, ticker, year,
  ai_patents_parent_only, ai_patents_with_subs,
  all_patents_with_subs, ai_share,
  n_papers, annual_return, annual_sp500_return, annual_excess_return,
  patent_truncated  (1 = 受 pre-grant 18 個月公開時滯影響，數字必然低估)

股票來源用 CRSP 月資料 (stock_and_paper_count/group_A_stocks.csv，AVGO 取自
group_C_stocks.csv)，不用 LEVEL4/panel_monthly.csv——後者的月份是由「該月有論文」
驅動的，AVGO 全期只有 3 個月、TSLA 只有 1 個月，複利成年報酬會嚴重失真。

同時輸出 out/alignment_report.txt 記錄涵蓋率與已知問題。
"""

import collections
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent

# pre-grant publication 自申請日起約 18 個月才公開，故最近兩個 filing year 必然不完整
TRUNC_FROM = 2024

# 專利資料的 ticker -> CRSP 歷史上用過的 ticker。Alphabet 2014 年分割出 C 股、
# Facebook 2022 年更名 Meta，CRSP 兩段各自獨立；在 group_A 內兩段月份不重疊
# （2014 = GOOG 3 + GOOGL 9；2022 = FB 5 + META 7），可直接聯集成連續序列。
TICKER_HISTORY = {
    "GOOGL": ["GOOG", "GOOGL"],
    "META": ["FB", "META"],
}
STOCK_FILES = [
    ROOT.parent / "stock_and_paper_count" / "group_A_stocks.csv",
    ROOT.parent / "stock_and_paper_count" / "group_C_stocks.csv",  # 只取 AVGO
]
ONLY_FROM_GROUP_C = {"AVGO"}


def load_alias():
    out = {}
    with open(ROOT / "config" / "company_alias.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["assignee_name"]] = ("parent", r["parent_company"], r["ticker"], None, None)
    with open(ROOT / "config" / "subsidiary_alias.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["assignee_name"] in out:
                continue
            ef = r["effective_from"].replace("-", "") if r["effective_from"] else None
            et = r["effective_to"].replace("-", "") if r["effective_to"] else None
            out[r["assignee_name"]] = ("subsidiary", r["parent_company"], r["ticker"], ef, et)
    return out


def total_patents():
    """全部（非只 AI）publication 的公司-年度件數，作為 AI 佔比的分母。"""
    alias = load_alias()
    seen = set()
    cnt = collections.Counter()
    csv.field_size_limit(10**7)
    with open(ROOT / "out" / "raw_publications.csv", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            fd = row["filing_date"]
            if not fd or len(fd) < 8:
                continue
            for name in (row["matched_assignees"] or "").split("|"):
                a = alias.get(name)
                if not a:
                    continue
                tier, parent, _tk, ef, et = a
                if tier == "subsidiary" and ((ef and fd < ef) or (et and fd > et)):
                    continue
                key = (parent, row["application_number"])
                if key in seen:
                    continue
                seen.add(key)
                cnt[(parent, fd[:4])] += 1
    return cnt


def load_ai():
    ai = collections.defaultdict(dict)
    tick = {}
    with open(ROOT / "out" / "ai_patents_yearly.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (r["parent_company"], r["filing_year"])
            ai[key][r["version"]] = int(r["ai_patent_count"])
            tick[r["parent_company"]] = r["ticker"]
    return ai, tick


def load_returns():
    """CRSP 月報酬複利成年報酬。

    超額報酬定義為 buy-and-hold 差額（個股年報酬 - S&P500 年報酬），
    而非逐月差額的複利，後者沒有可持有的投資組合對應。
    """
    acc = collections.defaultdict(lambda: [1.0, 1.0, 0])
    seen = set()
    missing = []
    for p in STOCK_FILES:
        if not p.exists():
            missing.append(f"找不到 {p}")
            continue
        only_c = p.name.startswith("group_C")
        with open(p, encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                tk = r["ticker"].strip()
                if only_c and tk not in ONLY_FROM_GROUP_C:
                    continue
                ym = r["yyyymm"]
                if (tk, ym) in seen:  # CRSP 分割月份有重複列
                    continue
                seen.add((tk, ym))
                try:
                    mr = float(r["mthret"])
                    sp = float(r["sprtrn"])
                except (ValueError, TypeError):
                    continue
                a = acc[(tk, ym[:4])]
                a[0] *= (1 + mr)
                a[1] *= (1 + sp)
                a[2] += 1
    return acc, "; ".join(missing) or None


def annual_return(acc, ticker, yr):
    """合併同一家公司歷史上用過的多個 ticker，回傳 (年報酬, 大盤, 月數)。"""
    r, s, n = 1.0, 1.0, 0
    for tk in TICKER_HISTORY.get(ticker, [ticker]):
        a = acc.get((tk, yr))
        if a:
            r *= a[0]
            s *= a[1]
            n += a[2]
    return (r - 1, s - 1, n) if n else None


def load_papers():
    p = REPO / "analysis" / "out" / "company_papers_annual.csv"
    if not p.exists():
        return {}, f"找不到 {p}"
    out = collections.Counter()
    with open(p, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            tk = (r["ticker"] or "").strip().strip('"')
            if not tk:
                continue
            out[(tk, r["yr"].strip())] += int(r["papers"])
    return out, None


def annual_papers(papers, ticker, yr):
    """FB/META、GOOG/GOOGL 兩段合併；兩段在 CRSP 內月份不重疊，可直接相加。"""
    hist = TICKER_HISTORY.get(ticker, [ticker])
    vals = [papers[(t, yr)] for t in hist if (t, yr) in papers]
    return sum(vals) if vals else ""


def main():
    ai, tick = load_ai()
    tot = total_patents()
    rets, e1 = load_returns()
    papers, e2 = load_papers()

    # 平衡面板：AI 專利為 0 的公司-年度也要有列（值為 0），否則迴歸會把「零」誤當成缺值
    years = [str(y) for y in range(2010, 2026)]
    cells = sorted((c, y) for c in tick for y in years)

    rows = []
    for (comp, yr) in cells:
        tk = tick[comp]
        r = annual_return(rets, tk, yr)
        rows.append({
            "parent_company": comp,
            "ticker": tk,
            "year": yr,
            "ai_patents_parent_only": ai[(comp, yr)].get("parent_only", 0),
            "ai_patents_with_subs": ai[(comp, yr)].get("with_subs", 0),
            "all_patents_with_subs": tot.get((comp, yr), 0),
            "ai_share": round(ai[(comp, yr)].get("with_subs", 0) / tot[(comp, yr)], 4)
                        if tot.get((comp, yr)) else "",
            "n_papers": annual_papers(papers, tk, yr),
            "annual_return": round(r[0], 6) if r else "",
            "annual_sp500_return": round(r[1], 6) if r else "",
            "annual_excess_return": round(r[0] - r[1], 6) if r else "",
            "months_in_year": r[2] if r else "",
            "patent_truncated": 1 if int(yr) >= TRUNC_FROM else 0,
        })

    out = ROOT / "out" / "patent_stock_paper_annual.csv"
    cols = list(rows[0])
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # ---- 涵蓋率報告 ----
    L = []
    L.append(f"公司-年度列數: {len(rows)}")
    L.append(f"有股票年報酬的列: {sum(1 for r in rows if r['annual_return'] != '')}")
    L.append(f"有論文數的列:     {sum(1 for r in rows if r['n_papers'] != '')}")
    if e1:
        L.append(f"⚠ 股票資料: {e1}")
    if e2:
        L.append(f"⚠ 論文資料: {e2}")

    L.append("\n各公司 AI 專利佔全部專利比例（with_subs）")
    bycomp = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        b = bycomp[r["parent_company"]]
        b[0] += r["ai_patents_with_subs"]
        b[1] += r["all_patents_with_subs"]
    for c, (a, t) in sorted(bycomp.items(), key=lambda x: -x[1][0]):
        L.append(f"  {c:<11} {a:>6} / {t:>6} = {a/t:6.1%}" if t else f"  {c:<11} 無資料")

    L.append("\n論文 vs AI 專利（交叉檢驗 OpenAlex 2022 斷裂）")
    L.append(f"  {'公司':<10}{'年':<6}{'論文':>7}{'AI專利':>8}")
    for r in rows:
        if r["n_papers"] != "" and 2020 <= int(r["year"]) <= 2023:
            L.append(f"  {r['parent_company']:<10}{r['year']:<6}{r['n_papers']:>7}"
                     f"{r['ai_patents_with_subs']:>8}")

    L.append("\n已知限制")
    L.append(f"  1. filing_year >= {TRUNC_FROM} 的專利數必然低估：US pre-grant publication")
    L.append("     自申請日起約 18 個月才公開，近兩年的申請案尚未全部公開。")
    L.append("     做時間序列分析時應截斷或明確標註，切勿把它當成真實下降。")
    L.append("  2. 論文資料 (company_papers_annual.csv) 自 2022 年起有系統性缺漏，")
    L.append("     來源為 OpenAlex 機構隸屬連結斷裂，非企業行為改變。")
    L.append("     專利資料獨立於 OpenAlex，可作為該時期的對照。")
    L.append("  3. 股票用 CRSP 月資料 (group_A_stocks.csv，AVGO 取自 group_C_stocks.csv)，")
    L.append("     涵蓋 2010-2025 全期。先前版本用 LEVEL4/panel_monthly.csv 是錯的：")
    L.append("     該檔月份由「該月有論文」驅動，AVGO 全期僅 3 個月、TSLA 僅 1 個月。")
    L.append("  4. Alphabet 2014 分割 C 股 (GOOG->GOOGL)、Facebook 2022 更名 (FB->META)，")
    L.append("     兩段在 CRSP 內月份不重疊，已合併為連續序列；論文數亦同樣合併。")
    L.append("  5. annual_excess_return = 個股年報酬 - S&P500 年報酬（buy-and-hold 差額），")
    L.append("     非逐月超額報酬的複利。")
    nfull = sum(1 for r in rows if r["months_in_year"] not in ("", 12))
    if nfull:
        L.append(f"  6. 有 {nfull} 個公司-年度的月數不足 12（上市/更名當年），年報酬非全年。")

    rep = ROOT / "out" / "alignment_report.txt"
    rep.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n寫入 {out}\n寫入 {rep}")


if __name__ == "__main__":
    main()
