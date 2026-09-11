"""回歸檢查：擴大版跑出來的 8 家數字，要能跟原本的 8 家版對得上。

擴大版換了一整套 alias（自動比對 + 人工裁決取代原本手工挑的名單），
如果比對邏輯有錯，最容易看出來的地方就是這 8 家——它們原本是逐一人工查證過的。

預期行為：
  **新版 >= 舊版**。自動比對會替這 8 家補進原本沒列到的子公司
  （例如 T2_PREFIX 掃到的 MICROSOFT TECH LICENSING LLC 之類），所以件數只會增加。
  **下降就是警訊**：代表新 alias 漏了原本有的名稱，或併購生效日切錯。

比對以 ticker 為鍵，因為 parent_company 的寫法變了
（舊版手寫 "Alphabet"，新版取自 CRSP 名冊 "ALPHABET INC"）。
"""

import collections
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import firmkeys  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TICKERS = ["GOOGL", "AMZN", "AAPL", "AVGO", "META", "MSFT", "NVDA", "TSLA"]
DROP_TOL = 0      # 容許的下降件數；0 = 任何下降都要報出來


def key(ticker):
    """兩版的 ticker 寫法不同，一律收斂成 CRSP 主 ticker 再比。

    舊版（8 家人工表）把 Meta 記成 META，新版依 CRSP 名冊記成 FB。
    不收斂的話 Meta 會變成「舊版有、新版沒有」，被誤判成大幅下降。
    """
    f = firmkeys.canon(ticker)
    return f.ticker if f else ticker


def load(path):
    """{(version, ticker, year): count}；同一公司的多個舊標籤會被合併相加。

    舊版把一家公司拆成兩個 parent_company 標籤（"Alphabet" 與 "ALPHABET INC"）
    時，同一 (version, ticker, year) 會出現多列，必須累加而非覆蓋。
    """
    out = collections.Counter()
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[(r["version"], key(r["ticker"]), r["filing_year"])] += int(r["ai_patent_count"])
    return out


def main():
    old_p = ROOT / "out" / "ai_patents_yearly_8firms.csv"
    new_p = ROOT / "out" / "ai_patents_yearly.csv"
    if not old_p.exists():
        sys.exit(f"找不到舊版備份 {old_p}")
    if not new_p.exists():
        sys.exit(f"找不到新版 {new_p}（擴大版還沒跑完？）")

    old, new = load(old_p), load(new_p)
    years = sorted({k[2] for k in old} | {k[2] for k in new})
    tickers = [key(t) for t in TICKERS]

    drops, rises = [], []
    for ver in ("parent_only", "with_subs"):
        for tk in tickers:
            for y in years:
                o = old.get((ver, tk, y), 0)
                n = new.get((ver, tk, y), 0)
                if o == 0 and n == 0:
                    continue
                if n < o - DROP_TOL:
                    drops.append((ver, tk, y, o, n))
                elif n > o:
                    rises.append((ver, tk, y, o, n))

    print("=== 8 家回歸比對：舊版(人工 alias) vs 新版(自動+人工裁決 alias) ===\n")
    for ver in ("parent_only", "with_subs"):
        print(f"[{ver}] 各公司總件數")
        print(f"  {'ticker':<8}{'舊版':>8}{'新版':>8}{'差異':>9}   {'變化'}")
        for tk in tickers:
            o = sum(v for k, v in old.items() if k[0] == ver and k[1] == tk)
            n = sum(v for k, v in new.items() if k[0] == ver and k[1] == tk)
            d = n - o
            flag = "⚠ 下降" if d < 0 else ("+" if d > 0 else "一致")
            pct = f"{d / o:+.1%}" if o else "—"
            print(f"  {tk:<8}{o:>8}{n:>8}{d:>+9}   {flag} {pct}")
        print()

    if drops:
        print(f"⚠ 有 {len(drops)} 個公司-年度下降（新 alias 可能漏了名稱或切錯併購日）：")
        for ver, tk, y, o, n in drops[:25]:
            print(f"    {ver:<12}{tk:<7}{y}  {o} -> {n}")
        if len(drops) > 25:
            print(f"    ...另外 {len(drops) - 25} 筆")
    else:
        print("✓ 沒有任何公司-年度下降")
    print(f"\n上升的公司-年度: {len(rises)} 個（自動比對補進子公司，屬預期）")

    # AVGO/BRCM 併購切分專項檢查：BRCM 在 2016 前應該要有專利
    brcm = {y: new.get(("with_subs", key("BRCM"), y), 0) for y in years}
    have = {y: v for y, v in brcm.items() if v}
    print("\n[併購切分檢查] BRCM（舊博通，2016-02 被 Avago 收購）各年 AI 專利：")
    if have:
        print("   " + "  ".join(f"{y}:{v}" for y, v in sorted(have.items())))
        late = {y: v for y, v in have.items() if y >= "2016"}
        print(f"   2016 年(含)以後仍有 {sum(late.values())} 件"
              f"{'（申請日切在 2016-01-31，2016 年初的申請屬正常）' if late else ''}")
    else:
        print("   ⚠ 完全沒有——切分可能失敗，舊博通的專利全被算到 AVGO 頭上了")

    if drops:
        sys.exit(1)


if __name__ == "__main__":
    main()
