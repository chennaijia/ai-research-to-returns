# 04_rnd —— 八家科技公司的 R&D 支出

把 Compustat 的 R&D 支出畫成圖。這條線是輔助性的：用來檢查「公司論文數下降」是不是伴隨
研發投入下降（結論是沒有——R&D 支出持續成長，論文下降來自 OpenAlex 的資料瑕疵，
見 `data/README.md` 陷阱 3 與 `03_patents/README.md`）。

## 執行

```r
source("04_rnd/scripts/01_plot_rd.R")   # 工作目錄設在 repo 根
```

讀 `data/compustat/rnd_8comp.csv`（年）與 `rnd_8comp_month.csv`（季），輸出到 `out/`。

## 方法上唯一要注意的地方

**R&D 支出依實際財務期間對齊，不硬塞進日曆年。** 八家公司的財年結束日不同（AAPL 是 9 月、
NVDA 是 1 月、其餘多為 12 月），直接按 `fyear` 相加會把不同期間的數字加在一起。所以圖上
每一條水平線段的**長度就是該公司的真實財報期間**，加總圖也用 point-in-time 的方式做：對每個
日曆時點，只加總「當下仍在該財季區間內」的公司。

## 輸出（`out/`）

| 檔案 | 由誰產生 |
|---|---|
| `fig_rd_annual_segments.png` | `01_plot_rd.R` 圖 1 |
| `fig_rd_quarterly_segments.png` | 圖 2 |
| `fig_rd_aggregate_pit.png` | 圖 3（point-in-time 加總） |
| `fig_rd_annual_facet_segments.png` | 圖 4（八家分面） |
| `fig_rd_sales_aggregate_pit.png` | ⚠️ **孤兒圖** |
| `fig_rd_sales_aggregate_annual_pit.png` | ⚠️ **孤兒圖** |

⚠️ 最後兩張（R&D 佔營收比）**無法重建**——產生它們的腳本版本沒有進版控。內容看起來是在
現有腳本上加了 `sale` 欄位做比值。要重現得自己補寫。
