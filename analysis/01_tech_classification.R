# ============================================================
#  01_tech_classification.R
#
#  目的：從 CRSP 全市場面板建立「科技業 vs 非科技業」分類。
#
#  取代 stock_and_paper_count 原有的 is_ict 欄位，因為它有兩個 bug：
#
#  Bug 1 — ICT 代碼表是舊版 NAICS，CRSP 卻會把公司改成新版代碼。
#    NAICS 2022 改版把「軟體出版」從 511210 搬到 513210，舊表沒有 5132，
#    於是所有軟體公司自 2023 年起被判為非科技業。
#    資料證據：5112 的公司數 1,939(2022) → 0(2025)；5132 為 0(2022) → 1,797(2025)。
#    2022 年屬 ICT 且活到 2025 的 673 家公司，有 263 家(39.1%)純因改版掉出科技業。
#
#  Bug 2 — 分類隨時間翻轉，同一家公司會換組。
#    is_ict 曾翻轉的公司佔全體 7.9%，但在「有發論文」的公司裡高達 26%(59/229)，
#    含 GOOGL、MSFT、META、ADBE、BIDU、CRM 等論文數最高的幾家。
#    對照組設計若讓公司中途換組，價差檢定不管顯不顯著都無法解讀。
#
#  修法：
#    (1) 規則寫在 6 碼層級，處理「同碼異義」——
#        舊表的 5161 指「網路出版與廣播」，但 NAICS 2022 的 5161 是廣播電視台。
#        照字面補新碼會把電視台當成科技業。
#    (2) 分類固定在公司層級（以月份數多數決），時間不變。
#
#  跨版本對應：
#    5161(2007) + 5181(2007) → 519130(2012/17) → 516210 + 519290 (2022)
#    5112(2017)                                → 513210 (2022)
#    5179(2017)                                → 517810 (2022)
#
#  科技業定義採「純 NAICS，不手動調整」——
#    AMZN(零售 4541)、TSLA(汽車 3361) 因此歸入非科技組。這是刻意的：
#    規則客觀可複現，避免挑樣本的質疑。
#
#  輸出：out/tech_classification.csv   公司層級對照表
#        out/tech_classification_diagnostics.txt
# ============================================================

suppressMessages({
  library(data.table)
})

PANEL   <- file.path("stock_and_paper_count",
                     "crsp_all_classified_with_papers_detailed.csv")
OUT_DIR <- file.path("analysis", "out")

dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

con <- file(file.path(OUT_DIR, "tech_classification_diagnostics.txt"), open = "wt")
say <- function(...) { msg <- paste0(...); cat(msg, "\n"); writeLines(msg, con) }
show <- function(x) { txt <- capture.output(print(x)); cat(txt, sep = "\n"); cat("\n")
                      writeLines(txt, con) }

# ------------------------------------------------------------
# 1. ICT 定義（6 碼，跨 NAICS 版本）
# ------------------------------------------------------------

# (a) 製造業：4 碼在各版本間穩定，用前綴比對
ict_mfg_prefix <- c(
  "3341",  # 電腦與週邊設備製造
  "3342",  # 通訊設備製造
  "3344",  # 半導體與電子零組件製造
  "3345"   # 導航、量測、電子醫療、控制儀器製造
)

# (b) 資訊服務業：4 碼在 NAICS 2022 大幅重編，必須逐 6 碼列舉
ict_info_6digit <- c(
  # 軟體出版
  "511210", "511200",           # NAICS 2012/2017
  "513210",                     # NAICS 2022（同一批公司搬過來）

  # 網路出版 / 搜尋入口 / 社群平台
  "519130", "519190",           # NAICS 2012/2017
  "516210", "519290",           # NAICS 2022（519130 拆成這兩碼）
  "518111",                     # NAICS 2007 殘留的 ISP

  # 資料處理、主機代管、雲端基礎設施
  "518210",                     # 兩版皆同

  # 其他電信（非電信商）
  "517911", "517919",           # NAICS 2012/2017
  "517810",                     # NAICS 2022

  # 電腦系統設計與相關服務
  "541511", "541512", "541513", "541519"
)

# (c) 明確排除：這些碼在新版與 ICT 舊碼「同號但異義」，或本質是媒體/圖書館
ict_excluded_note <- c(
  "516110", "516120",   # NAICS 2022 的 5161 = 廣播電視台，不是舊表的「網路出版」
  "519110", "519120",   # 新聞通訊社、圖書館檔案館
  "519210"              # NAICS 2022 圖書館檔案館
)

is_ict_code <- function(naics6) {
  n <- as.character(naics6)
  ok <- n %in% ict_info_6digit
  for (p in ict_mfg_prefix) ok <- ok | startsWith(n, p)
  ok & !is.na(n)
}

# ------------------------------------------------------------
# 2. 讀資料
# ------------------------------------------------------------
say("=== 讀取 CRSP 面板 ===")
dt <- fread(PANEL,
            select = c("permno", "ticker", "issuernm", "naics", "naics_4digit",
                       "siccd", "year_month", "mthret", "mthcap",
                       "ai_group", "is_ict", "n_papers"),
            showProgress = FALSE)
say("列數: ", format(nrow(dt), big.mark = ","),
    "   公司數: ", format(uniqueN(dt$permno), big.mark = ","),
    "   期間: ", min(dt$year_month), " ~ ", max(dt$year_month))

# CRSP 用 naics = 0 表示「無資料」，不是 NA。fread 讀進來是整數 0，
# 所以 is.na() 完全抓不到。已下市公司的最後幾個月幾乎都是 0，
# 若不排除，「期末代碼」規則會把所有下市公司判成非科技。
dt[, naics_ok := !is.na(naics) & naics > 0]
say("NAICS 缺值（is.na）: ", sum(is.na(dt$naics)))
say("NAICS 為 0（CRSP 的缺值碼）: ", format(sum(dt$naics == 0, na.rm = TRUE), big.mark = ","),
    sprintf("  (%.2f%%)", 100 * mean(dt$naics == 0, na.rm = TRUE)))
say("NAICS 全程為 0 的公司數: ", dt[, sum(!any(naics_ok)), by = permno][, sum(V1)])

# ------------------------------------------------------------
# 3. 逐月套用新規則
# ------------------------------------------------------------
dt[, tech_m := is_ict_code(naics)]

say("")
say("=== 月層級：新舊規則差異 ===")
say("舊規則判定為科技的列數: ", format(sum(dt$is_ict, na.rm = TRUE), big.mark = ","))
say("新規則判定為科技的列數: ", format(sum(dt$tech_m), big.mark = ","))
say("新增（舊非科技→新科技）: ",
    format(sum(dt$tech_m & !dt$is_ict, na.rm = TRUE), big.mark = ","))
say("移除（舊科技→新非科技）: ",
    format(sum(!dt$tech_m & dt$is_ict, na.rm = TRUE), big.mark = ","))

# ------------------------------------------------------------
# 4. 固定到公司層級
#
#    三種收斂規則，因為它們在「CRSP 中途更正舊代碼」時會分歧：
#      tech      多數決 —— 公司在樣本期間「大部分時候」是什麼
#      tech_last 期末代碼 —— 相信 CRSP 最新一次的判定
#      tech_ever 曾經是 —— 最寬鬆，僅作上界參考
#
#    CRM 是最好的例子：2010-01~2019-08 共 116 個月被 CRSP 編為 541611
#    （管理顧問業），2019-09 才改成 511210/513210（軟體出版）。
#    多數決 → 非科技；期末 → 科技。兩者都不算錯，是 CRSP 更正造成的。
#
#    主分類採多數決：報酬序列橫跨整個樣本期，用「期末身分」回頭標記
#    2010 年的報酬，前視偏誤比多數決更嚴重。tech_last 留作穩健性檢查。
# ------------------------------------------------------------
setorder(dt, permno, year_month)
firm <- dt[, {
  v <- which(naics_ok)                        # 只用有效 NAICS 的月份
  .(ticker      = last(ticker[!is.na(ticker) & ticker != ""]),
    issuernm    = last(issuernm),
    months      = .N,
    months_ok   = length(v),
    tech_share  = if (length(v)) mean(tech_m[v]) else NA_real_,
    tech_last   = if (length(v)) tech_m[last(v)] else NA,
    naics_modal = if (length(v)) names(sort(table(naics[v]), decreasing = TRUE))[1] else NA_character_,
    naics_last  = if (length(v)) naics[last(v)] else NA_integer_,
    ai_group    = first(ai_group),
    papers      = sum(n_papers, na.rm = TRUE),
    mthcap_avg  = mean(mthcap, na.rm = TRUE))
}, by = permno]

firm[, tech      := tech_share >= 0.5]
firm[, tech_ever := tech_share > 0]

say("")
say("=== 三種收斂規則的比較 ===")
say("（無任何有效 NAICS、無法分類的公司: ", sum(is.na(firm$tech)), " 家）")
tot <- sum(firm$papers)
say(sprintf("多數決  科技 %5d 家，拿到 %.1f%% 的論文",
            sum(firm$tech, na.rm = TRUE),
            100 * sum(firm[tech == TRUE]$papers) / tot))
say(sprintf("期末碼  科技 %5d 家，拿到 %.1f%% 的論文",
            sum(firm$tech_last, na.rm = TRUE),
            100 * sum(firm[tech_last == TRUE]$papers) / tot))
say(sprintf("曾經是  科技 %5d 家，拿到 %.1f%% 的論文",
            sum(firm$tech_ever, na.rm = TRUE),
            100 * sum(firm[tech_ever == TRUE]$papers) / tot))
say("多數決與期末碼分歧的公司數: ", sum(firm$tech != firm$tech_last, na.rm = TRUE))

say("")
say("--- 分歧公司中論文數最高的 15 家 ---")
show(head(firm[tech != tech_last][order(-papers),
     .(ticker, issuernm, naics_modal, naics_last,
       tech_share = round(tech_share, 2), tech, tech_last, papers)], 15))

say("")
say("=== 界線模糊的公司（0.2 < tech_share < 0.8）: ",
    sum(firm$tech_share > 0.2 & firm$tech_share < 0.8, na.rm = TRUE), " 家 ===")
amb <- firm[tech_share > 0.2 & tech_share < 0.8][order(-papers)]
if (nrow(amb) > 0) {
  show(head(amb[, .(ticker, issuernm, naics_modal, naics_last,
                    tech_share = round(tech_share, 2), months, papers)], 15))
}

# ------------------------------------------------------------
# 5. 驗證：Mag7 與論文數最高的公司歸類是否合理
# ------------------------------------------------------------
say("")
say("=== 驗證 A：Mag7 的歸類 ===")
show(firm[ai_group == "A"][order(-papers),
     .(ticker, issuernm, naics_modal, tech_share = round(tech_share, 2),
       tech, tech_last, papers)])

say("")
say("=== 驗證 B：論文數前 25 大公司 ===")
show(head(firm[order(-papers),
     .(ticker, issuernm, naics_modal, tech, tech_last, ai_group, papers)], 25))

# ------------------------------------------------------------
# 6. 最終分組規模
# ------------------------------------------------------------
say("")
say("=== 最終分組（全 CRSP，主分類＝多數決）===")
show(firm[, .(公司數 = .N,
              總論文 = sum(papers),
              平均市值_百萬 = round(mean(mthcap_avg, na.rm = TRUE) / 1000, 1),
              中位市值_百萬 = round(median(mthcap_avg, na.rm = TRUE) / 1000, 1)),
          by = tech][order(-tech)])

say("")
say("=== 有發 AI 論文的公司分布 ===")
show(firm[papers > 0, .(公司數 = .N, 總論文 = sum(papers)), by = tech][order(-tech)])

say("")
say("=== 新舊規則對照：論文落在科技組的比例 ===")
old_firm <- dt[, .(papers = sum(n_papers, na.rm = TRUE),
                   old_tech = mean(is_ict, na.rm = TRUE) >= 0.5), by = permno]
say(sprintf("舊規則: 科技組拿到 %.1f%% 的論文",
            100 * sum(old_firm[old_tech == TRUE]$papers) / sum(old_firm$papers)))
say(sprintf("新規則: 科技組拿到 %.1f%% 的論文",
            100 * sum(firm[tech == TRUE]$papers) / sum(firm$papers)))

# ------------------------------------------------------------
# 7. 存檔
# ------------------------------------------------------------
setcolorder(firm, c("permno", "ticker", "issuernm", "naics_modal", "naics_last",
                    "tech", "tech_last", "tech_ever", "tech_share",
                    "ai_group", "papers", "months", "months_ok", "mthcap_avg"))
fwrite(firm, file.path(OUT_DIR, "tech_classification.csv"))

say("")
say("=== 已輸出 ===")
say(file.path(OUT_DIR, "tech_classification.csv"), "  (", nrow(firm), " 家公司)")
close(con)
