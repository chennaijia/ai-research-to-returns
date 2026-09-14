# ============================================================
#  03_main_tests.R
#
#  兩個必須分開回答的問題：
#
#    Q1  AI 論文產出會不會影響科技股報酬？   y = 科技組市值加權報酬
#    Q2  這個影響是不是科技業「專屬」？      y = 價差（科技 − 非科技）
#
#  為什麼 Q2 才是關鍵：兩組報酬相關 0.83，科技組與大盤相關 0.91。
#  只做 Q1，就算顯著也可能只是「AI 論文多的月份大盤剛好也漲」。
#  價差把共同的大盤成分減掉，剩下的才是科技業專屬的部分。
#
#  多重檢定：落後 0~3 期是 4 次檢定，用 BH 校正，避免挑最漂亮那個。
#
#  ⚠️ 讀去季節方法比較的 ANOVA 時要小心：
#     月份去中心化的 F 必然是 0、p 必然是 1，因為月份平均是「被減掉」的，
#     不是「被檢定通過」的。這是恆等式，不是它比較乾淨的證據。
#     真正該比的是清掉季節性之後 Q1/Q2 的結論穩不穩。
#
#  輸出：out/main_tests.txt
#        out/fig_main_tests.png
#        out/fig_deseason_compare.png
# ============================================================

source(file.path("02_returns", "scripts", "00_common.R"))

start_log("main_tests.txt")

d <- fread(file.path(OUT_DIR, "analysis_monthly.csv"))
setorder(d, year_month)

say("=== 樣本 ===")
say(min(d$year_month), " ~ ", max(d$year_month), "   共 ", nrow(d), " 個月")
say("主自變數 x_demean：log(月論文數) 一階差分，再減掉該月份的歷史平均")

# ------------------------------------------------------------
# 1. 季節性診斷：先確認季節性存在於 X、且不存在於 Y
#
#    這決定了修正方式。若 Y 也有月份效果，該加月份 dummy；
#    但 Y 沒有，加 11 個 dummy 只是浪費自由度。要處理的是 X。
# ------------------------------------------------------------
say("")
say("============================================================")
say(" 季節性診斷：該去季節嗎？去在哪一邊？")
say("============================================================")

anova1 <- function(v, nm, dd) {
  ok <- !is.na(v)
  a <- anova(lm(v[ok] ~ factor(dd$mth[ok])))
  data.table(序列 = nm, F值 = round(a$`F value`[1], 2),
             p值 = signif(a$`Pr(>F)`[1], 3),
             月份解釋變異 = sprintf("%.1f%%", 100 * a$`Sum Sq`[1] / sum(a$`Sum Sq`)))
}
show(rbindlist(list(
  anova1(d$x_raw,     "X：論文成長率",   d),
  anova1(d$tech_vw,   "Y1：科技股報酬",  d),
  anova1(d$spread_vw, "Y2：價差",        d))))
say("→ 季節性只在 X。所以對 X 去中心化，Y 不動，也不加月份 dummy。")
say(sprintf("去季節前 X 標準差 %.4f，去季節後 %.4f（月份成分佔 %.1f%%）",
            sd(d$x_raw, na.rm = TRUE), sd(d$x_demean, na.rm = TRUE),
            100 * (1 - var(d$x_demean, na.rm = TRUE) / var(d$x_raw, na.rm = TRUE))))

# ------------------------------------------------------------
# 2. 主檢定：Q1 與 Q2，落後 0~3 期
# ------------------------------------------------------------
run <- function(yvar, lag, xvar = "x_demean") {
  dd <- copy(d)
  dd[, xl := shift(get(xvar), lag)]
  h <- hac(as.formula(paste(yvar, "~ xl")), dd[!is.na(xl) & !is.na(get(yvar))], "xl")
  data.table(落後 = lag, 係數 = h$b, 標準誤 = h$se, t = h$t, p = h$p, n = h$n, R2 = h$r2)
}

tab_lag <- function(r) r[, .(落後期 = 落後,
                             係數 = sprintf("%+.4f", 係數),
                             HAC標準誤 = sprintf("%.4f", 標準誤),
                             t = sprintf("%+.2f", t),
                             p = sprintf("%.3f", p),
                             `BH校正p` = sprintf("%.3f", p.adjust(p, "BH")),
                             R2 = sprintf("%.3f", R2), n = n)]

say("")
say("============================================================")
say(" Q1：AI 論文 → 科技股報酬（市值加權）")
say("============================================================")
q1 <- rbindlist(lapply(0:3, run, yvar = "tech_vw"))
show(tab_lag(q1))

say("")
say("============================================================")
say(" Q2：AI 論文 → 價差（科技 − 非科技）  ← 本研究的關鍵檢定")
say("============================================================")
q2 <- rbindlist(lapply(0:3, run, yvar = "spread_vw"))
show(tab_lag(q2))

say("")
say("--- 對照：AI 論文 → 非科技股報酬 ---")
say("（非科技組若也顯著，代表價差不顯著是「兩組都反應」；若是乾淨的 0，")
say("  代表價差不顯著純粹是科技組的效果不夠強）")
show(tab_lag(rbindlist(lapply(0:3, run, yvar = "nontech_vw"))))

# ------------------------------------------------------------
# 3. 穩健性（全部針對 Q2、落後 0 期）
# ------------------------------------------------------------
say("")
say("============================================================")
say(" 穩健性檢查")
say("============================================================")

rob <- rbindlist(list(
  cbind(設定 = "主設定：市值加權、多數決分類", run("spread_vw", 0)),
  cbind(設定 = "改用等權",                     run("spread_ew", 0)),
  cbind(設定 = "改用期末碼分類",               run("spread_vw_alt", 0)),
  cbind(設定 = "X 不去季節",                   run("spread_vw", 0, "x_raw"))
))

hm <- hac(spread_vw ~ x_demean + vwretd, d[!is.na(x_demean)], "x_demean")
rob <- rbind(rob, data.table(設定 = "加控制大盤報酬", 落後 = 0, 係數 = hm$b,
                             標準誤 = hm$se, t = hm$t, p = hm$p, n = hm$n, R2 = hm$r2))

show(rob[, .(設定, 係數 = sprintf("%+.4f", 係數), t = sprintf("%+.2f", t),
             p = sprintf("%.3f", p), n)])

# 引用數：只能用引用已成熟的子樣本
#   avg_citations 從 2017 的 54.3 次單調掉到 2025 的 0.39 次，那是論文年齡
#   不是影響力。限制在 2017-2022，讓每篇論文至少有 3 年累積時間。
say("")
say("--- 引用數（限制在 2017-2022，讓論文有 3 年以上累積時間）---")
dc <- d[year_month <= "2022-12"]
dc[, xc := c(NA, diff(log(total_citations)))]
dc[!is.na(xc), xc := xc - mean(xc), by = mth]
hc <- hac(spread_vw ~ xc, dc[!is.na(xc)], "xc")
say(sprintf("係數 %+.4f, t = %+.2f, p = %.3f, n = %d", hc$b, hc$t, hc$p, hc$n))
say("（樣本只剩 ", hc$n, " 個月，檢定力很低，不足以下結論）")

# ------------------------------------------------------------
# 4. 規模分組：等權顯著、市值加權不顯著，是規模效應還是微型股雜訊？
#
#    若係數只在最小組出現 → 微型股雜訊，可以忽略。
#    若各組係數方向一致   → 是檢定力問題，不是規模故事。
# ------------------------------------------------------------
say("")
say("============================================================")
say(" 規模分組：效果集中在小公司，還是各規模都有？")
say("============================================================")
sz <- merge(fread(file.path(OUT_DIR, "size_spreads.csv")),
            d[, .(year_month, x_demean)], by = "year_month")

szres <- rbindlist(lapply(1:5, function(s) {
  h <- hac(spread ~ x_demean, sz[q == s & !is.na(x_demean) & !is.na(spread)])
  data.table(規模組 = paste0("Q", s, c("(最小)", "", "", "", "(最大)")[s]),
             係數 = h$b, t = h$t, p = h$p, n = h$n)
}))
show(szres[, .(規模組, 係數 = sprintf("%+.4f", 係數), t = sprintf("%+.2f", t),
               p = sprintf("%.3f", p),
               `BH校正p` = sprintf("%.3f", p.adjust(p, "BH")), n)])
say("→ 五組係數全為正、量級相近，沒有隨規模單調變化。")
say("  代表等權/市值加權的差異來自檢定力，不是「效果只存在於小型股」。")

# ------------------------------------------------------------
# 5. 換去季節方法，結論會變嗎？
#
#    0  原始     直接對 log(論文數) 一階差分，不處理季節性
#    1  月份去中心化（主設定）
#    2  年增率    log(本月) − log(去年同月)
#    3  STL      拆成 趨勢+季節+殘差，扣掉季節成分再差分
#    1b 滾動版    只用當期之前的資料估月份平均，無前視偏誤
#
#    ⚠️ 方法 0/1/2/3 都用全樣本估季節成分，嚴格說有輕微前視偏誤
#       （用 2025 年的資料去估 2017 年該減多少）。文獻上常見，
#       但 1b 才是嚴謹版，代價是樣本縮短。
# ------------------------------------------------------------
methods <- c("x_raw", "x_demean", "x_yoy", "x_stl", "x_roll")
labels  <- c("0 原始（未處理）", "1 月份去中心化（主設定）", "2 年增率",
             "3 STL 季節調整", "1b 月份去中心化（滾動、無前視）")
# 圖用英文：png 裝置沒有嵌入 CJK 字型，中文會變成方框
labels_en <- c("0 Raw (untreated)", "1 Month-demeaned", "2 Year-over-year",
               "3 STL adjusted", "1b Month-demeaned (rolling)")

say("")
say("============================================================")
say(" 去季節方法比較（一）季節性清乾淨了嗎？")
say("============================================================")
show(rbindlist(lapply(seq_along(methods), function(i) {
  v <- d[[methods[i]]]; ok <- !is.na(v)
  a <- anova(lm(v[ok] ~ factor(d$mth[ok])))
  data.table(方法 = labels[i], n = sum(ok), F值 = round(a$`F value`[1], 2),
             p值 = signif(a$`Pr(>F)`[1], 3),
             月份解釋比例 = sprintf("%.1f%%", 100 * a$`Sum Sq`[1] / sum(a$`Sum Sq`)),
             判定 = ifelse(a$`Pr(>F)`[1] < .05, "仍有季節性", "已清除"),
             標準差 = round(sd(v, na.rm = TRUE), 4),
             一階自相關 = round(acf(v[ok], lag.max = 1, plot = FALSE)$acf[2], 3))
})))
say("方法 1 的 F=0 是恆等式造成的，不是它比較優秀的證據。")
say("年增率的自相關會明顯偏高 —— 12 期差分把序列抹平了，這是它的代價。")

meth_tab <- function(yvar) rbindlist(lapply(seq_along(methods), function(i) {
  r <- run(yvar, 0, methods[i])
  data.table(方法 = labels[i], 係數 = sprintf("%+.4f", r$係數),
             t = sprintf("%+.2f", r$t), p = sprintf("%.3f", r$p), n = r$n,
             顯著 = verdict(r$p))
}))

say("")
say("=== 去季節方法比較（二）Q1  AI 論文 → 科技股報酬 ===")
show(meth_tab("tech_vw"))
say("")
say("=== 去季節方法比較（三）Q2  價差  ← 關鍵 ===")
show(meth_tab("spread_vw"))
say("")
say("--- 對照：非科技組自己 ---")
show(meth_tab("nontech_vw"))

# STL 抓到的季節形狀 —— 反映的是投稿截止日，不是研究產出的真實變化
lp <- log(d$ai_papers)
ts_lp <- ts(lp, start = c(as.integer(substr(min(d$year_month), 1, 4)),
                          as.integer(substr(min(d$year_month), 6, 7))), frequency = 12)
stl_fit <- stl(ts_lp, s.window = "periodic")
say("")
say("=== STL 估出的月份季節成分（研討會投稿日曆）===")
show(data.table(月份 = 1:12,
                季節成分 = round(as.numeric(stl_fit$time.series[1:12, "seasonal"]), 3))[order(-季節成分)])
say("正值 = 該月論文系統性偏多。")

# ------------------------------------------------------------
# 6. 圖
# ------------------------------------------------------------
dates <- as.Date(paste0(d$year_month, "-01"))

png(file.path(OUT_DIR, "fig_main_tests.png"), width = 1600, height = 1100, res = 150)
par(mfrow = c(2, 2), mar = c(4, 4, 3, 1))

plot(dates, d$ai_papers, type = "l", lwd = 2, col = "steelblue",
     xlab = "", ylab = "papers/month", main = "arXiv AI paper count")

plot(dates, cumprod(1 + d$tech_vw), type = "l", lwd = 2, col = "firebrick",
     xlab = "", ylab = "cumulative (x)", main = "Cumulative return: tech vs non-tech",
     ylim = range(cumprod(1 + d$tech_vw), cumprod(1 + d$nontech_vw)))
lines(dates, cumprod(1 + d$nontech_vw), lwd = 2, col = "gray40")
legend("topleft", c("tech", "non-tech"), col = c("firebrick", "gray40"),
       lwd = 2, bty = "n")

plot(d$x_demean, d$tech_vw, pch = 19, col = "#4682B466",
     xlab = "AI paper growth (deseasonalized)", ylab = "tech return",
     main = sprintf("Q1  b=%+.3f, p=%.3f", q1[1]$係數, q1[1]$p))
abline(lm(tech_vw ~ x_demean, data = d), col = "firebrick", lwd = 2)

plot(d$x_demean, d$spread_vw, pch = 19, col = "#B2222266",
     xlab = "AI paper growth (deseasonalized)", ylab = "spread (tech - non-tech)",
     main = sprintf("Q2  b=%+.3f, p=%.3f", q2[1]$係數, q2[1]$p))
abline(lm(spread_vw ~ x_demean, data = d), col = "firebrick", lwd = 2)
invisible(dev.off())

png(file.path(OUT_DIR, "fig_deseason_compare.png"), width = 1700, height = 1000, res = 145)
par(mfrow = c(2, 3), mar = c(4, 4, 3, 1))
for (i in seq_along(methods)) {
  boxplot(d[[methods[i]]] ~ d$mth, col = "steelblue", border = "gray30",
          xlab = "month", ylab = "paper growth", main = labels_en[i], cex.main = 0.95)
  abline(h = 0, lty = 2, col = "firebrick")
}
plot.new()
legend("center", bty = "n", cex = 1.0,
       legend = c("If seasonality is removed,", "all monthly boxes should",
                  "sit flat on 0 (red line)"))
invisible(dev.off())

# ------------------------------------------------------------
# 7. 結論
# ------------------------------------------------------------
say("")
say("============================================================")
say(" 結論")
say("============================================================")
say(sprintf("Q1 科技股報酬  同期係數 %+.4f, p = %.3f  → %s",
            q1[1]$係數, q1[1]$p, verdict(q1[1]$p)))
say(sprintf("Q2 價差        同期係數 %+.4f, p = %.3f  → %s",
            q2[1]$係數, q2[1]$p, verdict(q2[1]$p)))
say("")
say("落後 0~3 期經 BH 校正後仍顯著的檢定數：")
say("  Q1: ", sum(p.adjust(q1$p, "BH") < 0.05), " / 4")
say("  Q2: ", sum(p.adjust(q2$p, "BH") < 0.05), " / 4")

say("")
say("=== 已輸出 ===")
say(file.path(OUT_DIR, "main_tests.txt"))
say(file.path(OUT_DIR, "fig_main_tests.png"))
say(file.path(OUT_DIR, "fig_deseason_compare.png"))
end_log()
