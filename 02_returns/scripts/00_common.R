# ============================================================
#  00_common.R  —— 共用路徑、紀錄器與統計工具
#
#  各腳本開頭 source("02_returns/scripts/00_common.R")。
#  全部路徑相對於 repo 根目錄，執行方式：Rscript 02_returns/scripts/0X_xxx.R
# ============================================================

suppressMessages({
  library(data.table)
  library(sandwich)
  library(lmtest)
})

PANEL      <- file.path("01_universe", "out",
                        "crsp_all_classified_with_papers_detailed.csv")
AI_MONTHLY <- file.path("data", "arxiv", "ai_monthly.csv")
OUT_DIR    <- file.path("02_returns", "out")
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

HAC_LAG <- 4          # Newey-West 落後階數，月頻資料取 4

# ------------------------------------------------------------
#  紀錄器：同時印到畫面與寫進診斷檔
#
#  start_log 會先關掉還開著的連線。在 RStudio 裡 session 是持續的，
#  腳本中途出錯就不會執行到 end_log()，連線會一直開著；累積夠多次
#  會撞到 R 的連線上限而報「all connections are in use」。
# ------------------------------------------------------------
if (!exists(".log_con")) .log_con <- NULL   # 重新 source 時不要蓋掉還開著的連線

start_log <- function(filename) {
  if (!is.null(.log_con)) try(close(.log_con), silent = TRUE)
  .log_con <<- file(file.path(OUT_DIR, filename), open = "wt")
}
end_log <- function() { close(.log_con); .log_con <<- NULL }

say <- function(...) {
  m <- paste0(...)
  cat(m, "\n")
  if (!is.null(.log_con)) writeLines(m, .log_con)
}

show <- function(x) {
  txt <- capture.output(print(x))
  cat(txt, sep = "\n"); cat("\n")
  if (!is.null(.log_con)) writeLines(txt, .log_con)
}

# ------------------------------------------------------------
#  以 Newey-West HAC 標準誤估迴歸，取出關心的那個係數
#
#  月頻報酬同時有序列相關與異質變異，一般 OLS 標準誤會低估。
#  term 預設取第二個係數（也就是第一個解釋變數）。
# ------------------------------------------------------------
hac <- function(formula, data, term = NULL) {
  m  <- lm(formula, data = data)
  ct <- coeftest(m, vcov = NeweyWest(m, lag = HAC_LAG, prewhite = FALSE))
  if (is.null(term)) term <- rownames(ct)[2]
  list(b = ct[term, 1], se = ct[term, 2], t = ct[term, 3], p = ct[term, 4],
       n = nobs(m), r2 = summary(m)$r.squared, ct = ct)
}

fmt <- function(h) sprintf("%+.4f (t=%+.2f, p=%.3f, n=%d)", h$b, h$t, h$p, h$n)

verdict <- function(p) ifelse(p < 0.05, "顯著", ifelse(p < 0.10, "邊緣", "否"))

# 圖用英文標籤：png 裝置沒有嵌入 CJK 字型，中文會變成方框
