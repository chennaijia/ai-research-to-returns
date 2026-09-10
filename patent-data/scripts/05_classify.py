"""套用 WIPO AI 判定規則，輸出 ai_patents_detail.csv 與 ai_patents_yearly.csv。

判定 = Block1(CPC) OR Block2(K1 關鍵詞) OR (Block3: (C1|C2) AND K2)
CPC 代碼集合 = WIPO 2019 原始清單 ∪ 由 cpc_concordance.json 推導的現行替代碼
  （替代碼採用門檻: 共現率 >= 0.5，避免把非 AI 的旁支代碼一併納入）

公司歸屬兩版本，供穩健性檢驗:
  parent_only  只採 company_alias.csv 的母公司名稱
  with_subs    另計子公司，且僅在 filing_date 落在併購生效期間內才歸屬

去重: 同一 (歸屬公司, application_number) 只留一件，保留最早的 publication。
"""

import collections
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from wipo_keywords import compile_terms  # noqa: E402
from wipo_match import Matcher, load_rules  # noqa: E402
from wipo_terms import K1, K2  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPL_MIN = 0.50

# CPC 家族 -> WIPO AI 領域標籤（依 CPC 官方標題判讀，見 README）
FIELD_RULES = [
    ("neural_network", ("G06N3/",)),
    ("machine_learning", ("G06N20/", "G06N99/", "G06F15/18")),
    ("probabilistic_reasoning", ("G06N7/", "G06N5/")),
    ("computer_vision", ("G06V", "G06K9/", "G06T")),
    ("speech", ("G10L",)),
    ("nlp", ("G06F40/", "G06F17/27", "G06F17/28")),
    ("information_retrieval", ("G06F16/", "G06F17/30")),
    ("control_robotics", ("G05B13/", "G05D1/", "B25J", "B60W")),
    ("bioinformatics_health", ("G16B", "G16C", "G16H", "G06F19/")),
]


def load_alias():
    """回傳 {assignee_name: (tier, parent, ticker, eff_from, eff_to)}"""
    out = {}
    with open(ROOT / "config" / "company_alias.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["assignee_name"]] = ("parent", r["parent_company"], r["ticker"], None, None)
    with open(ROOT / "config" / "subsidiary_alias.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["assignee_name"] in out:
                continue
            ef = r["effective_from"].replace("-", "") if r["effective_from"] else None
            et = r["effective_to"].replace("-", "") if r["effective_to"] else None
            out[r["assignee_name"]] = ("subsidiary", r["parent_company"], r["ticker"], ef, et)
    return out


def build_cpc_sets():
    rules = load_rules()
    conc = json.loads((ROOT / "config" / "cpc_concordance.json").read_text(encoding="utf-8"))

    extra = collections.defaultdict(set)
    n_added = 0
    for dead, info in conc["mappings"].items():
        for rep in info["replacements"]:
            if rep["cooccurrence_share"] < REPL_MIN:
                continue
            for blk in info["wipo_blocks"]:
                extra[blk].add(rep["symbol"])
                n_added += 1

    sets = {}
    for blk in ("block1_cpc", "c1_cpc", "c2_ipc"):
        b = dict(rules[blk])
        b["exact"] = sorted(set(b["exact"]) | extra[blk])
        sets[blk] = Matcher(b)
    print(f"納入的現行替代碼（共現率 >= {REPL_MIN:.0%}）: "
          f"block1 {len(extra['block1_cpc'])}, c1 {len(extra['c1_cpc'])}, c2 {len(extra['c2_ipc'])}")
    return sets


def ai_field(codes):
    for label, pats in FIELD_RULES:
        if any(c.startswith(pats) for c in codes):
            return label
    return "other"


def main():
    alias = load_alias()
    m = build_cpc_sets()
    k1 = compile_terms(K1)
    k2 = compile_terms(K2)

    # (version, parent, application_number) -> best row
    best = {}
    csv.field_size_limit(10**7)
    n_read = 0
    with open(ROOT / "out" / "raw_publications.csv", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            n_read += 1
            fd = row["filing_date"]
            if not fd or len(fd) < 8:
                continue
            codes = row["cpc_codes"].split(";") if row["cpc_codes"] else []
            text = (row["title"] or "") + " " + (row["abstract"] or "")

            hit_b1 = [c for c in codes if m["block1_cpc"](c)]
            hit_b3c = [c for c in codes if m["c1_cpc"](c) or m["c2_ipc"](c)]
            b1 = bool(hit_b1)
            b2 = bool(k1.search(text))
            b3 = bool(hit_b3c) and bool(k2.search(text))
            if not (b1 or b2 or b3):
                continue

            basis = ",".join(x for x, ok in (("block1", b1), ("block2", b2), ("block3", b3)) if ok)
            rec = {
                "application_number": row["application_number"],
                "publication_number": row["publication_number"],
                "title": row["title"],
                "abstract": row["abstract"],
                "filing_date": fd,
                "filing_year": fd[:4],
                "cpc_codes": row["cpc_codes"],
                "ai_basis": basis,
                "ai_category": ai_field(hit_b1 or codes),
                "matched_ai_cpc": ";".join(hit_b1[:10]),
            }

            for name in (row["matched_assignees"] or "").split("|"):
                a = alias.get(name)
                if not a:
                    continue
                tier, parent, ticker, ef, et = a
                versions = ["with_subs"] if tier == "subsidiary" else ["parent_only", "with_subs"]
                if tier == "subsidiary":
                    if (ef and fd < ef) or (et and fd > et):
                        continue  # 併購生效期間外，不歸屬
                for v in versions:
                    key = (v, parent, row["application_number"])
                    prev = best.get(key)
                    if prev is None or rec["publication_number"] < prev["publication_number"]:
                        best[key] = {**rec, "version": v, "parent_company": parent,
                                     "ticker": ticker, "assignee_matched": name,
                                     "assignee_tier": tier}

    print(f"讀入 {n_read} 件 publication，判定為 AI 且完成歸屬去重後 {len(best)} 列")

    cols = ["version", "parent_company", "ticker", "application_number", "publication_number",
            "filing_date", "filing_year", "title", "abstract", "cpc_codes", "matched_ai_cpc",
            "ai_basis", "ai_category", "assignee_matched", "assignee_tier"]
    det = ROOT / "out" / "ai_patents_detail.csv"
    with open(det, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for k in sorted(best):
            w.writerow({c: best[k].get(c, "") for c in cols})

    agg = collections.Counter()
    for k, r in best.items():
        agg[(r["version"], r["parent_company"], r["ticker"], r["filing_year"])] += 1
    yr = ROOT / "out" / "ai_patents_yearly.csv"
    with open(yr, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["version", "parent_company", "ticker", "filing_year", "ai_patent_count"])
        for key in sorted(agg):
            w.writerow(list(key) + [agg[key]])

    print(f"寫入 {det}")
    print(f"寫入 {yr}")

    # 摘要：with_subs 版本逐年
    print("\nwith_subs 版本 AI 專利件數（依 filing year）")
    comps = sorted({k[1] for k in agg if k[0] == "with_subs"})
    yrs = sorted({k[3] for k in agg if k[0] == "with_subs"})
    print(f"{'':<11}" + "".join(f"{y[2:]:>6}" for y in yrs))
    for c in comps:
        print(f"{c:<11}" + "".join(f"{agg[('with_subs', c, _t(agg, c), y)]:>6}" for y in yrs))


def _t(agg, comp):
    for k in agg:
        if k[1] == comp:
            return k[2]
    return ""


if __name__ == "__main__":
    main()
