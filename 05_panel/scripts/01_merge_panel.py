"""把 CRSP v2 月頻面板與 AI 專利合併成單一分析用面板。

輸出兩個檔（同源、欄位一致，差別只在時間粒度）：

  out/panel_firm_month.csv   公司 x 月   —— 專利用申請月份，真實月頻，非年數攤平
  out/panel_firm_year.csv    公司 x 年   —— 月報酬複利成年報酬，專利與論文加總

為什麼專利可以做到月頻
----------------------
ai_patents_detail.csv 的 filing_date 是 YYYYMMDD（日層級），所以「某公司某月申請了
幾件 AI 專利」是資料裡本來就有的事實，不需要把年度數字平均攤到 12 個月。攤平會製造
不存在的年內變異，讓月頻迴歸的標準誤嚴重低估；這裡沒有這個問題。

但月頻有稀疏性代價：2017-2025 期間 59.2% 的公司-月是 0 件（年頻只有 24.0% 是 0）。
只有 24 家公司在 108 個月裡超過 100 個月有申請。要跑月頻迴歸的話，這個分布要先看過
——對長尾公司而言月頻幾乎全是零，年頻才有訊息。兩個檔都產就是為了讓這個選擇是明示的。

為什麼一律以 permco 為鍵
------------------------
permco 是 CRSP 的「公司」識別碼，permno 是「證券」。一家公司可以有多個股別
（Alphabet 的 GOOGL/GOOG、Moog 的 MOG.A/MOG.B），也可以換過 ticker（FB -> META）。
用 ticker 當鍵會讓換名公司被切成兩段，用 permno 當鍵會讓多股別公司同月出現兩列、
報酬被重複複利。這兩個坑 03_patents/scripts/08_align.py 都踩過，理由詳見該檔。

同月多股別的處理沿用 08_align 的規則，兩者方向相反且都有驗證過：
  報酬 -> 取當月市值最大的股別。相加或平均都不對，那不是任何人可以持有的部位。
  論文 -> 跨股別相加。CRSP 的 n_papers 只掛在其中一個 permno 上
          （Alphabet 2020-01 是 GOOGL 掛 58 篇、GOOG 掛 0），取單一股別會漏掉。

執行：
    03_patents/.venv/bin/python 05_panel/scripts/01_merge_panel.py
工作目錄設在 repo 根。
"""

import collections
import csv
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "03_patents" / "scripts"))
from common import firmkeys  # noqa: E402

V2 = REPO / "data" / "crsp" / "crsp_all_classified_with_papers_detailed_v2.csv"
PAT_DETAIL = REPO / "03_patents" / "out" / "ai_patents_detail.csv"
RAW_PUBS = REPO / "03_patents" / "out" / "raw_publications.csv"
CONFIG = REPO / "03_patents" / "config"
OUT = REPO / "05_panel" / "out"

YM_MIN, YM_MAX = "201701", "202512"

# US pre-grant publication 自申請日起約 18 個月才公開。本資料的最大 publication_date
# 是 2026-04-09，所以 2026-04 往前推 18 個月 = 2024-10 之後的申請月必然不完整。
# 實測吻合：月件數在 202409 是 938，202410 掉到 619，之後一路下滑到 202512 只剩 70。
# 這個下滑是資料尚未公開，不是企業真的減少申請，做時間序列時必須截斷或明確標註。
TRUNC_FROM_YM = "202410"

csv.field_size_limit(10 ** 7)


def load_alias():
    """{assignee_name: [(parent_permco, eff_from, eff_to), ...]}

    一個 assignee 名稱可能對應多家公司（被併購過），靠申請日區間分開。
    """
    out = collections.defaultdict(list)
    for fn in ("company_alias.csv", "subsidiary_alias.csv", "subsidiary_alias_auto.csv"):
        with open(CONFIG / fn, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                f = firmkeys.canon(r["ticker"])
                if f is None:
                    continue
                ef = (r.get("effective_from") or "").replace("-", "") or None
                et = (r.get("effective_to") or "").replace("-", "") or None
                out[r["assignee_name"]].append((f.permco, ef, et))
    return out


def load_ai_patents():
    """{(permco, ym): {"parent_only": n, "with_subs": n}} —— 依申請月份計數。"""
    cnt = collections.defaultdict(lambda: {"parent_only": 0, "with_subs": 0})
    with open(PAT_DETAIL, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            fd = r["filing_date"]
            if len(fd) < 6 or not (YM_MIN <= fd[:6] <= YM_MAX):
                continue
            cnt[(r["permco"], fd[:6])][r["version"]] += 1
    return cnt


def load_all_patents():
    """{(permco, ym): n} —— 全部（非只 AI）publication，作為 AI 佔比的分母。

    一個申請案在同一家公司只計一次（同案可能多次公開），故用 seen 去重。
    """
    alias = load_alias()
    seen = set()
    cnt = collections.Counter()
    with open(RAW_PUBS, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            fd = row["filing_date"]
            if len(fd) < 6 or not (YM_MIN <= fd[:6] <= YM_MAX):
                continue
            for name in (row["matched_assignees"] or "").split("|"):
                for permco, ef, et in alias.get(name, ()):
                    if (ef and fd < ef) or (et and fd > et):
                        continue
                    key = (permco, row["application_number"])
                    if key in seen:
                        continue
                    seen.add(key)
                    cnt[(permco, fd[:6])] += 1
    return cnt


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_v2(roster):
    """串流讀 297 MB 的 v2 檔，回傳 {(permco, ym): 代表列}。

    只留名冊上的 253 家，所以記憶體用量與全市場無關。
    """
    # (permco, ym) -> {permno: (cap, row)}
    cell = collections.defaultdict(dict)
    with open(V2, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            permco = r["permco"]
            if permco not in roster:
                continue
            ym = r["yyyymm"]
            if len(ym) != 6 or not (YM_MIN <= ym <= YM_MAX):
                continue
            cell[(permco, ym)][r["permno"]] = (_f(r["mthcap"]) or 0.0, r)

    out = {}
    n_multi = 0
    for key, permnos in cell.items():
        if len(permnos) > 1:
            n_multi += 1
        _cap, rep = max(permnos.values(), key=lambda v: v[0])   # 報酬取市值最大股別
        papers = sum(int(_f(v[1]["n_papers"]) or 0) for v in permnos.values())
        papers_ax = sum(int(_f(v[1]["n_papers_arxiv"]) or 0) for v in permnos.values())
        out[key] = (rep, papers, papers_ax, len(permnos))
    return out, n_multi


COLS = [
    "permco", "ticker", "company", "yyyymm", "year",
    "mthret", "mthcap", "mthprc", "sprtrn", "vwretd", "n_permno",
    "naics", "naics_4digit", "ai_group", "ai_group_detailed",
    "is_ict_firm", "is_ict_month", "tech_share",
    "n_papers", "n_papers_arxiv",
    "ai_patents_parent_only", "ai_patents_with_subs",
    "all_patents", "ai_share", "patent_truncated",
]


def build_month(v2, ai, allpat, roster):
    """平衡面板：名冊 x 全部月份都出列。

    專利為 0 的公司-月一定要有列且值為 0，不能留空——這些公司都查過了，
    「查了是 0」和「沒查」在迴歸裡意義完全不同。報酬缺值才留空字串。

    只收錄在 v2 裡有資料的公司。名冊上另外 15 家（DELL、BRCM、HIT、PC 等）
    在 2017 年前就下市或 ADR 已終止，v2 從 2017 年起算所以完全沒有它們，
    留著只會是整片空列。
    """
    yms = [f"{y}{m:02d}" for y in range(2017, 2026) for m in range(1, 13)]
    in_v2 = {p for p, _ in v2}
    rows = []
    for permco, f in sorted(roster.items(), key=lambda x: x[1].ticker):
        if permco not in in_v2:
            continue
        for ym in yms:
            hit = v2.get((permco, ym))
            rep, papers, papers_ax, n_pn = hit if hit else (None, "", "", "")
            a = ai.get((permco, ym), {"parent_only": 0, "with_subs": 0})
            tot = allpat.get((permco, ym), 0)
            rows.append({
                "permco": permco,
                "ticker": f.ticker,
                "company": f.name,
                "yyyymm": ym,
                "year": ym[:4],
                "mthret": rep["mthret"] if rep else "",
                "mthcap": rep["mthcap"] if rep else "",
                "mthprc": rep["mthprc"] if rep else "",
                "sprtrn": rep["sprtrn"] if rep else "",
                "vwretd": rep["vwretd"] if rep else "",
                "n_permno": n_pn,
                "naics": rep["naics"] if rep else "",
                "naics_4digit": rep["naics_4digit"] if rep else "",
                "ai_group": rep["ai_group"] if rep else "",
                "ai_group_detailed": rep["ai_group_detailed"] if rep else "",
                "is_ict_firm": rep["is_ict_firm"] if rep else "",
                "is_ict_month": rep["is_ict_month"] if rep else "",
                "tech_share": rep["tech_share"] if rep else "",
                "n_papers": papers,
                "n_papers_arxiv": papers_ax,
                "ai_patents_parent_only": a["parent_only"],
                "ai_patents_with_subs": a["with_subs"],
                "all_patents": tot,
                "ai_share": round(a["with_subs"] / tot, 4) if tot else "",
                "patent_truncated": 1 if ym >= TRUNC_FROM_YM else 0,
            })
    return rows


def build_year(month_rows):
    """月頻 -> 年頻。報酬複利，專利與論文加總。

    annual_excess_return 是 buy-and-hold 差額（個股年報酬 - S&P500 年報酬），
    不是逐月超額報酬的複利，兩者不同。
    """
    acc = collections.OrderedDict()
    for r in month_rows:
        k = (r["permco"], r["year"])
        a = acc.get(k)
        if a is None:
            a = acc[k] = {
                "permco": r["permco"], "ticker": r["ticker"], "company": r["company"],
                "year": r["year"], "_r": 1.0, "_s": 1.0, "months_in_year": 0,
                "n_papers": 0, "n_papers_arxiv": 0,
                "ai_patents_parent_only": 0, "ai_patents_with_subs": 0,
                "all_patents": 0, "_cap": [], "_last": None,
            }
        ret, spr = _f(r["mthret"]), _f(r["sprtrn"])
        if ret is not None and spr is not None:
            a["_r"] *= (1 + ret)
            a["_s"] *= (1 + spr)
            a["months_in_year"] += 1
            a["_last"] = r
            cap = _f(r["mthcap"])
            if cap is not None:
                a["_cap"].append(cap)
        for c in ("n_papers", "n_papers_arxiv", "ai_patents_parent_only",
                  "ai_patents_with_subs", "all_patents"):
            a[c] += int(r[c] or 0)

    out = []
    for a in acc.values():
        m = a["months_in_year"]
        last = a["_last"]
        tot = a["all_patents"]
        out.append({
            "permco": a["permco"], "ticker": a["ticker"], "company": a["company"],
            "year": a["year"],
            "annual_return": round(a["_r"] - 1, 6) if m else "",
            "annual_sp500_return": round(a["_s"] - 1, 6) if m else "",
            "annual_excess_return": round(a["_r"] - a["_s"], 6) if m else "",
            "avg_mthcap": round(sum(a["_cap"]) / len(a["_cap"]), 1) if a["_cap"] else "",
            "months_in_year": m,
            "naics": last["naics"] if last else "",
            "naics_4digit": last["naics_4digit"] if last else "",
            "ai_group": last["ai_group"] if last else "",
            "ai_group_detailed": last["ai_group_detailed"] if last else "",
            "is_ict_firm": last["is_ict_firm"] if last else "",
            "tech_share": last["tech_share"] if last else "",
            "n_papers": a["n_papers"], "n_papers_arxiv": a["n_papers_arxiv"],
            "ai_patents_parent_only": a["ai_patents_parent_only"],
            "ai_patents_with_subs": a["ai_patents_with_subs"],
            "all_patents": tot,
            "ai_share": round(a["ai_patents_with_subs"] / tot, 4) if tot else "",
            # 年內只要有任何一個月落在截斷區就標記，不能等整年都截斷才標
            "patent_truncated": 1 if a["year"] >= TRUNC_FROM_YM[:4] else 0,
        })
    return out


def write(path, rows, cols):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    roster = firmkeys.all_firms()

    print(f"讀 {PAT_DETAIL.name} ...")
    ai = load_ai_patents()
    print(f"讀 {RAW_PUBS.name}（804 MB，約需一兩分鐘）...")
    allpat = load_all_patents()
    print(f"讀 {V2.name}（297 MB）...")
    v2, n_multi = load_v2(roster)

    mrows = build_month(v2, ai, allpat, roster)
    yrows = build_year(mrows)

    write(OUT / "panel_firm_month.csv", mrows, COLS)
    write(OUT / "panel_firm_year.csv", yrows, list(yrows[0]))

    # ---- 涵蓋率報告 ----
    L = []
    in_v2 = {p for p, _ in v2}
    have_ret = sum(1 for r in mrows if r["mthret"] not in ("", None))
    have_pat = sum(1 for r in mrows if r["ai_patents_with_subs"])
    have_pap = sum(1 for r in mrows if r["n_papers"])
    L.append(f"名冊公司: {len(roster)}    收錄（v2 裡有資料的）: {len(in_v2)}")
    L.append(f"期間: {YM_MIN}-{YM_MAX}（108 個月 / 9 年）")
    L.append("")
    L.append(f"panel_firm_month.csv  {len(mrows):,} 列")
    L.append(f"  有月報酬的列:   {have_ret:,} ({have_ret / len(mrows):.1%})")
    L.append(f"  有 AI 專利的列: {have_pat:,} ({have_pat / len(mrows):.1%})")
    L.append(f"  有論文的列:     {have_pap:,} ({have_pap / len(mrows):.1%})")
    L.append("")
    yret = sum(1 for r in yrows if r["annual_return"] != "")
    ypat = sum(1 for r in yrows if r["ai_patents_with_subs"])
    L.append(f"panel_firm_year.csv   {len(yrows):,} 列")
    L.append(f"  有年報酬的列:   {yret:,} ({yret / len(yrows):.1%})")
    L.append(f"  有 AI 專利的列: {ypat:,} ({ypat / len(yrows):.1%})")
    L.append("")
    L.append(f"同月多股別的公司-月（報酬取市值最大股別，論文相加）: {n_multi}")

    dropped = sorted(f.ticker for p, f in roster.items() if p not in in_v2)
    if dropped:
        L.append(f"\n已排除：名冊上但 v2 沒有的公司 {len(dropped)} 家"
                 f"（2017 年前下市或 ADR 終止，v2 自 2017 起算）:")
        L.append(f"  {dropped}")
        lost = sum(v for (p, _ym), v in ai.items() if p not in in_v2
                   for v in (v["with_subs"],))
        L.append(f"  這些公司合計 {lost:,} 件 AI 專利不在本面板內"
                 f"（DELL/PC/HIT/BRCM 等曾是大量申請者）。")

    L.append("\nAI 專利前 20 大（with_subs，2017-2025 合計）")
    by = collections.defaultdict(lambda: [0, 0, 0])
    for r in yrows:
        b = by[(r["ticker"], r["company"])]
        b[0] += r["ai_patents_with_subs"]
        b[1] += r["all_patents"]
        b[2] += r["n_papers"]
    L.append(f"  {'ticker':<8}{'公司':<28}{'AI專利':>8}{'全部專利':>10}{'AI佔比':>8}{'論文':>8}")
    for (tk, nm), (a, t, p) in sorted(by.items(), key=lambda x: -x[1][0])[:20]:
        L.append(f"  {tk:<8}{nm[:26]:<28}{a:>8}{t:>10}"
                 f"{(a / t if t else 0):>8.1%}{p:>8}")

    L.append("\n已知限制")
    L.append(f"  1. filing ym >= {TRUNC_FROM_YM} 的專利數必然低估（pre-grant publication")
    L.append("     約 18 個月後才公開，本資料最大 publication_date 為 2026-04-09）。")
    L.append("     已標在 patent_truncated 欄，切勿把它當成企業真的減少申請。")
    L.append("  2. 論文數自 2022 年起系統性偏低，來源是 OpenAlex 機構隸屬連結斷裂")
    L.append("     （資料瑕疵，非企業行為改變）。專利獨立於 OpenAlex，可作該時期的對照。")
    L.append("  3. 月頻專利稀疏：多數公司-月為 0。長尾公司建議改用年頻檔。")
    L.append("  4. months_in_year < 12 的年度（上市/下市當年）年報酬非全年，")
    L.append("     跑迴歸時建議只取 months_in_year == 12 的列。")
    L.append("  5. ai_share 的分母是該公司該期間全部 publication，分子是 with_subs 版。")

    rep = OUT / "merge_report.txt"
    rep.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n寫入 {OUT / 'panel_firm_month.csv'}")
    print(f"寫入 {OUT / 'panel_firm_year.csv'}")
    print(f"寫入 {rep}")


if __name__ == "__main__":
    main()
