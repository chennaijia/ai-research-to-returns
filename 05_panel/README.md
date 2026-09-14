# 05_panel —— CRSP v2 月頻面板 × AI 專利的合併表

把 `data/crsp/crsp_all_classified_with_papers_detailed_v2.csv`（公司-月的股價、報酬、
修正後的科技分類、論文數）與 `03_patents/out/` 的 AI 專利合併成單一分析用面板。

## 執行

```bash
03_patents/.venv/bin/python 05_panel/scripts/01_merge_panel.py
```

## 輸出（`out/`）

| 檔案 | 粒度 | 列數 | 大小 |
|---|---|---|---|
| `panel_firm_month.csv` | 公司 × 月 | 27,324（253 家 × 108 月） | 3.3 MB |
| `panel_firm_year.csv` | 公司 × 年 | 2,277（253 家 × 9 年） | 256 KB |
| `merge_report.txt` | 涵蓋率與限制 | — | — |


### 主要欄位

| 欄位 | 來源 | 說明 |
|---|---|---|
| `permco` / `ticker` / `company` | firm_roster | 公司層級識別碼 |
| `mthret` / `mthcap` / `sprtrn` | v2 | 月報酬、月底市值、S&P500 月報酬 |
| `annual_return` / `annual_excess_return` | 年頻檔 | 月報酬複利；超額是 buy-and-hold 差額，非逐月超額複利 |
| `is_ict_firm` / `tech_share` / `is_ict_month` | v2 | 科技業分類（見下） |
| `ai_group` / `ai_group_detailed` | v2 | A/B/C/D 分組 |
| `n_papers` | v2 | 公司 AI 論文數 |
| `ai_patents_parent_only` | 03_patents | 只算母公司本體的 AI 專利，依申請月份 |
| `ai_patents_with_subs` | 03_patents | 含子公司版（依併購生效日歸屬） |
| `all_patents` | 03_patents | 該公司全部 publication，作為 AI 佔比分母 |
| `ai_share` | 計算 | `ai_patents_with_subs / all_patents` |
| `patent_truncated` | 計算 | 1 = 該期專利數必然低估，見下 |

## 方法上的四個決定

**1. 專利是真實月頻，不是年數攤平。** `ai_patents_detail.csv` 的 `filing_date` 是
YYYYMMDD，所以「某公司某月申請幾件 AI 專利」是資料裡本來就有的事實。把年度數字除以 12
攤到每個月會製造不存在的年內變異，讓月頻迴歸的標準誤嚴重低估——這裡沒有這個問題。

**2. 一律以 `permco`（公司）為鍵，不用 ticker 或 permno。** 一家公司可以有多個股別
（Alphabet 的 GOOGL/GOOG）、也可以換過 ticker（FB → META）。用 ticker 會讓換名公司被切成
兩段，用 permno 會讓多股別公司同月出現兩列、報酬被重複複利。本資料有 **385 個**公司-月是
多股別的。處理規則沿用 `03_patents/scripts/08_align.py`，兩個方向相反且都驗證過：

- **報酬取當月市值最大的股別。** 相加或平均都不對，那不是任何人可以持有的部位。
- **論文跨股別相加。** CRSP 的 `n_papers` 只掛在其中一個 permno 上（Alphabet 2020-01 是
  GOOGL 掛 58 篇、GOOG 掛 0），取單一股別會漏掉。

**3. 零與缺值嚴格區分。** 專利欄位為 `0` 代表「查過，這個月沒有」；報酬欄位留**空字串**
代表「該月沒有 CRSP 資料」。這 253 家全部查過專利，所以專利欄不會有缺值。迴歸時把 0 誤當
缺值（或反之）會改變結論。

**4. 平衡面板。** 253 家 × 全部 108 個月都出列，即使該月沒有任何資料。要篩選請自己下條件，
不要靠列的存在與否來篩。

## 限制

### 1. `patent_truncated == 1` 的期間專利數必然低估

美國 pre-grant publication 自申請日起約 **18 個月**才公開。本資料最大的
`publication_date` 是 **2026-04-09**，往前推 18 個月，**2024-10 之後的申請月一定不完整**。

實測完全吻合：月件數在 2024-09 是 938 件，2024-10 掉到 619，一路下滑到 2025-12 只剩 70。

**這個下滑是專利還沒公開，不是企業真的減少申請。** 做時間序列時必須截斷或明確控制，
否則會得到一個完全虛假的「2024 年後 AI 研發崩潰」結論。

### 2. 已排除 15 家公司，其中有大量專利申請者

名冊 268 家中有 15 家在 v2 裡完全沒有資料（2017 年前下市或 ADR 終止，而 v2 自 2017 起算）：

```
ALU ATE ATML BRCM COGT DELL HIT HRBN IRF JCI LNKD OVTI PC TCH XLS
```

這些公司合計 **6,049 件** AI 專利不在本面板內。DELL（1,928 件）、PC／Panasonic（1,918）、
HIT／Hitachi（1,636）都是大量申請者。做專利總量的敘述統計時要記得這個缺口；
`03_patents/out/patent_stock_paper_annual.csv` 涵蓋 2010 起算的全部 268 家，需要完整專利
母體時用那個檔。

## 月頻、年頻分析

專利在月頻是**稀疏**的：

| 粒度 | 非零的格子 |
|---|---|
| 公司-月 | 30.2% |
| 公司-年 | 56.8% |

108 個月裡有超過 100 個月在申請 AI 專利的只有 **24 家**；有 33 家全期只有 1–4 個月有申請。

所以：**大型申請者（Google、Microsoft、Intel 等）用月頻沒問題**，長尾公司的月頻幾乎全是零，
零膨脹會讓 OLS 的估計失真，建議改用年頻檔或改用計數模型。

## 與既有檔案的關係

`03_patents/out/patent_stock_paper_annual.csv` 做的事類似，差別為：

| | 本檔 | patent_stock_paper_annual.csv |
|---|---|---|
| 期間 | 2017–2025 | 2010–2025 |
| 公司 | 253（v2 有資料的） | 268（全名冊） |
| 粒度 | 月 + 年 | 只有年 |
| 股票來源 | v2（修正後的科技分類） | `01_universe/out/` 四個 group 檔 |
| 科技分類欄位 | 有（`is_ict_firm`/`tech_share`） | 無 |
| 論文數 | v2 版（無 2022 斷崖） | 舊面板版（有 2022 斷崖） |

要**跨 2010–2016**或要**完整專利母體**時用舊的；要**修正後的科技分類**、**月頻專利**或
**v2 的論文數**時用本檔。