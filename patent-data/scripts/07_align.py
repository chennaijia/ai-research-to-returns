"""把 AI 專利資料對齊 repo 既有的股票與論文資料，輸出公司-年度面板。

輸出 out/patent_stock_paper_annual.csv:
  permco, parent_company, ticker, year,
  ai_patents_parent_only, ai_patents_with_subs,
  all_patents_with_subs, ai_share,
  n_papers, annual_return, annual_sp500_return, annual_excess_return,
  months_in_year, patent_truncated

為什麼一律以 permco 為鍵
------------------------
permco 是 CRSP 的「公司」識別碼，permno 是「證券」。一家公司可以有多個股別
（Alphabet 的 GOOGL/GOOG、Moog 的 MOG.A/MOG.B、Zillow 的 Z/ZG），也可以換過
ticker（FB -> META、GOOG -> GOOGL）。用 ticker 當鍵會同時犯兩個錯：

  1. 換名的公司被切成兩段。Meta 在 CRSP 名冊的主 ticker 是 FB，先前版本卻
     寫死 TICKER_HISTORY = {"META": ["FB","META"]}，查表時用的是 "FB"，
     所以 2022 年後的 META 月份全數遺失（2023-2025 年報酬整欄空白）。
  2. 多股別的公司同月出現兩列，報酬被重複複利。

改以 permco 後這兩件事都自動消失，TICKER_HISTORY 那張硬編碼表也不再需要。

股票與論文都取自 stock_and_paper_count/ 的 CRSP 月檔（四個 group 檔才涵蓋
全部 268 家；先前只讀 group_A + group_C 是 8 家版的遺留，導致只有 6.6% 的
公司-年度有報酬）。不用 LEVEL4/panel_monthly.csv——後者的月份是由「該月有
論文」驅動的，AVGO 全期只有 3 個月、TSLA 只有 1 個月，複利成年報酬會嚴重失真。

同時輸出 out/alignment_report.txt 記錄涵蓋率與已知問題。
"""

import collections
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import firmkeys  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent

# pre-grant publication 自申請日起約 18 個月才公開，故最近兩個 filing year 必然不完整
TRUNC_FROM = 2024

YEARS = [str(y) for y in range(2010, 2026)]

# 四個檔合起來才覆蓋名冊全部 268 家（A 只命中 7 家、C 只多補 1 家，
# 主力在兩個 B 檔）。同一個 permno-月份可能同時出現在多個檔，需全域去重。
STOCK_FILES = [
    REPO / "stock_and_paper_count" / "group_A_stocks.csv",
    REPO / "stock_and_paper_count" / "group_B_INFO_COMMU_TECH.csv",
    REPO / "stock_and_paper_count" / "group_B_OTHER.csv",
    REPO / "stock_and_paper_count" / "group_C_stocks.csv",
]


def load_alias():
    """{assignee_name: [(tier, parent, ticker, permco, eff_from, eff_to), ...]}

    一個 assignee 可對應多家公司，靠申請日區間分開（見 05_classify.load_alias 說明）。
    公司標籤一律過 firmkeys.canon() 收斂，理由同 05。
    """
    out = collections.defaultdict(list)
    for fn, tier in (("company_alias.csv", "parent"),
                     ("subsidiary_alias.csv", "subsidiary"),
                     ("subsidiary_alias_auto.csv", "subsidiary")):
        with open(ROOT / "config" / fn, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                f = firmkeys.canon(r["ticker"])
                if f is None:
                    continue
                ef = (r.get("effective_from") or "").replace("-", "") or None
                et = (r.get("effective_to") or "").replace("-", "") or None
                out[r["assignee_name"]].append(
                    (tier, f.name, f.ticker, f.permco, ef, et))
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
                for _tier, _parent, _tk, permco, ef, et in alias.get(name, ()):
                    if (ef and fd < ef) or (et and fd > et):
                        continue
                    key = (permco, row["application_number"])
                    if key in seen:
                        continue
                    seen.add(key)
                    cnt[(permco, fd[:4])] += 1
    return cnt


def load_ai():
    """{(permco, year): {version: count}}"""
    ai = collections.defaultdict(dict)
    with open(ROOT / "out" / "ai_patents_yearly.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ai[(r["permco"], r["filing_year"])][r["version"]] = int(r["ai_patent_count"])
    return ai


def load_stock():
    """讀四個 CRSP group 月檔，回傳 (年報酬表, 論文表, 警告清單)。

    報酬：同一 (permco, 月份) 若有多個股別，取當月市值最大的那一個當代表。
      直接相加或平均都不對——那不是任何人可以持有的部位。實測有 604 個
      公司-月份是雙股別（Moog A/B、Shell A/B、Alphabet GOOG/GOOGL、Zillow Z/ZG），
      同月兩股別的報酬幾乎相同，取大股別是標準做法。

    論文：反過來要**相加**。CRSP 檔的 n_papers 只掛在其中一個 permno 上
      （Alphabet 2020-01 是 GOOGL 掛 58 篇、GOOG 掛 0），取單一股別會漏掉。
      已全檔驗證：604 個雙股別月份中，沒有任何一個月是兩個 permno 同時有論文，
      故相加不會重複計算。與 analysis/out/company_papers_annual.csv 交叉比對，
      GOOGL/MSFT/NVDA/FB/AMZN 2020 年完全相同。
    """
    warn = []
    # (permco, ym) -> {permno: (cap, ret, sprtrn, papers)}
    cell = collections.defaultdict(dict)
    csv.field_size_limit(10**7)
    for p in STOCK_FILES:
        if not p.exists():
            warn.append(f"找不到 {p}")
            continue
        with open(p, encoding="utf-8", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                f = firmkeys.by_permco(r["permco"])
                if f is None:                      # 不在名冊的公司，略過
                    continue
                ym = r["yyyymm"]
                if len(ym) != 6 or not (YEARS[0] <= ym[:4] <= YEARS[-1]):
                    continue
                try:
                    ret = float(r["mthret"])
                    spr = float(r["sprtrn"])
                except (ValueError, TypeError):
                    continue                       # 缺報酬的月份不計入
                try:
                    cap = float(r["mthcap"])
                except (ValueError, TypeError):
                    cap = 0.0
                try:
                    pap = int(float(r["n_papers"] or 0))
                except (ValueError, TypeError):
                    pap = 0
                # 同一 permno-月份跨檔重複時直接覆寫（各檔數值相同，實測一致）
                cell[(f.permco, ym)][r["permno"]] = (cap, ret, spr, pap)

    acc = collections.defaultdict(lambda: [1.0, 1.0, 0])   # (permco,year) -> [個股, 大盤, 月數]
    papers = collections.Counter()                          # (permco,year) -> 論文數
    n_multi = 0
    for (permco, ym), permnos in cell.items():
        if len(permnos) > 1:
            n_multi += 1
        cap, ret, spr, _ = max(permnos.values(), key=lambda v: v[0])
        a = acc[(permco, ym[:4])]
        a[0] *= (1 + ret)
        a[1] *= (1 + spr)
        a[2] += 1
        papers[(permco, ym[:4])] += sum(v[3] for v in permnos.values())
    return acc, papers, warn, n_multi


def main():
    ai = load_ai()
    tot = total_patents()
    acc, papers, warn, n_multi = load_stock()
    firms = firmkeys.all_firms()

    # 平衡面板：268 家 x 16 年全部出列。AI 專利為 0 的公司-年度也要有列（值為 0），
    # 否則迴歸會把「零」誤當成缺值。報酬缺值則留空字串，兩者意義不同。
    rows = []
    for permco, f in sorted(firms.items(), key=lambda x: x[1].ticker):
        for yr in YEARS:
            a = acc.get((permco, yr))
            r = (a[0] - 1, a[1] - 1, a[2]) if a else None
            cell_ai = ai.get((permco, yr), {})
            n_tot = tot.get((permco, yr), 0)
            n_sub = cell_ai.get("with_subs", 0)
            rows.append({
                "permco": permco,
                "parent_company": f.name,
                "ticker": f.ticker,
                "year": yr,
                "ai_patents_parent_only": cell_ai.get("parent_only", 0),
                "ai_patents_with_subs": n_sub,
                "all_patents_with_subs": n_tot,
                "ai_share": round(n_sub / n_tot, 4) if n_tot else "",
                "n_papers": papers.get((permco, yr), 0),
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
    n_ret = sum(1 for r in rows if r["annual_return"] != "")
    n_pap = sum(1 for r in rows if r["n_papers"])
    n_pat = sum(1 for r in rows if r["ai_patents_with_subs"])
    L.append(f"公司數: {len(firms)}    年度: {YEARS[0]}-{YEARS[-1]}    "
             f"公司-年度列數: {len(rows)}")
    L.append(f"有股票年報酬的列: {n_ret} ({n_ret / len(rows):.1%})")
    L.append(f"有論文數的列:     {n_pap} ({n_pap / len(rows):.1%})")
    L.append(f"有 AI 專利的列:   {n_pat} ({n_pat / len(rows):.1%})")
    L.append(f"有 AI 專利的公司: {len({r['permco'] for r in rows if r['ai_patents_with_subs']})}")
    L.append(f"多股別的公司-月份（取市值最大股別）: {n_multi}")
    for w_ in warn:
        L.append(f"⚠ 股票資料: {w_}")

    nofull = sorted({(r["ticker"], r["parent_company"]) for r in rows
                     if r["annual_return"] == ""} -
                    {(r["ticker"], r["parent_company"]) for r in rows
                     if r["annual_return"] != ""})
    if nofull:
        L.append(f"\n完全沒有任何年報酬的公司 {len(nofull)} 家: "
                 f"{[t for t, _ in nofull][:20]}")

    L.append("\nAI 專利件數前 25 大（with_subs 全期合計）")
    by = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows:
        b = by[(r["ticker"], r["parent_company"])]
        b[0] += r["ai_patents_with_subs"]
        b[1] += r["all_patents_with_subs"]
        b[2] += r["n_papers"]
    L.append(f"  {'ticker':<8}{'公司':<26}{'AI專利':>8}{'全部專利':>10}{'AI佔比':>8}{'論文':>8}")
    for (tk, nm), (a, t, p) in sorted(by.items(), key=lambda x: -x[1][0])[:25]:
        L.append(f"  {tk:<8}{nm[:24]:<26}{a:>8}{t:>10}"
                 f"{(a / t if t else 0):>8.1%}{p:>8}")

    L.append("\n已知限制")
    L.append(f"  1. filing_year >= {TRUNC_FROM} 的專利數必然低估：US pre-grant publication")
    L.append("     自申請日起約 18 個月才公開，近兩年的申請案尚未全部公開。")
    L.append("     做時間序列分析時應截斷或明確標註，切勿把它當成真實下降。")
    L.append("  2. 論文資料自 2022 年起有系統性缺漏，來源為 OpenAlex 機構隸屬連結斷裂，")
    L.append("     非企業行為改變。專利資料獨立於 OpenAlex，可作為該時期的對照。")
    L.append("  3. 股票與論文皆取自 stock_and_paper_count/ 的四個 CRSP group 月檔，")
    L.append("     以 permco（公司層級）為鍵，涵蓋名冊全部 268 家。")
    L.append("  4. 同月多股別者取市值最大股別的報酬（不可相加，那不是可持有的部位）；")
    L.append("     論文則跨股別相加（已驗證同月不會有兩個股別同時掛論文）。")
    L.append("  5. annual_excess_return = 個股年報酬 - S&P500 年報酬（buy-and-hold 差額），")
    L.append("     非逐月超額報酬的複利。")
    nfull = sum(1 for r in rows if r["months_in_year"] not in ("", 12))
    L.append(f"  6. 有 {nfull} 個公司-年度的月數不足 12（上市/下市/更名當年），年報酬非全年，")
    L.append("     已放在 months_in_year 欄，迴歸時建議只用 months_in_year == 12 的列。")

    rep = ROOT / "out" / "alignment_report.txt"
    rep.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n寫入 {out}\n寫入 {rep}")


if __name__ == "__main__":
    main()
