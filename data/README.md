# data/

**不可重建的原始資料。** 這裡的每一個檔都來自外部系統（CRSP、OpenAlex、BigQuery、SEC），
repo 裡沒有任何腳本能重新產生它們。刪掉就得回原始來源重新取得。

反過來說，**四條 pipeline 的 `out/` 都是可重建的**——照各自 README 的順序重跑即可。
磁碟不夠時先清 `out/`，不要動這裡。

| 檔案 | 來源 | 內容 | 大小 | 版控 |
|---|---|---|---|---|
| `crsp/crsp_all_classified_with_papers_detailed_v2.csv` | CRSP（經 WRDS）+ OpenAlex，已合併並修正 | 全市場月頻股價、報酬、市值、NAICS、科技分類、公司 AI 論文數，2017-01 起 | 297 MB | LFS |
| `arxiv/ai_monthly.csv` | arXiv metadata snapshot | 月頻 AI 論文數與引用數，2017-01 起 | 4.5 KB | git |
| `arxiv/ai_monthly_subfield.csv` | 同上 | 月頻 × AI 子領域論文數 | 19 KB | git |
| `compustat/rnd_8comp.csv` | Compustat | 8 家公司年度 R&D 支出（`xrd`，單位百萬美元） | 21 KB | git |
| `compustat/rnd_8comp_month.csv` | Compustat | 同上，季頻（`xrdq`） | 130 KB | git |
| `sec/rd_expense_annual.csv` | SEC XBRL | 8 家公司年度 R&D 支出，與 Compustat 互為對照 | 9 KB | git |

**2026-09-25 更新：`crsp/stock_on_crsp.csv`（舊版全市場原始檔）與
`openalex/paper_company_panel.csv`（舊版論文-機構明細）已刪除**，改用上面的
`crsp_all_classified_with_papers_detailed_v2.csv`（下稱 v2）取代——v2 已經把股價、
NAICS 分類、公司 AI 論文數合併好，且修正了舊版資料的下述陷阱 3。v2 只涵蓋
2017-01 起（已在 CRSP 上市的公司），不含 2010-2016，這段期間本來就在 Q1/Q2
的分析窗格之外（arXiv 論文序列從 2017-01 才開始）。

## 誰讀誰

```
crsp/v2  ─→ 01_universe、02_returns
arxiv/ai_monthly   ─→ 02_returns
compustat/         ─→ 04_rnd
sec/               ─→ （目前無現役腳本讀取，保留作為 Compustat 的對照來源）
```

`03_patents` 不直接讀這裡——它的專利母體來自 BigQuery，股票與論文則取自 `01_universe/out/`。

## ⚠️ 使用這些資料前必讀的兩個陷阱

1. **CRSP 用 `naics = 0` 表示缺值，不是 `NA`。** `fread()` 會讀成整數 0，`is.na()` 完全抓不到
   （已下市公司最後幾個月幾乎都是 0）。
2. **CRSP 分割月份有重複列**，聚合前要以 `(permno, yyyymm)` 去重。

### 🟢 已修正：舊版 OpenAlex 公司論文自 2022 年起系統性缺漏

舊版 `paper_company_panel.csv`（機構隸屬不再掛在 arXiv 記錄上，捕捉率 36% → 5%）曾
導致公司層級論文數在 2022 年出現不存在的「暴跌」（GOOGL 654→101、MSFT 429→122 等）。
v2 已修正這個問題：公司論文數延續 arXiv 母體語料的成長趨勢，2022 年不再出現斷崖
（詳見 `02_returns/out/structural_change.txt` 的前提檢驗、`01_universe/out/fig_papers_indexed_3groups.png`）。
