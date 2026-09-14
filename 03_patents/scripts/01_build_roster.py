"""建立比對的左右兩張表：CRSP 公司名冊，以及 BigQuery assignee 名稱字典。

    左表 out/firm_roster.csv    我們要找的 268 家公司（含所有歷史名稱與代號）
    右表 out/assignee_dict.csv  專利資料裡實際出現過的所有專利權人名稱

後面 02 就是拿這兩張表互相比對。分成左右表來想，是因為這兩邊的性質完全不同：
左表小而權威（CRSP 給的），右表大而髒（自由文字，含大量拼錯與子公司實體）。

用法：
    python3 scripts/01_build_roster.py          # 只建左表（純本機，秒級）
    python3 scripts/01_build_roster.py --yes    # 左表 + 下載右表（需 BigQuery 認證）
    python3 scripts/01_build_roster.py --yes --force-dict   # 強制重新下載右表
"""

import collections
import csv
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent
SRC = REPO / "01_universe" / "out"


# ════════════════════════════════════════════════════ 左表：CRSP 公司名冊
#
# 以 permco（公司層級 ID）為單位，而非 permno（證券層級）——同一家公司可能有多個
# 證券（如 Alphabet 的 GOOG/GOOGL），必須合併成一家。
#
# 同時保留 issuernm 的**所有歷史變體**：CRSP 會隨公司更名而改值，例如
# FACEBOOK INC -> META PLATFORMS INC。專利的 assignee 記錄的是**申請當時**的名稱，
# 所以舊名同樣要納入比對，否則會漏掉更名前的專利。

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


def build_roster():
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


# ══════════════════════════════════════════ 右表：BigQuery assignee 名稱字典
#
# 只跑一次，之後所有名稱比對都在本機做。這樣做的理由：比對規則需要反覆調整
# （短名誤配、同名不同公司、更名），若每次都回 BigQuery 掃描，成本與時間都不划算。
#
# first/last filing year 是重要的判斷輔助——若某 assignee 只在 2010-2013 出現，
# 而公司 2018 才上市，多半是同名的不同實體。

PROJECT = "devjam2026-accesscity-505815"
FILING_FROM, FILING_TO = 20100101, 20251231
KIND_CODES = ("A1", "A2")
MIN_PUBS = 3   # 只留至少 3 件的 assignee，濾掉個人發明者與一次性實體

DICT_SQL = f"""
SELECT
  a.name AS assignee_name,
  COUNT(DISTINCT p.application_number) AS n_publications,
  MIN(CAST(SUBSTR(CAST(p.filing_date AS STRING), 1, 4) AS INT64)) AS first_filing_year,
  MAX(CAST(SUBSTR(CAST(p.filing_date AS STRING), 1, 4) AS INT64)) AS last_filing_year
FROM `patents-public-data.patents.publications` AS p,
     UNNEST(p.assignee_harmonized) AS a
WHERE p.country_code = 'US'
  AND p.kind_code IN ({", ".join(f"'{k}'" for k in KIND_CODES)})
  AND p.filing_date BETWEEN {FILING_FROM} AND {FILING_TO}
  AND a.name IS NOT NULL
  AND a.name != ''
GROUP BY assignee_name
HAVING n_publications >= {MIN_PUBS}
ORDER BY n_publications DESC
"""


def _bq_query(dry_run):
    cmd = ["bq", f"--project_id={PROJECT}", "query", "--use_legacy_sql=false"]
    if dry_run:
        cmd.append("--dry_run")
    else:
        cmd += ["--format=csv", "--max_rows=2000000"]
    cmd.append(DICT_SQL)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def fetch_assignee_dict(force=False):
    out = ROOT / "out" / "assignee_dict.csv"
    if out.exists() and not force:
        print(f"\n{out.name} 已存在，跳過下載（要重抓加 --force-dict）")
        return

    dry = _bq_query(dry_run=True)
    print(dry.stdout.strip() or dry.stderr.strip(), file=sys.stderr)
    if dry.returncode != 0:
        sys.exit("dry run 失敗，未送出查詢")

    res = _bq_query(dry_run=False)
    if res.returncode != 0:
        sys.exit(res.stderr)

    out.write_text(res.stdout, encoding="utf-8")
    n = res.stdout.count("\n") - 1
    print(f"寫入 {out}（{n} 個 assignee）")


def main():
    build_roster()
    if "--yes" in sys.argv:
        fetch_assignee_dict(force="--force-dict" in sys.argv)
    else:
        print("\n（未加 --yes，略過 assignee 字典下載；該步驟需要 BigQuery 認證）")


if __name__ == "__main__":
    main()
