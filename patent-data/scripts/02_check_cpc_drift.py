"""驗證 WIPO 2019 AI 檢索式裡的 CPC 代碼是否已被改編（reclassification drift）。

WIPO Technology Trends 2019 的代碼表停在 2018 年的 CPC scheme，
但 Google Patents 帶的是「現行」CPC。若直接套用舊碼，2019 年之後的專利會被大量漏掉。
本腳本只讀不寫，輸出各代碼家族依 filing_year 的命中數。
"""

import collections
import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (標籤, 判定函式)。WIPO 舊碼 vs 現行替代碼成對排列。
PAIRS = [
    ("G06F17/30* (舊: 資訊檢索)", lambda c: c.startswith("G06F17/30")),
    ("G06F16/*  (新)", lambda c: c.startswith("G06F16/")),
    ("G06N99/005 (舊: 機器學習)", lambda c: c == "G06N99/005"),
    ("G06N20/*  (新)", lambda c: c.startswith("G06N20/")),
    ("G06N7/005 (舊: 機率推論)", lambda c: c == "G06N7/005"),
    ("G06N7/01  (新)", lambda c: c == "G06N7/01"),
    ("G06K9/*   (舊: 圖像辨識)", lambda c: c.startswith("G06K9/")),
    ("G06V/*    (新)", lambda c: c.startswith("G06V")),
    ("G06F17/27,28 (舊: 自然語言)", lambda c: c.startswith(("G06F17/27", "G06F17/28"))),
    ("G06F40/*  (新)", lambda c: c.startswith("G06F40/")),
    ("G06F19/*  (舊: 生醫資訊)", lambda c: c.startswith("G06F19/")),
    ("G16B,G16C (新)", lambda c: c.startswith(("G16B", "G16C"))),
    ("G06N3/*   (未改編對照組)", lambda c: c.startswith("G06N3/")),
]

counts = {label: collections.Counter() for label, _ in PAIRS}
years = collections.Counter()

csv.field_size_limit(10**7)
with open(ROOT / "out" / "raw_publications.csv", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh):
        fd = row["filing_date"]
        if not fd or len(fd) < 4:
            continue
        yr = int(fd[:4])
        years[yr] += 1
        codes = row["cpc_codes"].split(";") if row["cpc_codes"] else []
        for label, pred in PAIRS:
            if any(pred(c) for c in codes):
                counts[label][yr] += 1

yrs = sorted(years)
w = max(len(l) for l, _ in PAIRS) + 1
print("每格 = 該 filing year 有幾件 publication 至少帶一個該家族的 CPC\n")
print(" " * w + "".join(f"{y % 100:>6d}" for y in yrs))
print(" " * w + "".join(f"{years[y]:>6d}" for y in yrs) + "   <- 該年總件數")
print("-" * (w + 6 * len(yrs)))
for label, _ in PAIRS:
    print(f"{label:<{w}}" + "".join(f"{counts[label][y]:>6d}" for y in yrs))
