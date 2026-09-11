"""組裝擴大版 alias 表：268 家公司 x assignee 名稱。

輸入三份，優先序由高到低：
  config/assignee_manual.csv     人工裁決（INCLUDE 補回、EXCLUDE 否決、VERIFIED_ZERO 註記）
  out/assignee_match_auto.csv    T1_EXACT / T2_PREFIX 自動比對
  config/subsidiary_alias.csv    原 8 家的子公司對照（含併購生效日），原樣保留

EXCLUDE 是**否決權**：人工看過確認是同名不同公司者，即使自動比對命中也要拿掉。
例如 TCH（Technicolor）不得吃下 THOMSON REUTERS 的專利。

併購換手（ACQUIRED）另行處理：同一個 assignee 名稱在不同時期屬於不同上市公司，
必須靠申請日切開，否則會有一家被錯記成「幾乎沒有專利」。

輸出兩份：
  config/company_alias.csv          母公司本體（parent_company, ticker, assignee_name,
                                    effective_from, effective_to, date_basis, note）
  config/subsidiary_alias_auto.csv  自動比對出的子公司，供 with_subs 版使用
"""

import collections
import csv
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import firmkeys  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 併購換手：assignee 名稱在切分日前後分屬不同上市公司。
# 依據 CRSP 本身的最後交易月份（firm_roster.csv 的 ym_max），不引用外部記憶日期。
#   BRCM ym_max = 201601 -> 舊博通最後一個完整交易月為 2016-01
#   安華高(AVGO)完成收購後沿用 Broadcom 名稱，故 2016-02 起的申請歸 AVGO
ACQUIRED = [
    {"prefix": "BROADCOM", "cut": "2016-02-01", "before": "BRCM", "after": "AVGO",
     "basis": "crsp_delist_month",
     "note": "舊博通 BRCM 於 CRSP 最後交易月 201601 後被 Avago 收購 新公司沿用 Broadcom 名稱"},
]


def read_csv(p):
    with open(p, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    roster = {r["primary_ticker"]: r for r in read_csv(ROOT / "out" / "firm_roster.csv")}
    manual = read_csv(ROOT / "config" / "assignee_manual.csv")
    auto = read_csv(ROOT / "out" / "assignee_match_auto.csv")

    excluded = {(r["ticker"], r["assignee_name"]) for r in manual if r["decision"] == "EXCLUDE"}
    zero = {r["ticker"] for r in manual if r["decision"] == "VERIFIED_ZERO"}

    # 原 8 家的人工子公司表帶有查證過的併購生效日與來源 URL，必須優先。
    # 自動比對產生的列沒有日期（等同「全期間持有」），若與人工列並存，
    # 併購前的專利會從沒有日期的那一列漏進來——例如 Google Technology Holdings
    # （Motorola 來源）會被回溯到 2010 年，而人工表正確地從收購日才起算。
    #
    # 鍵一定要先過 canon()：人工表把 Meta 寫成 ticker "META"，但 CRSP 名冊的主
    # ticker 是 "FB"（FB 有約 10 年月份、META 只有 3.5 年）。不收斂的話
    # ("META", name) 永遠對不上自動表的 ("FB", name)，這道讓位機制對 Meta 會
    # 整個失效，Oculus/WhatsApp 的收購生效日就會被沒有日期的自動列蓋掉。
    curated = set()
    for r in read_csv(ROOT / "config" / "subsidiary_alias.csv"):
        f = firmkeys.canon(r["ticker"])
        curated.add(((f.ticker if f else r["ticker"]), r["assignee_name"]))

    # ticker -> {assignee_name: source}
    pairs = collections.defaultdict(dict)
    n_vetoed = 0
    for r in auto:
        tk, nm = r["primary_ticker"], r["assignee_name"]
        if (tk, nm) in excluded:
            n_vetoed += 1
            continue
        pairs[tk][nm] = r["tier"]
    for r in manual:
        if r["decision"] != "INCLUDE":
            continue
        pairs[r["ticker"]][r["assignee_name"]] = "MANUAL"

    # 原 8 家逐一人工查證過的母公司名單，優先序最高。
    #
    # 為什麼不能丟掉：這份表收錄了大量 OCR / 打字錯誤的變體
    # （MICROSOFT TECH LICESNING LLC、GOOGLE ELLC、APPLE LNC、NVIDIA CORPRATION、
    #  AMAZON TECHOLOGEIS INC…），光 Microsoft Technology Licensing 就有約 45 種
    # 拼法。自動比對是「以公司名開頭」，拼錯的變體一個都接不到。
    #
    # 也決定 tier：這些是母公司本體的持有實體（AMAZON TECH INC、
    # MICROSOFT TECH LICENSING LLC），自動比對會因為多了一個詞而判成 T2_PREFIX
    # 子公司，導致 parent_only 版本暴跌（實測 MSFT -75%、AMZN -99.9%）。
    n_cur8 = 0
    for r in read_csv(ROOT / "config" / "company_alias_8firms_backup.csv"):
        f = firmkeys.canon(r["ticker"])
        tk = f.ticker if f else r["ticker"]
        pairs[tk][r["assignee_name"]] = "CURATED8"
        n_cur8 += 1

    # 併購換手：把命中的名稱從單一歸屬改成兩段
    windows = {}   # (ticker, name) -> (eff_from, eff_to, basis, note)
    for a in ACQUIRED:
        names = {nm for tk in (a["before"], a["after"]) for nm in pairs.get(tk, {})
                 if nm.upper().startswith(a["prefix"])}
        for nm in names:
            src = pairs.get(a["before"], {}).get(nm) or pairs.get(a["after"], {}).get(nm)
            pairs[a["before"]][nm] = src
            pairs[a["after"]][nm] = src
            windows[(a["before"], nm)] = ("", a["cut"], a["basis"], a["note"] + " 併購前歸舊公司")
            windows[(a["after"], nm)] = (a["cut"], "", a["basis"], a["note"] + " 併購後歸新公司")
        print(f"併購換手 {a['before']} -> {a['after']}：切分 {a['cut']}，涉及 {len(names)} 個 assignee")

    rows, n_curated = [], 0
    for tk, names in sorted(pairs.items()):
        f = roster.get(tk)
        if not f:
            continue
        for nm, src in sorted(names.items()):
            if (tk, nm) in curated:
                n_curated += 1      # 已在人工子公司表中，交給該表處理
                continue
            ef, et, basis, note = windows.get((tk, nm), ("", "", "", ""))
            # 下游用 (et and fd > et) 判斷，屬於閉區間，故「併購前」那段的
            # effective_to 要是切分日的前一天，否則切分日當天會被兩邊同時計入
            if et:
                et = (datetime.date.fromisoformat(et)
                      - datetime.timedelta(days=1)).isoformat()
            rows.append({
                "parent_company": f["primary_name"],
                "ticker": tk,
                "assignee_name": nm,
                "effective_from": ef,
                "effective_to": et,
                "date_basis": basis,
                "note": (note + f" [{src}]").strip(),
                "_src": src,
            })

    # 分流成兩個 tier，保住 parent_only / with_subs 兩版的區別：
    #   T1_EXACT 正規化後與公司名完全相同 -> 母公司本體（含 APPLE COMPUTER 這類舊名變體）
    #   MANUAL   人工裁決者多半是該公司的專利持有主體（TARGET BRANDS、THOMSON LICENSING），
    #            若歸為子公司會讓 parent_only 變成 0，反而失真，故一併視為母公司
    #   T2_PREFIX 帶有額外詞的獨立實體（QUALCOMM ATHEROS、HITACHI HIGH TECH）-> 子公司
    #   CURATED8  原 8 家人工查證的母公司持有實體與其拼寫變體 -> 母公司
    parent_rows = [r for r in rows if r["_src"] in ("T1_EXACT", "MANUAL", "CURATED8")]
    sub_rows = [r for r in rows if r["_src"] == "T2_PREFIX"]

    cols = ["parent_company", "ticker", "assignee_name", "effective_from",
            "effective_to", "date_basis", "note"]
    out_p = ROOT / "config" / "company_alias.csv"
    out_s = ROOT / "config" / "subsidiary_alias_auto.csv"
    for path, rs in ((out_p, parent_rows), (out_s, sub_rows)):
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rs)

    covered = {r["ticker"] for r in rows}
    src_cnt = collections.Counter(r["_src"] for r in rows)
    print(f"\nalias 總列數: {len(rows)}")
    print(f"  母公司本體 company_alias.csv:        {len(parent_rows)}")
    print(f"  自動比對子公司 subsidiary_alias_auto: {len(sub_rows)}")
    print(f"  （原 8 家人工子公司表 subsidiary_alias.csv 保持不動）")
    print(f"相異 assignee 名稱: {len({r['assignee_name'] for r in rows})}")
    print(f"有 alias 的公司: {len(covered)} / {len(roster)}")
    print(f"確認零專利的公司: {len(zero)}")
    print(f"被人工 EXCLUDE 否決的自動比對: {n_vetoed} 列")
    print(f"讓位給人工子公司表（已有查證過的併購日）: {n_curated} 列")
    print(f"原 8 家人工母公司表帶入（含拼寫變體）: {n_cur8} 列")
    print(f"來源分布: {dict(src_cnt)}")

    missing = sorted(set(roster) - covered - zero)
    if missing:
        print(f"\n⚠ 既無 alias 也未確認零專利的公司 {len(missing)} 家：{missing}")
    else:
        print("\n268 家公司全部已處理（有 alias 或已確認無專利）")
    print(f"\n寫入 {out_p}\n寫入 {out_s}")


if __name__ == "__main__":
    main()
