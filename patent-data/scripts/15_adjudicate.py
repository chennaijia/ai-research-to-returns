"""把 T3_REVIEW 中件數 >= 100 的 266 筆逐筆裁決，追加寫入 config/assignee_manual.csv。

裁決原則（與 10_ 的設計一致：寧可漏抓，不可錯抓）
------------------------------------------------
偽陽性會把別家公司的專利算到我們頭上，憑空製造訊號；漏抓只是低估。
所以只有「確定是同一家公司的持有／營運實體」才 INCLUDE，其餘一律 EXCLUDE。

以下四類明確排除，每一類都附理由：

  A. 同名不同公司   GEN ELECTRIC vs GEN DYNAMICS、ARM vs AMD、
                    PARC vs Palo Alto Networks、Boston Dynamics vs Boston Scientific
  B. 分拆後另立門戶  Motorola Mobility（2011 分拆，2012 賣給 Google，2014 賣給 Lenovo）
                    不屬於 Motorola Solutions；HP Development Co 屬分拆後的 HP Inc(HPQ)，
                    而 HPQ 不在本名冊，HPE 自己的實體是 HEWLETT PACKARD ENTPR DEV LP
  C. 另行上市的集團關係企業  豐田自動織機(TOYOTA JIDOSHOKKI)、豐田紡織(TOYOTA BOSHOKU)、
                    豐田車體(TOYOTA AUTO BODY)、豐田鐵工(TOYOTA TEKKO) 都是獨立上市公司，
                    併進 TM 會重複計算
  D. 合資公司       Sony Ericsson（與 Ericsson 各半）、Sony Olympus Medical、
                    Dow Corning Toray（與東麗合資）——雙方都可主張，計給任一方都會失真

INCLUDE 的判準是「該實體的專利權最終歸屬於名冊上的這家公司」，
包含改名（Adobe Systems -> Adobe、Salesforce.com -> Salesforce）、
專利持有子公司（Amazon Technologies、Cisco Technology、Dow Global Technologies）、
以及 CRSP 名冊本身已認定為同一 permco 的前身（Delphi Automotive -> Aptiv、
Motorola Inc -> Motorola Solutions，兩者的 all_tickers 都涵蓋前身代碼）。
"""

import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIN_PUB = 100

# (ticker, assignee_name) -> 納入理由。其餘 >= MIN_PUB 的待審列一律 EXCLUDE。
INCLUDE = {
    ("CSCO", "CISCO TECH INC"): "Cisco Technology Inc 思科的專利持有實體",
    ("AMZN", "AMAZON TECH INC"): "Amazon Technologies Inc 亞馬遜的專利持有實體",
    ("ADBE", "ADOBE INC"): "Adobe Systems 於 2018 更名為 Adobe Inc 同一法人",
    ("CRM", "SALESFORCE INC"): "Salesforce.com 於 2022 更名為 Salesforce Inc 同一法人",
    ("LMT", "LOCKHEED CORP"): "Lockheed Corp 為 Lockheed Martin 合併前身 專利已歸屬現法人",
    ("MSI", "MOTOROLA INC"): "Motorola Inc 2011 更名為 Motorola Solutions CRSP 同一 permco(all_tickers 含 MOT)",
    ("ETN", "EATON INTELLIGENT POWER LTD"): "Eaton Intelligent Power Ltd 為 Eaton 的 IP 持有實體",
    ("FLEX", "FLEXTRONICS AP LLC"): "Flextronics 於 2016 更名為 Flex Ltd 同一法人",
    ("XRAY", "DENTSPLY INT INC"): "Dentsply International 與 Sirona 合併為 Dentsply Sirona 同一法人",
    ("TDY", "TELEDYNE SCIENT & IMAGING LLC"): "Teledyne Scientific & Imaging 為 Teledyne 全資子公司",
    ("SWKS", "SKYWORKS GLOBAL PTE LTD"): "Skyworks Global 為 Skyworks Solutions 的海外持有實體",
    ("LN", "LINE PLUS CORP"): "LINE Plus 為 LINE Corp 的海外營運子公司",
    ("PSO", "PEARSON EDUCATION INC"): "Pearson Education 為 Pearson plc 全資子公司",
    ("TMO", "THERMO FINNIGAN LLC"): "Thermo Finnigan 為 Thermo Fisher 質譜事業子公司",
    # --- Dow：陶氏的專利持有與事業子公司 ---
    ("DOW", "DOW GLOBAL TECHNOLOGIES LLC"): "Dow Global Technologies 為陶氏的專利持有實體",
    ("DOW", "DOW GLOBAL TECHNOLOGIES INC"): "Dow Global Technologies 改制前名稱",
    ("DOW", "DOW AGROSCIENCES LLC"): "Dow AgroSciences 為陶氏全資農化子公司",
    ("DOW", "DOW SILICONES CORP"): "Dow Corning 2016 由陶氏全資持有後更名 Dow Silicones",
    ("DOW", "DOW CORNING"): "Dow Corning 2016 起為陶氏全資子公司",
    # --- Toyota：僅納入豐田自有研發實體，另行上市的關係企業一律排除 ---
    ("TM", "TOYOTA ENG & MFG NORTH AMERICA"): "豐田北美研發製造中心 全資",
    ("TM", "TOYOTA RES INST INC"): "Toyota Research Institute 豐田 AI 研究所 全資",
    # --- Sony：全資子公司；與他方合資者另行排除 ---
    ("SNE", "SONY SEMICONDUCTOR SOLUTIONS CORP"): "Sony 半導體事業全資子公司",
    ("SNE", "SONY INTERACTIVE ENTERTAINMENT INC"): "Sony PlayStation 事業全資子公司",
    ("SNE", "Sony Interactive Entertainment LLC"): "Sony PlayStation 事業全資子公司",
    ("SNE", "SONY INTERACTIVE ENTERTAINMENT EUROPE LTD"): "Sony PlayStation 歐洲 全資",
    ("SNE", "SONY INTERACTIVE ENTERTAINMENT AMERICA LLC"): "Sony PlayStation 美洲 全資",
    ("SNE", "SONY COMPUTER ENTERTAINMENT INC"): "Sony Interactive Entertainment 改名前名稱",
    ("SNE", "SONY COMP ENTERTAINMENT US"): "Sony Interactive Entertainment 美國 改名前名稱",
    ("SNE", "SONY MOBILE COMMUNICATIONS INC"): "2012 起由 Sony 全資持有（買回 Ericsson 持股）",
    ("SNE", "SONY MOBILE COMM AB"): "2012 起由 Sony 全資持有（買回 Ericsson 持股）",
    ("SNE", "SONY ELECTRONICS INC"): "Sony 美國電子事業 全資",
    ("SNE", "SONY CORP AMERICA"): "Sony 美國控股 全資",
    ("SNE", "SONY EUROPE LTD"): "Sony 歐洲 全資",
    ("SNE", "SONY NETWORK ENTERTAINMENT INT"): "Sony 網路娛樂事業 全資",
    # --- Dell ---
    ("DELL", "DELL PRODUCTS LP"): "Dell Products LP 為戴爾的專利申請主體",
    ("DELL", "DELL SOFTWARE INC"): "Dell Software 為戴爾軟體事業子公司",
    # --- Dana ---
    ("DAN", "DANA AUTOMOTIVE SYSTEMS GROUP"): "Dana 汽車系統事業子公司",
    ("DAN", "DANA HEAVY VEHICLE SYS GROUP"): "Dana 商用車事業子公司",
    ("DAN", "DANA CANADA CORP"): "Dana 加拿大 全資",
    ("DAN", "DANA BELGIUM NV"): "Dana 比利時 全資",
    ("DAN", "DANA ITALIA SRL"): "Dana 義大利 全資",
    # --- Aptiv：CRSP 名冊 all_tickers 含 DLPH 且 all_names 含 DELPHI AUTOMOTIVE PLC ---
    ("APTV", "DELPHI TECH INC"): "Delphi Automotive 於 2017 更名 Aptiv CRSP 同一 permco(all_tickers 含 DLPH)",
    ("APTV", "DELPHI TECH IP LTD"): "Delphi/Aptiv 的 IP 持有實體",
    ("APTV", "DELPHI TECH LLC"): "Delphi/Aptiv 的營運實體",
    ("APTV", "DELPHI INT OPERATIONS LUXEMBOURG SARL"): "Delphi/Aptiv 的海外營運實體",
}

# 排除理由：沒有列到的一律用預設語句，這裡只標註需要特別說明的類型
EXCLUDE_WHY = {
    ("HPE", "HEWLETT PACKARD DEVELOPMENT CO"):
        "屬 2015 分拆後的 HP Inc(HPQ) HPQ 不在本名冊 HPE 自身實體為 HEWLETT PACKARD ENTPR DEV LP",
    ("HPE", "HEWLETT PACKARD DEVELOPMENT CO LP"):
        "屬 2015 分拆後的 HP Inc(HPQ) 不歸 HPE",
    ("HPE", "HEWLETT PACKARD INDIGO BV"):
        "HP Indigo 數位印刷屬分拆後的 HP Inc(HPQ) 不歸 HPE",
    ("UTX", "RAYTHEON CO"):
        "舊 Raytheon Company(RTN) 為獨立上市公司 不在本名冊 UTX 合併後實體為 RAYTHEON TECH CORP",
    ("UTX", "RAYTHEON BBN TECHNOLOGIES CORP"):
        "屬合併前的舊 Raytheon Company(RTN) 不歸 UTX",
    ("MSI", "MOTOROLA MOBILITY LLC"):
        "Motorola Mobility 於 2011 分拆 2012 售予 Google 2014 售予 Lenovo 不歸 Motorola Solutions",
    ("MSI", "MOTOROLA MOBILITY INC"):
        "Motorola Mobility 於 2011 分拆 不歸 Motorola Solutions",
    ("TM", "TOYOTA JIDOSHOKKI KK"): "豐田自動織機為另行上市公司 併入會重複計算",
    ("TM", "TOYOTA BOSHOKU KK"): "豐田紡織為另行上市公司 併入會重複計算",
    ("TM", "TOYOTA AUTO BODY CO LTD"): "豐田車體為另行上市公司 併入會重複計算",
    ("TM", "TOYOTA TEKKO KK"): "豐田鐵工為另行上市公司 併入會重複計算",
    ("TM", "TOYOTA CHUO KENKYUSHO KK"): "豐田中央研究所為豐田集團 13 社共同出資的獨立法人 非全資",
    ("SNE", "SONY ERICSSON MOBILE COMM AB"): "與 Ericsson 各半合資 雙方皆可主張 不計入",
    ("SNE", "SONY OLYMPUS MEDICAL SOLUTIONS INC"): "與 Olympus 合資 不計入",
    ("DOW", "DOW CORNING TORAY CO LTD"): "與東麗合資 不計入",
    ("DOW", "DOW TORAY CO LTD"): "與東麗合資 不計入",
    ("TRI", "THOMSON LICENSING"): "Thomson Licensing 屬 Technicolor(TCH) 非 Thomson Reuters",
    ("PANW", "PALO ALTO RES CT INC"): "PARC 為 Xerox 旗下研究機構 與 Palo Alto Networks 無關",
    ("AMD", "ADVANCED RISC MACH LTD"): "ARM Ltd 與 AMD 無關",
    ("BSX", "BOSTON DYNAMICS INC"): "Boston Dynamics 與 Boston Scientific 無關",
    ("TMO", "THERMO KING CORP"): "Thermo King 屬 Ingersoll Rand 非 Thermo Fisher",
    ("EMN", "EASTMAN KODAK CO"): "Eastman Kodak 與 Eastman Chemical 為不同公司",
    ("EW", "EDWARDS LTD"): "Edwards 真空設備 與 Edwards Lifesciences 無關",
    ("EW", "EDWARDS JAPAN LTD"): "Edwards 真空設備日本 與 Edwards Lifesciences 無關",
    ("ANTM", "ELEVANCE RENEWABLE SCIENCES"): "Elevance Renewable Sciences 為生質化學公司 與 Anthem/Elevance Health 無關",
}
DEFAULT_WHY = "人工複核為同名不同公司 首詞相同但非同一法人"


def main():
    """只輸出裁決本身，不碰 config/assignee_manual.csv。

    那個檔由 11_verify_manual.py 單一產出（它會把每一筆裁決回頭對照字典，
    確保沒有打錯字或憑空捏造的名稱）。這裡若直接追加，下次跑 11_ 就會被覆蓋掉。
    """
    sug = list(csv.DictReader(open(ROOT / "out" / "assignee_review_suggest.csv",
                                   encoding="utf-8")))

    out_rows = []
    n_inc = n_exc = 0
    unmatched = set(INCLUDE)
    for r in sug:
        k = (r["primary_ticker"], r["assignee_name"])
        if int(r["n_publications"]) < MIN_PUB:
            continue
        if k in INCLUDE:
            dec, why = "INCLUDE", INCLUDE[k]
            unmatched.discard(k)
            n_inc += 1
        else:
            dec, why = "EXCLUDE", EXCLUDE_WHY.get(k, DEFAULT_WHY)
            n_exc += 1
        out_rows.append({"ticker": r["primary_ticker"],
                         "assignee_name": r["assignee_name"],
                         "decision": dec, "note": why})

    if unmatched:
        # 名稱打錯就會靜默漏掉一整家公司的專利，必須當成錯誤
        sys.exit(f"✗ INCLUDE 清單中有 {len(unmatched)} 筆在待審表裡找不到，"
                 f"請核對字串: {sorted(unmatched)}")

    p = ROOT / "config" / "assignee_manual_t3.csv"
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ticker", "assignee_name", "decision", "note"])
        w.writeheader()
        w.writerows(sorted(out_rows, key=lambda x: (x["ticker"], x["assignee_name"])))

    inc_pub = sum(int(r["n_publications"]) for r in sug
                  if (r["primary_ticker"], r["assignee_name"]) in INCLUDE)
    print(f"裁決 {n_inc + n_exc} 筆：INCLUDE {n_inc}、EXCLUDE {n_exc}")
    print(f"INCLUDE 可挽回 {inc_pub:,} 件 pre-grant publication")
    print(f"\n寫入 {p}（交由 11_verify_manual.py 驗證後併入 assignee_manual.csv）")


if __name__ == "__main__":
    main()
