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
    names = {}
    with open(ROOT / "config" / "company_alias.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            names[row["assignee_name"]] = ("parent", row["parent_company"], row["ticker"])
    with open(ROOT / "config" / "subsidiary_alias.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            names.setdefault(
                row["assignee_name"], ("subsidiary", row["parent_company"], row["ticker"])
            )
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


def run(sql, dry_run):
    cmd = ["bq", f"--project_id={PROJECT}", "query", "--use_legacy_sql=false"]
    if dry_run:
        cmd.append("--dry_run")
    else:
        cmd += ["--format=csv", "--max_rows=1000000"]
    cmd.append(sql)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


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

    res = run(sql, dry_run=False)
    if res.returncode != 0:
        sys.exit(res.stderr)

    out = ROOT / "out" / "raw_publications.csv"
    out.write_text(res.stdout, encoding="utf-8")

    alias_map = {n: v for n, v in names.items()}
    (ROOT / "out" / "alias_map.json").write_text(
        json.dumps(alias_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"寫入 {out}（{res.stdout.count(chr(10)) - 1} 列）", file=sys.stderr)


if __name__ == "__main__":
    main()
