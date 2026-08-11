# ============================================================
# 將 CRSP 全市場股票分成 A / B / C / D 四組
# A = Magnificent 7（AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA）
# B = 非 Mag7、但在 OpenAlex 有 AI 論文的美國上市公司
# C = 其餘 CRSP 公司（假定無 AI 論文）
# D = 有 AI 論文但不在 CRSP 上的公司（例如非上市、國外）
# ============================================================
library(tidyverse)
library(data.table)

# 1. 讀取三個資料檔
crsp <- fread("stock_on_crsp.csv")
setnames(crsp, tolower(names(crsp)))
# permno 統一為數值
crsp[, permno := as.integer(permno)]

papers <- fread("paper_company_panel.csv", encoding = "UTF-8")

# 2. 從 OpenAlex 論文萃取「有 AI 論文的機構名稱」
# 因為 OpenAlex 把同一家公司按國家分開，先做名稱歸屬到母公司
firms_with_papers <- papers |>
  distinct(institution_name) |>
  mutate(
    # 移除末尾的「(國家)」括號，得到公司主體名稱
    company_root = str_replace(institution_name, "\\s*\\([^)]+\\)\\s*$", "") |> str_trim()
  )

# 檢視有多少家獨立公司（去掉國家分部後）
distinct_firms_with_papers<-firms_with_papers |>
  count(company_root) |>
  arrange(company_root)

# 3. 定義 A 組：Magnificent 7 的 permno 
group_A_permno <- c(
  14593,  # AAPL
  10107,  # MSFT
  90319,  # GOOGL
  84788,  # AMZN
  86580,  # NVDA
  13407,  # META
  93436   # TSLA
)

# A 組對應的公司名稱字串（用於 B 組排除）
group_A_names <- c(
  "Apple", "Microsoft", "Google", "Alphabet", "DeepMind", "Google DeepMind",
  "Amazon", "Nvidia", "NVIDIA", "Meta", "Facebook", "FAIR", 
  "Meta Platforms", "Tesla"
)

# 4. 定義 B 組候選：OpenAlex 有論文、但不屬於 Mag7 
# 從 papers 資料抓出「company_root 不屬於 A 組」的機構
group_B_candidates <- firms_with_papers |>
  filter(!company_root %in% group_A_names) |>
  # 排除明顯不是公司的機構（雖然 institution_type=='company' 應該已過濾，但雙保險）
  distinct(company_root) |>
  arrange(company_root)

# 檢視 B 組候選有多少家、樣貌
cat("B 組候選公司數（未對到 CRSP 前）:", nrow(group_B_candidates), "\n")
print(head(group_B_candidates, 30))

# 5. 從 CRSP 建立「公司名稱 → permno」對照表
# CRSP 的 issuernm 是發行公司名稱
crsp_firms <- crsp |>
  distinct(permno, ticker, issuernm) |>
  filter(!is.na(issuernm))

# 6. 把 B 組候選名稱對到 CRSP permno
# 用「大小寫忽略、允許部分匹配」的方式對照
# 因為 OpenAlex 名稱通常是「Salesforce」而 CRSP 是「SALESFORCE INC」

# 建立簡化的公司名稱欄位方便比對（去除法律後綴、統一大寫）
clean_name <- function(x) {
  x |>
    toupper() |>
    str_replace_all(",", "") |>
    str_replace_all("\\.", "") |>
    str_replace_all("\\s+(INC|CORP|CORPORATION|LTD|LIMITED|LLC|CO|COMPANY|PLC|HOLDINGS|GROUP)$", "") |>
    str_trim()
}

crsp_firms <- crsp_firms |>
  mutate(issuernm_clean = clean_name(issuernm))

group_B_candidates <- group_B_candidates |>
  mutate(company_root_clean = clean_name(company_root))

# 精準比對（可能會漏掉，但作為第一輪先做這個）
matched <- group_B_candidates |>
  inner_join(crsp_firms, by = c("company_root_clean" = "issuernm_clean"))

cat("B 組成功對到 CRSP 的公司數:", nrow(matched |> distinct(permno)), "\n")

# 未對到的名單（之後可以手動處理或用模糊比對）
unmatched <- group_B_candidates |>
  anti_join(crsp_firms, by = c("company_root_clean" = "issuernm_clean"))

cat("未對到 CRSP 的 OpenAlex 公司:", nrow(unmatched), "\n")
print(head(unmatched, 30))

# 7. 決定最終 B 組的 permno
group_B_permno <- matched |>
  pull(permno) |>
  unique() |>
  setdiff(group_A_permno)   # 保險：排除 A 組

cat("最終 B 組 permno 數:", length(group_B_permno), "\n")

# 8. 建立四組分類欄位
crsp_classified <- crsp |>
  mutate(
    ai_group = case_when(
      permno %in% group_A_permno ~ "A",
      permno %in% group_B_permno ~ "B",
      TRUE                       ~ "C"
    )
  )

# 9. 檢查分組結果
crsp_classified |>
  distinct(permno, ai_group) |>
  count(ai_group) |>
  mutate(share_pct = round(n / sum(n) * 100, 2))

# 10. 檢查 A 組是否都對到
crsp_classified |>
  filter(ai_group == "A") |>
  distinct(permno, ticker, issuernm) |>
  print()

# 11. 建立 D 組：有論文但不在 CRSP
group_D_names <- unmatched |>
  distinct(company_root, company_root_clean)

cat("D 組公司數（有論文但不在 CRSP）:", nrow(group_D_names), "\n")

# ============================================================
# 儲存各組 CSV
# ============================================================
if (!dir.exists("ai_groups_output")) dir.create("ai_groups_output")

# A 組股票資料
crsp_classified |>
  filter(ai_group == "A") |>
  fwrite("ai_groups_output/group_A_stocks.csv")

# B 組股票資料
crsp_classified |>
  filter(ai_group == "B") |>
  fwrite("ai_groups_output/group_B_stocks.csv")

# C 組股票資料
crsp_classified |>
  filter(ai_group == "C") |>
  fwrite("ai_groups_output/group_C_stocks.csv")

# D 組公司名單（僅公司名，因為無股價資料）
group_D_names |>
  fwrite("ai_groups_output/group_D_firms.csv")

# 對照表：全部 permno 的分組（方便後續分析引用）
crsp_classified |>
  distinct(permno, ticker, issuernm, ai_group) |>
  fwrite("ai_groups_output/permno_group_mapping.csv")

# 完整資料 + 分組欄位（若你想用單一大檔案）
fwrite(crsp_classified, "ai_groups_output/crsp_all_classified.csv")

cat("\n完成，四個 CSV 已存到 ai_groups_output/ 資料夾\n")

#======================================================
# ============================================================
# 把每月論文數對應到 CRSP 每月股價 row
# 
# 論文時間：兩個都存（publication_date, arxiv_date）
# 論文計算：先歸屬到母公司，再用 distinct(work_id, parent_company) 去重
# 分組：A、B 有真實論文數；C、D 用 0 填補（D 只有名單，不併入 CRSP）
# ============================================================
library(tidyverse)
library(data.table)
library(lubridate)

if (!dir.exists("ai_groups_output")) dir.create("ai_groups_output")

# 1. 讀資料
cat("=== 步驟 1: 讀資料 ===\n")
crsp <- fread("stock_on_crsp.csv")
setnames(crsp, tolower(names(crsp)))
crsp[, permno := as.integer(permno)]

papers <- fread("paper_company_panel.csv", encoding = "UTF-8")
cat("CRSP 維度:", dim(crsp), "\n")
cat("papers 維度:", dim(papers), "\n\n")

# ============================================================
# 段 A：建立 A / B 組的公司 → permno 對照表
# ============================================================

cat("=== 步驟 2: 定義 A 組（Mag7）對照 ===\n")

# A 組：每個 permno 對應到的「OpenAlex 機構名稱模式」
# 用 regex 抓母公司所有變體（含子公司、國家分部）
group_A_mapping <- tribble(
  ~permno,   ~ticker,   ~name_pattern,
  14593,     "AAPL",    "^Apple( |$|\\()",
  10107,     "MSFT",    "^Microsoft( |$|\\()",
  90319,     "GOOGL",   "^(Google|Alphabet|DeepMind|Google DeepMind|YouTube)( |$|\\()",
  84788,     "AMZN",    "^Amazon( |$|\\()",
  86580,     "NVDA",    "^Nvidia( |$|\\()",
  13407,     "META",    "^(Meta|Facebook)( |$|\\()",
  93436,     "TSLA",    "^Tesla( |$|\\()"
)

# 用 regex 把 papers 裡的 institution_name 標記到 A 組
papers_A <- papers |>
  mutate(parent_permno = NA_integer_,
         parent_ticker = NA_character_)

for (i in seq_len(nrow(group_A_mapping))) {
  pattern <- group_A_mapping$name_pattern[i]
  papers_A <- papers_A |>
    mutate(
      parent_permno = if_else(
        is.na(parent_permno) & str_detect(institution_name, pattern),
        group_A_mapping$permno[i],
        parent_permno
      ),
      parent_ticker = if_else(
        is.na(parent_ticker) & str_detect(institution_name, pattern),
        group_A_mapping$ticker[i],
        parent_ticker
      )
    )
}

# 檢查：A 組每家公司抓到多少 unique institution_name
cat("A 組各家公司抓到的機構名稱:\n")
papers_A |>
  filter(!is.na(parent_ticker)) |>
  distinct(parent_ticker, institution_name) |>
  count(parent_ticker) |>
  print()
cat("\n")

# ============================================================
# 段 B：B 組公司 → permno 對照（複用你之前的名稱比對邏輯）
# ============================================================

cat("=== 步驟 3: 建立 B 組對照 ===\n")

# 把不屬於 A 組的機構名歸屬到公司主體
papers_non_A <- papers_A |>
  filter(is.na(parent_permno)) |>
  distinct(institution_name) |>
  mutate(
    company_root = str_replace(institution_name, "\\s*\\([^)]+\\)\\s*$", ""),
    company_root = str_trim(company_root)
  )

# CRSP 公司名清單
crsp_firms <- crsp |>
  distinct(permno, ticker, issuernm) |>
  filter(!is.na(issuernm)) |>
  mutate(
    issuernm_clean = toupper(issuernm),
    issuernm_clean = str_replace_all(issuernm_clean, ",", ""),
    issuernm_clean = str_replace_all(issuernm_clean, "\\.", ""),
    issuernm_clean = str_replace_all(issuernm_clean,
                                     "\\s+(INC|CORP|CORPORATION|LTD|LIMITED|LLC|CO|COMPANY|PLC|HOLDINGS|GROUP)$", ""),
    issuernm_clean = str_trim(issuernm_clean)
  )

papers_non_A <- papers_non_A |>
  mutate(
    company_root_clean = toupper(company_root),
    company_root_clean = str_replace_all(company_root_clean, ",", ""),
    company_root_clean = str_replace_all(company_root_clean, "\\.", ""),
    company_root_clean = str_replace_all(company_root_clean,
                                         "\\s+(INC|CORP|CORPORATION|LTD|LIMITED|LLC|CO|COMPANY|PLC|HOLDINGS|GROUP)$", ""),
    company_root_clean = str_trim(company_root_clean)
  )

# 對照 CRSP
B_mapping <- papers_non_A |>
  inner_join(crsp_firms, by = c("company_root_clean" = "issuernm_clean")) |>
  select(institution_name, permno, ticker) |>
  distinct(institution_name, .keep_all = TRUE)  # 避免一個名字對到多家

# D 組：非 A、B 且沒對到 CRSP 的公司
D_names <- papers_non_A |>
  anti_join(crsp_firms, by = c("company_root_clean" = "issuernm_clean")) |>
  distinct(company_root, company_root_clean)

cat("B 組對到 CRSP 的獨立公司數:", length(unique(B_mapping$permno)), "\n")
cat("D 組公司數:", nrow(D_names), "\n\n")

# ============================================================
# 段 C：把 B 組 mapping merge 回 papers_A
# ============================================================

cat("=== 步驟 4: 合併 A + B 組的 permno 標記 ===\n")

# B 組的標記
papers_labeled <- papers_A |>
  left_join(
    B_mapping |> rename(B_permno = permno, B_ticker = ticker),
    by = "institution_name"
  ) |>
  mutate(
    parent_permno = coalesce(parent_permno, B_permno),
    parent_ticker = coalesce(parent_ticker, B_ticker)
  ) |>
  select(-B_permno, -B_ticker)

# 只保留有對到 A 或 B 組的論文列
papers_matched <- papers_labeled |>
  filter(!is.na(parent_permno))

cat("有對到 A/B permno 的論文列數:", nrow(papers_matched), "\n")
cat("涵蓋的獨立 permno 數:", length(unique(papers_matched$parent_permno)), "\n\n")

# ============================================================
# 段 D：算每家公司每月論文數（去重）
# ============================================================

cat("=== 步驟 5: 計算每家公司每月論文數 ===\n")

# 關鍵：先歸屬到 parent_permno，再對 (work_id, parent_permno) 去重
papers_monthly <- papers_matched |>
  # 準備兩個時間欄位（回應你「兩個都存」的需求）
  mutate(
    publication_date = as.Date(publication_date),
    # arxiv_id 若非 NA，可解析成日期；這裡先簡單放同 publication_date
    # 若你未來從 arxiv metadata 另外抓 arxiv 首發日，這裡再改
    arxiv_available = !is.na(arxiv_id) & arxiv_id != "NA"
  ) |>
  # 去重：每篇論文對每家公司只算一次
  distinct(work_id, parent_permno, parent_ticker, publication_date, arxiv_available) |>
  # 加上年月欄位（用 publication_date 決定歸屬到哪一個月）
  mutate(year_month = format(publication_date, "%Y-%m")) |>
  # 分組加總
  group_by(parent_permno, parent_ticker, year_month) |>
  summarise(
    n_papers = n(),                            # 該月論文總數（用 publication_date）
    n_papers_arxiv = sum(arxiv_available),     # 該月有 arxiv_id 的論文數
    .groups = "drop"
  )

cat("每月論文數紀錄總筆數:", nrow(papers_monthly), "\n")
cat("涵蓋的公司數:", length(unique(papers_monthly$parent_permno)), "\n\n")

# 檢查：A 組每家公司總論文數
cat("A 組各家公司總論文數（去重後）:\n")
papers_monthly |>
  filter(parent_permno %in% group_A_mapping$permno) |>
  group_by(parent_ticker) |>
  summarise(total_papers = sum(n_papers)) |>
  print()
cat("\n")

# ============================================================
# 段 E：把月度論文數 join 到 CRSP
# ============================================================

cat("=== 步驟 6: 把論文數 join 到 CRSP 月頻股價 ===\n")

# 定義 A / B 組 permno
group_A_permno <- group_A_mapping$permno
group_B_permno <- setdiff(unique(B_mapping$permno), group_A_permno)

# CRSP 加上年月欄位、加上分組標籤
crsp_enriched <- crsp |>
  mutate(
    mthcaldt = as.Date(mthcaldt),
    year_month = format(mthcaldt, "%Y-%m"),
    ai_group = case_when(
      permno %in% group_A_permno ~ "A",
      permno %in% group_B_permno ~ "B",
      TRUE                        ~ "C"
    )
  ) |>
  # left join 論文月度資料
  left_join(
    papers_monthly |> select(-parent_ticker),
    by = c("permno" = "parent_permno", "year_month" = "year_month")
  ) |>
  # C 組公司沒論文，填 0；A/B 組某些月份沒論文也填 0
  mutate(
    n_papers = coalesce(n_papers, 0L),
    n_papers_arxiv = coalesce(n_papers_arxiv, 0L)
  )

cat("CRSP enriched 維度:", dim(crsp_enriched), "\n")
cat("各組分布:\n")
crsp_enriched |>
  distinct(permno, ai_group) |>
  count(ai_group) |>
  print()
cat("\n")

# ============================================================
# 段 F：存檔
# ============================================================

cat("=== 步驟 7: 存檔 ===\n")

# A 組
fwrite(
  crsp_enriched |> filter(ai_group == "A"),
  "ai_groups_output/group_A_stocks.csv"
)
cat("已存: group_A_stocks.csv (", 
    nrow(crsp_enriched[ai_group == "A"]), " rows)\n", sep = "")

# B 組
fwrite(
  crsp_enriched |> filter(ai_group == "B"),
  "ai_groups_output/group_B_stocks.csv"
)
cat("已存: group_B_stocks.csv (",
    nrow(crsp_enriched[ai_group == "B"]), " rows)\n", sep = "")

# C 組
fwrite(
  crsp_enriched |> filter(ai_group == "C"),
  "ai_groups_output/group_C_stocks.csv"
)
cat("已存: group_C_stocks.csv (",
    nrow(crsp_enriched[ai_group == "C"]), " rows)\n", sep = "")

# D 組：純公司名單 + 論文數（無股價資料）
D_papers <- papers_labeled |>
  filter(is.na(parent_permno)) |>
  mutate(
    company_root = str_replace(institution_name, "\\s*\\([^)]+\\)\\s*$", ""),
    company_root = str_trim(company_root),
    publication_date = as.Date(publication_date),
    year_month = format(publication_date, "%Y-%m")
  ) |>
  distinct(work_id, company_root, year_month, arxiv_id) |>
  mutate(arxiv_available = !is.na(arxiv_id) & arxiv_id != "NA") |>
  group_by(company_root, year_month) |>
  summarise(
    n_papers = n(),
    n_papers_arxiv = sum(arxiv_available),
    .groups = "drop"
  )

fwrite(D_papers, "ai_groups_output/group_D_firms_monthly_papers.csv")
cat("已存: group_D_firms_monthly_papers.csv (", nrow(D_papers), " rows)\n", sep = "")

# 整合大檔（若需要單一檔案跑迴歸）
fwrite(crsp_enriched, "ai_groups_output/crsp_all_classified_with_papers.csv")
cat("已存: crsp_all_classified_with_papers.csv (", 
    nrow(crsp_enriched), " rows)\n", sep = "")

# permno 對照表
fwrite(
  crsp_enriched |> distinct(permno, ticker, issuernm, ai_group),
  "ai_groups_output/permno_group_mapping.csv"
)
cat("已存: permno_group_mapping.csv\n")

cat("\n=== 全部完成 ===\n")


#+++++++++++++++++++++++++++++++++
#+# ============================================================
# 把 B 組細分為 ICT（資訊通訊科技業） vs OTHER（其他產業）
# 依據：NAICS 4-digit 分類
# 分類來源：ICT 標準定義（10 個 NAICS codes）
# ============================================================
library(tidyverse)
library(data.table)

# ---- 1. 定義 ICT 產業的 NAICS 4-digit 代碼 ----
ict_naics_4digit <- c(
  "3341",  # Computer and peripheral equipment manufacturing
  "3342",  # Communications equipment manufacturing
  "3344",  # Semiconductor and other electronic component manufacturing
  "3345",  # Navigational, measuring, electromedical, and control instruments
  "5112",  # Software publishers
  "5161",  # Internet publishing and broadcasting
  "5179",  # Other telecommunications
  "5181",  # Internet service providers and Web search portals
  "5182",  # Data processing, hosting, and related services
  "5415"   # Computer systems design and related services
)

cat("=== ICT NAICS 分類（10 個 4-digit codes）===\n")
print(ict_naics_4digit)
cat("\n")

# ---- 2. 讀取上一階段已分類的 CRSP 資料 ----
cat("=== 讀取 crsp_all_classified_with_papers.csv ===\n")
crsp_enriched <- fread("ai_groups_output/crsp_all_classified_with_papers.csv")
cat("維度:", dim(crsp_enriched), "\n\n")

# ---- 3. 建立 NAICS 4-digit 欄位與 ICT 判定 ----
cat("=== 加上 naics_4digit 與 is_ict 欄位 ===\n")
crsp_enriched <- crsp_enriched |>
  mutate(
    naics_str    = as.character(naics),
    naics_4digit = if_else(nchar(naics_str) >= 4, substr(naics_str, 1, 4), NA_character_),
    is_ict       = naics_4digit %in% ict_naics_4digit
  ) |>
  select(-naics_str)   # 移除中介欄位

# ---- 4. 建立四層次分類（A / B_ICT / B_Other / C）----
crsp_enriched <- crsp_enriched |>
  mutate(
    ai_group_detailed = case_when(
      ai_group == "A"                    ~ "A",
      ai_group == "B" & is_ict == TRUE   ~ "B_ICT",
      ai_group == "B" & is_ict == FALSE  ~ "B_Other",
      ai_group == "C"                    ~ "C"
    )
  )

# ---- 5. 檢查分類結果 ----
cat("=== 各組公司數分布 ===\n")
crsp_enriched |>
  distinct(permno, ai_group_detailed) |>
  count(ai_group_detailed) |>
  print()
cat("\n")

# ---- 6. B_ICT 論文數前 15 大 ----
cat("=== B_ICT（科技業）論文數前 15 大 ===\n")
crsp_enriched |>
  filter(ai_group_detailed == "B_ICT") |>
  group_by(permno, ticker, issuernm, naics_4digit) |>
  summarise(total_papers = sum(n_papers), .groups = "drop") |>
  arrange(desc(total_papers)) |>
  head(15) |>
  as_tibble() |>
  print()
cat("\n")

# ---- 7. B_Other 論文數前 15 大 ----
cat("=== B_Other（非科技業）論文數前 15 大 ===\n")
crsp_enriched |>
  filter(ai_group_detailed == "B_Other") |>
  group_by(permno, ticker, issuernm, naics_4digit) |>
  summarise(total_papers = sum(n_papers), .groups = "drop") |>
  arrange(desc(total_papers)) |>
  head(15) |>
  as_tibble() |>
  print()
cat("\n")

# ============================================================
# 存檔：把 B 組拆成兩個 CSV
# ============================================================
cat("=== 存檔 ===\n")

# B_ICT：資訊通訊科技業
fwrite(
  crsp_enriched |> filter(ai_group_detailed == "B_ICT"),
  "ai_groups_output/group_B_INFO_COMMU_TECH.csv"
)
cat("已存: group_B_INFO_COMMU_TECH.csv (",
    nrow(crsp_enriched[ai_group_detailed == "B_ICT"]), " rows, ",
    length(unique(crsp_enriched[ai_group_detailed == "B_ICT"]$permno)), " companies)\n",
    sep = "")

# B_Other：其他產業
fwrite(
  crsp_enriched |> filter(ai_group_detailed == "B_Other"),
  "ai_groups_output/group_B_OTHER.csv"
)
cat("已存: group_B_OTHER.csv (",
    nrow(crsp_enriched[ai_group_detailed == "B_Other"]), " rows, ",
    length(unique(crsp_enriched[ai_group_detailed == "B_Other"]$permno)), " companies)\n",
    sep = "")

# 也更新完整分類檔（含 naics_4digit 與 ai_group_detailed 兩個新欄位）
fwrite(crsp_enriched, "ai_groups_output/crsp_all_classified_with_papers_detailed.csv")
cat("已存: crsp_all_classified_with_papers_detailed.csv（含 naics_4digit 與 ai_group_detailed）\n")

# 更新 permno 對照表（含新的細分欄位）
fwrite(
  crsp_enriched |> distinct(permno, ticker, issuernm, naics, naics_4digit, siccd,
                            ai_group, ai_group_detailed, is_ict),
  "ai_groups_output/permno_group_mapping_detailed.csv"
)
cat("已存: permno_group_mapping_detailed.csv\n")

cat("\n=== 完成 ===\n")
cat("最終 ai_groups_output/ 資料夾內容：\n")
print(list.files("ai_groups_output"))
