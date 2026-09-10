"""WIPO 規則的 CPC 比對器（供其他腳本 import）。"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def pad_ge(a, b):
    n = max(len(a), len(b))
    return a.ljust(n, "0") >= b.ljust(n, "0")


def pad_le(a, b):
    n = max(len(a), len(b))
    return a.ljust(n, "0") <= b.ljust(n, "0")


class Matcher:
    """判斷單一 CPC 代碼是否落在某個 WIPO 代碼集合內。"""

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
    p = pathlib.Path(path) if path else ROOT / "config" / "wipo_ai_rules.json"
    return json.loads(p.read_text(encoding="utf-8"))


def load_symbols(csv_path):
    """讀 cpc_*.csv（symbol,title），回傳 {symbol: title}。"""
    import csv

    out = {}
    with open(csv_path, encoding="utf-8", newline="") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for row in rd:
            if len(row) >= 2:
                out[row[0].strip()] = row[1].strip()
    return out
