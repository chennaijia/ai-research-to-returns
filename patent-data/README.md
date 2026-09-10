# patent-data

八家科技公司 2010–2025 年 AI 專利的抽取、判定與對齊管線。

建立目的是檢驗一個假說：**「2022 年後企業改發專利、不發論文」**。母專案觀察到公司論文數
在 2022 年集體暴跌約 75%，若企業真的把揭露管道從論文轉向專利，專利數應同期上升。專利資料
與 OpenAlex 完全獨立，可以當作獨立證人。

> **結論先講：假說的前提不成立。** 論文腰斬的同時 AI 專利穩定成長，沒有出現「此消彼長」。
> 這支持論文崩塌來自 OpenAlex 機構隸屬連結斷裂（資料瑕疵），而非企業行為改變。
> 見 [對齊結果](#6-對齊股票與論文)。

---

## 資料口徑

| 項目 | 設定 | 理由 |
|---|---|---|
| 專利型態 | 美國 **pre-grant publication**（kind code A1/A2） | 核准與否受審查積壓影響，公開件數較貼近「當年投入」 |
| 時間索引 | **filing year**（申請年），非公開年或核准年 | 申請日最接近研發決策的時點 |
| 期間 | 2010-01-01 – 2025-12-31 | 涵蓋母專案股票面板全期 |
| 計數單位 | 一個 `application_number` 計一次 | 同一申請案可能有多次公開 |
| 資料源 | BigQuery `patents-public-data.patents.publications` | Google Patents Public Data |
| 判定標準 | WIPO Technology Trends 2019 AI 檢索式 | 國際組織公開發表、可引用的既有標準 |
| 公司歸屬 | 母公司版 / 含子公司版**兩套** | 穩健性檢驗；子公司依併購生效日歸屬 |

母體共 **144,826** 件 publication，判定為 AI 者 **37,010** 件（25.6%）。

---

## 執行順序

```bash
cd patent-data
.venv/bin/python scripts/01_fetch_publications.py   # 需 gcloud 認證，會產生 BigQuery 費用
.venv/bin/python scripts/03_build_wipo_rules.py
.venv/bin/python scripts/04_derive_concordance.py
.venv/bin/python scripts/05_classify.py
.venv/bin/python scripts/07_align.py
```

`02_check_cpc_drift.py` 與 `06_diagnose.py` 是**唯讀的診斷腳本**，不產生下游依賴，但它們是
下面兩個關鍵決策的證據來源，建議保留並在改動規則後重跑。

---

## 1. 公司名稱對照

專利資料的 `assignee` 是自由文字，同一家公司有幾十種寫法（含拼錯）。對照表**全部由
BigQuery 實際出現的字串建立**，未憑印象填寫。

- `config/company_alias.csv`（182 列）—— 母公司層級。含 `MICROSOFT TECHNOLOGY LICENSING, LLC`、
  `MICROSOFT TECHNOLOGY LICENSING, LLC.` 這類標點差異，以及觀察到的拼寫變體。
- `config/subsidiary_alias.csv`（50 列）—— 子公司，附 `effective_from` / `effective_to` /
  `date_basis` / `source_url`。

**併購時點必須處理。** 子公司在被收購**之前**申請的專利不能算給收購方，否則會憑空製造出
一段成長。例如：

| 子公司 | 生效區間 | 說明 |
|---|---|---|
| MOTOROLA MOBILITY LLC | 2012-05-22 → **2014-10-30** | Google 買入後又賣給 Lenovo，**有結束日** |
| BROADCOM CORP | 2016-02-01 → | 被 Avago 併購後 Avago 改名 Broadcom |
| NUANCE COMMUNICATIONS | 2022-03-04 → | Microsoft |
| MELLANOX | 2020-04-27 → | Nvidia |
| VMWARE INC | 2023-11-22 → | Broadcom |
| DEEPMIND | 2014-01-27 → | Alphabet |

`date_basis` 區分 `completed`（交易完成日）、`announced`（僅查到宣布日）、`internal_unit`
（Waymo/Verily/Wing 等內部單位，非併購）。

> ⚠️ 曾經有三列 Apple 子公司因為找不到可靠來源而被**整列刪除**，而不是填一個猜測的 URL。
> 這個原則要維持：`source_url` 欄位若無法查證，寧可不收該列。

---

## 2. WIPO AI 判定規則

`config/wipo_search_strings_verbatim.txt` 是 WIPO 方法論 PDF 第 7c 節的**逐字轉錄**，含
取得日期與頁碼，供日後核對。

### 結構是三個 Block 的 OR，不是「CPC AND 關鍵詞」

```
AI = Block1  OR  Block2  OR  Block3
     └ CPC 代碼命中即可，不需關鍵詞
              └ K1 核心關鍵詞命中即可，不需 CPC
                       └ (C1 或 C2 代碼)  AND  K2 泛用關鍵詞
```

**這點很容易搞錯。** Block 2 的 K1 是「人工智慧」「神經網路」「深度學習」這類**本身就足以
判定**的詞，不需要再要求 CPC 同時命中。若寫成 `CPC AND 關鍵詞`，Block 2 會被整個吃掉。
實測 Block 2 單獨貢獻 763 件（0.5%）是其他兩者都沒抓到的。

各 Block 命中率（可重疊，見 `06_diagnose.py`）：

| Block | 命中 | 佔母體 |
|---|---|---|
| Block1（CPC） | 36,074 | 24.9% |
| Block2（K1 關鍵詞） | 8,928 | 6.2% |
| Block3（C1/C2 + K2） | 3,145 | 2.2% |
| **聯集** | **37,010** | **25.6%** |

### Orbit 檢索語法 → 正規表示式

WIPO 用 Questel Orbit 語法，需要翻譯（`scripts/wipo_keywords.py`）：

| 運算子 | 意義 | 對應 regex |
|---|---|---|
| `+` | 任意長度截斷 | `\w*` |
| `?` | 0 或 1 個字元 | `\w?` |
| `#` | 恰好 1 個字元 | `\w` |
| `nW` | 有序鄰近，中間至多 n 個詞 | `(?:\W+\w+){0,n}\W+` |
| `nD` | 無序鄰近 | 同上，但額外產生反向排列 |
| `_` `-` | 詞內連接 | `[-_\s]` |

`scripts/wipo_terms.py` 把 K1（45 條）與 K2（18 條）逐條編碼，**每一條後面都附 WIPO 原文
註解**，可以一行一行對。

### 兩個已知的規則面限制

1. **檢索欄位比 WIPO 窄。** WIPO 搜 title / abstract / claims / description，我們只有
   title + abstract。這會**系統性低估**，但低估幅度逐年大致固定，不會製造時間序列上的斷點。
2. **C3（FI）與 C4（F-term）不適用。** 這兩者是日本特許廳專用分類，美國 pre-grant
   publication 沒有該欄位。已在 `wipo_ai_rules.json` 中明確標記 `applicable: false` 並附理由，
   而不是靜默略過。

---

## 3. 🔴 CPC 重分類漂移 —— 本專案最危險的陷阱

**如果直接套用 WIPO 2019 年的代碼清單，會製造出一場完全虛構的 AI 專利崩塌，而且時間點正好
落在 2019–2023，也就是母專案結構斷點分析的窗格內，方向還剛好「證實」原假說。**

CPC 分類體系會改版。WIPO 清單寫於 2019 年，其中多個代碼此後已被廢止，專利局改用新代碼。
舊代碼在改版後的申請案上**歸零**——不是因為公司不做這類研發了，而是因為那個代碼不存在了。

`02_check_cpc_drift.py` 的輸出（每格 = 該 filing year 至少帶一個該家族代碼的件數）：

| 代碼家族 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 |
|---|---|---|---|---|---|---|---|---|---|---|
| G06F17/30\* 舊·資訊檢索 | 1262 | 1518 | 1585 | 1095 | **0** | 0 | 0 | 0 | 0 | 0 |
| G06F16/\* 新 | 1618 | 1965 | 1924 | 1520 | 1447 | 1218 | 1119 | 1146 | 1214 | 850 |
| G06F17/27,28 舊·自然語言 | 189 | 259 | 299 | 230 | 235 | **0** | 0 | 0 | 0 | 0 |
| G06F40/\* 新 | 548 | 744 | 664 | 540 | 563 | 432 | 496 | 555 | 695 | 558 |
| G06N99/005 舊·機器學習 | 131 | 231 | 345 | 206 | **0** | 0 | 0 | 0 | 0 | 0 |
| G06N20/\* 新 | 181 | 306 | 559 | 620 | 751 | 723 | 744 | 689 | 693 | 567 |
| G06K9/\* 舊·圖像辨識 | 371 | 420 | 549 | 634 | 763 | 747 | 687 | 191 | **0** | 0 |
| G06V/\* 新 | 425 | 510 | 634 | 634 | 784 | 850 | 850 | 885 | 973 | 804 |
| G06N7/005 舊·機率推論 | 46 | 95 | 96 | 54 | 65 | 63 | 38 | 34 | **0** | 0 |
| G06N7/01 新 | 53 | 86 | 149 | 149 | 190 | 156 | 127 | 125 | 130 | 104 |
| **G06N3/\* 未改編對照組** | 113 | 199 | 465 | 572 | 941 | 1036 | 1092 | 1053 | **1168** | 957 |

最後一列是關鍵：`G06N3/*`（神經網路）從未被改編，同期一路成長到 1168。**真實趨勢是成長，
不是崩塌。**

### 廢止的證據來自官方，不是我推論的

用 BigQuery 的 CPC scheme 版本快照互比：

- `patents-public-data.cpc.definitions_201710` —— 舊碼存在，`status = published`
- `patents-public-data.cpc.definition`（現行）—— 舊碼**完全消失**

再加上兩層佐證：

- **官方 `dateRevised` 與資料斷崖對得上**：G06F16/00 → 2019-01-01（斷崖 2019）、
  G06F40/00 → 2020-01-01（斷崖 2020）、G06N7/01 → 2023-01-01（斷崖 2023）、
  G06V10/00 → 2023-08-01（斷崖 2023）
- **標題延續**：G06N7/005「Probabilistic **networks**」→ G06N7/01「Probabilistic graphical
  models, e.g. probabilistic **networks**」

> ⚠️ 注意 schema 欄名在版本間不一致：`definition_201903` 用 `title_full`（snake_case），
> `definition_202302` 與現行版用 `titleFull`（camelCase）。同一支 SQL 跑兩個版本會報錯。

---

## 4. 🔴 共現 ≠ 取代 —— 一個造成 77% 誤判的錯誤

知道舊碼被廢止之後，還要知道**替代碼是什麼**。做法是利用「USPTO 廢止代碼時會把舊文件追溯
重新掛上新碼」這個事實：帶舊碼的文件會同時帶著新碼，用共現率推導。

**第一版直接用共現率排序取 top-N，結果 77% 的專利被判成 AI。**

診斷（`06_diagnose.py`）顯示 Block 3 是無辜的（僅 2.2%），元凶是 Block 1 的 42.4%，命中最多的
代碼是：

```
G06F3/0482  5704    G06F3/04842  4394    G06F3/04883  3986
G06F3/011   3647    G06Q10/40    3473    G06F3/017    3453
```

全是 GUI 與輸入介面代碼，跟 AI 無關。

**根因**：共現有兩種完全不同的成因，而共現率分不出來。

- **取代**：G06K9/62 的文件被追溯改掛 G06F18/ —— 這是真的替代
- **互補**：手勢辨識專利同時帶 G06K9/00355（手勢**辨識**）與 G06F3/017（手勢**輸入介面**）
  —— 兩者是互補功能，共同出現，但後者從來不是前者的替代碼

**修法**：先用官方 CPC 改編公告把候選**限縮在確實接收該次改編的子類**（`TRANSFER_TARGETS`
白名單），再在白名單內用共現率細分子群。兩道關卡缺一不可——白名單決定「方向對不對」，
共現率決定「對到哪個子群」。

```python
TRANSFER_TARGETS = [
    ("G06K9/",    ("G06V", "G06F18/")),   # CPC Notice of Changes RP0760 (2022-01)
    ("G06F17/30", ("G06F16/",)),
    ("G06F17/27", ("G06F40/",)),
    ("G06N99/",   ("G06N20/",)),
    ("G06F19/",   ("G16B", "G16C", "G16H")),
    # ...
]
```

修正後降到 **25.6%**，Block 1 命中的 top-20 代碼全部是合理的 AI 代碼。

門檻設定：推導階段共現率 `>= 0.30`（`04_derive_concordance.py`），實際採用階段收緊到
`>= 0.50`（`05_classify.py`）。375 個廢止碼中 349 個找到替代候選，最終納入 383 個相異替代碼。
完整推導過程與每個候選的共現率留在 `out/concordance_report.txt`（13 萬字，供人工複核）。

---

## 5. 分類與去重

判定為 AI 後，依 `matched_ai_cpc` 的家族指派 `ai_category`：

| 領域 | 件數 | 佔比 |
|---|---|---|
| neural_network | 7,895 | 22.9% |
| computer_vision | 7,347 | 21.3% |
| information_retrieval | 6,716 | 19.5% |
| speech | 3,942 | 11.4% |
| machine_learning | 3,180 | 9.2% |
| nlp | 2,426 | 7.0% |
| other | 1,303 | 3.8% |
| control_robotics | 996 | 2.9% |
| probabilistic_reasoning | 593 | 1.7% |
| bioinformatics_health | 43 | 0.1% |

去重鍵為 `(歸屬公司, application_number)`，保留 `publication_number` 最小者（最早公開）。

`ai_patents_detail.csv` **保留 title、abstract 與完整 CPC 列表**，任何一件被判為 AI 的專利
都可以回頭檢查判定依據（`ai_basis` 欄位記錄是哪個 Block 命中）。

### with_subs 版逐年件數（依 filing year）

| 公司 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24* | 25* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Alphabet | 105 | 266 | 401 | 641 | 528 | 550 | 765 | 836 | 726 | 1117 | 1219 | 1139 | 1186 | 1377 | 1222 | 560 |
| Amazon | 1 | 3 | 14 | 45 | 126 | 109 | 114 | 145 | 122 | 169 | 224 | 161 | 182 | 200 | 166 | 73 |
| Apple | 45 | 46 | 93 | 156 | 169 | 201 | 220 | 208 | 279 | 283 | 308 | 300 | 347 | 413 | 347 | 292 |
| Broadcom | 1 | 2 | 0 | 1 | 3 | 8 | 1 | 0 | 3 | 3 | 0 | 5 | 9 | 6 | 15 | 6 |
| Meta | 6 | 0 | 51 | 102 | 221 | 281 | 388 | 476 | 166 | 173 | 155 | 167 | 212 | 171 | 115 | 83 |
| Microsoft | 609 | 586 | 465 | 504 | 579 | 606 | 791 | 940 | 948 | 871 | 602 | 717 | 856 | 890 | 699 | 199 |
| Nvidia | 1 | 0 | 12 | 25 | 6 | 7 | 4 | 23 | 64 | 170 | 242 | 318 | 352 | 445 | 499 | 261 |
| Tesla | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 10 | 13 | 6 | 9 | 14 | 37 | 15 | 13 |

`*` = 受 18 個月公開時滯影響，**必然低估**。

合理性檢查：Nvidia 從 2010 年的 1 件成長到 2024 年的 499 件，與 AI 熱潮時點吻合；Broadcom
全期近乎為零（純半導體廠，AI 專利佔比僅 2.7%，其餘七家為 10.9%–42.7%），是很好的天然安慰劑組。

---

## 6. 對齊股票與論文

`07_align.py` 輸出 `out/patent_stock_paper_annual.csv`，**128 列 = 8 家 × 16 年的平衡面板**。

### AI 專利為 0 的公司-年度也要有列

Tesla 2010–2016 的 AI 專利是**真實的 0**（該期間每年有 25–74 件一般專利，只是沒有 AI 專利），
不是缺值。若直接以「有 AI 專利的年度」建表，這些列會整個消失，迴歸會把「零」誤當成缺值。
現在補為 0，共補回 12 列。

### ⚠️ 股票資料不要用 `LEVEL4/panel_monthly.csv`

那個檔的**月份是由「該月有發論文」決定的**，不是完整股價序列：AVGO 全期只有 3 個月、
TSLA 只有 1 個月、NVDA 好幾年只有 7–10 個月。把這種殘缺月份複利成「年報酬」，數字看起來
正常但完全不是那一年的真實報酬（初版只有 56/116 列有報酬）。

改用 CRSP 原始月資料後覆蓋率變成 **126/128**：

| 來源 | 用途 |
|---|---|
| `stock_and_paper_count/group_A_stocks.csv` | 8 家中的 7 家，2010–2025 每年 12 個月齊全 |
| `stock_and_paper_count/group_C_stocks.csv` | **AVGO 在這裡**，不在 group_A |

唯二缺報酬的是 Meta 2010–2011（Facebook 2012 才上市，本來就該缺）。

三個處理細節：

- **CRSP 分割月份有重複列**，需以 `(ticker, yyyymm)` 去重（AAPL 2020-08、NVDA 2024-06）
- **Ticker 歷史分段**：Alphabet 是 GOOG →（2014Q2）→ GOOGL，Meta 是 FB →（2022 年中）→ META。
  在 group_A 內兩段月份**不重疊**（2014 = GOOG 3 + GOOGL 9；2022 = FB 5 + META 7），可直接
  聯集成連續序列。論文數同樣要合併，否則 Meta 2017–2021 的論文會整段遺失。
  ⚠️ 若同時讀 group_A 與 group_C 則**會**重疊，group_C 只取 AVGO。
- **超額報酬定義**為 buy-and-hold 差額（個股年報酬 − S&P500 年報酬），而非逐月超額報酬的
  複利——後者沒有可實際持有的投資組合與之對應

驗證：NVDA 2023 +239%、2024 +171%、2022 −50%；META 2022 −64%、2023 +194%；S&P 2022 −19.4%
—— 均與市場實際數字相符。

### 交叉檢驗結果：原假說的前提被推翻

| | 2020 | 2021 | 2022 | 2023 |
|---|---|---|---|---|
| Microsoft 論文 | 543 | 429 | **122** | 94 |
| Microsoft AI 專利 | 602 | 717 | **856** | 890 |
| Alphabet 論文 | 896 | 654 | **101** | 101 |
| Alphabet AI 專利 | 1219 | 1139 | **1186** | 1377 |
| Nvidia 論文 | 99 | 80 | **24** | 26 |
| Nvidia AI 專利 | 242 | 318 | **352** | 445 |

論文腰斬的同時 AI 專利照常成長。**沒有「此消彼長」，只有論文那一側斷掉。** 由於專利資料
完全獨立於 OpenAlex，這支持「OpenAlex 機構隸屬連結斷裂」的資料瑕疵解釋，而非「企業改用專利
揭露」的行為改變解釋。

---

## 輸出檔案

| 檔案 | 內容 |
|---|---|
| `out/raw_publications.csv` | 母體 144,826 件，含 title/abstract/CPC/assignee（135 MB） |
| `out/ai_patents_detail.csv` | 判定為 AI 的專利明細，含判定依據 `ai_basis`（70 MB） |
| `out/ai_patents_yearly.csv` | 公司 × filing year × 版本的件數 |
| `out/patent_stock_paper_annual.csv` | **最終面板**：專利 + 股票報酬 + 論文數 |
| `out/alignment_report.txt` | 涵蓋率、AI 佔比、交叉檢驗表、已知限制 |
| `out/concordance_report.txt` | CPC 對照推導的完整過程，供人工複核 |
| `config/cpc_concordance.json` | 廢止碼 → 現行碼對照表，含來源與共現率 |

---

## 已知限制

1. **`filing_year >= 2024` 的專利數必然低估。** 美國 pre-grant publication 自申請日起約 18
   個月才公開，近兩年的申請案尚未全部公開。做時間序列時應截斷或明確標註，**切勿把它當成
   真實下降**。`patent_truncated` 欄位已標記。
2. **論文資料 2022 年起有系統性缺漏**（OpenAlex 隸屬連結斷裂）。專利資料獨立於 OpenAlex，
   可作為該時期的對照，但論文數本身不可直接用於 2022 後的分析。
3. **檢索欄位僅 title + abstract**，比 WIPO 原始方法（含 claims/description）窄，AI 件數
   系統性低估。低估幅度逐年大致固定，不影響趨勢比較。
4. **C3/C4（JPO 的 FI 與 F-term）不適用**於美國 pre-grant publication。
5. **子公司歸屬依併購生效日**，`date_basis = announced` 的列（如 ZOOX）用的是宣布日而非
   完成日，有數月誤差。
6. **目前僅 Group A 八家公司。** 擴大到 `stock_and_paper_count` 的完整範圍（約 355 家）需要
   重建 assignee 對照表，這是最耗人工的一步。

---

## 資料來源

| 來源 | 用途 | 授權 |
|---|---|---|
| [Google Patents Public Data](https://console.cloud.google.com/marketplace/product/google_patents_public_datasets/google-patents-public-data) (BigQuery) | 專利母體、CPC scheme 版本快照 | CC BY 4.0 |
| [WIPO Technology Trends 2019: Artificial Intelligence — Data collection method and clustering scheme](https://www.wipo.int/documents/d/technology-trends/docs-en-techtrends_ai_methodology.pdf) §7c | AI 判定檢索式 | CC BY 3.0 IGO |
| CRSP（經 `stock_and_paper_count/`） | 月股價報酬與 S&P 500 | 母專案既有 |
| OpenAlex / arXiv（經 `analysis/out/`） | 公司論文數 | 母專案既有 |

專利判定規則的逐字原文見 `config/wipo_search_strings_verbatim.txt`（含取得日期與頁碼）。
