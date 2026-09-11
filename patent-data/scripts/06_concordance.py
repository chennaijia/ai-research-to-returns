"""處理 CPC 代碼改編（reclassification drift）：先診斷，再推導新舊對照表。

為什麼需要這一步
----------------
WIPO Technology Trends 2019 的 AI 代碼表停在 2018 年的 CPC scheme，
但 Google Patents 帶的是「現行」CPC。USPTO 會廢止舊碼並把文件重新掛上新碼
（G06K9 -> G06V/G06F18、G06F17/30 -> G06F16、G06N99/005 -> G06N20…）。
若直接套用 2019 年的舊碼，2019 年之後的專利會被大量漏掉。

§1 診斷：把 WIPO 舊碼與現行替代碼成對排開，看各自逐年的命中數。
        舊碼逐年歸零、新碼同時竄起，就是改編發生的直接證據。只讀不寫。

§2 推導：證據來源三層
        1. 官方 CPC scheme 快照（patents-public-data.cpc）：舊碼存在於 2017.10、
           消失於現行版 -> 證明「被廢止」，這是外部權威來源，非本腳本推論
        2. 追溯重分類事實：USPTO 廢止代碼時會把舊文件重新掛上新碼，
           因此帶舊碼的文件同時帶有新碼 -> 由共現關係推導「替代為何」
        3. 標題延續：部分新碼直接沿用舊碼措辭

兩段共用同一趟 raw_publications.csv 掃描（0.8 GB，掃兩次不划算）。
本檔只讀 out/ 下既有檔案，不呼叫任何 API。

輸出：
    out/concordance_report.txt     人工複核用
    config/cpc_concordance.json    供 07 使用
"""

import collections
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common.wipo import Matcher, load_rules, load_symbols  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIN_SHARE = 0.30  # 共現率門檻：至少三成帶舊碼的文件也帶該新碼才視為替代候選


# ══════════════════════════════════════════════ §1 改編診斷用的代碼家族
#
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


# ═══════════════════════════════════════════════ §2 官方轉移目標約束
#
# 共現率本身無法區分「取代」與「互補」——例如手勢辨識專利同時帶
# 舊碼 G06K9/00355(手勢辨識) 與 G06F3/017(手勢輸入介面)，兩者是互補而非取代。
# 因此先用官方 CPC scheme 證據把候選限制在確實接收該次改編的子類，再用共現率細分子群。
#
# 證據（皆可由 patents-public-data.cpc 快照與官方標題查證，見 out/concordance_report.txt）:
#   G06K9   -> G06V / G06F18   CPC Notice of Changes RP0760 (2022-01)；
#                              G06V10/00 dateRevised 2023-08-01、G06F18/00「Pattern recognition」
#   G06F17/30 -> G06F16        G06F16/00「Information retrieval; Database structures therefor」
#                              dateRevised 2019-01-01，標題延續舊碼措辭
#   G06F17/27,28 -> G06F40     G06F40/00「Handling natural language data」dateRevised 2020-01-01
#   G06N99/005, G06F15/18 -> G06N20   G06N20/00「Machine learning」
#   G06N7/005 -> G06N7/01      G06N7/01「Probabilistic graphical models, e.g. probabilistic networks」
#                              dateRevised 2023-01-01，標題保留舊碼「probabilistic networks」
#   G06F19  -> G16B/G16C/G16H  G16B「ICT specially adapted for bioinformatics」
TRANSFER_TARGETS = [
    ("G06K9/", ("G06V", "G06F18/")),
    ("G06F17/30", ("G06F16/",)),
    ("G06F17/27", ("G06F40/",)),
    ("G06F17/28", ("G06F40/",)),
    ("G06N99/", ("G06N20/",)),
    ("G06F15/18", ("G06N20/",)),
    ("G06N7/", ("G06N7/", "G06N20/")),
    ("G06N3/", ("G06N3/",)),
    ("G06N5/", ("G06N5/",)),
    ("G06F19/", ("G16B", "G16C", "G16H")),
    ("G10L13/", ("G10L13/",)),
    ("G10L15/", ("G10L15/",)),
    ("G10L17/", ("G10L17/",)),
]


def allowed_targets(dead_symbol):
    """回傳該廢止碼允許的替代碼前綴；找不到對應則回傳 None（不推導）。"""
    for old, new in TRANSFER_TARGETS:
        if dead_symbol.startswith(old):
            return new
    return None


# ══════════════════════════════════════════════════════════ 掃描與輸出

def scan(dead_set, cur):
    """掃一趟 raw_publications.csv，同時累積 §1 的逐年統計與 §2 的共現統計。"""
    drift = {label: collections.Counter() for label, _ in PAIRS}
    years = collections.Counter()
    co = collections.defaultdict(collections.Counter)
    base = collections.Counter()

    csv.field_size_limit(10**7)
    with open(ROOT / "out" / "raw_publications.csv", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            codes = row["cpc_codes"].split(";") if row["cpc_codes"] else []

            # §1 逐年漂移
            fd = row["filing_date"]
            if fd and len(fd) >= 4:
                yr = int(fd[:4])
                years[yr] += 1
                for label, pred in PAIRS:
                    if any(pred(c) for c in codes):
                        drift[label][yr] += 1

            # §2 舊碼 x 現行碼共現
            if not codes:
                continue
            present = [c for c in codes if c in dead_set]
            if not present:
                continue
            live = [c for c in codes if c in cur]
            for d in present:
                base[d] += 1
                # 一定要 sorted：set 的迭代順序受 Python 字串 hash 隨機化影響，
                # 每次執行都不同。順序會進到 Counter 的插入順序，再影響下面
                # 同分候選的排序，最後被 [:8] 截出不同的替代碼集合——
                # 同一份輸入跑兩次會得到不同的 cpc_concordance.json。
                for c in sorted(set(live)):
                    co[d][c] += 1

    return drift, years, co, base


def print_drift(drift, years):
    yrs = sorted(years)
    w = max(len(l) for l, _ in PAIRS) + 1
    print("每格 = 該 filing year 有幾件 publication 至少帶一個該家族的 CPC\n")
    print(" " * w + "".join(f"{y % 100:>6d}" for y in yrs))
    print(" " * w + "".join(f"{years[y]:>6d}" for y in yrs) + "   <- 該年總件數")
    print("-" * (w + 6 * len(yrs)))
    for label, _ in PAIRS:
        print(f"{label:<{w}}" + "".join(f"{drift[label][y]:>6d}" for y in yrs))


def main():
    rules = load_rules()
    cur = load_symbols(ROOT / "out" / "cpc_current.csv")
    old = load_symbols(ROOT / "out" / "cpc_201710.csv")

    matchers = {k: Matcher(rules[k]) for k in ("block1_cpc", "c1_cpc", "c2_ipc")}

    # 步驟 1：WIPO 清單涵蓋、且已從現行 CPC 消失的代碼
    dead = {}
    for sym, title in old.items():
        if sym in cur:
            continue
        hit = [k for k, m in matchers.items() if m(sym)]
        if hit:
            dead[sym] = {"title_2017": title, "wipo_blocks": hit}

    drift, years, co, base = scan(set(dead), cur)

    print_drift(drift, years)

    print(f"\nWIPO 清單涵蓋、且已被現行 CPC 廢止的代碼: {len(dead)} 個\n")
    fam = collections.Counter(s.split("/")[0] for s in dead)
    for f, n in fam.most_common():
        print(f"  {f:<12} {n:>4} 個子群")

    # 步驟 3：彙整成家族層級的對照表
    conc = {}
    lines = []
    n_no_target = 0
    for d in sorted(dead, key=lambda s: -base[s]):
        n = base[d]
        if n == 0:
            continue
        tgt = allowed_targets(d)
        if tgt is None:
            n_no_target += 1
            continue
        # 明確指定「先比次數再比代碼字串」，不倚賴 Counter 的插入順序
        ranked = sorted(co[d].items(), key=lambda x: (-x[1], x[0]))[:30]
        cands = [(c, k / n) for c, k in ranked
                 if k / n >= MIN_SHARE and c.startswith(tgt)][:8]
        conc[d] = {
            "title_2017": dead[d]["title_2017"],
            "wipo_blocks": dead[d]["wipo_blocks"],
            "docs_with_obsolete_code": n,
            "replacements": [
                {"symbol": c, "cooccurrence_share": round(s, 3),
                 "title_current": cur.get(c, "")}
                for c, s in cands
            ],
        }
        lines.append(f"\n{d}  ({n} 件)  {dead[d]['title_2017'][:90]}")
        for c, s in cands:
            lines.append(f"    -> {c:<16} {s:6.1%}  {cur.get(c, '')[:80]}")
        if not cands:
            lines.append("    -> 無達門檻的替代候選（需人工判斷）")

    rep = ROOT / "out" / "concordance_report.txt"
    header = (
        "WIPO 2019 AI 代碼清單 -> 現行 CPC 對照推導報告\n"
        "廢止判定來源: patents-public-data.cpc.definitions_201710 vs cpc.definition\n"
        f"替代推導方式: 帶舊碼文件的現行碼共現率, 門檻 {MIN_SHARE:.0%}\n"
        f"樣本: out/raw_publications.csv (8 家公司 US pre-grant 2010-2025)\n"
        + "=" * 78 + "\n"
    )
    rep.write_text(header + "\n".join(lines), encoding="utf-8")

    outj = ROOT / "config" / "cpc_concordance.json"
    outj.write_text(json.dumps({
        "method": "obsolescence from official CPC scheme snapshots; "
                  "replacement from retroactive-reclassification co-occurrence",
        "sources": [
            "patents-public-data.cpc.definitions_201710",
            "patents-public-data.cpc.definition",
            "out/raw_publications.csv",
        ],
        "min_cooccurrence_share": MIN_SHARE,
        "mappings": conc,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    covered = sum(1 for v in conc.values() if v["replacements"])
    reps = {r["symbol"] for v in conc.values() for r in v["replacements"]}
    print(f"\n有專利資料佐證的廢止碼: {len(conc)} 個，其中 {covered} 個找到替代候選")
    print(f"無官方轉移目標、略過不推導: {n_no_target} 個")
    print(f"納入的相異替代碼: {len(reps)} 個")
    print(f"報告: {rep}\n對照表: {outj}")


if __name__ == "__main__":
    main()
