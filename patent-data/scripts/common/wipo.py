"""WIPO AI 判定規則：CPC 代碼集合 + K1/K2 關鍵詞，全部集中在這裡。

判定結構（三塊 OR，**不是** CPC AND 關鍵詞）：

    AI = Block1            OR  Block2       OR  Block3
         └ CPC 命中即可         └ K1 命中即可    └ (C1|C2) AND K2

Block2 的 K1 是「neural network」「deep learning」這類**本身就足以判定**的詞，
不需要 CPC 同時命中。若誤寫成 AND，Block2 會被整個吃掉——實測有 3,242 件
只被 Block2 抓到，另外兩塊都漏。

本檔的四個段落
--------------
  §1 CPC 比對器      判斷單一 CPC 代碼是否落在 WIPO 代碼集合內
  §2 Orbit 語法轉譯   WIPO 的檢索語法 -> Python regex
  §3 K1 / K2 詞表     逐條對應 WIPO 原文，每條後面附原文註解
  §4 規則檔建置       逐字檢索式 -> config/wipo_ai_rules.json

§4 平常不會被 import，只在**改動或重新核對 WIPO 原文時**執行一次：

    python3 scripts/common/wipo.py

它只做格式轉換，不新增也不刪除任何代碼。

⚠ 實作限制（需寫進論文方法章節）
  WIPO 原檢索欄位為 /BI(title+abstract)、/OBJ(發明目的)、/CLMS(申請專利範圍)。
  本專案僅有 title + abstract，K1/K2 命中率會系統性低於 WIPO 原始結果。
  此偏誤在各年度一致，不會在時間序列上製造斷點。
"""

import csv
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RULES_JSON = ROOT / "config" / "wipo_ai_rules.json"
VERBATIM = ROOT / "config" / "wipo_search_strings_verbatim.txt"


# ══════════════════════════════════════════════════════════════════ §1 CPC 比對器

def pad_ge(a, b):
    n = max(len(a), len(b))
    return a.ljust(n, "0") >= b.ljust(n, "0")


def pad_le(a, b):
    n = max(len(a), len(b))
    return a.ljust(n, "0") <= b.ljust(n, "0")


class Matcher:
    """判斷單一 CPC 代碼是否落在某個 WIPO 代碼集合內。

    代碼集合有三種形態：exact（完整代碼）、prefix（主群，涵蓋所有子群）、
    range（子群區間，依 CPC 階層十進位序，右補零後字串比較）。
    """

    def __init__(self, block):
        self.exact = set(block.get("exact", []))
        self.prefix = tuple(block.get("prefix", []))
        self.ranges = [tuple(r) for r in block.get("range", [])]

    def __call__(self, code):
        if code in self.exact:
            return True
        if code.startswith(self.prefix):
            return True
        if "/" in code:
            head, sg = code.split("/", 1)
            for r_head, lo, hi in self.ranges:
                if head == r_head and pad_ge(sg, lo) and pad_le(sg, hi):
                    return True
        return False


def load_rules(path=None):
    return json.loads((pathlib.Path(path) if path else RULES_JSON).read_text(encoding="utf-8"))


def load_symbols(csv_path):
    """讀 cpc_*.csv（symbol,title），回傳 {symbol: title}。"""
    out = {}
    with open(csv_path, encoding="utf-8", newline="") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for row in rd:
            if len(row) >= 2:
                out[row[0].strip()] = row[1].strip()
    return out


# ══════════════════════════════════════════════════════════ §2 Orbit 語法轉譯

# Orbit 運算子對應（依 Questel Orbit 語法）:
#   +      字尾截詞              LEARNING+      -> learning\w*
#   ?      0 或 1 個字元          MODEL?         -> models?
#   #      恰好 1 個字元          CONNECTIONIS#  -> connectionis\w
#   nW     依序，中間最多 n 個字   NEURAL 1W NETWORK
#   nD     不限順序，中間最多 n 個字
#   _ 或 - 視為同一個詞的連接符，比對時允許 連字號/底線/空白 三種寫法

def term_to_regex(term):
    """單一詞（可含 + ? # 與 _ - 變體）-> regex 片段。"""
    out = []
    for ch in term.strip().lower():
        if ch == "+":
            out.append(r"\w*")
        elif ch == "?":
            out.append(r"\w?")
        elif ch == "#":
            out.append(r"\w")
        elif ch in "_-":
            out.append(r"[-_\s]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def phrase_to_regex(phrase):
    """空白分隔的詞組（隱含相鄰）。"""
    return r"\s+".join(term_to_regex(w) for w in phrase.split())


def _alt(words):
    return "(?:" + "|".join(phrase_to_regex(w) for w in words) + ")"


def _gap(n):
    # 中間最多 n 個字
    return rf"(?:\W+\w+){{0,{n}}}\W+" if n > 0 else r"\W+"


class Term:
    """slots: [[候選字, ...], ...]；gaps: 長度 = len(slots)-1；ordered: 是否要求順序。

    ordered=False 且 slots 為兩段時，兩種順序都接受（對應 Orbit 的 nD）。
    """

    def __init__(self, slots, gaps=None, ordered=True):
        self.slots = [[w] if isinstance(w, str) else list(w) for w in slots]
        self.gaps = list(gaps) if gaps else [0] * (len(self.slots) - 1)
        self.ordered = ordered

    def regex(self):
        parts = [_alt(s) for s in self.slots]
        fwd = parts[0]
        for i, p in enumerate(parts[1:]):
            fwd += _gap(self.gaps[i]) + p
        if self.ordered or len(parts) != 2:
            return f"(?:{fwd})"
        rev = parts[1] + _gap(self.gaps[0]) + parts[0]
        return f"(?:{fwd}|{rev})"


def compile_terms(terms):
    """terms: [Term]，回傳單一 compiled regex。"""
    return re.compile(r"\b(?:" + "|".join(t.regex() for t in terms) + r")", re.I)


def compile_named(terms):
    """回傳 [(name, compiled_regex)]，供逐詞診斷用。"""
    return [(t.slots[0][0], re.compile(r"\b" + t.regex(), re.I)) for t in terms]


# ══════════════════════════════════════════════════════════════ §3 K1 / K2 詞表
#
# 逐字對應 config/wipo_search_strings_verbatim.txt 的 Block 2 (K1) 與 Block 3 (K2)。
# 每一項後面的註解即為 WIPO 原文，可以一行一行核對。

# ---- K1：核心 AI 詞，命中即判定為 AI（Block 2）
K1 = [
    Term([["artific+", "computation+"], ["intelligen+"]], [1]),  # ((ARTIFIC+ OR COMPUTATION+) 1W INTELLIGEN+)
    Term([["neural"], ["network+"]], [1]),                       # (NEURAL 1W NETWORK+)
    Term(["neural_network+"]),                                   # NEURAL_NETWORK+ / NEURAL-NETWORK+
    Term([["bayes+"], ["network+"]], [1]),                       # (BAYES+ 1W NETWORK+)
    Term(["bayesian-network+"]),                                 # BAYESIAN-NETWORK+ / BAYESIAN_NETWORK+
    Term(["chatbot?"]),                                          # (CHATBOT?)
    Term([["data"], ["mining+"]], [1]),                          # (DATA 1W MINING+)
    Term([["decision"], ["model?"]], [1]),                       # (DECISION 1W MODEL?)
    Term([["deep"], ["learning+"]], [1]),                        # (DEEP 1W LEARNING+)
    Term(["deep-learning+"]),                                    # DEEP-LEARNING+ / DEEP_LEARNING+
    Term([["genetic"], ["algorithm?"]], [1]),                    # (GENETIC 1W ALGORITHM?)
    Term([["inductive"], ["logic"], ["programm+"]], [1, 1]),     # ((INDUCTIVE 1W LOGIC) 1D PROGRAMM+)
    Term([["machine"], ["learning+"]], [1]),                     # (MACHINE 1W LEARNING+)
    Term(["machine-learning+"]),                                 # MACHINE_LEARNING+ / MACHINE-LEARNING+
    Term([["natural"], ["language"], ["generation", "processing"]], [1, 1]),
    #                                     ((NATURAL 1D LANGUAGE) 1W (GENERATION OR PROCESSING))
    Term([["reinforcement"], ["learning"]], [1]),                # (REINFORCEMENT 1W LEARNING)
    Term([["supervised"], ["learning+", "training"]], [1]),      # (SUPERVISED 1W (LEARNING+ OR TRAINING))
    Term(["supervised-learning+"]),                              # SUPERVISED-LEARNING+ / SUPERVISED_LEARNING+
    Term([["swarm"], ["intelligen+"]], [1]),                     # (SWARM 1W INTELLIGEN+)
    Term(["swarm-intelligen+"]),                                 # SWARM-INTELLIGEN+ / SWARM_INTELLIGEN+
    Term([["unsupervised"], ["learning+", "training"]], [1]),    # (UNSUPERVISED 1W (LEARNING+ OR TRAINING))
    Term(["unsupervised-learning+"]),                            # UNSUPERVISED-LEARNING+ / UNSUPERVISED_LEARNING+
    Term([["semi-supervised"], ["learning+", "training"]], [1]),  # (SEMI-SUPERVISED 1W (LEARNING+ OR TRAINING))
    Term(["semi-supervised-learning+"]),                         # SEMI-SUPERVISED-LEARNING / SEMI_SUPERVISED_LEARNING+
    Term(["connectionis#"]),                                     # CONNECTIONIS#
    Term([["expert"], ["system?"]], [1]),                        # (EXPERT 1W SYSTEM?)
    Term([["fuzzy"], ["logic?"]], [1]),                          # (FUZZY 1W LOGIC?)
    Term(["transfer-learning"]),                                 # TRANSFER-LEARNING / TRANSFER_LEARNING
    Term([["transfer"], ["learning"]], [1]),                     # (TRANSFER 1W LEARNING)
    Term([["learning"], ["algorithm?"]], [3]),                   # (LEARNING 3W ALGORITHM?)
    Term([["learning"], ["model?"]], [1]),                       # (LEARNING 1W MODEL?)
    Term(["support vector machine?"]),                           # (SUPPORT VECTOR MACHINE?)
    Term(["random forest?"]),                                    # (RANDOM FOREST?)
    Term(["decision tree?"]),                                    # (DECISION TREE?)
    Term(["gradient tree boosting"]),                            # (GRADIENT TREE BOOSTING)
    Term(["xgboost"]),                                           # (XGBOOST)
    Term(["adaboost"]),                                          # ADABOOST
    Term(["rankboost"]),                                         # RANKBOOST
    Term(["logistic regression"]),                               # (LOGISTIC REGRESSION)
    Term(["stochastic gradient descent"]),                       # (STOCHASTIC GRADIENT DESCENT)
    Term(["multilayer perceptron?"]),                            # (MULTILAYER PERCEPTRON?)
    Term(["latent semantic analysis"]),                          # (LATENT SEMANTIC ANALYSIS)
    Term(["latent dirichlet allocation"]),                       # (LATENT DIRICHLET ALLOCATION)
    Term(["multi-agent system?"]),                               # (MULTI-AGENT SYSTEM?)
    Term(["hidden markov model?"]),                              # (HIDDEN MARKOV MODEL?)
]

# ---- K2：泛用詞，需與 C1/C2 代碼同時命中才算（Block 3）
K2 = [
    Term(["clustering"]),                                        # CLUSTERING
    Term(["comput+ creativity"]),                                # (COMPUT+ CREATIVITY)
    Term(["descriptive model?"]),                                # (DESCRIPTIVE MODEL?)
    Term(["inductive reasoning"]),                               # (INDUCTIVE REASONING)
    Term(["overfitting"]),                                       # OVERFITTING
    Term([["predictive"], ["analytics", "model?"]], [1]),        # (PREDICTIVE 1W (ANALYTICS OR MODEL?))
    Term([["target"], ["function?"]], [1]),                      # (TARGET 1W FUNCTION?)
    Term([["test", "training", "validation"], ["data"], ["set?"]], [1, 1]),
    #                                     ((TEST OR TRAINING OR VALIDATION) 1D DATA 1D SET?)
    Term(["backpropagation?"]),                                  # BACKPROPAGATION?
    Term(["self-learning"]),                                     # SELF-LEARNING / SELF_LEARNING
    Term(["objective function?"]),                               # (OBJECTIVE FUNCTION?)
    Term(["feature? selection"]),                                # (FEATURE? SELECTION)
    Term(["embedding?"]),                                        # (EMBEDDING?)
    Term(["active learning"]),                                   # (ACTIVE LEARNING)
    Term(["regression model?"]),                                 # (REGRESSION MODEL?)
    Term([["stochastic", "probabilist+"],
          ["approach+", "technique?", "method?", "algorithm?"]], [2], ordered=False),
    #             ((STOCHASTIC OR PROBABILIST+) 2D (APPROACH+ OR TECHNIQUE? OR METHOD? OR ALGORITHM?))
    Term([["recommend+"], ["system?"]], [0]),                    # (RECOMMEND+ SYSTEM?)
    Term([["text", "speech", "hand_writing", "facial", "face?", "character?"],
          ["analysis", "analytic?", "recognition"]], [1]),
    #   ((TEXT OR SPEECH OR HAND_WRITING OR FACIAL OR FACE? OR CHARACTER?) 1W (ANALYSIS OR ANALYTIC? OR RECOGNITION))
]


# ══════════════════════════════════════════════════════ §4 規則檔建置（直接執行）
#
# 輸入 config/wipo_search_strings_verbatim.txt（WIPO 官方 PDF 逐字轉錄），
# 輸出 config/wipo_ai_rules.json。只做格式轉換，不新增也不刪除任何代碼。
#
# Orbit → CPC 格式對應:
#   G06N-007/005   -> G06N7/005      （去連字號、群號去前導零）
#   G06N-003       -> G06N3/ 前綴     （主群 = 涵蓋所有子群）
#   G06T2207/20081 -> G06T2207/20081 （索引碼原樣保留）
#   A:B            -> 區間，依 CPC 階層十進位序（右補零後字串比較）

def _norm_code(tok):
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


def _parse_block(text):
    """回傳 {'exact': [...], 'prefix': [...], 'range': [(sub_grp, lo, hi), ...]}"""
    out = {"exact": [], "prefix": [], "range": []}
    body = re.sub(r"\s+", " ", text)
    for tok in body.split(" OR "):
        tok = tok.strip().strip("()").replace("+", "")
        if not tok:
            continue
        if ":" in tok:
            lo_s, hi_s = tok.split(":", 1)
            lo, hi = _norm_code(lo_s), _norm_code(hi_s)
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
            r = _norm_code(tok)
            if not r:
                print(f"  [跳過無法解析] {tok}")
                continue
            out[r[0]].append(r[1])
    out["exact"] = sorted(set(out["exact"]))
    out["prefix"] = sorted(set(out["prefix"]))
    out["range"] = sorted(set(out["range"]))
    return out


def _extract(text, label):
    """抓出 'Block 1' / 'C1 =' / 'C2 =' 等段落裡的代碼字串。"""
    if label == "block1":
        m = re.search(r"^Block 1\n-+\n(.*?)/CPC", text, re.S | re.M)
    else:
        m = re.search(rf"^{label} = \((.*?)\)/(?:CPC|IPC)", text, re.S | re.M)
    return m.group(1) if m else None


def build_rules_json():
    text = VERBATIM.read_text(encoding="utf-8")

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
        raw = _extract(text, label)
        if raw is None:
            raise SystemExit(f"找不到段落: {label}")
        print(f"解析 {label} ...")
        rules[key] = _parse_block(raw)
        n = len(rules[key]["exact"]) + len(rules[key]["prefix"]) + len(rules[key]["range"])
        print(f"  -> exact {len(rules[key]['exact'])}, "
              f"prefix {len(rules[key]['prefix'])}, "
              f"range {len(rules[key]['range'])} （共 {n} 條）")

    # C3(FI) / C4(F-term) 為日本專利廳專用分類，美國 pre-grant publication 不帶這些碼。
    # 明確標記並附理由，而不是靜默略過——讀者要看得出來這兩塊是「不適用」而非「忘了做」。
    rules["c3_fi"] = {"applicable": False,
                      "reason": "FI 為 JPO 專用分類，US pre-grant publications 不具此欄位"}
    rules["c4_fterm"] = {"applicable": False,
                         "reason": "F-term 為 JPO 專用分類，US pre-grant publications 不具此欄位"}

    RULES_JSON.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入 {RULES_JSON}")


if __name__ == "__main__":
    build_rules_json()
