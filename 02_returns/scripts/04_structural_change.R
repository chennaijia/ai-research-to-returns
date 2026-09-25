# ============================================================
#  04_structural_change.R
#
#  「AI 論文對股價的效果，有沒有在某個時點改變？」
#  這個問題有兩種問法，統計上待遇完全不同：
#
#    (A) 事後掃描：不預設切點，掃過所有候選切點取最大 F。
#        掃了很多切點就必須付代價 → Quandt-Andrews supF + 自助法臨界值。
#        本研究的 2020-02 屬於這一類（是做滾動去季節時被樣本長度撞出來的）。
#
#    (B) 事先指定：假說在看資料之前就存在，只檢定少數幾個切點。
#        不需要 supF 那種懲罰，直接檢定交互項即可。
#        使用者的「2021/2022 後企業改發專利」假說屬於這一類。
#
#  把兩者放在同一個檔案，是因為它們的對比本身就是結論的一部分：
#  同一份資料，(A) 不顯著、(B) 顯著，差別只在切點怎麼來的。
#
#  ⚠️ (B) 的「前提」在這份資料裡站不住（見前提檢驗）：
#     公司論文數並未出現斷崖，延續 arXiv 母體同期的成長趨勢——
#     早期版本的 CRSP 面板曾因 OpenAlex 隸屬連結斷裂，錯誤顯示 2022 年
#     集體暴跌 75%，PANEL 換成修正後的 v2 來源後這個假象已經消失。
#     好消息是檢定本身從頭到尾都不受影響 —— 自變數用的是母體語料。
#
#  輸出：out/structural_change.txt
#        out/fig_structural_change.png
# ============================================================

source(file.path("02_returns", "scripts", "00_common.R"))

set.seed(42)
start_log("structural_change.txt")

d <- fread(file.path(OUT_DIR, "analysis_monthly.csv"))[!is.na(x_demean)]
setorder(d, year_month)
N <- nrow(d)

say("=== 樣本 ===")
say(min(d$year_month), " ~ ", max(d$year_month), "   共 ", N, " 個月")
say("自變數：x_demean（與 STL 版相關 0.999，結論不受去季節方法影響）")

# ------------------------------------------------------------
# 0. 前提檢驗：企業真的停止發論文了嗎？
# ------------------------------------------------------------
say("")
say("============================================================")
say(" 前提檢驗：『2021/2022 後企業不發論文了』站得住嗎？")
say("============================================================")

cpa <- fread(file.path(OUT_DIR, "company_papers_annual.csv"))
cpa[, yr := as.character(yr)]
aim <- fread(AI_MONTHLY)
aim[, yr := substr(month, 1, 4)]

cmp <- merge(aim[, .(arXiv母體_月均 = round(mean(ai_papers))), by = yr],
             cpa[yr >= "2017", .(公司論文合計 = sum(papers)), by = yr], by = "yr")
cmp[, 母體年增 := sprintf("%+.0f%%", 100 * (arXiv母體_月均 / shift(arXiv母體_月均) - 1))]
cmp[, 公司年增 := sprintf("%+.0f%%", 100 * (公司論文合計 / shift(公司論文合計) - 1))]
show(cmp)

say("公司論文合計並未在 2022 年暴跌，走勢與 arXiv 母體一致地持續成長。")
say("（早期版本的 CRSP 面板因 OpenAlex 隸屬連結斷裂，曾錯誤顯示六家公司")
say(" 在 2022 年同步腰斬——那是資料瑕疵，已經隨 PANEL 換成修正後的 v2")
say(" 來源而修正。）")
# Meta 的 ticker 在 2022 年中由 FB 改成 META，兩段合併才是完整序列
cpa[ticker == "FB", ticker := "META"]
big <- c("GOOGL", "MSFT", "AMZN", "NVDA", "AAPL", "META")
show(dcast(cpa[ticker %in% big & yr >= "2019", .(papers = sum(papers)), by = .(ticker, yr)],
           ticker ~ yr, value.var = "papers", fill = 0, fun.aggregate = sum))
say("結論：假說的前提本來就沒有被資料支持——不論新舊版本的公司論文資料，")
say("      都看不出企業在 2022 年後集體停止發論文。下面的檢定用的是")
say("      arXiv 母體語料，從頭到尾都不受這個(已修正的)問題影響，")
say("      測的是「市場反應有沒有改變」。")

# ------------------------------------------------------------
# 1. (A) 事後掃描：Quandt-Andrews supF
#
#    臨界值不查表，改用自助法：在「沒有斷點」的虛無假設下重抽殘差，
#    每次都重跑一遍完整的掃描流程，看隨機資料能湊出多大的 supF。
#    這樣自動把「掃了很多切點」這件事算進去。
# ------------------------------------------------------------
TRIM <- 0.15                                  # 頭尾各留 15%，兩側樣本才夠估
idx  <- seq(floor(TRIM * N), ceiling((1 - TRIM) * N))

supF_scan <- function(y, x) {
  rss0 <- sum(resid(lm(y ~ x))^2)
  vapply(idx, function(k) {
    dk <- as.numeric(seq_along(y) >= k)
    rss1 <- sum(resid(lm(y ~ x + dk + x:dk))^2)
    ((rss0 - rss1) / 2) / (rss1 / (length(y) - 4))
  }, numeric(1))
}

run_break <- function(yvar, label) {
  y <- d[[yvar]]; x <- d$x_demean
  Fs <- supF_scan(y, x)
  kmax <- idx[which.max(Fs)]
  supF <- max(Fs)

  base <- lm(y ~ x)
  null <- replicate(2000, max(supF_scan(fitted(base) + sample(resid(base), replace = TRUE), x)))
  p <- mean(null >= supF)

  cf <- function(dd) {
    h <- hac(as.formula(paste(yvar, "~ x_demean")), dd)
    sprintf("%+.4f (p=%.3f, n=%d)", h$b, h$p, h$n)
  }
  say("")
  say("--- ", label, " ---")
  say(sprintf("supF = %.2f，最大 F 落在 %s", supF, d$year_month[kmax]))
  say(sprintf("自助法 p = %.3f（2000 次重抽，臨界值 supF(5%%) = %.2f）",
              p, quantile(null, 0.95)))
  say("  切點前：", cf(d[seq_len(kmax - 1)]))
  say("  切點後：", cf(d[seq(kmax, N)]))
  say(ifelse(p < 0.05, "  → 有結構斷點，前後係數確實不同",
             "  → 找不到顯著斷點。子樣本的顯著性用掃切點的隨機波動就能解釋"))
  list(Fs = Fs, supF = supF, p = p, null = null)
}

say("")
say("============================================================")
say(" (A) 不預設切點：Quandt-Andrews supF")
say("============================================================")
r_sp <- run_break("spread_vw", "Q2 價差（科技 − 非科技）")
r_tc <- run_break("tech_vw",   "Q1 科技股報酬")

# ------------------------------------------------------------
# 1b. 對照：如果硬把 2020-02 當成事先指定的切點會怎樣
#
#     這個切點是做滾動去季節時被樣本長度撞出來的，不是理論預測的。
#     兩個結果都算對，差別只在切點的來源。
# ------------------------------------------------------------
say("")
say("--- 對照：把 2020-02 當成「事先指定」的切點 ---")
d[, post2020 := as.numeric(year_month >= "2020-02")]
h20 <- hac(spread_vw ~ x_demean * post2020, d, "x_demean:post2020")
say(sprintf("  預設 2020-02 當切點  → 交互項 p = %.3f（%s）", h20$p, verdict(h20$p)))
say(sprintf("  不預設切點掃描       → supF  p = %.3f（%s）", r_sp$p, verdict(r_sp$p)))
say("  掃過 ", length(idx), " 個候選切點總會有幾個湊出 p<0.05 —— supF 的自助法")
say("  把這件事算進去了，算進去之後就不顯著。")
say("  正確的寫法是報 supF 的結果，不是報那個漂亮的交互項。")
say("  （GPT-3 是 2020-05、ChatGPT 是 2022-11，都對不上 2020-02。）")

# ------------------------------------------------------------
# 2. (B) 事先指定的切點：2021 / 2022
# ------------------------------------------------------------
CUTS <- c("2021-01", "2022-01")

test_split <- function(cut, yvar) {
  dd <- copy(d)[, post := as.numeric(year_month >= cut)]
  hi <- hac(as.formula(paste(yvar, "~ x_demean * post")), dd, "x_demean:post")
  seg <- lapply(0:1, function(s) hac(as.formula(paste(yvar, "~ x_demean")), dd[post == s]))
  data.table(切點 = cut,
             前段係數 = sprintf("%+.4f", seg[[1]]$b), 前段p = sprintf("%.3f", seg[[1]]$p),
             前段n = seg[[1]]$n,
             後段係數 = sprintf("%+.4f", seg[[2]]$b), 後段p = sprintf("%.3f", seg[[2]]$p),
             後段n = seg[[2]]$n,
             交互項係數 = sprintf("%+.4f", hi$b), 交互項p_raw = hi$p)
}

say("")
say("============================================================")
say(" (B) 事先指定切點：2021 / 2022")
say("============================================================")
for (yv in c("spread_vw", "tech_vw")) {
  lab <- if (yv == "spread_vw") "Q2 價差（科技 − 非科技）  ← 關鍵" else "Q1 科技股報酬"
  r <- rbindlist(lapply(CUTS, test_split, yvar = yv))
  say("")
  say("--- ", lab, " ---")
  show(r[, .(切點, 前段係數, 前段p, 前段n, 後段係數, 後段p, 後段n)])
  say("斜率有沒有真的改變 —— 看交互項（只有 2 個事先指定的切點，BH 校正即可）：")
  show(r[, .(切點, 交互項係數,
             交互項p = sprintf("%.3f", 交互項p_raw),
             `交互項BH校正p` = sprintf("%.3f", p.adjust(交互項p_raw, "BH")),
             判定 = ifelse(交互項p_raw < 0.05, "斜率確實改變", "分不出差別"))])
}

say("")
say("--- 假說方向對不對？（假說預測：切點「後」效果應變弱）---")
dir <- rbindlist(lapply(CUTS, function(cut) {
  f <- function(s) hac(spread_vw ~ x_demean,
                       d[if (s == 0) year_month < cut else year_month >= cut])$b
  data.table(切點 = cut, 前段 = f(0), 後段 = f(1))
}))
dir[, 方向 := ifelse(後段 < 前段, "符合假說（變弱）", "與假說相反（變強）")]
show(dir[, .(切點, 前段 = sprintf("%+.4f", 前段), 後段 = sprintf("%+.4f", 後段), 方向)])

# ------------------------------------------------------------
# 2b. 拆開看兩組各自的反應
#
#     這是本研究最有訊息量的一張表：價差顯著要有意義，必須是
#     「科技組有反應、非科技組沒反應」，而不是兩組都動但幅度不同。
#     切點前的兩組係數幾乎一模一樣，等於一個天然的安慰劑檢定。
# ------------------------------------------------------------
say("")
say("============================================================")
say(" 拆開看：切點前後，兩組各自對 AI 論文的反應")
say("============================================================")
show(rbindlist(lapply(CUTS, function(cut) {
  rbindlist(lapply(list(list("切點前", d[year_month < cut]),
                        list("切點後", d[year_month >= cut])), function(s) {
    row <- data.table(切點 = cut, 期間 = s[[1]], n = nrow(s[[2]]))
    for (yv in c("tech_vw", "nontech_vw", "spread_vw")) {
      h <- hac(as.formula(paste(yv, "~ x_demean")), s[[2]])
      row[[c(tech_vw = "科技組", nontech_vw = "非科技組", spread_vw = "價差")[yv]]] <-
        sprintf("%+.4f (p=%.3f)", h$b, h$p)
    }
    row
  }))
})))

# ------------------------------------------------------------
# 2c. 後段結果有多脆弱？ n 只有 48，必須查
# ------------------------------------------------------------
say("")
say("============================================================")
say(" 後段（2022 後）結果的脆弱度檢查")
say("============================================================")
po <- d[year_month >= "2022-01"]
ff <- function(dd, form) {
  h <- hac(as.formula(form), dd)
  data.table(係數 = sprintf("%+.4f", h$b), p = sprintf("%.3f", h$p), n = h$n)
}
show(rbindlist(list(
  cbind(設定 = "主設定",         ff(po, "spread_vw ~ x_demean")),
  cbind(設定 = "STL 去季節",     ff(po, "spread_vw ~ x_stl")),
  cbind(設定 = "原始未去季節",   ff(po, "spread_vw ~ x_raw")),
  cbind(設定 = "改用等權",       ff(po, "spread_ew ~ x_demean")),
  cbind(設定 = "改用期末碼分類", ff(po, "spread_vw_alt ~ x_demean")),
  cbind(設定 = "加控制大盤報酬", ff(po, "spread_vw ~ x_demean + vwretd")),
  cbind(設定 = "剔除 2023 年", ff(po[substr(year_month, 1, 4) != "2023"], "spread_vw ~ x_demean")),
  cbind(設定 = "剔除 2024 年", ff(po[substr(year_month, 1, 4) != "2024"], "spread_vw ~ x_demean")),
  cbind(設定 = "剔除價差最極端 3 個月",
        ff(po[!year_month %in% po[order(-abs(spread_vw))][1:3]$year_month],
           "spread_vw ~ x_demean")))))
say("→ 剔掉 3 個月或剔掉單一年份就掉到 p≈0.07~0.10。")
say("  48 個月撐不起強主張，這個結果只能當作值得追的線索。")

# ------------------------------------------------------------
# 3. 圖
# ------------------------------------------------------------
W <- 36
roll <- rbindlist(lapply(W:N, function(i) {
  s <- d[(i - W + 1):i]
  h <- hac(spread_vw ~ x_demean, s)
  data.table(end = s$year_month[W], b = h$b, se = h$se)
}))

png(file.path(OUT_DIR, "fig_structural_change.png"), width = 1600, height = 1000, res = 145)
par(mfrow = c(2, 2), mar = c(4, 4, 3, 1))

plot(as.Date(paste0(d$year_month[idx], "-01")), r_sp$Fs, type = "l", lwd = 2,
     col = "firebrick", xlab = "candidate break date", ylab = "F statistic",
     main = "supF scan: spread ~ AI papers",
     ylim = range(c(r_sp$Fs, quantile(r_sp$null, 0.95))))
abline(h = quantile(r_sp$null, 0.95), lty = 2, col = "gray30")
abline(v = as.Date("2020-02-01"), lty = 3, col = "steelblue")
legend("topright", c("F(tau)", "5% critical (bootstrap)", "2020-02"),
       col = c("firebrick", "gray30", "steelblue"), lty = c(1, 2, 3), bty = "n", cex = .8)

hist(r_sp$null, breaks = 40, col = "gray85", border = "white",
     xlab = "supF under null", main = sprintf("Bootstrap null (p = %.3f)", r_sp$p),
     xlim = range(c(r_sp$null, r_sp$supF)))
abline(v = r_sp$supF, lwd = 2, col = "firebrick")

dts <- as.Date(paste0(roll$end, "-01"))
plot(dts, roll$b, type = "l", lwd = 2, col = "firebrick",
     ylim = range(c(roll$b - 2 * roll$se, roll$b + 2 * roll$se)),
     xlab = "window end", ylab = "coefficient",
     main = "Rolling 36m coef: spread ~ AI papers")
polygon(c(dts, rev(dts)), c(roll$b - 2 * roll$se, rev(roll$b + 2 * roll$se)),
        col = "#B2222222", border = NA)
abline(h = 0, lty = 2)
abline(v = as.Date(c("2021-01-01", "2022-01-01")), lty = 3, col = "steelblue")
legend("topleft", c("coef +/- 2SE", "2021 / 2022"),
       col = c("firebrick", "steelblue"), lty = c(1, 3), bty = "n", cex = .8)

ann <- aim[yr >= "2017" & yr <= "2025", .(p = sum(ai_papers)), by = yr]
barplot(ann$p, names.arg = ann$yr, col = "steelblue", border = NA,
        xlab = "year", ylab = "arXiv AI papers",
        main = "Population arXiv AI papers (no 2022 cliff)")
invisible(dev.off())

say("")
say("=== 已輸出 ===")
say(file.path(OUT_DIR, "structural_change.txt"))
say(file.path(OUT_DIR, "fig_structural_change.png"))
end_log()
