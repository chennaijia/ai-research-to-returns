"""事後檢查：判定結構合不合理、擴大版跟原本的 8 家版對不對得上。

這支不產生任何資料，只負責回答「剛才那一輪跑出來的東西可信嗎」。
兩段檢查的性質不同：

§1 判定命中結構   看 Block1/2/3 各自貢獻多少、哪些 K2 詞和 C1/C2 代碼在
                  「只靠 Block3 進來」的案件裡出力最多。這是在找**偽陽性的來源**：
                  Block3 是 (C1|C2) AND K2，兩邊都寬鬆，最容易把非 AI 的東西拉進來。
                  需要 out/raw_publications.csv（0.8 GB，不入版控），沒有就跳過。

§2 8 家回歸比對   擴大版換了一整套 alias（自動比對 + 人工裁決取代原本手工挑的名單），
                  如果比對邏輯有錯，最容易看出來的地方就是這 8 家——它們原本是
                  逐一人工查證過的。

                  預期行為是**新版 >= 舊版**：自動比對會替這 8 家補進原本沒列到的
                  子公司（例如 T2_PREFIX 掃到的 MICROSOFT TECH LICENSING LLC），
                  所以件數只會增加。**下降就是警訊**：代表新 alias 漏了原本有的
                  名稱，或併購生效日切錯。有下降時本腳本以 exit code 1 結束。

                  比對以 ticker 為鍵並先過 firmkeys.canon()，因為兩版寫法不同
                  （舊版手寫 "Alphabet"/META，新版取自 CRSP 名冊 "ALPHABET INC"/FB）。
"""

import collections
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import firmkeys  # noqa: E402
from common.wipo import K1, K2, Matcher, compile_terms, load_rules  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPL_MIN = 0.50


# ═══════════════════════════════════════════════════ §1 判定命中結構診斷

def build_matchers(with_repl=True):
    rules = load_rules()
    extra = collections.defaultdict(set)
    if with_repl:
        conc = json.loads((ROOT / "config" / "cpc_concordance.json").read_text(encoding="utf-8"))
        for _d, info in conc["mappings"].items():
            for rep in info["replacements"]:
                if rep["cooccurrence_share"] >= REPL_MIN:
                    for blk in info["wipo_blocks"]:
                        extra[blk].add(rep["symbol"])
    out = {}
    for blk in ("block1_cpc", "c1_cpc", "c2_ipc"):
        b = dict(rules[blk])
        b["exact"] = sorted(set(b["exact"]) | extra[blk])
        out[blk] = Matcher(b)
    return out


def diagnose():
    raw = ROOT / "out" / "raw_publications.csv"
    if not raw.exists():
        print(f"（跳過 §1：找不到 {raw.name}，該檔不入版控，需先跑 05_fetch.py）\n")
        return

    m = build_matchers()
    k1 = compile_terms(K1)
    k2 = compile_terms(K2)
    named_k2 = [(t.slots[0][0], compile_terms([t])) for t in K2]
    named_c = [("c1", m["c1_cpc"]), ("c2", m["c2_ipc"])]

    tot = 0
    only = collections.Counter()
    anyb = collections.Counter()
    k2_drive = collections.Counter()
    c_drive = collections.Counter()
    b1_codes = collections.Counter()
    per_co = collections.defaultdict(lambda: collections.Counter())

    csv.field_size_limit(10**7)
    with open(raw, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            tot += 1
            codes = row["cpc_codes"].split(";") if row["cpc_codes"] else []
            text = (row["title"] or "") + " " + (row["abstract"] or "")
            hit1 = [c for c in codes if m["block1_cpc"](c)]
            b1 = bool(hit1)
            b2 = bool(k1.search(text))
            c_hit = [c for c in codes if m["c1_cpc"](c) or m["c2_ipc"](c)]
            b3 = bool(c_hit) and bool(k2.search(text))

            for name, flag in (("block1", b1), ("block2", b2), ("block3", b3)):
                if flag:
                    anyb[name] += 1
            if b1 or b2 or b3:
                anyb["ANY"] += 1
                lbl = ",".join(n for n, f in (("b1", b1), ("b2", b2), ("b3", b3)) if f)
                only[lbl] += 1
                for c in hit1:
                    b1_codes[c] += 1
            # block3 獨有（b1/b2 都沒中）時，是誰把它拉進來的
            if b3 and not b1 and not b2:
                for nm, rx in named_k2:
                    if rx.search(text):
                        k2_drive[nm] += 1
                for nm, mm in named_c:
                    for c in codes:
                        if mm(c):
                            c_drive[f"{nm}:{c}"] += 1
                            break

            co = (row["matched_assignees"] or "").split("|")[0]
            per_co[co]["tot"] += 1
            if b1 or b2 or b3:
                per_co[co]["ai"] += 1

    print(f"總 publication: {tot}\n")
    print("各 Block 單獨命中數（可重疊）")
    for k in ("block1", "block2", "block3", "ANY"):
        print(f"  {k:<8} {anyb[k]:>7}  {anyb[k]/tot:6.1%}")
    print("\n命中組合分布")
    for k, v in only.most_common():
        print(f"  {k:<12} {v:>7}  {v/tot:6.1%}")

    print("\n只靠 Block3 進來的案件，K2 詞的貢獻 top15")
    for k, v in k2_drive.most_common(15):
        print(f"  {k:<24} {v:>7}")
    print("\n只靠 Block3 進來的案件，C1/C2 代碼貢獻 top15")
    for k, v in c_drive.most_common(15):
        print(f"  {k:<24} {v:>7}")
    print("\nBlock1 命中代碼 top20")
    for k, v in b1_codes.most_common(20):
        print(f"  {k:<20} {v:>7}")


# ═══════════════════════════════════════════════════ §2 8 家回歸比對

TICKERS = ["GOOGL", "AMZN", "AAPL", "AVGO", "META", "MSFT", "NVDA", "TSLA"]
DROP_TOL = 0      # 容許的下降件數；0 = 任何下降都要報出來


def key(ticker):
    """兩版的 ticker 寫法不同，一律收斂成 CRSP 主 ticker 再比。

    舊版（8 家人工表）把 Meta 記成 META，新版依 CRSP 名冊記成 FB。
    不收斂的話 Meta 會變成「舊版有、新版沒有」，被誤判成大幅下降。
    """
    f = firmkeys.canon(ticker)
    return f.ticker if f else ticker


def load_yearly(path):
    """{(version, ticker, year): count}；同一公司的多個舊標籤會被合併相加。

    舊版把一家公司拆成兩個 parent_company 標籤（"Alphabet" 與 "ALPHABET INC"）
    時，同一 (version, ticker, year) 會出現多列，必須累加而非覆蓋。
    """
    out = collections.Counter()
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[(r["version"], key(r["ticker"]), r["filing_year"])] += int(r["ai_patent_count"])
    return out


def compare_8firms():
    old_p = ROOT / "out" / "ai_patents_yearly_8firms.csv"
    new_p = ROOT / "out" / "ai_patents_yearly.csv"
    if not old_p.exists():
        sys.exit(f"找不到舊版備份 {old_p}")
    if not new_p.exists():
        sys.exit(f"找不到新版 {new_p}（擴大版還沒跑完？）")

    old, new = load_yearly(old_p), load_yearly(new_p)
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

    return bool(drops)


def main():
    print("━━━ §1 判定命中結構 ━━━\n")
    diagnose()
    print("\n━━━ §2 8 家回歸比對 ━━━\n")
    if compare_8firms():
        sys.exit(1)


if __name__ == "__main__":
    main()
