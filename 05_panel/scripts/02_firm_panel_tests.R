# ============================================================
#  02_firm_panel_tests.R —— 公司層級面板迴歸：
#  「這家公司自己發的論文/申請的專利，跟自己下個月的股價報酬有沒有關係？」
#
#  跟 02_returns 的差別：02_returns 問的是總體層級（科技股整體 vs
#  非科技股整體），這裡問的是公司層級、用自己的時間序列變異（within-firm
#  variation），公司固定效果 + 月份固定效果拿掉：
#    (a) 每家公司自己的體質（規模、產業、體質好壞的平均水準）
#    (b) 每個月的大盤共同衝擊（月份固定效果本身就等於一個完整的市場對照組）
#  剩下的變異只可能來自：這家公司「這個月」的論文/專利活動是不是比自己
#  平常活躍，跟這家公司「這個月」的報酬是不是比自己平常好，兩者是否同動。
#
#  執行：Rscript 05_panel/scripts/02_firm_panel_tests.R
# ============================================================

suppressMessages({
  library(data.table)
  library(plm)
  library(lmtest)
  library(sandwich)
})

PANEL   <- file.path("05_panel", "out", "panel_firm_month.csv")
OUT_DIR <- file.path("05_panel", "out")
LOG     <- file(file.path(OUT_DIR, "firm_panel_tests.txt"), open = "wt")

say <- function(...) { m <- paste0(...); cat(m, "\n"); writeLines(m, LOG) }
show <- function(x) { txt <- capture.output(print(x)); cat(txt, sep = "\n"); cat("\n"); writeLines(txt, LOG) }

# ------------------------------------------------------------
#  兩期固定效果迴歸（公司 + 月份）+ 依公司分群的 cluster-robust 標準誤
#
#  用公司叢集（不是 HAC）是因為這裡的序列相關結構是「同一家公司跨月」，
#  不是總體時間序列的落後相關；月份固定效果已經把共同時間衝擊拿掉了。
# ------------------------------------------------------------
firm_fe <- function(formula, data, term) {
  pdata <- pdata.frame(data, index = c("permco", "yyyymm"))
  m  <- plm(formula, data = pdata, model = "within", effect = "twoways")
  ct <- coeftest(m, vcov = vcovHC(m, type = "HC1", cluster = "group"))
  list(b = ct[term, 1], se = ct[term, 2], t = ct[term, 3], p = ct[term, 4],
       n = nobs(m), n_firms = length(unique(index(m)[[1]])), r2 = r.squared(m))
}
fmt <- function(h) sprintf("%+.4f (t=%+.2f, p=%.3f, n=%d, %d 家公司)", h$b, h$t, h$p, h$n, h$n_firms)

bh <- function(p) p.adjust(p, method = "BH")

say("============================================================")
say(" 公司層級面板迴歸：自己的論文/專利 → 自己下期報酬")
say("============================================================")
say("")

d <- fread(PANEL)
setorder(d, permco, yyyymm)
say("原始面板: ", nrow(d), " 列（", uniqueN(d$permco), " 家公司 × 108 個月）")

d <- d[!is.na(mthret)]
say("有月報酬的列: ", nrow(d), " （", uniqueN(d$permco), " 家公司，",
    "剩下的是下市/未上市月份）")
say("")

# 自變數：log(1+x)。論文/專利都是計數且大量為 0，用 log1p 而不是差分——
# 差分在「0 → 0」佔絕大多數的稀疏計數資料上幾乎沒有訊號，且會把本來就
# 該有的公司固定效果（有些公司常年在發論文，有些從不發）跟著拿掉，
# 而固定效果迴歸本來就會做這件事，不需要再做一次差分。
d[, log_papers  := log1p(n_papers)]
d[, log_patents := log1p(ai_patents_with_subs)]

# 落後一期（依公司分組），用來看「上個月的論文/專利」是否領先「這個月的報酬」
setkey(d, permco, yyyymm)
d[, log_papers_l1  := shift(log_papers,  1), by = permco]
d[, log_patents_l1 := shift(log_patents, 1), by = permco]

say("=== 描述統計 ===")
say("曾經發過 AI 論文的公司: ", uniqueN(d[n_papers > 0, permco]), " 家")
say("曾經申請過 AI 專利的公司: ", uniqueN(d[ai_patents_with_subs > 0, permco]), " 家")
say("有論文的公司-月比例: ", sprintf("%.1f%%", 100 * mean(d$n_papers > 0, na.rm = TRUE)))
say("有專利的公司-月比例: ", sprintf("%.1f%%", 100 * mean(d$ai_patents_with_subs > 0, na.rm = TRUE)))
say("")

# ------------------------------------------------------------
#  測試一：論文
# ------------------------------------------------------------
say("============================================================")
say(" 測試一：自己的論文活動 → 自己的報酬")
say("============================================================")

r_papers_0  <- firm_fe(mthret ~ log_papers,     d, "log_papers")
r_papers_1  <- firm_fe(mthret ~ log_papers_l1,  d[!is.na(log_papers_l1)], "log_papers_l1")
say("同期: ", fmt(r_papers_0))
say("落後一期: ", fmt(r_papers_1))
p_adj <- bh(c(r_papers_0$p, r_papers_1$p))
say("BH 校正後 p: 同期 ", sprintf("%.3f", p_adj[1]), "，落後一期 ", sprintf("%.3f", p_adj[2]))
say("")
say("（本檔論文數來自修正後的 v2 CRSP 面板，2022 年起沒有 OpenAlex 機構隸屬")
say(" 斷鏈造成的系統性低估——公司論文數延續母體語料的成長趨勢，見")
say(" 02_returns/out/structural_change.txt 的前提檢驗。下面用 2022 年以前的")
say(" 子樣本重跑一次，純粹檢查結論是否跨期間穩定：）")

d_pre22 <- d[year < 2022]
r_papers_pre22 <- firm_fe(mthret ~ log_papers, d_pre22, "log_papers")
say("   2017-2021 子樣本: ", fmt(r_papers_pre22))
say("")

# ------------------------------------------------------------
#  測試二：專利（排除公開時滯必然低估的月份）
# ------------------------------------------------------------
say("============================================================")
say(" 測試二：自己的 AI 專利申請 → 自己的報酬")
say("============================================================")
say("排除 patent_truncated==1 的月份（申請後約 18 個月才公開，2024-10 之後")
say("的申請月數必然被低估，見 05_panel/README.md）。")
say("")

d_pat <- d[patent_truncated == 0]
say("排除後剩餘: ", nrow(d_pat), " 列")

r_pat_0 <- firm_fe(mthret ~ log_patents,    d_pat, "log_patents")
r_pat_1 <- firm_fe(mthret ~ log_patents_l1, d_pat[!is.na(log_patents_l1)], "log_patents_l1")
say("同期: ", fmt(r_pat_0))
say("落後一期: ", fmt(r_pat_1))
p_adj2 <- bh(c(r_pat_0$p, r_pat_1$p))
say("BH 校正後 p: 同期 ", sprintf("%.3f", p_adj2[1]), "，落後一期 ", sprintf("%.3f", p_adj2[2]))
say("")

# ------------------------------------------------------------
#  測試三：論文與專利放在同一條迴歸裡（互相控制）
# ------------------------------------------------------------
say("============================================================")
say(" 測試三：論文與專利放在同一條迴歸裡")
say("============================================================")

pdata3 <- pdata.frame(d_pat, index = c("permco", "yyyymm"))
m3  <- plm(mthret ~ log_papers + log_patents, data = pdata3, model = "within", effect = "twoways")
ct3 <- coeftest(m3, vcov = vcovHC(m3, type = "HC1", cluster = "group"))
show(ct3)
say("樣本數: ", nobs(m3), "，公司數: ", length(unique(index(m3)[[1]])))
say("")

say("=== 已輸出 ===")
say(file.path(OUT_DIR, "firm_panel_tests.txt"))
close(LOG)
