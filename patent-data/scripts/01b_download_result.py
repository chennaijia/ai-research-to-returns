"""把已完成的 BigQuery 查詢結果分頁下載成 out/raw_publications.csv。

**為什麼需要這支腳本。** `01_fetch_publications.py` 用
`bq query --format=csv` 一次把整份結果導出來，在 83 萬列 / 0.8 GB 這個量級會**卡死**：
查詢本身在伺服器端 7 秒就跑完了（job 紀錄可查），但 bq CLI 在把結果透過 REST API
拉回本機時會停在那裡不動——0% CPU、RSS 十幾 MB、放二十分鐘也不會前進。
而且 bq 會把全部輸出緩衝到最後才寫檔，所以過程中檔案一直是 0 bytes，
看起來跟「當掉」一模一樣，非常難診斷。實測分頁 2000 列 6 秒正常，50000 列就卡住。

所以改成：查詢照跑（或直接沿用快取），結果留在 BigQuery 的暫存表，
這支腳本再用 `bq head --start_row` 小批次分頁拉回來。

三個刻意的設計：

  1. **可續傳。** 每一頁單獨落檔在 out/_parts/，跑之前先檢查已存在的頁是否完整，
     完整就跳過。卡住重跑不必從頭來。
  2. **逐頁驗列數。** 每頁都用 csv reader 實際數過（abstract 內含換行，
     數行數會得到錯的數字），列數不符就重抓，不讓半截資料混進去。
  3. **最後對總數。** 合併完的總列數必須等於暫存表 metadata 的 numRows，
     不符就不寫出正式檔。這是「不編造資料」的底線：寧可失敗，
     也不要交出一份悄悄少了幾萬件的檔案。

查詢結果的暫存表由 BigQuery 保留 24 小時。超過就得重跑 01_（會再次命中
或重新掃描），這支腳本會自己去找最近一個成功的查詢 job。

用法：
    python3 scripts/01b_download_result.py              # 自動找最近一個成功的 query job
    python3 scripts/01b_download_result.py <job_id>     # 指定 job
"""

import csv
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = "devjam2026-accesscity-505815"

PAGE = 2000          # 實測 2000 穩定、50000 會卡住；寧可慢也不要卡
TIMEOUT = 180        # 單頁逾時（秒）。正常 6 秒，超過這麼多就是卡住了
RETRY = 4

# 01_fetch_publications.py 的 SELECT 欄位，用來確認抓到的是對的 job
EXPECT = ["publication_number", "application_number", "kind_code", "filing_date",
          "publication_date", "title", "abstract", "cpc_codes", "matched_assignees"]


def bq(args, timeout=60):
    return subprocess.run(["bq", f"--project_id={PROJECT}"] + args,
                          capture_output=True, text=True, timeout=timeout)


def find_job(job_id=None):
    """回傳 (table_ref, n_rows)。沒給 job_id 就找最近一個 schema 相符的成功查詢。"""
    if job_id:
        ids = [job_id]
    else:
        r = bq(["ls", "-j", "-a", "-n", "25", "--format=json"])
        if r.returncode != 0:
            sys.exit(f"列出 job 失敗：{r.stderr}")
        ids = [j["jobReference"]["jobId"] for j in json.loads(r.stdout or "[]")
               if j.get("status", {}).get("state") == "DONE"
               and not j.get("status", {}).get("errorResult")
               and j.get("configuration", {}).get("jobType") == "QUERY"]

    for jid in ids:
        r = bq(["show", "--format=prettyjson", "-j", jid])
        if r.returncode != 0:
            continue
        d = json.loads(r.stdout)
        t = d.get("configuration", {}).get("query", {}).get("destinationTable")
        if not t:
            continue
        ref = f"{t['projectId']}:{t['datasetId']}.{t['tableId']}"
        r2 = bq(["show", "--format=prettyjson", ref])
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
             "可能已過期，請重跑 01_fetch_publications.py --yes")


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


def main():
    ref, n_rows = find_job(sys.argv[1] if len(sys.argv) > 1 else None)
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

    # alias_map.json 由 01_ 產出；這裡補一份，讓 05_ 不必依賴 01_ 跑完
    names = {}
    for fn, tier in (("company_alias.csv", "parent"),
                     ("subsidiary_alias.csv", "subsidiary"),
                     ("subsidiary_alias_auto.csv", "subsidiary")):
        with open(ROOT / "config" / fn, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                names.setdefault(row["assignee_name"],
                                 (tier, row["parent_company"], row["ticker"]))
    (ROOT / "out" / "alias_map.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✓ 寫入 {out}（{total:,} 筆，{out.stat().st_size / 1e9:.2f} GB）")
    print(f"  分頁暫存仍在 {parts}，確認下游跑通後可刪除以釋出磁碟")


if __name__ == "__main__":
    main()
