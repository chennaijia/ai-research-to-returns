"""把 WIPO 逐字檢索式解析成機器可讀的 wipo_ai_rules.json。

輸入 config/wipo_search_strings_verbatim.txt（WIPO 官方 PDF 逐字轉錄）。
只做格式轉換，不新增也不刪除任何代碼；轉換規則見 README 與逐字檔開頭說明。

Orbit → CPC 格式對應:
  G06N-007/005   -> G06N7/005      （去連字號、群號去前導零）
  G06N-003       -> G06N3/ 前綴     （主群 = 涵蓋所有子群）
  G06T2207/20081 -> G06T2207/20081 （索引碼原樣保留）
  A:B            -> 區間，依 CPC 階層十進位序（右補零後字串比較）
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "config" / "wipo_search_strings_verbatim.txt"


def norm(tok):
    """單一 Orbit 代碼 -> (kind, value)。kind: exact / prefix"""
    t = tok.strip().replace(" ", "")
    m = re.fullmatch(r"([A-Z]\d{2}[A-Z])-?(\d+)(?:/(\d+[A-Z]?))?", t)
    if not m:
        return None
    sub, grp, sg = m.groups()
    # 索引群（4 碼，如 2207/2219/2250）不去前導零；一般主群去前導零
    grp = grp if len(grp) == 4 else str(int(grp))
    if sg is None:
        return ("prefix", f"{sub}{grp}/")
    return ("exact", f"{sub}{grp}/{sg}")


def pad_cmp(a, b):
    """CPC 子群階層十進位序: 右補零到等長後比較。"""
    n = max(len(a), len(b))
    return (a.ljust(n, "0") > b.ljust(n, "0")) - (a.ljust(n, "0") < b.ljust(n, "0"))


def parse_block(text):
    """回傳 {'exact': [...], 'prefix': [...], 'range': [(sub_grp, lo, hi), ...]}"""
    out = {"exact": [], "prefix": [], "range": []}
    body = re.sub(r"\s+", " ", text)
    for tok in body.split(" OR "):
        tok = tok.strip().strip("()").replace("+", "")
        if not tok:
            continue
        if ":" in tok:
            lo_s, hi_s = tok.split(":", 1)
            lo, hi = norm(lo_s), norm(hi_s)
            if not lo or not hi:
                print(f"  [跳過無法解析的區間] {tok}")
                continue
            if lo[0] == "prefix" or hi[0] == "prefix":
                out["prefix"].append(lo[1] if lo[0] == "prefix" else hi[1])
                continue
            lo_head, lo_sg = lo[1].split("/")
            hi_head, hi_sg = hi[1].split("/")
            if lo_head != hi_head:
                # 跨主群區間（如 B64G2001/24:B64G1/38）解析為兩端各自納入
                out["exact"] += [lo[1], hi[1]]
                print(f"  [跨主群區間，改取兩端] {tok}")
                continue
            out["range"].append((lo_head, lo_sg, hi_sg))
        else:
            r = norm(tok)
            if not r:
                print(f"  [跳過無法解析] {tok}")
                continue
            out[r[0]].append(r[1])
    out["exact"] = sorted(set(out["exact"]))
    out["prefix"] = sorted(set(out["prefix"]))
    out["range"] = sorted(set(out["range"]))
    return out


def extract(text, label):
    """抓出 'Block 1' / 'C1 =' / 'C2 =' 等段落裡的代碼字串。"""
    if label == "block1":
        m = re.search(r"^Block 1\n-+\n(.*?)/CPC", text, re.S | re.M)
    else:
        m = re.search(rf"^{label} = \((.*?)\)/(?:CPC|IPC)", text, re.S | re.M)
    return m.group(1) if m else None


def main():
    text = SRC.read_text(encoding="utf-8")

    rules = {
        "source": {
            "title": "WIPO Technology Trends 2019: Artificial Intelligence — "
                     "Data collection method and clustering scheme (Background paper)",
            "publisher": "World Intellectual Property Organization",
            "year": 2018,
            "licence": "CC BY 3.0 IGO",
            "url": "https://www.wipo.int/documents/d/technology-trends/"
                   "docs-en-techtrends_ai_methodology.pdf",
            "section": "7c Detailed search strings",
            "retrieved": "2026-09-11",
            "verbatim_file": "config/wipo_search_strings_verbatim.txt",
        },
        "query_structure": "Block1 OR Block2 OR (Block3 = (C1|C2|C3|C4) AND K2)",
    }

    for key, label in [("block1_cpc", "block1"), ("c1_cpc", "C1"), ("c2_ipc", "C2")]:
        raw = extract(text, label)
        if raw is None:
            raise SystemExit(f"找不到段落: {label}")
        print(f"解析 {label} ...")
        rules[key] = parse_block(raw)
        n = len(rules[key]["exact"]) + len(rules[key]["prefix"]) + len(rules[key]["range"])
        print(f"  -> exact {len(rules[key]['exact'])}, "
              f"prefix {len(rules[key]['prefix'])}, "
              f"range {len(rules[key]['range'])} （共 {n} 條）")

    # C3(FI) / C4(F-term) 為日本專利廳專用分類，美國 pre-grant publication 不帶這些碼
    rules["c3_fi"] = {"applicable": False,
                      "reason": "FI 為 JPO 專用分類，US pre-grant publications 不具此欄位"}
    rules["c4_fterm"] = {"applicable": False,
                         "reason": "F-term 為 JPO 專用分類，US pre-grant publications 不具此欄位"}

    out = ROOT / "config" / "wipo_ai_rules.json"
    out.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入 {out}")


if __name__ == "__main__":
    main()
