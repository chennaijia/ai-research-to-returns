"""下載 US pre-grant publications 2010-2025 的完整 assignee 名稱字典。

只跑一次，之後所有名稱比對都在本機做。這樣做的理由：比對規則需要反覆調整
（短名誤配、同名不同公司、更名），若每次都回 BigQuery 掃描，成本與時間都不划算。

輸出 out/assignee_dict.csv: assignee_name, n_publications, first_filing_year, last_filing_year

first/last filing year 是重要的判斷輔助——若某 assignee 只在 2010-2013 出現，
而公司 2018 才上市，多半是同名的不同實體。
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = "devjam2026-accesscity-505815"
FILING_FROM, FILING_TO = 20100101, 20251231
KIND_CODES = ("A1", "A2")
MIN_PUBS = 3   # 只留至少 3 件的 assignee，濾掉個人發明者與一次性實體

SQL = f"""
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


def run(dry_run):
    cmd = ["bq", f"--project_id={PROJECT}", "query", "--use_legacy_sql=false"]
    if dry_run:
        cmd.append("--dry_run")
    else:
        cmd += ["--format=csv", "--max_rows=2000000"]
    cmd.append(SQL)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def main():
    dry = run(dry_run=True)
    print(dry.stdout.strip() or dry.stderr.strip(), file=sys.stderr)
    if dry.returncode != 0:
        sys.exit("dry run 失敗，未送出查詢")
    if "--yes" not in sys.argv:
        sys.exit("加上 --yes 才會實際送出查詢")

    res = run(dry_run=False)
    if res.returncode != 0:
        sys.exit(res.stderr)

    out = ROOT / "out" / "assignee_dict.csv"
    out.write_text(res.stdout, encoding="utf-8")
    n = res.stdout.count("\n") - 1
    print(f"寫入 {out}（{n} 個 assignee）")


if __name__ == "__main__":
    main()
