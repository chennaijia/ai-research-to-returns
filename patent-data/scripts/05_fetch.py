"""從 Google Patents BigQuery 抓取名冊上所有公司的美國 pre-grant publications。

輸出 out/raw_publications.csv，一列一件 publication。
母公司與子公司在同一支查詢取回，歸屬與併購生效日留到 07/08 處理。

分成「送出查詢」與「分頁下載」兩步，不是為了好看，是因為一次導出會卡死
------------------------------------------------------------------
`bq query --format=csv` 在 83 萬列 / 0.8 GB 這個量級會**停在那裡不動**：
查詢本身在伺服器端 7 秒就跑完了（job 紀錄可查），但 bq CLI 把結果透過 REST API
拉回本機時會 0% CPU、RSS 十幾 MB、放二十分鐘也不前進。而且 bq 會把全部輸出
緩衝到最後才寫檔，過程中檔案一直是 0 bytes，看起來跟當掉一模一樣，極難診斷。
實測分頁 2000 列 6 秒正常，50000 列就卡住。

所以 --yes 只負責把 job 送出去（結果留在 BigQuery 的暫存表），
--download 再用 `bq head --start_row` 小批次分頁拉回來。

分頁下載的三個刻意設計：

  1. **可續傳。** 每一頁單獨落檔在 out/_parts/，跑之前先檢查已存在的頁是否完整，
     完整就跳過。卡住重跑不必從頭來。
  2. **逐頁驗列數。** 每頁都用 csv reader 實際數過（abstract 內含換行，
     數行數會得到錯的數字），列數不符就重抓，不讓半截資料混進去。
  3. **最後對總數。** 合併完的總列數必須等於暫存表 metadata 的 numRows，
     不符就不寫出正式檔。這是「不編造資料」的底線：寧可失敗，
     也不要交出一份悄悄少了幾萬件的檔案。

查詢結果的暫存表由 BigQuery 保留 24 小時。超過就得重送（會再次命中快取或重新
掃描），--download 會自己去找最近一個欄位相符的成功 job。

用法：
    python3 scripts/05_fetch.py                    # 只做 dry run，估算掃描量
    python3 scripts/05_fetch.py --yes              # 送出查詢
    python3 scripts/05_fetch.py --download         # 分頁拉回結果
    python3 scripts/05_fetch.py --download <job_id>
"""

import csv
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = "devjam2026-accesscity-505815"
FILING_FROM, FILING_TO = 20100101, 20251231
KIND_CODES = ("A1", "A2")

# SELECT 的欄位順序，用來確認 --download 抓到的是對的 job
EXPECT = ["publication_number", "application_number", "kind_code", "filing_date",
          "publication_date", "title", "abstract", "cpc_codes", "matched_assignees"]


def _bq(args, timeout=60):
    return subprocess.run(["bq", f"--project_id={PROJECT}"] + args,
                          capture_output=True, text=True, timeout=timeout)


# ═══════════════════════════════════════════════════ §1 alias（兩階段共用）

def read_alias():
    """抓取階段只需要「要撈哪些 assignee 名稱」，歸屬與生效日留到 07/08 處理。

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


def write_alias_map(names):
    (ROOT / "out" / "alias_map.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════ §2 送出查詢

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


def submit():
    names = read_alias()
    sql = build_sql(names)
    print(f"alias 實體數: {len(names)}", file=sys.stderr)

    dry = _bq(["query", "--use_legacy_sql=false", "--dry_run", sql])
    print(dry.stdout.strip() or dry.stderr.strip(), file=sys.stderr)
    if dry.returncode != 0:
        sys.exit("dry run 失敗，未送出查詢")
    if "--yes" not in sys.argv:
        sys.exit("加上 --yes 才會實際送出查詢")

    # --format=none --max_rows=0：只要 job 跑完、結果落在暫存表即可，
    # 不在這裡導出（導出會卡死，見檔頭說明）。
    res = _bq(["query", "--use_legacy_sql=false", "--format=none", "--max_rows=0", sql],
              timeout=1800)
    if res.returncode != 0:
        sys.exit(res.stderr)

    write_alias_map(names)
    print("✓ 查詢已送出並完成，結果留在 BigQuery 暫存表（保留 24 小時）",
          file=sys.stderr)
    print("  接著跑： python3 scripts/05_fetch.py --download", file=sys.stderr)


# ═══════════════════════════════════════════════════════════ §3 分頁下載

PAGE = 2000          # 實測 2000 穩定、50000 會卡住；寧可慢也不要卡
TIMEOUT = 180        # 單頁逾時（秒）。正常 6 秒，超過這麼多就是卡住了
RETRY = 4


def find_job(job_id=None):
    """回傳 (table_ref, n_rows)。沒給 job_id 就找最近一個 schema 相符的成功查詢。"""
    if job_id:
        ids = [job_id]
    else:
        r = _bq(["ls", "-j", "-a", "-n", "25", "--format=json"])
        if r.returncode != 0:
            sys.exit(f"列出 job 失敗：{r.stderr}")
        ids = [j["jobReference"]["jobId"] for j in json.loads(r.stdout or "[]")
               if j.get("status", {}).get("state") == "DONE"
               and not j.get("status", {}).get("errorResult")
               and j.get("configuration", {}).get("jobType") == "QUERY"]

    for jid in ids:
        r = _bq(["show", "--format=prettyjson", "-j", jid])
        if r.returncode != 0:
            continue
        d = json.loads(r.stdout)
        t = d.get("configuration", {}).get("query", {}).get("destinationTable")
        if not t:
            continue
        ref = f"{t['projectId']}:{t['datasetId']}.{t['tableId']}"
        r2 = _bq(["show", "--format=prettyjson", ref])
        if r2.returncode != 0:
            continue
        td = json.loads(r2.stdout)
        fields = [f["name"] for f in td.get("schema", {}).get("fields", [])]
        if fields != EXPECT:
            continue        # 別的查詢的結果，跳過
        n = int(td.get("numRows", 0))
        print(f"使用 job {jid}\n  結果表 {ref}\n  列數 {n:,}")
        return ref, n
    sys.exit("找不到欄位相符的成功查詢 job。查詢結果暫存表只保留 24 小時，"
             "可能已過期，請重跑 05_fetch.py --yes")


def count_rows(path):
    """實際用 csv parser 數資料列。abstract 內含換行，數行數會得到錯的數字。"""
    csv.field_size_limit(10 ** 7)
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rd = csv.reader(fh)
            head = next(rd, None)
            if head != EXPECT:
                return None
            return sum(1 for _ in rd)
    except (OSError, csv.Error, UnicodeDecodeError):
        return None


def fetch_page(ref, start, want, path):
    for attempt in range(1, RETRY + 1):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                r = subprocess.run(
                    ["bq", f"--project_id={PROJECT}", "head",
                     "-n", str(want), "--start_row", str(start), "--format=csv", ref],
                    stdout=fh, stderr=subprocess.PIPE, text=True, timeout=TIMEOUT)
            if r.returncode == 0 and count_rows(path) == want:
                return True
            err = (r.stderr or "").strip()[:200]
            print(f"    第 {attempt} 次失敗（rc={r.returncode} 列數不符）{err}")
        except subprocess.TimeoutExpired:
            print(f"    第 {attempt} 次逾時（>{TIMEOUT}s，卡在下載）")
        pathlib.Path(path).unlink(missing_ok=True)
    return False


def download(job_id=None):
    ref, n_rows = find_job(job_id)
    parts = ROOT / "out" / "_parts"
    parts.mkdir(parents=True, exist_ok=True)

    starts = list(range(0, n_rows, PAGE))
    print(f"共 {len(starts)} 頁，每頁 {PAGE} 列\n")

    done = 0
    for i, start in enumerate(starts, 1):
        want = min(PAGE, n_rows - start)
        p = parts / f"p{start:09d}.csv"
        if count_rows(p) == want:
            done += want
            continue
        if not fetch_page(ref, start, want, p):
            sys.exit(f"\n✗ 第 {i}/{len(starts)} 頁（start={start}）重試 {RETRY} 次仍失敗。"
                     f"\n  已下載的頁保留在 {parts}，重跑本腳本會從這裡接續。")
        done += want
        if i % 20 == 0 or i == len(starts):
            print(f"  {i}/{len(starts)} 頁，{done:,}/{n_rows:,} 列 "
                  f"({done / n_rows:.1%})")

    # 合併：只留第一頁的表頭
    out = ROOT / "out" / "raw_publications.csv"
    tmp = out.with_suffix(".csv.tmp")
    print(f"\n合併 {len(starts)} 頁 -> {out.name}")
    with open(tmp, "w", encoding="utf-8", newline="") as w:
        for i, start in enumerate(starts):
            with open(parts / f"p{start:09d}.csv", encoding="utf-8", newline="") as r:
                if i:
                    r.readline()        # 表頭只保留一次
                shutil.copyfileobj(r, w)

    total = count_rows(tmp)
    if total != n_rows:
        tmp.unlink(missing_ok=True)
        sys.exit(f"✗ 合併後 {total:,} 列，與結果表的 {n_rows:,} 列不符，未寫出正式檔")
    tmp.replace(out)

    # 補一份 alias_map.json，讓 07 不必依賴 --yes 那一步跑在同一台機器上
    write_alias_map(read_alias())

    print(f"✓ 寫入 {out}（{total:,} 筆，{out.stat().st_size / 1e9:.2f} GB）")
    print(f"  分頁暫存仍在 {parts}，確認下游跑通後可刪除以釋出磁碟")


def main():
    if "--download" in sys.argv:
        rest = [a for a in sys.argv[1:] if not a.startswith("-")]
        download(rest[0] if rest else None)
    else:
        submit()


if __name__ == "__main__":
    main()
