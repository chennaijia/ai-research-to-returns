# ============================================================
#  02_build_panel.R
#
#  把 426MB 的 CRSP 面板讀進來一次，產出後續所有檢定要用的月頻資料。
#  （整併前 02/03/04/06 各讀一次，光讀檔就四遍。）
#
#  產出三個檔：
#    analysis_monthly.csv       主資料集，一列一個月
#    size_spreads.csv           規模五分組 × 月份的價差
#    company_papers_annual.csv  公司論文年度數，供前提檢驗用
#
#  三個容易出錯的地方：
#
#  (1) 市值加權必須用「上月底」的市值。
#      mthcap 是月底市值，已經含了當月報酬。用當月市值加權等於讓漲得多的
#      股票同時拿到高權重，會系統性高估組合報酬。
#
#  (2) 不能用 shift() 取上個月。
#      公司在 CRSP 有斷月，shift() 取到的是「上一筆觀測」而非「上個月」。
#      這裡用整數月份索引 t，明確 merge (permno, t-1)。
#
#  (3) 主結果用市值加權。非科技組有 17,000 家、中位市值僅 1.7 億，
#      mthret 最大值達 3900%，等權序列會被單一微型股綁架。等權仍算出來備查。
#
#  去季節性：對 X 做四種處理，理由與比較見 03。
# ============================================================

source(file.path("02_returns", "scripts", "00_common.R"))

start_log("build_panel_diagnostics.txt")

# ------------------------------------------------------------
# 1. 讀檔並接上 01 的公司層級分類
# ------------------------------------------------------------
say("=== 讀取 CRSP 面板 ===")
dt <- fread(PANEL,
            select = c("permno", "ticker", "year_month", "mthret", "mthcap",
                       "vwretd", "n_papers"),
            showProgress = FALSE)
cls <- fread(file.path(OUT_DIR, "tech_classification.csv"),
             select = c("permno", "tech", "tech_last"))

say("CRSP 列數: ", format(nrow(dt), big.mark = ","))
say("無法分類而剔除的公司: ", sum(is.na(cls$tech)), " 家（全程無有效 NAICS）")

# 公司論文年度數：留給 04 檢驗「企業是否真的停止發論文」
cpa <- dt[, .(papers = sum(n_papers, na.rm = TRUE)), by = .(ticker, yr = substr(year_month, 1, 4))]
fwrite(cpa[papers > 0], file.path(OUT_DIR, "company_papers_annual.csv"))

dt <- merge(dt, cls[!is.na(tech)], by = "permno")
say("併入分類後列數: ", format(nrow(dt), big.mark = ","))

# ------------------------------------------------------------
# 2. 取上月市值當權重
# ------------------------------------------------------------
dt[, t := as.integer(substr(year_month, 1, 4)) * 12L +
          as.integer(substr(year_month, 6, 7))]
dt <- merge(dt, dt[!is.na(mthcap) & mthcap > 0, .(permno, t = t + 1L, w = mthcap)],
            by = c("permno", "t"), all.x = TRUE)

say("")
say("=== 權重可用性 ===")
say("有上月市值的列: ", format(sum(!is.na(dt$w)), big.mark = ","),
    sprintf("  (%.1f%%)", 100 * mean(!is.na(dt$w))))
say("（缺的是每家公司在 CRSP 的第一個月，以及斷月後的第一個月）")

dt <- dt[!is.na(w) & !is.na(mthret)]
say("實際進入計算的列: ", format(nrow(dt), big.mark = ","))

# ------------------------------------------------------------
# 3. 兩組月報酬
# ------------------------------------------------------------
g <- dt[, .(vw = sum(w * mthret) / sum(w), ew = mean(mthret), n = .N),
        by = .(year_month, tech)]
m <- dcast(g, year_month ~ tech, value.var = c("vw", "ew", "n"))
setnames(m, c("vw_TRUE", "vw_FALSE", "ew_TRUE", "ew_FALSE", "n_TRUE", "n_FALSE"),
         c("tech_vw", "nontech_vw", "tech_ew", "nontech_ew", "n_tech", "n_nontech"))
m[, spread_vw := tech_vw - nontech_vw]
m[, spread_ew := tech_ew - nontech_ew]

# 期末碼分類的版本，供穩健性檢查
alt <- dcast(dt[, .(vw = sum(w * mthret) / sum(w)), by = .(year_month, tech_last)],
             year_month ~ tech_last, value.var = "vw")
m <- merge(m, alt[, .(year_month, spread_vw_alt = `TRUE` - `FALSE`)], by = "year_month")
m <- merge(m, dt[, .(vwretd = first(vwretd)), by = year_month], by = "year_month")
setorder(m, year_month)

# ------------------------------------------------------------
# 4. 規模五分組的價差
#
#    等權顯著、市值加權不顯著時，要能分辨是「效果只在小公司」還是
#    「單純檢定力差異」。依上月市值切全市場五等分，組內再算價差。
# ------------------------------------------------------------
dt[, q := cut(w, breaks = quantile(w, 0:5 / 5), labels = 1:5,
              include.lowest = TRUE), by = year_month]
sz <- dcast(dt[, .(vw = sum(w * mthret) / sum(w)), by = .(year_month, q, tech)],
            year_month + q ~ tech, value.var = "vw")
sz[, spread := `TRUE` - `FALSE`]
sz_n <- dt[tech == TRUE, .(n_tech_firms = uniqueN(permno)), by = q]
fwrite(sz[, .(year_month, q, tech_r = `TRUE`, nontech_r = `FALSE`, spread)],
       file.path(OUT_DIR, "size_spreads.csv"))

say("")
say("=== 各規模組的科技公司數 ===")
show(sz_n[order(q)])

rm(dt); invisible(gc())

# ------------------------------------------------------------
# 5. 併 AI 論文序列，建自變數
#
#    用發表數不用引用數：引用數在這份資料裡是「論文年齡」的代理，
#    2017 年論文平均 54.3 次引用、2025 年只剩 0.39 次，單調遞減。
#    放進迴歸會造出一條假的下降趨勢。
#
#    取對數差分：ai_papers 從月均 1,322(2017) 漲到 8,971(2025)，
#    水準值直接迴歸會是假迴歸。
# ------------------------------------------------------------
ai <- fread(AI_MONTHLY)
ai[, year_month := format(as.Date(month), "%Y-%m")]
d <- merge(m, ai[, .(year_month, ai_papers, total_citations)], by = "year_month")
setorder(d, year_month)
d[, mth := as.integer(substr(year_month, 6, 7))]

lp <- log(d$ai_papers)

# 方法 0：原始，完全不處理季節性
d[, x_raw := c(NA, diff(lp))]

# 方法 1：月份去中心化 —— 減掉該月份的歷史平均成長率（主設定）
d[, x_demean := x_raw - ave(x_raw, mth, FUN = function(z) mean(z, na.rm = TRUE))]

# 方法 2：年增率 —— 會議日曆每年重複，同月相比會自動抵消
d[, x_yoy := c(rep(NA_real_, 12), diff(lp, lag = 12))]

# 方法 3：STL 分解 —— 拆成趨勢+季節+殘差，扣掉季節成分再差分
ts_lp <- ts(lp, start = c(as.integer(substr(min(d$year_month), 1, 4)),
                          as.integer(substr(min(d$year_month), 6, 7))), frequency = 12)
d[, x_stl := c(NA, diff(as.numeric(ts_lp - stl(ts_lp, s.window = "periodic")$time.series[, "seasonal"])))]

# 方法 1b：滾動版 —— 只用當期之前的資料估月份平均，無前視偏誤
d[, x_roll := {
  out <- rep(NA_real_, .N)
  for (i in seq_len(.N)) {
    if (is.na(x_raw[i])) next
    h <- x_raw[seq_len(i - 1)][mth[seq_len(i - 1)] == mth[i]]
    h <- h[!is.na(h)]
    if (length(h) >= 3) out[i] <- x_raw[i] - mean(h)
  }
  out
}]

# ------------------------------------------------------------
# 6. 診斷
# ------------------------------------------------------------
say("")
say("=== 序列概況 ===")
say("報酬序列: ", min(m$year_month), " ~ ", max(m$year_month), "  (", nrow(m), " 月)")
say("論文序列: ", min(ai$year_month), " ~ ", max(ai$year_month), "  (", nrow(ai), " 月)")
say("重疊樣本: ", min(d$year_month), " ~ ", max(d$year_month), "  (", nrow(d), " 月)")
say("每月平均家數 —— 科技: ", round(mean(m$n_tech)), "   非科技: ", round(mean(m$n_nontech)))

desc <- function(x, nm) data.table(
  序列 = nm,
  平均月報酬 = sprintf("%.3f%%", 100 * mean(x)),
  年化 = sprintf("%.1f%%", 100 * ((1 + mean(x))^12 - 1)),
  標準差 = sprintf("%.2f%%", 100 * sd(x)),
  最小 = sprintf("%.1f%%", 100 * min(x)),
  最大 = sprintf("%.1f%%", 100 * max(x)))

say("")
show(rbindlist(list(
  desc(m$tech_vw, "科技 市值加權"),   desc(m$nontech_vw, "非科技 市值加權"),
  desc(m$spread_vw, "價差 市值加權"), desc(m$tech_ew, "科技 等權"),
  desc(m$nontech_ew, "非科技 等權"),  desc(m$spread_ew, "價差 等權"),
  desc(m$vwretd, "CRSP 大盤"))))

say("")
say("=== 合理性檢查 ===")
say(sprintf("科技組 vs CRSP 大盤相關: %.3f", cor(m$tech_vw, m$vwretd)))
say(sprintf("非科技組 vs CRSP 大盤相關: %.3f", cor(m$nontech_vw, m$vwretd)))
say(sprintf("兩組報酬相關: %.3f", cor(m$tech_vw, m$nontech_vw)))
say("（兩組高度相關是正常的 —— 這正是為什麼要看價差而不是各自的水準）")
say(sprintf("主分類 vs 期末碼分類的價差序列相關: %.3f", cor(m$spread_vw, m$spread_vw_alt)))

tt <- t.test(m$spread_vw)
say("")
say(sprintf("價差平均 %.3f%%/月，t = %.2f, p = %.3f",
            100 * mean(m$spread_vw), tt$statistic, tt$p.value))
say("→ 這是科技溢酬，還沒牽扯到 AI 論文")

say("")
say("=== 自變數：各去季節方法保留的變異 ===")
show(rbindlist(lapply(c("x_raw", "x_demean", "x_yoy", "x_stl", "x_roll"), function(v) {
  z <- d[[v]][!is.na(d[[v]])]
  data.table(方法 = v, n = length(z), 標準差 = round(sd(z), 4),
             一階自相關 = round(acf(z, lag.max = 1, plot = FALSE)$acf[2], 3))
})))

fwrite(d, file.path(OUT_DIR, "analysis_monthly.csv"))
say("")
say("=== 已輸出 ===")
say(file.path(OUT_DIR, "analysis_monthly.csv"), "  (", nrow(d), " 個月)")
say(file.path(OUT_DIR, "size_spreads.csv"))
say(file.path(OUT_DIR, "company_papers_annual.csv"))
end_log()
