"""從 Google Patents BigQuery 抓取 8 家公司的美國 pre-grant publications。

輸出 out/raw_publications.csv，一列一件 publication。
母公司與子公司在同一支查詢取回，tier 欄位標記來源，併購時點邏輯留到 02 步驟處理。
"""

import csv
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = "devjam2026-accesscity-505815"
FILING_FROM, FILING_TO = 20100101, 20251231
KIND_CODES = ("A1", "A2")


def read_alias():
    """抓取階段只需要「要撈哪些 assignee 名稱」，歸屬與生效日留到 05/07 處理。

    同一個名稱可能分屬多家公司（併購換手，如 BROADCOM CORP），這裡只保留第一筆，
    因為 SQL 的 IN 清單只需要相異名稱。
    """
    names = {}
    for fn, tier in (("company_alias.csv", "parent"),
                     ("subsidiary_alias.csv", "subsidiary"),
                     ("subsidiary_alias_auto.csv", "subsidiary")):
        with open(ROOT / "config" / fn, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                names.setdefault(
                    row["assignee_name"], (tier, row["parent_company"], row["ticker"]))
    return names


def build_sql(names):
    literals = ",\n    ".join("'" + n.replace("'", "\\'") + "'" for n in sorted(names))
    kinds = ", ".join(f"'{k}'" for k in KIND_CODES)
    return f"""
WITH target AS (
  SELECT name FROM UNNEST([
    {literals}
  ]) AS name
),
matched AS (
  SELECT
    p.publication_number,
    p.application_number,
    p.kind_code,
    p.filing_date,
    p.publication_date,
    (SELECT t.text FROM UNNEST(p.title_localized) AS t
      WHERE t.language = 'en' LIMIT 1) AS title,
    (SELECT a.text FROM UNNEST(p.abstract_localized) AS a
      WHERE a.language = 'en' LIMIT 1) AS abstract,
    ARRAY_TO_STRING(ARRAY(
      SELECT DISTINCT c.code FROM UNNEST(p.cpc) AS c ORDER BY c.code
    ), ';') AS cpc_codes,
    ARRAY_TO_STRING(ARRAY(
      SELECT DISTINCT a.name FROM UNNEST(p.assignee_harmonized) AS a
      WHERE a.name IN (SELECT name FROM target) ORDER BY a.name
    ), '|') AS matched_assignees
  FROM `patents-public-data.patents.publications` AS p
  WHERE p.country_code = 'US'
    AND p.kind_code IN ({kinds})
    AND p.filing_date BETWEEN {FILING_FROM} AND {FILING_TO}
    AND EXISTS (
      SELECT 1 FROM UNNEST(p.assignee_harmonized) AS a
      WHERE a.name IN (SELECT name FROM target)
    )
)
SELECT * FROM matched ORDER BY application_number, publication_number
"""


def run(sql, dry_run, stream_to=None):
    """stream_to 給定時直接把 stdout 寫進檔案，不在記憶體裡累積。

    擴大到 268 家後結果約 0.75 GB，capture_output 會先把整份結果讀進記憶體
    再寫檔（bytes + str 兩份，峰值 1.5 GB 以上）。磁碟只剩 2.4 GB 時風險太高。
    """
    cmd = ["bq", f"--project_id={PROJECT}", "query", "--use_legacy_sql=false"]
    if dry_run:
        cmd.append("--dry_run")
    else:
        cmd += ["--format=csv", "--max_rows=1000000"]
    cmd.append(sql)
    if stream_to is None:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    with open(stream_to, "w", encoding="utf-8") as fh:
        return subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE,
                              text=True, check=False)


def main():
    names = read_alias()
    sql = build_sql(names)
    print(f"alias 實體數: {len(names)}", file=sys.stderr)

    dry = run(sql, dry_run=True)
    print(dry.stdout.strip() or dry.stderr.strip(), file=sys.stderr)
    if dry.returncode != 0:
        sys.exit("dry run 失敗，未送出查詢")
    if "--yes" not in sys.argv:
        sys.exit("加上 --yes 才會實際送出查詢")

    out = ROOT / "out" / "raw_publications.csv"
    res = run(sql, dry_run=False, stream_to=out)
    if res.returncode != 0:
        out.unlink(missing_ok=True)     # 別留下半截檔案被下游當成完整資料
        sys.exit(res.stderr)

    # 磁碟寫滿時 bq 仍可能以 0 收場，只是結果被截斷。截斷的檔案流到下游會變成
    # 「憑空少掉的專利」，比直接失敗更難發現，所以這裡自己驗一次。
    problems = []
    if not out.exists() or out.stat().st_size == 0:
        problems.append("輸出檔不存在或為空")
    else:
        with open(out, encoding="utf-8", errors="replace") as fh:
            head = fh.readline()
            if "application_number" not in head:
                problems.append(f"缺少表頭，第一行是: {head[:120]!r}")
            last = None
            for last in fh:
                pass
            if last is not None and not last.endswith("\n"):
                problems.append("最後一行沒有換行，檔案疑似被截斷（磁碟寫滿？）")
    if problems:
        for p in problems:
            print(f"✗ {p}", file=sys.stderr)
        sys.exit("輸出檔未通過完整性檢查，已保留供檢視，請勿讓下游使用")

    alias_map = {n: v for n, v in names.items()}
    (ROOT / "out" / "alias_map.json").write_text(
        json.dumps(alias_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 摘要內含換行，行數 != 記錄數，必須用 csv reader 才是真實筆數
    csv.field_size_limit(10 ** 7)
    with open(out, encoding="utf-8", errors="replace", newline="") as fh:
        n = sum(1 for _ in csv.DictReader(fh))
    print(f"寫入 {out}（{n:,} 筆，{out.stat().st_size / 1e9:.2f} GB）", file=sys.stderr)


if __name__ == "__main__":
    main()
