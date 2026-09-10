"""診斷 AI 判定的命中結構：各 Block 貢獻、各公司比例、Block3 的噪音來源。

只讀 out/raw_publications.csv，不寫大檔。
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


def build(with_repl=True):
    rules = load_rules()
    extra = collections.defaultdict(set)
    if with_repl:
        conc = json.loads((ROOT / "config" / "cpc_concordance.json").read_text(encoding="utf-8"))
        for _d, info in conc["mappings"].items():
            for rep in info["replacements"]:
                if rep["cooccurrence_share"] >= REPL_MIN:
                    for blk in info["wipo_blocks"]:
                        extra[blk].add(rep["symbol"])
    out = {}
    for blk in ("block1_cpc", "c1_cpc", "c2_ipc"):
        b = dict(rules[blk])
        b["exact"] = sorted(set(b["exact"]) | extra[blk])
        out[blk] = Matcher(b)
    return out


def main():
    m = build()
    k1 = compile_terms(K1)
    k2 = compile_terms(K2)
    named_k2 = [(t.slots[0][0], compile_terms([t])) for t in K2]
    named_c = [("c1", m["c1_cpc"]), ("c2", m["c2_ipc"])]

    tot = 0
    only = collections.Counter()
    anyb = collections.Counter()
    k2_drive = collections.Counter()
    c_drive = collections.Counter()
    b1_codes = collections.Counter()
    per_co = collections.defaultdict(lambda: collections.Counter())

    csv.field_size_limit(10**7)
    with open(ROOT / "out" / "raw_publications.csv", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            tot += 1
            codes = row["cpc_codes"].split(";") if row["cpc_codes"] else []
            text = (row["title"] or "") + " " + (row["abstract"] or "")
            hit1 = [c for c in codes if m["block1_cpc"](c)]
            b1 = bool(hit1)
            b2 = bool(k1.search(text))
            c_hit = [c for c in codes if m["c1_cpc"](c) or m["c2_ipc"](c)]
            b3 = bool(c_hit) and bool(k2.search(text))

            for name, flag in (("block1", b1), ("block2", b2), ("block3", b3)):
                if flag:
                    anyb[name] += 1
            if b1 or b2 or b3:
                anyb["ANY"] += 1
                lbl = ",".join(n for n, f in (("b1", b1), ("b2", b2), ("b3", b3)) if f)
                only[lbl] += 1
                for c in hit1:
                    b1_codes[c] += 1
            # block3 獨有（b1/b2 都沒中）時，是誰把它拉進來的
            if b3 and not b1 and not b2:
                for nm, rx in named_k2:
                    if rx.search(text):
                        k2_drive[nm] += 1
                for nm, mm in named_c:
                    for c in codes:
                        if mm(c):
                            c_drive[f"{nm}:{c}"] += 1
                            break

            co = (row["matched_assignees"] or "").split("|")[0]
            per_co[co]["tot"] += 1
            if b1 or b2 or b3:
                per_co[co]["ai"] += 1

    print(f"總 publication: {tot}\n")
    print("各 Block 單獨命中數（可重疊）")
    for k in ("block1", "block2", "block3", "ANY"):
        print(f"  {k:<8} {anyb[k]:>7}  {anyb[k]/tot:6.1%}")
    print("\n命中組合分布")
    for k, v in only.most_common():
        print(f"  {k:<12} {v:>7}  {v/tot:6.1%}")

    print("\n只靠 Block3 進來的案件，K2 詞的貢獻 top15")
    for k, v in k2_drive.most_common(15):
        print(f"  {k:<24} {v:>7}")
    print("\n只靠 Block3 進來的案件，C1/C2 代碼貢獻 top15")
    for k, v in c_drive.most_common(15):
        print(f"  {k:<24} {v:>7}")
    print("\nBlock1 命中代碼 top20")
    for k, v in b1_codes.most_common(20):
        print(f"  {k:<20} {v:>7}")


if __name__ == "__main__":
    main()
