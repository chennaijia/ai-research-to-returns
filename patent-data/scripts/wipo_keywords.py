"""把 WIPO 的 Orbit 關鍵詞語法轉成 Python 正規表示式。

Orbit 運算子對應（依 Questel Orbit 語法）:
  +      字尾截詞              LEARNING+      -> learning\\w*
  ?      0 或 1 個字元          MODEL?         -> models?
  #      恰好 1 個字元          CONNECTIONIS#  -> connectionis\\w
  nW     依序，中間最多 n 個字   NEURAL 1W NETWORK
  nD     不限順序，中間最多 n 個字
  _ 或 - 視為同一個詞的連接符，比對時允許 連字號/底線/空白 三種寫法

一個詞項用 Term 表示：slots 為各詞位的候選字，gaps 為詞位之間允許的間隔字數。
ordered=False 且 slots 為兩段時，兩種順序都接受。

⚠ 實作限制（需寫進論文方法章節）:
  WIPO 原檢索欄位為 /BI(title+abstract)、/OBJ(發明目的)、/CLMS(申請專利範圍)。
  本專案僅有 title + abstract，K1/K2 命中率會系統性低於 WIPO 原始結果。
  此偏誤在各年度一致，不會在時間序列上製造斷點。
"""

import re


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
    """slots: [[候選字, ...], ...]；gaps: 長度 = len(slots)-1；ordered: 是否要求順序。"""

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
