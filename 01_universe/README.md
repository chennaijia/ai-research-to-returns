# 01_universe —— 建立公司母體與 A/B_ICT/B_Other/C 分組

把 CRSP 全市場股票依「有沒有 AI 論文」切成幾組，方便用視覺化比較不同族群的論文趨勢。
下游的 `03_patents` 讀這裡的產出取股價；`02_returns` 的主分析改為直接讀
`data/crsp/crsp_all_classified_with_papers_detailed_v2.csv`（見下），不再依賴這個
資料夾的輸出。

| 組 | 定義 |
|---|---|
| A | Magnificent 7（AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA） |
| B_ICT | 非 Mag7、屬 ICT 產業、且在 OpenAlex 有 AI 論文的美國上市公司 |
| B_Other | 非 Mag7、非 ICT 產業、但仍在 OpenAlex 有 AI 論文的上市公司 |
| C | 其餘 CRSP 公司（假定無 AI 論文） |
| D | 有 AI 論文但不在 CRSP 上的機構（非上市、國外）——**已是舊資料源的凍結快照，見下** |

## 2026-09-25：改用 v2 面板，不再自建論文對照

**舊版本**直接讀 `data/crsp/stock_on_crsp.csv` + `data/openalex/paper_company_panel.csv`，
自己用機構名稱字串比對把論文掛回公司——這個比對邏輯繼承了 OpenAlex 自 2022 年起
機構隸屬連結斷裂的問題，導致公司論文數在 2022 年出現不存在的「暴跌」（見
`data/README.md`）。這兩個原始檔已刪除，**現在改成直接切分**
`data/crsp/crsp_all_classified_with_papers_detailed_v2.csv`（下稱 v2）——它已經把
股價、NAICS 科技分類、修正後的公司論文數都合併好了，不需要（也不應該）再自己重新比對一次。

代價：v2 只涵蓋 2017-01 起、且已在 CRSP 上市的公司，因此**不再產生 D 組**（那需要
原始 OpenAlex 全文檔才能重建）。既有的 `group_D_firms.csv` /
`group_D_firms_monthly_papers.csv` 沒有下游分析在用，維持原樣，視為舊資料源的
凍結快照，不再隨此腳本更新。

## 執行

路徑全部相對 repo 根目錄。**工作目錄要設在 repo 根，不是這個資料夾。**

```r
source("01_universe/scripts/01_build_groups.R")       # 讀 297 MB 的 v2，直接切分
source("01_universe/scripts/02_plot_group_papers.R")  # 畫三組論文趨勢圖
```

## 輸出（`out/`）

| 檔案 | 內容 | 誰在用 |
|---|---|---|
| `group_A_stocks.csv` | Mag7 月頻股價 + 論文數 | `03_patents/scripts/08_align.py` |
| `group_B_INFO_COMMU_TECH.csv`、`group_B_OTHER.csv` | B_ICT / B_Other 月頻股價 + 論文數 | `02_plot_group_papers.R` |
| `group_C_stocks.csv` | C 組月頻股價 | `03_patents` |
| `group_D_firms.csv`、`group_D_firms_monthly_papers.csv` | ⚠️ 舊資料源的凍結快照，非上市機構名單與月頻論文數 | — |
| `fig_papers_absolute_3groups.png`、`fig_papers_indexed_3groups.png` | 三組論文趨勢：2020 年後三組論文數持續成長，沒有斷崖 | — |

## ⚠️ 一件必須知道的事

**`is_ict` 欄位（若在其他舊檔案中看到）是壞的，不要用。** 它有兩個獨立的 bug：代碼表是舊版
NAICS（NAICS 2022 把軟體出版從 511210 改到 513210，導致軟體公司自 2023 年起全部掉出科技業），
而且分類隨時間翻轉（在有發論文的公司裡高達 26%，含 GOOGL / MSFT / META）。**科技業分類一律
改用 `02_returns/out/tech_classification.csv`**，那是 6 碼、跨 NAICS 版本、以多數決收斂的
修正版（現在也是直接讀 v2 算出來的）。
