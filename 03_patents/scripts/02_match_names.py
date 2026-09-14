"""把 CRSP 公司名冊比對到 assignee 字典，分三層，並替最可疑的一層產生裁決建議。

**這支腳本不下最終判斷，只做分級。** 名稱比對必然有偽陽性，而偽陽性會把別家公司的
專利算到我們的公司頭上——這比漏抓嚴重得多，因為它會憑空製造訊號。所以：

    T1_EXACT   正規化後完全相同               -> 可自動採用
    T2_PREFIX  assignee 以公司名開頭且在詞界   -> 可自動採用（公司名需夠長）
    T3_REVIEW  其他包含關係、或公司名太短太泛  -> **必須人工看過**

本檔的四個段落
--------------
  §1 名稱正規化      法律字尾、縮寫收斂、普通詞黑名單
  §2 個人發明者過濾   從字典自己學「名字」與「姓氏」，不靠猜字表
  §3 三層比對        -> assignee_match_auto.csv / _review.csv / _report.txt
  §4 T3 裁決建議      -> assignee_review_suggest.csv（供人工逐筆確認）

輸出：
  out/assignee_match_auto.csv      T1+T2，可直接進 alias 表
  out/assignee_match_review.csv    T3，待人工裁決
  out/assignee_match_report.txt    分布與風險摘要
  out/assignee_review_suggest.csv  T3 中件數 >= MIN_PUB 者的建議與理由
"""

import collections
import csv
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ══════════════════════════════════════════════════════════════ §1 名稱正規化
#
# `assignee_harmonized` 已由 Google 正規化（無標點、CO LTD/KK/TECH 等縮寫），
# 所以這裡只需處理法律字尾與 CRSP 自己的標記（(Last Known)、NEW 等）。

# 法律形式字尾，可安全從尾端剝除
LEGAL = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "COMPANIES",
    "LLC", "LC", "LP", "LLP", "PLLC", "LTD", "LIMITED", "PLC", "SA", "SAS", "SARL",
    "NV", "BV", "AG", "GMBH", "KG", "KGAA", "KK", "AB", "OY", "OYJ", "SPA", "SRL",
    "AS", "ASA", "APS", "PTE", "PTY", "SE", "CV", "OG", "EV", "TRUST", "HOLDING",
    "HOLDINGS", "GROUP", "THE", "AND", "OF", "NEW", "CL", "ADR", "SPON",
}
# CRSP 對下市/更名公司的標記
CRSP_TAGS = re.compile(r"\((LAST KNOWN|NEW|OLD|DEL|POST|PRE)[^)]*\)", re.I)

# Google 的 assignee_harmonized 會把常見詞縮寫，CRSP 則用完整拼法，兩邊對不上。
# 下表由 out/assignee_dict.csv 的 token 詞頻實證得出（短式次數 >> 長式者才收錄），
# 並同時套用到兩邊做標準化收斂。例如：
#   CRSP "HEWLETT PACKARD ENTERPRISE CO" vs assignee "HEWLETT PACKARD ENTPR DEV LP"
#   CRSP "ZEBRA TECHNOLOGIES CORP"       vs assignee "ZEBRA TECH CORP"
ABBREV = {
    "TECHNOLOGIES": "TECH", "TECHNOLOGY": "TECH",
    "INTERNATIONAL": "INT",
    "ENTERPRISE": "ENTPR", "ENTERPRISES": "ENTPR",
    "SCIENTIFIC": "SCIENT", "SCIENCES": "SCIENT", "SCIENCE": "SCIENT",
    "MANUFACTURING": "MFG",
    "LABORATORY": "LAB", "LABORATORIES": "LAB", "LABS": "LAB",
    "INDUSTRIES": "IND", "INDUSTRIAL": "IND",
    "ASSOCIATION": "ASS",
    "INSTRUMENTS": "INSTR",
    "RESEARCH": "RES",
    "NATIONAL": "NAT",
    "UNIVERSITY": "UNIV",
    "DEVELOPMENT": "DEV",
    # harmonizer 本身不一致，長短式並存（GEN ELECTRIC 23212 件 vs GENERAL ELECTRIC ... 548 件），
    # 一律收斂到短式，讓兩邊在同一個標準形相遇
    "GENERAL": "GEN",
    "SYSTEMS": "SYS", "SYST": "SYS",
    "ELECTRIC": "ELEC",
    "EQUIPMENT": "EQUIP",
    "MACHINES": "MACH",
    "BUSINESS": "BUS",
    "PRECISION": "PREC",
    "CHEMICAL": "CHEM", "CHEMICALS": "CHEM",
    "AMERICA": "AMER", "AMERICAN": "AMER",
}

# 單獨出現時過於普通、極易誤配的詞。公司名剝到只剩這些之一時一律送人工複核。
GENERIC = {
    "ORANGE", "APPLE", "SHELL", "GENERAL", "AMERICAN", "NATIONAL", "UNITED",
    "FIRST", "GLOBAL", "UNIVERSAL", "PIONEER", "SUMMIT", "LIBERTY", "ALLIANCE",
    "CENTURY", "PACIFIC", "ATLANTIC", "EAGLE", "PHOENIX", "APEX", "VANTAGE",
    "SQUARE", "BLOCK", "MATCH", "OPEN", "NEXT", "ON", "V", "G", "IAC", "AS",
    "GO", "UP", "ARM", "LINE", "SONY", "VISA", "TARGET", "GAP", "NIKE",
}
MIN_CORE_LEN = 5   # 單詞公司名短於此長度一律複核


def norm(s):
    s = CRSP_TAGS.sub(" ", s.upper())
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def core(s):
    """縮寫標準化 + 剝除尾端法律字尾，回傳 token list。"""
    toks = [ABBREV.get(t, t) for t in norm(s).split()]
    while toks and toks[-1] in LEGAL:
        toks.pop()
    # 開頭的 THE 也剝掉
    while toks and toks[0] in {"THE"}:
        toks.pop(0)
    return toks


# ══════════════════════════════════════════════════════════ §2 個人發明者過濾
#
# 姓氏型公司名（THOMSON、EATON、BRADY、ROGERS...）會前綴命中大量「姓 + 名」的個人
# 發明者。實測 TCH（Technicolor，原名 Thomson SA）自動命中 46 個 assignee，其中
# 33 個是叫 Thomson 的個人。MIN_PUBS=3 擋不住——多產發明者輕易超過 3 件。
#
# 判斷「某 token 是不是人名的名字」不靠猜字表，而是從 375k 字典自己算兩個訊號：
#   follow  該 token 跟過幾個相異的首詞（姓氏）。MICHAEL 4144、DAVID 3595，
#           而公司專屬詞 GAMBLE 2、MAXELL 1、LUCENT 2。
#   legal   含該 token 的名稱中，同時含法律字尾的比例。名字幾乎為 0%
#           （MICHAEL 0.0%、DAVID 0.1%），公司詞則極高（TECH 90%、CORP 100%）。
# 兩個訊號正交，能把 MICHAEL 和 TECH 分開——兩者 follow 都很高，但 legal 天差地遠。
# 門檻由實測校準：真名字的 legal 比例幾乎都是 0%（BRAD/CHAD/KEVIN/PHILIP 0.0%），
# 而 INST 有 20.8%——把上限壓到 10% 才能把 WISTAR INST 這類機構留住。
# follow 下限 100 是為了收進 BRAD(103)、CHAD(149) 這些較少見的名字。
GIVEN_MIN_FOLLOW = 100
GIVEN_MAX_LEGAL = 0.10

# 只用真正的法律形式判斷 legal 比例，不含 THE/AND/GROUP 等泛詞。
# ⚠ AS 是丹麥/挪威的 Aktieselskab（等同 Inc），漏掉它會把 NOVOZYMES AS、
#   COLOPLAST AS、OTICON AS、DANFOSS AS 等真公司誤判成「姓+名」的個人。
LEGAL_STRICT = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "COMPANIES",
    "LLC", "LC", "LP", "LLP", "PLLC", "LTD", "LIMITED", "PLC", "SA", "SAS", "SARL",
    "NV", "BV", "AG", "GMBH", "KG", "KGAA", "KK", "AB", "OY", "OYJ", "SPA", "SRL",
    "AS", "ASA", "APS", "OG", "PTE", "PTY", "SE", "CV", "EV",
}

# 該姓氏底下有幾個相異的個人 assignee 才算「常見姓氏」。
# 設 15 是為了收進 THOMSON(19) 與 EATON(17)——TCH 是 Technicolor（原 Thomson SA），
# 若不擋，它會自動吃下 THOMSON REUTERS 的專利，而 Thomson Reuters 以 TRI 另列在名冊中。
# 寧可多送人工複核：偽陽性會憑空製造訊號，漏抓只是少算。
SURNAME_MIN = 15

# 機構前綴：這些詞開頭的一定是組織不是人。
# 實例：UNIV CHUNG YUAN CHRISTIAN（中原大學）會因 CHRISTIAN 被當成名字而誤殺。
INSTITUTION_HEAD = {
    "UNIV", "UNIVERSITY", "INST", "INSTITUTE", "COLLEGE", "SCHOOL", "ACADEMY",
    "HOSPITAL", "CLINIC", "FOUND", "FOUNDATION", "CENTER", "CENTRE", "LAB",
    "MUSEUM", "SOCIETY", "COUNCIL", "BOARD", "AGENCY", "BUREAU", "MINISTRY",
}


def learn_given_names(raw_names):
    """從字典實證推導『名字』token 集合，回傳 set。"""
    follow = collections.defaultdict(set)
    tot = collections.Counter()
    with_legal = collections.Counter()
    for nm in raw_names:
        t = re.sub(r"[^A-Z0-9]+", " ", nm.upper()).split()
        if not t:
            continue
        hl = any(x in LEGAL_STRICT for x in t)
        for x in set(t[1:]):
            follow[x].add(t[0])
            tot[x] += 1
            if hl:
                with_legal[x] += 1
    given = set()
    for tok, surs in follow.items():
        if len(surs) >= GIVEN_MIN_FOLLOW and with_legal[tok] / tot[tok] < GIVEN_MAX_LEGAL:
            given.add(tok)
    return given


def learn_surnames(raw_names, given):
    """哪些 token 是常見姓氏：統計它作為個人名首詞出現過幾次。

    公司名剝到只剩一個常見姓氏時（THOMSON、EATON、HALL），前綴比對會把
    同姓的個人與其他同姓公司全掃進來，必須送人工複核。
    """
    cnt = collections.Counter()
    for nm in raw_names:
        if is_person(nm, given):
            cnt[re.sub(r"[^A-Z0-9]+", " ", nm.upper()).split()[0]] += 1
    return {k for k, v in cnt.items() if v >= SURNAME_MIN}


def is_person(name, given):
    """姓 + 名(+中間名/縮寫)，且不含任何法律字尾 -> 判為個人。"""
    t = re.sub(r"[^A-Z0-9]+", " ", name.upper()).split()
    if len(t) < 2 or len(t) > 4:
        return False
    if any(x in LEGAL_STRICT for x in t):
        return False
    if t[0] in INSTITUTION_HEAD or any(x in INSTITUTION_HEAD for x in t):
        return False
    # 首詞視為姓氏，其後每一個都必須是「名字」或單字母縮寫
    return all(x in given or (len(x) == 1 and x.isalpha()) for x in t[1:])


# ══════════════════════════════════════════════════════════════ §3 三層比對

def load_roster():
    with open(ROOT / "out" / "firm_roster.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_dict():
    with open(ROOT / "out" / "assignee_dict.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    raw_names = [r["assignee_name"] for r in rows]
    given = learn_given_names(raw_names)
    surnames = learn_surnames(raw_names, given)
    out, persons = [], 0
    for r in rows:
        if is_person(r["assignee_name"], given):
            persons += 1
            continue
        c = core(r["assignee_name"])
        if not c:
            continue
        out.append((r["assignee_name"], " ".join(c), int(r["n_publications"]),
                    int(r["first_filing_year"]), int(r["last_filing_year"])))
    return out, given, surnames, persons


def match():
    roster = load_roster()
    adict, given, surnames, n_persons = load_dict()

    # 依首個 token 建索引，避免 268 x 375k 全比對
    by_first = collections.defaultdict(list)
    exact = collections.defaultdict(list)
    for name, ckey, n, y0, y1 in adict:
        by_first[ckey.split()[0]].append((name, ckey, n, y0, y1))
        exact[ckey].append((name, ckey, n, y0, y1))

    auto, review = [], []
    per_firm = collections.defaultdict(lambda: {"auto": 0, "rev": 0, "pubs": 0})

    for f in roster:
        names = [x for x in f["all_names"].split("|") if x.strip()]
        # 同一家公司的多個歷史名稱各自產生 core，去重
        cores = []
        for nm in names:
            c = " ".join(core(nm))
            if c and c not in cores:
                cores.append(c)

        seen_assignee = set()
        for c in cores:
            toks = c.split()
            # 單一 token 的公司名，若是普通詞、太短、或是常見姓氏，都不可自動採用：
            # 姓氏型（THOMSON、EATON）會把同姓的其他公司一起掃進來
            risky = (len(toks) == 1
                     and (c in GENERIC or len(c) < MIN_CORE_LEN or c in surnames))

            cands = []
            # T1 完全相同
            for cand in exact.get(c, []):
                cands.append(("T1_EXACT", cand))
            # T2 詞界前綴
            for cand in by_first.get(toks[0], []):
                if cand[1] == c:
                    continue
                if cand[1].startswith(c + " "):
                    cands.append(("T2_PREFIX", cand))
                else:
                    cands.append(("T3_REVIEW", cand))

            for tier, (aname, ackey, n, y0, y1) in cands:
                if aname in seen_assignee:
                    continue
                seen_assignee.add(aname)
                if risky and tier != "T1_EXACT":
                    tier = "T3_REVIEW"
                row = {
                    "permco": f["permco"],
                    "primary_ticker": f["primary_ticker"],
                    "primary_name": f["primary_name"],
                    "matched_from_name": c,
                    "assignee_name": aname,
                    "assignee_core": ackey,
                    "n_publications": n,
                    "first_filing_year": y0,
                    "last_filing_year": y1,
                    "tier": tier,
                    "risky_short_name": 1 if risky else 0,
                }
                if tier == "T3_REVIEW":
                    review.append(row)
                    per_firm[f["permco"]]["rev"] += 1
                else:
                    auto.append(row)
                    per_firm[f["permco"]]["auto"] += 1
                    per_firm[f["permco"]]["pubs"] += n

    cols = list(auto[0]) if auto else list(review[0])
    for rows, fn in ((auto, "assignee_match_auto.csv"), (review, "assignee_match_review.csv")):
        rows.sort(key=lambda r: (r["primary_ticker"], -r["n_publications"]))
        with open(ROOT / "out" / fn, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    L = []
    hit = sum(1 for f in roster if per_firm[f["permco"]]["auto"] > 0)
    L.append(f"實證推導的『名字』token: {len(given)} 個")
    L.append(f"實證推導的『常見姓氏』token: {len(surnames)} 個")
    L.append(f"判為個人發明者而排除的 assignee: {n_persons}")
    L.append(f"公司數: {len(roster)}")
    L.append(f"自動比對到 assignee 的公司: {hit}")
    L.append(f"完全沒比對到的公司: {len(roster) - hit}")
    L.append(f"T1+T2 自動採用列數: {len(auto)}")
    L.append(f"T3 待複核列數:      {len(review)}")

    L.append("\n沒有任何自動比對結果的公司（需人工找 assignee 或確認其無專利）")
    for f in roster:
        if per_firm[f["permco"]]["auto"] == 0:
            L.append(f"  {f['primary_ticker']:<8}{f['primary_name'][:44]:<46}"
                     f"論文{f['papers']:>5}  複核候選{per_firm[f['permco']]['rev']:>4}")

    L.append("\n自動比對件數 top 30（數字異常大者要懷疑誤配）")
    top = sorted(roster, key=lambda f: -per_firm[f["permco"]]["pubs"])[:30]
    for f in top:
        p = per_firm[f["permco"]]
        L.append(f"  {f['primary_ticker']:<8}{f['primary_name'][:34]:<36}"
                 f"{p['pubs']:>8} 件 / {p['auto']:>3} 個 assignee")

    L.append("\n風險：公司名剝除後只剩單一普通詞，其非完全相符的候選已全數移入複核")
    risky = sorted({(r["primary_ticker"], r["matched_from_name"])
                    for r in review if r["risky_short_name"]})
    for tk, c in risky:
        L.append(f"  {tk:<8}{c}")

    rep = ROOT / "out" / "assignee_match_report.txt"
    rep.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n寫入 {rep}")

    return roster


# ══════════════════════════════════════════════════════════════ §4 T3 裁決建議
#
# T3 之所以是偽陽性溫床，是因為「第一個詞相同」太便宜：
#   GEN DYNAMICS  vs GEN ELECTRIC      -> 兩家毫不相干
#   AMAZON COM    vs AMAZON TECH       -> 同一家（Amazon 的專利持有實體）
# 兩者的差別不在字串距離，而在**第一個詞是不是該公司獨有的品牌詞**。
#
# 所以用兩個資料驅動的訊號，不憑記憶：
#   head_firms  名冊裡有幾家公司的核心名以這個詞開頭。
#               GEN -> GD/GIS/GM/SYMC/GE 共 5 家，是共用詞，第二個詞才是品牌。
#               AMAZON -> 只有 AMZN 一家，是獨有品牌詞。
#   head_orgs   字典裡有幾個「不同的核心名」以這個詞開頭。數字大代表這個詞被
#               無數不相干的機構共用（UNIV、NAT、KOREA…）。
#
# 「品牌詞 + 功能詞」幾乎一定是同集團持有實體；「品牌詞 + 另一個實詞」則可能是
# 另一家獨立公司（TOYOTA JIDOSHOKKI 是另外上市的豐田自動織機），一律丟回人工。

# 企業功能/地理詞：接在品牌詞後面時，幾乎都是同集團的持有或營運實體
FUNCTIONAL = {
    "TECH", "RES", "DEV", "IP", "LICENSING", "SOLUTIONS", "PRODUCTS", "SERVICES",
    "SYS", "LAB", "GLOBAL", "INT", "ENTPR", "HOLDING", "HOLDINGS", "GROUP",
    "DIGITAL", "VENTURES", "INVESTMENTS", "OPERATIONS", "MFG", "ENG", "DESIGN",
    "SOFTWARE", "NETWORKS", "SEMICONDUCTOR", "MICROELECTRONICS", "INSTR",
    "AMERICA", "AMERICAS", "NORTH", "EUROPE", "ASIA", "JAPAN", "CHINA", "KOREA",
    "USA", "US", "UK", "DEUTSCHLAND", "FRANCE", "CANADA", "INDIA", "SINGAPORE",
    "COM", "ONLINE", "INTERACTIVE", "ENTERTAINMENT", "MEDIA", "STUDIOS",
}

MIN_PUB = 100      # 件數門檻：>=100 的 266 筆已涵蓋未裁決量的 87%


def suggest(roster):
    heads_firm = collections.defaultdict(set)
    for r in roster:
        c = core(r["primary_name"])          # core() 回傳 token list
        if c:
            heads_firm[c[0]].add(r["primary_ticker"])

    rev = list(csv.DictReader(open(ROOT / "out" / "assignee_match_review.csv",
                                   encoding="utf-8")))
    heads_org = collections.Counter()
    for r in rev:
        c = r["assignee_core"]
        if c:
            heads_org[c.split()[0]] += 1

    # 已裁決過的不再重複建議。首次執行時這個檔還不存在。
    manual = ROOT / "config" / "assignee_manual.csv"
    done = set()
    if manual.exists():
        with open(manual, encoding="utf-8") as fh:
            done = {(r["ticker"], r["assignee_name"]) for r in csv.DictReader(fh)}

    out = []
    for r in rev:
        if (r["primary_ticker"], r["assignee_name"]) in done:
            continue
        n = int(r["n_publications"])
        if n < MIN_PUB:
            continue
        p = (r["matched_from_name"] or "").split()
        a = (r["assignee_core"] or "").split()
        if not p or not a:
            continue
        head = p[0]
        nf, no = len(heads_firm.get(head, ())), heads_org.get(head, 0)
        rest = a[len(p):] if a[:len(p)] == p else None

        if a[0] != head:
            why, sug = "首詞不同", "EXCLUDE"
        elif nf > 1:
            # 共用首詞，品牌在第二個詞：必須整串前綴相同才可能是同一家
            if rest is not None:
                why, sug = f"首詞{head}為{nf}家共用，但完整前綴相符", "CHECK"
            else:
                why, sug = f"首詞{head}為{nf}家共用，第二詞不同", "EXCLUDE"
        elif rest is None:
            why, sug = "首詞獨有，但非完整前綴", "CHECK"
        elif not rest:
            why, sug = "核心名完全相同", "INCLUDE"
        elif all(t in FUNCTIONAL or t in LEGAL for t in rest):
            why, sug = f"品牌詞獨有 + 功能詞 {' '.join(rest)}", "INCLUDE"
        else:
            why, sug = f"品牌詞獨有，但多出實詞 {' '.join(rest)}", "CHECK"

        out.append({**r, "n": n, "suggest": sug, "why": why,
                    "head_firms": nf, "head_orgs": no})

    out.sort(key=lambda x: (x["suggest"], -x["n"]))
    p = ROOT / "out" / "assignee_review_suggest.csv"
    cols = ["suggest", "why", "primary_ticker", "primary_name", "matched_from_name",
            "assignee_name", "assignee_core", "n_publications", "first_filing_year",
            "last_filing_year", "head_firms", "head_orgs", "permco"]
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    c = collections.Counter(x["suggest"] for x in out)
    print(f"\n待審且件數 >= {MIN_PUB} 的有 {len(out)} 筆")
    for k in ("INCLUDE", "CHECK", "EXCLUDE"):
        rows = [x for x in out if x["suggest"] == k]
        print(f"  {k:<8}{c[k]:>4} 筆，涉及 {sum(x['n'] for x in rows):>7,} 件 publication")
    print(f"\n寫入 {p}")
    if not out:
        # 這不是錯誤：所有 >= MIN_PUB 的候選都已在 assignee_manual.csv 裡裁決過了。
        # 裁決的完整紀錄（含每一筆的理由）在 config/assignee_manual.csv，不在這裡。
        # 要再挖一批出來審，把 MIN_PUB 調低即可。
        print(f"  （空的是正常的：件數 >= {MIN_PUB} 者已全數裁決完畢。"
              f"要續審請調低 MIN_PUB）")


def main():
    roster = match()
    suggest(roster)


if __name__ == "__main__":
    main()
