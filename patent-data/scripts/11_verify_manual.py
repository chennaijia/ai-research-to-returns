"""驗證人工裁決的 assignee 名稱確實存在於 BigQuery 字典中。

自動比對跑完後仍有 28 家公司零命中。我逐一在 out/assignee_dict.csv 裡查找，
得到下面的裁決清單。但「我查過了」不算證據——這支腳本把每一筆裁決回頭對照字典，
任何打錯字、記錯、或字典裡根本不存在的名稱都會被標成 MISSING。

只有全部通過，才輸出 config/assignee_manual.csv 進入 alias 表。
這是為了守住「不編造任何資料」：人工裁決可以有判斷，但不能有幻覺。

EXCLUDE 那些是同名不同公司，寫下來是為了留下「我看過且刻意排除」的紀錄，
否則後人（或未來的我）會以為只是漏了。
"""

import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (ticker, assignee_name, note)
INCLUDE = [
    ("V", "VISA INT SERVICE ASS", "Visa 全球專利主體 harmonizer 縮寫 INTERNATIONAL SERVICE ASSOCIATION"),
    ("V", "VISA USA INC", "Visa 美國子公司"),
    ("V", "VISA EUROPE LTD", "2016-06-21 Visa Inc 完成收購 Visa Europe"),
    ("TGT", "TARGET BRANDS INC", "Target 的智財持有子公司 專利均掛此名"),
    ("ALTR", "ALTAIR ENG INC", "Altair Engineering 本體 harmonizer 縮寫 ENGINEERING"),
    ("CACI", "CACI INC FED", "CACI Inc-Federal 為 CACI International 主要營運子公司"),
    ("IQ", "BEIJING QIYI CENTURY SCIENCE & TECHNOLOGY CO LTD", "愛奇藝北京營運主體 中文名北京愛奇藝科技"),
    ("RDS", "SHELL OIL CO", "Shell 美國主體"),
    ("RDS", "SHELL USA INC", "2022 Shell Oil Co 更名"),
    ("RDS", "SHELL INT RESEARCH", "Shell International Research 研發主體"),
    ("RDS", "SHELL CANADA ENERGY", "Shell 加拿大子公司"),
    ("VRSK", "XACTWARE SOLUTIONS INC", "Verisk 子公司 保險理賠估價軟體"),
    ("VRSK", "COMMERCE SIGNALS INC C/O VERISK ANALYTICS INC", "字典名稱直接寫明 c/o Verisk Analytics"),
    ("AFL", "AMERICAN FAMILY LIFE ASSURANCE COMPANY OF COLUMBUS", "AFLAC 全稱 未被 harmonizer 縮寫"),
    ("IAC", "IAC SEARCH & MEDIA INC", "IAC 旗下 Ask.com 母體"),
    ("PII", "POLARIS INC", "2018 Polaris Industries 更名為 Polaris Inc"),
    ("INGR", "CORN PRODUCTS DEV INC", "Ingredion 前身 Corn Products International 研發主體"),
    ("MYL", "MYLAN INC", "Mylan 美國主體"),
    ("MYL", "MYLAN LABORATORIES LTD", "Mylan 印度子公司"),
    ("MYL", "MYLAN LAB LTD", "同上 harmonizer 縮寫變體"),
    ("MYL", "MYLAN TECHNOLOGIES INC", "Mylan 透皮貼片子公司"),
    ("NEM", "NEWMONT USA LTD", "Newmont Mining 美國營運主體"),
    ("NEE", "FLORIDA POWER & LIGHT CO", "NextEra Energy 主要子公司 專利掛 FPL 名下"),
    ("OXY", "OCCIDENTAL CHEM CO", "Occidental Petroleum 化學部門 OxyChem"),
    ("OXY", "OCCIDENTAL OIL AND GAS CORP", "Occidental 油氣子公司"),
    ("RGTI", "RIGETTI & CO INC", "Rigetti Computing 專利登記主體"),
    ("RGTI", "RIGETTI & CO LLC", "同上 改制前形式"),
    ("TTNP", "TITAN PHARMACEUTICALS INC", "與 roster 同名 但 core 被 PHARMACEUTICALS 差異擋下"),
    ("LJPC", "LA JOLLA PHARMA CO", "La Jolla Pharmaceutical 本體"),
    ("LJPC", "LA JOLLA PHARMA LLC", "同上 改制後形式"),
    ("XPER", "TESSERA INC", "Xperi 前身 Tessera Technologies"),
    ("XPER", "DTS INC", "2016-12 Tessera 收購 DTS 後改名 Xperi"),
    ("XPER", "TESSERA TECH IRELAND LTD", "Tessera 愛爾蘭智財主體"),
    # 以下三家因「姓氏型公司名」被擋在自動比對外（THOMSON/BERRY/BRADY 都是常見姓氏）
    ("TCH", "THOMSON LICENSING", "Technicolor 前身 Thomson SA 的專利授權主體 roster naics=334310 影音設備"),
    ("TCH", "THOMSON LICENSING SA", "同上 法國母體"),
    ("TCH", "THOMSON LICENSING A CORP", "同上 字典中的另一種寫法"),
    ("TCH", "THOMSON LICENSING LLC", "同上 美國實體"),
    ("TCH", "THOMSON LICENSING DTV", "同上 數位電視部門"),
    ("BRC", "BRADY WORLDWIDE INC", "Brady Corp 主要營運子公司 roster naics=339999"),
]

# 看過且刻意排除的同名實體（不入 alias，但留下紀錄）
EXCLUDE = [
    ("ALTR", "ALTAIR SEMICONDUCTOR LTD", "以色列 LTE 晶片商 2016 被 Sony 收購 與 Altair Engineering 無關"),
    ("ALTR", "ALTAIRE PHARMACEUTICALS INC", "眼科藥廠 名稱相近但無關"),
    ("RDS", "SHELL INTERNET BEIJING SECURITY TECHNOLOGY CO LTD", "中國網路安全公司 與 Royal Dutch Shell 無關"),
    ("RDS", "SHELL INTERNET (BEIJING) SECURITY TECH CO LTD", "同上 字典中的另一種寫法"),
    ("RDS", "SHELL SHOCK TECH LLC", "彈藥技術 與 Royal Dutch Shell 無關"),
    ("IAC", "IAC IN NAT UNIV CHUNGNAM", "韓國忠南大學產學合作機構 非 IAC/InterActiveCorp"),
    ("PII", "POLARIS WIRELESS INC", "美國定位技術公司 與 Polaris Industries 無關"),
    ("PII", "POLARIS SENSOR TECH INC", "光學感測商 與 Polaris Industries 無關"),
    ("MYL", "MYLAN GROUP", "加拿大化工 與 Mylan NV 製藥無關"),
    ("NEE", "NEXTERA VIDEO INC", "影音技術公司 與 NextEra Energy 無關"),
    ("OXY", "OCCIDENTAL COLLEGE", "洛杉磯文理學院 非 Occidental Petroleum"),
    ("RGTI", "RIGETTI CHAD T", "個人發明者姓名 非公司"),
    ("LJPC", "LA JOLLA INST FOR ALLERGY & IMMUNOLOGY", "非營利研究機構 非 La Jolla Pharmaceutical"),
    ("VRSK", "VERISKIN INC", "皮膚檢測器材商 名稱相近但無關"),
    ("XPER", "ADEIA GUIDES INC", "2022-10 Xperi 分拆 Adeia 為另一家上市公司 不應計入 XPER"),
    ("CLVT", "THOMSON REUTERS GLO RESOURCES", "Clarivate 前身業務為 2016 從 Thomson Reuters 分拆的 IP&Science 但 TRI 本身在 roster 內 此類 THOMSON REUTERS* 實體一律歸 TRI 不歸 CLVT 否則重複計算"),
    ("CLVT", "THOMSON REUTERS GLOBAL RESOURCES UNLIMITED CO", "同上"),
    ("CLVT", "THOMSON REUTERS ENTPR CENTRE GMBH", "同上"),
    # TCH = Technicolor（原 Thomson SA，法國影音設備），與 Thomson Reuters（TRI，資訊服務）
    # 是完全不同的兩家公司。名字都叫 THOMSON 純屬巧合，混算會把 TRI 的專利記到 TCH 頭上。
    ("TCH", "THOMSON REUTERS GLO RESOURCES", "Thomson Reuters 實體 應歸 TRI 非 Technicolor"),
    ("TCH", "THOMSON REUTERS MARKETS LLC", "同上"),
    ("TCH", "THOMSON FINANCIAL LLC", "Thomson Reuters 金融資訊部門 應歸 TRI"),
    ("TCH", "THOMSON IND INC", "Thomson Industries 直線軸承製造商 與 Technicolor 無關"),
    # BRY = Berry Petroleum（naics 211120 原油開採），與 Berry Plastics/Berry Global
    # （塑膠包裝，ticker BERY，不在名冊內）不同公司，不可混算
    ("BRY", "BERRY PLASTICS CORP", "Berry Global 前身 塑膠包裝 ticker BERY 非 BRY"),
    ("BRY", "BERRY GLOBAL INC", "同上 2017 更名"),
    ("BRY", "BERRY METAL CO", "冶金設備商 與 Berry Petroleum 無關"),
    ("BRY", "BERRY GENOMICS CO LTD", "中國基因定序公司 無關"),
]

# 查過字典後確認確實沒有任何專利的公司（服務業/資源業為主）
VERIFIED_ZERO = [
    ("NGG", "NATIONAL GRID PLC", "英國電網 字典中 NATIONAL GRID 開頭者均為他方"),
    ("MELI", "MERCADOLIBRE INC", "拉美電商 無 US pre-grant 專利"),
    ("MUR", "MURPHY OIL CORP", "字典中 MURPHY 開頭者均為同姓個人或他公司"),
    ("STN", "STANTEC INC", "加拿大工程顧問 無專利"),
    ("SIFY", "SIFY TECHNOLOGIES LTD", "印度 IT 服務商 無專利"),
    ("HSKA", "HESKA CORP", "獸醫診斷 無 US pre-grant 專利"),
    ("VSR", "VERSAR INC", "環境工程顧問 無專利"),
    ("HRBN", "HARBIN ELECTRIC INC", "中概股 2011 私有化下市 無專利"),
    ("CLVT", "CLARIVATE PLC", "資訊服務商 本體無專利"),
    ("BRY", "BERRY CORP", "原油開採商 字典中 BERRY 開頭者均為塑膠/冶金/基因或個人 無油氣業者"),
]


def main():
    dic = {}
    with open(ROOT / "out" / "assignee_dict.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            dic[r["assignee_name"]] = (int(r["n_publications"]),
                                       r["first_filing_year"], r["last_filing_year"])

    roster = {}
    with open(ROOT / "out" / "firm_roster.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            roster[r["primary_ticker"]] = r

    # T3_REVIEW 的大量裁決由 15_adjudicate.py 產出（266 筆，件數 >= 100 者）。
    # 放外部檔而非本檔的 Python 清單只是因為量太大，驗證標準完全相同：
    # 一樣逐筆回頭對照字典，任何不存在的名稱都會被擋下。
    t3_inc, t3_exc = [], []
    t3_p = ROOT / "config" / "assignee_manual_t3.csv"
    if t3_p.exists():
        with open(t3_p, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                (t3_inc if r["decision"] == "INCLUDE" else t3_exc).append(
                    (r["ticker"], r["assignee_name"], r["note"]))

    all_inc = INCLUDE + t3_inc
    all_exc = EXCLUDE + t3_exc

    bad, ok = [], []
    for tk, name, note in all_inc:
        if tk not in roster:
            bad.append(f"MISSING TICKER  {tk}  不在 firm_roster.csv")
            continue
        if name not in dic:
            bad.append(f"MISSING NAME    {tk:<6} {name!r} 不在 assignee_dict.csv")
            continue
        n, y0, y1 = dic[name]
        ok.append((tk, roster[tk]["permco"], roster[tk]["primary_name"], name, n, y0, y1, note))

    for tk, name, note in all_exc:
        if name not in dic:
            bad.append(f"EXCLUDE 不存在  {tk:<6} {name!r} 排除一個不存在的名稱 表示我記錯了")

    for tk, _, _ in VERIFIED_ZERO:
        if tk not in roster:
            bad.append(f"MISSING TICKER  {tk}  不在 firm_roster.csv")

    print(f"INCLUDE 驗證通過: {len(ok)}/{len(all_inc)}"
          f"（本檔 {len(INCLUDE)} + T3 裁決 {len(t3_inc)}）")
    print(f"EXCLUDE 條目:     {len(all_exc)}"
          f"（本檔 {len(EXCLUDE)} + T3 裁決 {len(t3_exc)}）")
    print(f"確認零專利公司:   {len(VERIFIED_ZERO)}")
    if bad:
        print("\n✗ 驗證失敗，未寫出檔案：")
        for b in bad:
            print(f"  {b}")
        sys.exit(1)

    out = ROOT / "config" / "assignee_manual.csv"
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "permco", "primary_name", "assignee_name", "decision",
                    "n_publications", "first_filing_year", "last_filing_year", "note"])
        for tk, pc, pn, name, n, y0, y1, note in ok:
            w.writerow([tk, pc, pn, name, "INCLUDE", n, y0, y1, note])
        for tk, name, note in all_exc:
            n, y0, y1 = dic[name]
            r = roster.get(tk, {})
            w.writerow([tk, r.get("permco", ""), r.get("primary_name", ""), name,
                        "EXCLUDE", n, y0, y1, note])
        for tk, pn, note in VERIFIED_ZERO:
            w.writerow([tk, roster[tk]["permco"], roster[tk]["primary_name"], "",
                        "VERIFIED_ZERO", 0, "", "", note])

    tot = sum(x[4] for x in ok)
    print(f"\n人工補回的 pre-grant 件數合計: {tot}")
    print("補回件數 top 10")
    for tk, _, pn, name, n, y0, y1, _ in sorted(ok, key=lambda x: -x[4])[:10]:
        print(f"  {tk:<6}{name[:44]:<46}{n:>7} 件  {y0}-{y1}")
    print(f"\n寫入 {out}")


if __name__ == "__main__":
    main()
