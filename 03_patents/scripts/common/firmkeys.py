"""公司識別碼的唯一真相來源：out/firm_roster.csv。

為什麼需要這支模組
------------------
同一家公司在不同檔案裡有不同寫法，直接拿字串當鍵會把一家公司拆成兩家：

  config/subsidiary_alias.csv  原 8 家人工表，寫 "Alphabet" / GOOGL、"Meta" / META
  out/firm_roster.csv          CRSP 名冊，寫 "ALPHABET INC" / GOOGL、"FACEBOOK INC" / FB

07_classify 以 (parent_company, ticker) 聚合，標籤一不同就變成兩列。實測後果：
  Alphabet 的專利被拆成 ALPHABET INC 10717 件 + Alphabet 1920 件
  Meta 更慘，連 ticker 都不同（FB vs META），下游完全串不起來

所以所有腳本一律先過 canon()，把任何歷史 ticker 收斂成 CRSP 的 permco 與主 ticker。
permco 才是 CRSP 的「公司」層級識別碼（permno 是「證券」，一家公司可有多個股別）。

roster 的 all_tickers 已驗證：308 個歷史 ticker 對 268 家公司，無一詞多義。
"""

import csv
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

_BY_TICKER = None      # 任何歷史 ticker -> 正規記錄
_BY_PERMCO = None


class Firm:
    __slots__ = ("permco", "ticker", "name", "all_tickers")

    def __init__(self, permco, ticker, name, all_tickers):
        self.permco = permco
        self.ticker = ticker          # roster 的 primary_ticker
        self.name = name              # roster 的 primary_name
        self.all_tickers = all_tickers

    def __repr__(self):
        return f"Firm({self.ticker}, permco={self.permco})"


def _load():
    global _BY_TICKER, _BY_PERMCO
    if _BY_TICKER is not None:
        return
    _BY_TICKER, _BY_PERMCO = {}, {}
    path = ROOT / "out" / "firm_roster.csv"
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            tks = [t for t in r["all_tickers"].split("|") if t]
            f = Firm(r["permco"], r["primary_ticker"], r["primary_name"], tks)
            _BY_PERMCO[f.permco] = f
            for t in set(tks) | {f.ticker}:
                # roster 已驗證無歧義；真的撞到要立刻停，不能默默選一個
                if t in _BY_TICKER and _BY_TICKER[t].permco != f.permco:
                    raise SystemExit(
                        f"ticker {t} 同時屬於 permco {_BY_TICKER[t].permco} 與 {f.permco}，"
                        f"firm_roster.csv 需要人工釐清")
                _BY_TICKER[t] = f


def canon(ticker):
    """歷史 ticker -> Firm；查無此 ticker 回 None（呼叫端自行決定要略過還是報錯）。"""
    _load()
    return _BY_TICKER.get((ticker or "").strip().upper())


def by_permco(permco):
    _load()
    return _BY_PERMCO.get(str(permco).strip())


def all_firms():
    _load()
    return dict(_BY_PERMCO)
