"""從 CRSP 月資料擷取公司名冊，作為擴大版 assignee 比對的左表。

以 permco（公司層級 ID）為單位，而非 permno（證券層級）——同一家公司可能有多個
證券（如 Alphabet 的 GOOG/GOOGL），必須合併成一家。

同時保留 issuernm 的**所有歷史變體**：CRSP 會隨公司更名而改值，例如
FACEBOOK INC -> META PLATFORMS INC。專利的 assignee 記錄的是**申請當時**的名稱，
所以舊名同樣要納入比對，否則會漏掉更名前的專利。

輸出 out/firm_roster.csv，一列一家公司。
"""

import collections
import csv
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent
SRC = REPO / "stock_and_paper_count"

# group_C 是 CRSP 全市場檔（19,460 家），只取名冊裡缺的少數幾家，不整份納入
EXTRA_FROM_GROUP_C = {"AVGO"}   # Broadcom 不在 group_A/B，但屬於原始 8 家研究對象

FILES = [
    ("A", SRC / "group_A_stocks.csv"),
    ("B_ICT", SRC / "group_B_INFO_COMMU_TECH.csv"),
    ("B_OTHER", SRC / "group_B_OTHER.csv"),
]


def blank():
    return {
        "names": collections.Counter(),
        "tickers": collections.Counter(),
        "groups": set(),
        "papers": 0,
        "months": 0,
        "ym": [],
        "naics": collections.Counter(),
    }


def absorb(firms, group, path, only_tickers=None):
    if not path.exists():
        return f"找不到 {path}"
    with open(path, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            tk = r["ticker"].strip()
            if only_tickers is not None and tk not in only_tickers:
                continue
            f = firms[r["permco"].strip()]
            nm = r["issuernm"].strip()
            if nm:
                f["names"][nm] += 1
            if tk:
                f["tickers"][tk] += 1
            f["groups"].add(group)
            f["months"] += 1
            f["ym"].append(r["yyyymm"])
            f["papers"] += int(r["n_papers"] or 0)
            nc = (r.get("naics") or "").strip()
            if nc and nc != "0":       # CRSP 用 0 表示缺值，不是 NA
                f["naics"][nc] += 1
    return None


def main():
    firms = collections.defaultdict(blank)
    problems = []
    for g, p in FILES:
        e = absorb(firms, g, p)
        if e:
            problems.append(e)
    e = absorb(firms, "C_extra", SRC / "group_C_stocks.csv", only_tickers=EXTRA_FROM_GROUP_C)
    if e:
        problems.append(e)

    rows = []
    for permco, f in firms.items():
        # 主名稱取出現月數最多者；其餘為歷史變體
        names = [n for n, _ in f["names"].most_common()]
        ticks = [t for t, _ in f["tickers"].most_common()]
        rows.append({
            "permco": permco,
            "primary_name": names[0] if names else "",
            "all_names": "|".join(names),
            "n_names": len(names),
            "primary_ticker": ticks[0] if ticks else "",
            "all_tickers": "|".join(ticks),
            "groups": ",".join(sorted(f["groups"])),
            "naics": f["naics"].most_common(1)[0][0] if f["naics"] else "",
            "ym_min": min(f["ym"]) if f["ym"] else "",
            "ym_max": max(f["ym"]) if f["ym"] else "",
            "months": f["months"],
            "papers": f["papers"],
        })
    rows.sort(key=lambda r: (-r["papers"], r["primary_name"]))

    out = ROOT / "out" / "firm_roster.csv"
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    renamed = [r for r in rows if r["n_names"] > 1]
    multi_tk = [r for r in rows if len(r["all_tickers"].split("|")) > 1]
    print(f"公司數 (permco): {len(rows)}")
    print(f"相異 ticker:     {len({t for r in rows for t in r['all_tickers'].split('|') if t})}")
    print(f"有論文的公司:    {sum(1 for r in rows if r['papers'] > 0)}")
    print(f"曾更名的公司:    {len(renamed)}")
    print(f"多 ticker 的公司: {len(multi_tk)}")
    for e in problems:
        print(f"⚠ {e}")

    print("\n曾更名的公司（舊名同樣要納入 assignee 比對）")
    for r in renamed[:25]:
        print(f"  {r['primary_ticker']:<8}{r['all_names'][:78]}")

    print("\n論文數 top 15")
    for r in rows[:15]:
        print(f"  {r['primary_ticker']:<8}{r['primary_name'][:36]:<38}{r['papers']:>6}  {r['groups']}")

    print(f"\n寫入 {out}")


if __name__ == "__main__":
    main()
