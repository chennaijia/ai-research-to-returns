# 01_universe —— 建立公司母體與 A/B/C/D 分組

把 CRSP 全市場股票依「有沒有 AI 論文」切成四組，並把 OpenAlex 的論文數併回股票面板。
下游的 `02_returns` 與 `03_patents` 都吃這裡的產出。

| 組 | 定義 |
|---|---|
| A | Magnificent 7（AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA） |
| B | 非 Mag7、但在 OpenAlex 有 AI 論文的美國上市公司（再細分 ICT / OTHER） |
| C | 其餘 CRSP 公司（假定無 AI 論文） |
| D | 有 AI 論文但不在 CRSP 上的機構（非上市、國外） |

## 執行

路徑全部相對 repo 根目錄。**工作目錄要設在 repo 根，不是這個資料夾。**

```r
source("01_universe/scripts/01_build_groups.R")       # 讀 399 MB，需數 GB 記憶體
source("01_universe/scripts/02_plot_group_papers.R")  # 畫三組論文趨勢圖
```

## 輸出（`out/`）

| 檔案 | 內容 | 誰在用 |
|---|---|---|
| `crsp_all_classified_with_papers_detailed.csv` | **主要產出**，426 MB：全市場月頻面板 + 論文數 + 分組標記 | `02_returns` |
| `group_A_stocks.csv` | Mag7 月頻股價 | `03_patents/scripts/08_align.py` |
| `group_B_INFO_COMMU_TECH.csv`、`group_B_OTHER.csv` | B 組月頻股價 | 同上 + `02_plot_group_papers.R` |
| `group_C_stocks.csv` | C 組月頻股價，396 MB | `03_patents` |
| `group_D_firms.csv`、`group_D_firms_monthly_papers.csv` | 非上市機構名單與月頻論文數 | — |
| `fig_papers_absolute_3groups.png`、`fig_papers_indexed_3groups.png` | 三組論文趨勢 | — |

## ⚠️ 兩件必須知道的事

**1. `is_ict` 欄位是壞的，不要用。** 它有兩個獨立的 bug：代碼表是舊版 NAICS（NAICS 2022 把
軟體出版從 511210 改到 513210，導致軟體公司自 2023 年起全部掉出科技業），而且分類隨時間翻轉
（在有發論文的公司裡高達 26%，含 GOOGL / MSFT / META）。後果是 GOOGL、META、AMZN 全被歸入
非科技組。**科技業分類一律改用 `02_returns/out/tech_classification.csv`**，那是 6 碼、跨
NAICS 版本、以多數決收斂的修正版。

**2. 重跑會產生約 1.2 GB 的中間檔。** `01_build_groups.R` 途中會寫出
`crsp_all_classified.csv` 與 `crsp_all_classified_with_papers.csv`（兩者都約 400 MB），
它們只是分段存檔，不是最終產物，也沒有進版控。跑完確認 `_detailed.csv` 存在後即可刪除。
