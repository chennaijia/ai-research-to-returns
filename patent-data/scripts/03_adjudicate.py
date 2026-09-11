"""人工裁決：決定哪些 assignee 名稱真的屬於名冊上的公司。

02 跑完後留下兩種東西需要人來判斷：

  (a) 零命中的公司     自動比對一筆都沒配到。可能真的沒專利，也可能是名稱寫法
                       差太多（VISA INT SERVICE ASS）。要逐一去字典裡翻。
  (b) T3_REVIEW 候選   「首詞相同」就被撈出來的一大堆，多數是同名不同公司
                       （GEN ELECTRIC vs GEN DYNAMICS）。件數 >= 100 的逐筆裁決。

裁決原則（與 02 的設計一致：寧可漏抓，不可錯抓）
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

「我查過了」不算證據
--------------------
§3 會把每一筆裁決回頭對照 out/assignee_dict.csv，任何打錯字、記錯、或字典裡
根本不存在的名稱都會被標成 MISSING 並中止，不寫出檔案。這是為了守住
「不編造任何資料」：人工裁決可以有判斷，但不能有幻覺。

EXCLUDE 那些寫下來是為了留下「我看過且刻意排除」的紀錄，
否則後人（或未來的我）會以為只是漏了。

用法：
    python3 scripts/03_adjudicate.py
輸出：
    config/assignee_manual_t3.csv   §2 的逐筆裁決（審計用中間檔）
    config/assignee_manual.csv      合併 §1+§2 並驗證後的最終裁決表，供 04 使用
"""

import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════ §1 零命中公司的人工裁決
#
# 自動比對跑完後仍有 28 家公司零命中。我逐一在 out/assignee_dict.csv 裡查找，
# 得到下面的清單。這批是「大海撈針」式的查找，量小但每一筆都很關鍵——
# 漏一筆就整家公司變成 0 專利。

# (ticker, assignee_name, note)
MANUAL_INCLUDE = [
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
MANUAL_EXCLUDE = [
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


# ═══════════════════════════════════════════════ §2 T3_REVIEW 大量裁決
#
# 來源是 02 產出的 out/assignee_match_review.csv，只看件數 >= MIN_PUB 者
# ——件數少的就算判錯，對總量也幾乎沒影響，不值得花人力。
#
# 注意：§1 已經裁決過的 (ticker, name) 會先扣掉，不重複判。這件事很重要：
# 早期版本是讀 out/assignee_review_suggest.csv，而那個檔已經被 02 依
# config/assignee_manual.csv 過濾過一輪 —— 於是形成「02 要先有 03 的產出，
# 03 又要先有 02 的產出」的循環依賴，整條管線只在全新環境下跑得動。
# 改讀未過濾的 review 檔、自己扣掉 §1，才是真正可重跑的寫法。

MIN_PUB = 100

# (ticker, assignee_name) -> 納入理由。其餘 >= MIN_PUB 的待審列一律 EXCLUDE。
T3_INCLUDE = {
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
T3_EXCLUDE_WHY = {
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


def adjudicate_t3():
    """逐筆裁決 T3 候選，回傳 (裁決列, INCLUDE 可挽回件數)。"""
    rows = list(csv.DictReader(open(ROOT / "out" / "assignee_match_review.csv",
                                    encoding="utf-8")))
    # §1 已裁決者不重複判（見上方循環依賴的說明）
    seen = {(t, n) for t, n, _ in MANUAL_INCLUDE} | {(t, n) for t, n, _ in MANUAL_EXCLUDE}

    out_rows, inc_pub = [], 0
    unmatched = set(T3_INCLUDE)
    for r in rows:
        k = (r["primary_ticker"], r["assignee_name"])
        if int(r["n_publications"]) < MIN_PUB or k in seen:
            continue
        if k in T3_INCLUDE:
            dec, why = "INCLUDE", T3_INCLUDE[k]
            unmatched.discard(k)
            inc_pub += int(r["n_publications"])
        else:
            dec, why = "EXCLUDE", T3_EXCLUDE_WHY.get(k, DEFAULT_WHY)
        out_rows.append({"ticker": r["primary_ticker"],
                         "assignee_name": r["assignee_name"],
                         "decision": dec, "note": why})

    if unmatched:
        # 名稱打錯就會靜默漏掉一整家公司的專利，必須當成錯誤
        sys.exit(f"✗ T3_INCLUDE 清單中有 {len(unmatched)} 筆在待審表裡找不到，"
                 f"請核對字串: {sorted(unmatched)}")

    out_rows.sort(key=lambda x: (x["ticker"], x["assignee_name"]))
    p = ROOT / "config" / "assignee_manual_t3.csv"
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ticker", "assignee_name", "decision", "note"])
        w.writeheader()
        w.writerows(out_rows)

    n_inc = sum(1 for r in out_rows if r["decision"] == "INCLUDE")
    print(f"T3 裁決 {len(out_rows)} 筆：INCLUDE {n_inc}、EXCLUDE {len(out_rows) - n_inc}")
    print(f"INCLUDE 可挽回 {inc_pub:,} 件 pre-grant publication")
    print(f"寫入 {p}")
    return out_rows


# ═════════════════════════════════════════════════ §3 驗證並寫出最終裁決表
#
# 把 §1 + §2 的每一筆都回頭對照 out/assignee_dict.csv 與 out/firm_roster.csv。
# 只要有一筆對不上就整批不寫出——寧可什麼都沒有，也不要放一筆幻覺進資料流。

def verify_and_write(t3_rows):
    dic = {}
    with open(ROOT / "out" / "assignee_dict.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            dic[r["assignee_name"]] = (int(r["n_publications"]),
                                       r["first_filing_year"], r["last_filing_year"])

    roster = {}
    with open(ROOT / "out" / "firm_roster.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            roster[r["primary_ticker"]] = r

    t3_inc = [(r["ticker"], r["assignee_name"], r["note"])
              for r in t3_rows if r["decision"] == "INCLUDE"]
    t3_exc = [(r["ticker"], r["assignee_name"], r["note"])
              for r in t3_rows if r["decision"] != "INCLUDE"]

    all_inc = MANUAL_INCLUDE + t3_inc
    all_exc = MANUAL_EXCLUDE + t3_exc

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

    print(f"\nINCLUDE 驗證通過: {len(ok)}/{len(all_inc)}"
          f"（本檔 {len(MANUAL_INCLUDE)} + T3 裁決 {len(t3_inc)}）")
    print(f"EXCLUDE 條目:     {len(all_exc)}"
          f"（本檔 {len(MANUAL_EXCLUDE)} + T3 裁決 {len(t3_exc)}）")
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


def main():
    verify_and_write(adjudicate_t3())


if __name__ == "__main__":
    main()
