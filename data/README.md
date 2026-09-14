# data/

**不可重建的原始資料。** 這裡的每一個檔都來自外部系統（CRSP、OpenAlex、BigQuery、SEC），
repo 裡沒有任何腳本能重新產生它們。刪掉就得回原始來源重新取得。

反過來說，**四條 pipeline 的 `out/` 都是可重建的**——照各自 README 的順序重跑即可。
磁碟不夠時先清 `out/`，不要動這裡。

| 檔案 | 來源 | 內容 | 大小 | 版控 |
|---|---|---|---|---|
| `crsp/stock_on_crsp.csv` | CRSP（經 WRDS） | 全市場月頻股價、報酬、市值、NAICS | 399 MB | LFS |
| `openalex/paper_company_panel.csv` | OpenAlex + arXiv | 論文-作者-機構明細，用於辨識有 AI 論文的公司 | 78 MB | LFS |
| `arxiv/ai_monthly.csv` | arXiv metadata snapshot | 月頻 AI 論文數與引用數，2017-01 起 | 4.5 KB | git |
| `arxiv/ai_monthly_subfield.csv` | 同上 | 月頻 × AI 子領域論文數 | 19 KB | git |
| `compustat/rnd_8comp.csv` | Compustat | 8 家公司年度 R&D 支出（`xrd`，單位百萬美元） | 21 KB | git |
| `compustat/rnd_8comp_month.csv` | Compustat | 同上，季頻（`xrdq`） | 130 KB | git |
| `sec/rd_expense_annual.csv` | SEC XBRL | 8 家公司年度 R&D 支出，與 Compustat 互為對照 | 9 KB | git |

## 誰讀誰

```
crsp/ + openalex/  ─→ 01_universe
arxiv/ai_monthly   ─→ 02_returns
compustat/         ─→ 04_rnd
sec/               ─→ （目前無現役腳本讀取，保留作為 Compustat 的對照來源）
```

`03_patents` 不直接讀這裡——它的專利母體來自 BigQuery，股票與論文則取自 `01_universe/out/`。

## ⚠️ 使用這些資料前必讀的三個陷阱

1. **CRSP 用 `naics = 0` 表示缺值，不是 `NA`。** `fread()` 會讀成整數 0，`is.na()` 完全抓不到
   （1.63% 的列、350 家公司全程為 0）。已下市公司最後幾個月幾乎都是 0。
2. **CRSP 分割月份有重複列**，聚合前要以 `(permno, yyyymm)` 去重。
3. **OpenAlex 的公司論文自 2022 年起系統性缺漏**（機構隸屬不再掛在 arXiv 記錄上，捕捉率
   36% → 5%）。`paper_company_panel.csv` 在 2022 年後不可直接用於公司層級的時間比較；
   `arxiv/ai_monthly.csv` 是母體語料，**不受影響**。
