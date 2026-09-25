# ============================================================
# 將 CRSP 全市場股票分成 A / B_ICT / B_Other / C 四組
# A       = Magnificent 7（AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA）
# B_ICT   = 非 Mag7、屬 ICT 產業、且在 OpenAlex 有 AI 論文的美國上市公司
# B_Other = 非 Mag7、非 ICT 產業、但仍在 OpenAlex 有 AI 論文的上市公司
# C       = 其餘 CRSP 公司（假定無 AI 論文）
#
# 直接從 data/crsp/crsp_all_classified_with_papers_detailed_v2.csv 切分。
# 該檔已經把公司 <-> OpenAlex 論文的對應、NAICS 科技分類都做好了，
# 不需要（也不應該）像舊版一樣自己重新用機構名稱字串比對一遍——
# 舊版直接讀 data/crsp/stock_on_crsp.csv + data/openalex/paper_company_panel.csv
# 做名稱比對，繼承了 OpenAlex 自 2022 年起機構隸屬連結斷裂的問題，
# 導致公司論文數在 2022 年出現不存在的「暴跌」（詳見 data/README.md）。
# v2 檔已修正這個問題，論文數延續母體語料的成長趨勢。
#
# 註：v2 只涵蓋 2017-01 起、且已在 CRSP 上市的公司，因此本腳本不再產生
# 「D 組」（有論文但不在 CRSP 上的機構）——那需要原始 OpenAlex 全文檔
# 才能重建，且沒有下游分析在用它。既有的 group_D_firms*.csv 維持原樣，
# 視為此前用舊資料源產生的凍結快照，不再隨此腳本更新。
# ============================================================
library(data.table)

OUT_DIR <- "01_universe/out"
if (!dir.exists(OUT_DIR)) dir.create(OUT_DIR, recursive = TRUE)

cat("=== 讀取 v2 面板 ===\n")
v2 <- fread("data/crsp/crsp_all_classified_with_papers_detailed_v2.csv")
cat("列數:", format(nrow(v2), big.mark = ","),
    "  公司數:", uniqueN(v2$permco), "\n\n")

cat("=== 各組公司數（依 ai_group_detailed）===\n")
print(v2[, .(公司數 = uniqueN(permco), 總論文 = sum(n_papers, na.rm = TRUE)),
         by = ai_group_detailed][order(ai_group_detailed)])
cat("\n")

fwrite(v2[ai_group_detailed == "A"],       file.path(OUT_DIR, "group_A_stocks.csv"))
fwrite(v2[ai_group_detailed == "B_ICT"],   file.path(OUT_DIR, "group_B_INFO_COMMU_TECH.csv"))
fwrite(v2[ai_group_detailed == "B_Other"], file.path(OUT_DIR, "group_B_OTHER.csv"))
fwrite(v2[ai_group_detailed == "C"],       file.path(OUT_DIR, "group_C_stocks.csv"))

cat("=== 已輸出 ===\n")
for (f in c("group_A_stocks.csv", "group_B_INFO_COMMU_TECH.csv",
            "group_B_OTHER.csv", "group_C_stocks.csv")) {
  cat(file.path(OUT_DIR, f), "\n")
}
cat("\n(group_D_firms.csv 與 group_D_firms_monthly_papers.csv 為舊資料源的",
    "凍結快照，未隨本次改版更新)\n")
