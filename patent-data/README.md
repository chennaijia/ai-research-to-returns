# patent-data

八家科技公司 2010–2025 年 AI 專利的抽取、判定與對齊管線。

主要用來檢驗「2022 年後企業是否由發表論文轉向申請專利」這個假說。母專案的公司論文數在 2022 年出現約 75% 的明顯下降；如果企業確實將部分研究揭露從論文轉向專利，理論上同一時期應能觀察到專利數的對應上升。

專利資料來自 Google Patents Public Data，與 OpenAlex 的論文資料獨立。

目前結果不支持上述假說。2022 年後公司論文數明顯下降，但 AI 專利仍延續原本的成長趨勢，沒有明顯的此消彼長關係。

相關結果見 [對齊股票與論文](#6-對齊股票與論文)。

---

## 資料口徑

| 項目   | 設定                                                  | 理由                           |
| ---- | --------------------------------------------------- | ---------------------------- |
| 專利型態 | 美國 **pre-grant publication**（kind code A1/A2）       | 核准與否會受到審查積壓影響，公開件數較接近當年的研發投入 |
| 時間索引 | **filing year**（申請年），非公開年或核准年                       | 申請日較接近研發與專利決策發生的時間           |
| 期間   | 2010-01-01 – 2025-12-31                             | 涵蓋母專案股票面板全期                  |
| 計數單位 | 一個 `application_number` 計一次                         | 同一申請案可能有多次公開                 |
| 資料源  | BigQuery `patents-public-data.patents.publications` | Google Patents Public Data   |
| 判定標準 | WIPO Technology Trends 2019 AI 檢索式                  | 採用公開且可引用的既有分類方法              |
| 公司歸屬 | 母公司版 / 含子公司版兩套                                      | 作為穩健性檢驗；子公司依併購生效日歸屬          |

母體共 144,826 件 publication，其中 37,010 件被判定為 AI 專利，占 25.6%。

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

`02_check_cpc_drift.py` 與 `06_diagnose.py` 為唯讀診斷腳本，不會產生下游依賴。不過它們分別用來檢查 CPC 分類漂移與分類結果，因此修改分類規則後建議重新執行。

---

## 1. 公司名稱對照

專利資料中的 `assignee` 為自由文字欄位，同一家公司可能有多種名稱、標點或拼寫方式。這裡的名稱對照表都是根據 BigQuery 中實際出現的字串建立，沒有額外加入未觀察到的名稱。

* `config/company_alias.csv`（182 列）：母公司層級。包含 `MICROSOFT TECHNOLOGY LICENSING, LLC`、`MICROSOFT TECHNOLOGY LICENSING, LLC.` 等標點差異，以及資料中出現的拼寫變體。
* `config/subsidiary_alias.csv`（50 列）：子公司名稱，另外記錄 `effective_from`、`effective_to`、`date_basis` 與 `source_url`。

### 併購時點

子公司的專利只會在併購生效後歸入母公司。若將收購前的專利一併計入，可能在人為上增加母公司的歷史專利數。

例如：

| 子公司                   | 生效區間                    | 說明                             |
| --------------------- | ----------------------- | ------------------------------ |
| MOTOROLA MOBILITY LLC | 2012-05-22 → 2014-10-30 | Google 收購後再出售給 Lenovo，因此有結束日   |
| BROADCOM CORP         | 2016-02-01 →            | 被 Avago 併購後，Avago 更名為 Broadcom |
| NUANCE COMMUNICATIONS | 2022-03-04 →            | Microsoft                      |
| MELLANOX              | 2020-04-27 →            | Nvidia                         |
| VMWARE INC            | 2023-11-22 →            | Broadcom                       |
| DEEPMIND              | 2014-01-27 →            | Alphabet                       |

`date_basis` 用來區分日期來源：

* `completed`：交易完成日
* `announced`：僅取得交易宣布日
* `internal_unit`：Waymo、Verily、Wing 等內部單位，並非透過併購取得

曾有三筆 Apple 子公司資料因找不到可靠來源而移除。`source_url` 無法查證時，不納入該筆子公司對照。

---

## 2. WIPO AI 判定規則

`config/wipo_search_strings_verbatim.txt` 保存 WIPO 方法論 PDF 第 7c 節的原始檢索式，並記錄取得日期與頁碼，方便後續核對。

### 三個判定 Block

WIPO 的 AI 判定邏輯是三個 Block 的 OR，而不是單純的「CPC AND 關鍵詞」：

```text
AI = Block1  OR  Block2  OR  Block3
     └ CPC 代碼命中即可，不需關鍵詞
              └ K1 核心關鍵詞命中即可，不需 CPC
                       └ (C1 或 C2 代碼) AND K2 泛用關鍵詞
```

其中 Block 2 的 K1 包含「人工智慧」、「神經網路」、「深度學習」等本身即可作為 AI 判定依據的詞，因此不需要另外要求 CPC 命中。

如果將整個規則寫成 `CPC AND 關鍵詞`，會漏掉 Block 2。實際資料中，Block 2 有 763 件專利是另外兩個 Block 都沒有抓到的。

各 Block 的命中情況如下。不同 Block 之間可以重疊，詳細診斷見 `06_diagnose.py`。

| Block              |         命中 |       佔母體 |
| ------------------ | ---------: | --------: |
| Block1（CPC）        |     36,074 |     24.9% |
| Block2（K1 關鍵詞）     |      8,928 |      6.2% |
| Block3（C1/C2 + K2） |      3,145 |      2.2% |
| **聯集**             | **37,010** | **25.6%** |

### Orbit 檢索語法轉換

WIPO 使用 Questel Orbit 的檢索語法，因此需要先轉換成 Python 正規表示式。相關實作位於 `scripts/wipo_keywords.py`。

| 運算子     | 意義             | 對應 regex             |
| ------- | -------------- | -------------------- |
| `+`     | 任意長度截斷         | `\w*`                |
| `?`     | 0 或 1 個字元      | `\w?`                |
| `#`     | 恰好 1 個字元       | `\w`                 |
| `nW`    | 有序鄰近，中間至多 n 個詞 | `(?:\W+\w+){0,n}\W+` |
| `nD`    | 無序鄰近           | 同上，但另外產生反向排列         |
| `_` `-` | 詞內連接           | `[-_\s]`             |

`scripts/wipo_terms.py` 將 K1（45 條）與 K2（18 條）逐條編碼，每一條規則旁都保留對應的 WIPO 原文註解，方便人工檢查。

### 規則限制

目前有兩項已知限制：

1. **檢索欄位較 WIPO 原始方法少。** WIPO 搜尋 title、abstract、claims 與 description，目前資料只使用 title + abstract，因此 AI 專利數會有系統性低估。只要低估程度沒有在特定年份突然改變，對時間趨勢的影響相對有限。
2. **C3（FI）與 C4（F-term）無法使用。** 兩者屬於日本特許廳的分類系統，美國 pre-grant publication 沒有對應欄位。目前已在 `wipo_ai_rules.json` 中標記為 `applicable: false` 並記錄原因。

---

## 3. CPC 重分類漂移

直接將 WIPO 2019 年公布的 CPC 代碼套用到後續年份，會對時間序列造成明顯偏差。

CPC 分類體系會定期改版。WIPO 的代碼清單建立於 2019 年，其中部分代碼後來被廢止或重新分類，因此舊代碼在較新的專利中可能直接降到 0。這種下降代表分類方式改變，不代表相關技術活動停止。

`02_check_cpc_drift.py` 的輸出如下，每一格表示該 filing year 至少包含一個該家族代碼的專利件數：

| 代碼家族                |   15 |   16 |   17 |   18 |    19 |    20 |   21 |   22 |       23 |  24 |
| ------------------- | ---: | ---: | ---: | ---: | ----: | ----: | ---: | ---: | -------: | --: |
| G06F17/30* 舊·資訊檢索   | 1262 | 1518 | 1585 | 1095 | **0** |     0 |    0 |    0 |        0 |   0 |
| G06F16/* 新          | 1618 | 1965 | 1924 | 1520 |  1447 |  1218 | 1119 | 1146 |     1214 | 850 |
| G06F17/27,28 舊·自然語言 |  189 |  259 |  299 |  230 |   235 | **0** |    0 |    0 |        0 |   0 |
| G06F40/* 新          |  548 |  744 |  664 |  540 |   563 |   432 |  496 |  555 |      695 | 558 |
| G06N99/005 舊·機器學習   |  131 |  231 |  345 |  206 | **0** |     0 |    0 |    0 |        0 |   0 |
| G06N20/* 新          |  181 |  306 |  559 |  620 |   751 |   723 |  744 |  689 |      693 | 567 |
| G06K9/* 舊·圖像辨識      |  371 |  420 |  549 |  634 |   763 |   747 |  687 |  191 |    **0** |   0 |
| G06V/* 新            |  425 |  510 |  634 |  634 |   784 |   850 |  850 |  885 |      973 | 804 |
| G06N7/005 舊·機率推論    |   46 |   95 |   96 |   54 |    65 |    63 |   38 |   34 |    **0** |   0 |
| G06N7/01 新          |   53 |   86 |  149 |  149 |   190 |   156 |  127 |  125 |      130 | 104 |
| **G06N3/* 未改編對照組**  |  113 |  199 |  465 |  572 |   941 |  1036 | 1092 | 1053 | **1168** | 957 |

作為對照，未經重分類的 `G06N3/*`（神經網路）在同期持續成長。由此可看出，部分舊 CPC 代碼的歸零主要來自分類制度變更，而不是相關 AI 技術活動下降。

### CPC 改版確認方式

主要使用 BigQuery 中不同年份的 CPC scheme snapshot 進行比對：

* `patents-public-data.cpc.definitions_201710`：舊代碼仍存在，`status = published`
* `patents-public-data.cpc.definition`：現行版本中舊代碼已不存在

另外使用兩種方式交叉確認：

* **`dateRevised` 與資料變化時間相符**

  * G06F16/00 → 2019-01-01
  * G06F40/00 → 2020-01-01
  * G06N7/01 → 2023-01-01
  * G06V10/00 → 2023-08-01
* **分類標題具有延續性**

  * G06N7/005：`Probabilistic networks`
  * G06N7/01：`Probabilistic graphical models, e.g. probabilistic networks`

需要注意的是，不同 CPC scheme snapshot 的 schema 並不完全一致。`definition_201903` 使用 `title_full`，而 `definition_202302` 與現行版本使用 `titleFull`，因此同一段 SQL 不一定能直接套用到所有版本。

---

## 4. 從舊 CPC 對應到現行 CPC

確認舊 CPC 已被廢止後，下一步是找出其對應的新分類。

這裡利用 USPTO 在分類改版後會對既有文件重新掛上現行 CPC 的特性，觀察舊碼與新碼在同一文件中的共現情況。

不過，共現本身不能直接視為「取代關係」。

第一版直接依共現率排序並取 top-N，最後約 77% 的專利被判定為 AI，明顯高於合理範圍。

`06_diagnose.py` 顯示主要問題來自 Block 1。當時命中數最高的 CPC 包含：

```text
G06F3/0482   5704
G06F3/04842  4394
G06F3/04883  3986
G06F3/011    3647
G06Q10/40    3473
G06F3/017    3453
```

這些大多屬於 GUI 或輸入介面分類，並不能直接作為 AI 判定依據。

### 共現與取代的差別

同一份專利同時出現兩個 CPC，大致可能有兩種原因：

* **分類取代**：例如原本屬於 G06K9/62 的文件，在 CPC 改版後重新掛上 G06F18/。
* **功能共存**：例如手勢辨識專利可能同時包含 G06K9/00355（手勢辨識）與 G06F3/017（手勢輸入介面）。兩個分類經常共現，但並不代表其中一個取代另一個。

因此，目前的做法分成兩個步驟：

1. 先根據官方 CPC 改編公告，以 `TRANSFER_TARGETS` 將候選範圍限制在確實接收該分類轉移的子類。
2. 再在這些候選分類中使用共現率判斷較可能的對應子群。

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

修正後，AI 專利占母體比例降至 25.6%，而 Block 1 命中數最高的 CPC 也回到合理的 AI 分類。

目前門檻設定如下：

* 推導階段：共現率 `>= 0.30`（`04_derive_concordance.py`）
* 實際採用階段：共現率 `>= 0.50`（`05_classify.py`）

375 個廢止碼中，有 349 個找到替代候選，最終納入 383 個相異替代碼。

完整推導結果與各候選共現率保存在 `out/concordance_report.txt`，可供後續人工複核。

---

## 5. 分類與去重

判定為 AI 專利後，再依 `matched_ai_cpc` 所屬家族指定 `ai_category`：

| 領域                      |    件數 |    佔比 |
| ----------------------- | ----: | ----: |
| neural_network          | 7,895 | 22.9% |
| computer_vision         | 7,347 | 21.3% |
| information_retrieval   | 6,716 | 19.5% |
| speech                  | 3,942 | 11.4% |
| machine_learning        | 3,180 |  9.2% |
| nlp                     | 2,426 |  7.0% |
| other                   | 1,303 |  3.8% |
| control_robotics        |   996 |  2.9% |
| probabilistic_reasoning |   593 |  1.7% |
| bioinformatics_health   |    43 |  0.1% |

去重鍵為 `(歸屬公司, application_number)`。同一申請案若有多次 publication，保留 `publication_number` 最小者，也就是最早公開的版本。

`ai_patents_detail.csv` 保留 title、abstract、完整 CPC 列表，以及 `ai_basis`。因此每一筆被判定為 AI 的專利都可以回頭檢查是由哪一個 Block 命中。

### with_subs 版逐年件數

以下依 filing year 統計：

| 公司        |  10 |  11 |  12 |  13 |  14 |  15 |  16 |  17 |  18 |   19 |   20 |   21 |   22 |   23 |  24* | 25* |
| --------- | --: | --: | --: | --: | --: | --: | --: | --: | --: | ---: | ---: | ---: | ---: | ---: | ---: | --: |
| Alphabet  | 105 | 266 | 401 | 641 | 528 | 550 | 765 | 836 | 726 | 1117 | 1219 | 1139 | 1186 | 1377 | 1222 | 560 |
| Amazon    |   1 |   3 |  14 |  45 | 126 | 109 | 114 | 145 | 122 |  169 |  224 |  161 |  182 |  200 |  166 |  73 |
| Apple     |  45 |  46 |  93 | 156 | 169 | 201 | 220 | 208 | 279 |  283 |  308 |  300 |  347 |  413 |  347 | 292 |
| Broadcom  |   1 |   2 |   0 |   1 |   3 |   8 |   1 |   0 |   3 |    3 |    0 |    5 |    9 |    6 |   15 |   6 |
| Meta      |   6 |   0 |  51 | 102 | 221 | 281 | 388 | 476 | 166 |  173 |  155 |  167 |  212 |  171 |  115 |  83 |
| Microsoft | 609 | 586 | 465 | 504 | 579 | 606 | 791 | 940 | 948 |  871 |  602 |  717 |  856 |  890 |  699 | 199 |
| Nvidia    |   1 |   0 |  12 |  25 |   6 |   7 |   4 |  23 |  64 |  170 |  242 |  318 |  352 |  445 |  499 | 261 |
| Tesla     |   0 |   0 |   0 |   0 |   0 |   0 |   0 |   4 |  10 |   13 |    6 |    9 |   14 |   37 |   15 |  13 |

`*` 2024–2025 年會受到約 18 個月的公開時滯影響，因此件數仍不完整。

作為基本合理性檢查，Nvidia 的 AI 專利從 2010 年 1 件增加至 2024 年 499 件；Broadcom 全期則維持在相對低的水準。Broadcom 的 AI 專利占比約 2.7%，其他七家公司則約為 10.9%–42.7%。

---

## 6. 對齊股票與論文

`07_align.py` 會輸出 `out/patent_stock_paper_annual.csv`，共 128 列，對應 8 家公司 × 16 年的平衡面板。

### 保留 AI 專利為 0 的公司年度

例如 Tesla 在 2010–2016 年仍有一般專利，每年約 25–74 件，但其中沒有被判定為 AI 的專利，因此這些年份的 AI 專利數應為 0，而不是缺值。

如果只從「至少有一件 AI 專利」的資料建立面板，這些公司年度會直接消失，後續分析便會將 0 錯誤處理為 missing value。

目前已補回 12 筆這類資料。

### 股票資料來源

股票資料不使用 `LEVEL4/panel_monthly.csv`。

該檔案中的月份是由「該月是否有論文」決定，並不是完整的股票月資料。例如 AVGO 全期只有 3 個月、TSLA 只有 1 個月，NVDA 部分年份也只有 7–10 個月。

因此，如果直接將該檔案的月報酬複利成年報酬，結果無法代表完整年度的股票表現。

目前改用 CRSP 原始月資料後，年報酬覆蓋率為 126/128：

| 來源                                         | 用途                        |
| ------------------------------------------ | ------------------------- |
| `stock_and_paper_count/group_A_stocks.csv` | 八家公司中的七家，2010–2025 各年月份完整 |
| `stock_and_paper_count/group_C_stocks.csv` | AVGO 資料來源                 |

唯二缺少股票報酬的資料為 Meta 2010–2011，因 Facebook 直到 2012 年才上市。

處理股票資料時另外需要注意三件事：

* **CRSP 分割月份可能有重複列**：使用 `(ticker, yyyymm)` 去重，例如 AAPL 2020-08、NVDA 2024-06。
* **Ticker 有歷史變更**：

  * Alphabet：GOOG → GOOGL（2014Q2）
  * Meta：FB → META（2022 年中）

  `group_A` 中新舊 ticker 的月份沒有重疊。例如 2014 年 Alphabet 為 GOOG 3 個月 + GOOGL 9 個月；2022 年 Meta 為 FB 5 個月 + META 7 個月，因此可以直接合併為連續序列。

  論文資料也需要進行相同的 ticker 合併，否則 Meta 2017–2021 的論文會遺失。

  如果同時讀取 `group_A` 與 `group_C` 則可能產生重複，因此 `group_C` 只取 AVGO。
* **超額報酬**定義為 buy-and-hold 差額：

  ```text
  個股年報酬 − S&P 500 年報酬
  ```

  不使用逐月超額報酬再複利的方式。

目前得到的年報酬包括：

* NVDA：2022 −50%、2023 +239%、2024 +171%
* META：2022 −64%、2023 +194%
* S&P 500：2022 −19.4%

可作為資料處理後的 sanity check。

### 專利與論文的交叉檢驗

|                 | 2020 | 2021 |     2022 | 2023 |
| --------------- | ---: | ---: | -------: | ---: |
| Microsoft 論文    |  543 |  429 |  **122** |   94 |
| Microsoft AI 專利 |  602 |  717 |  **856** |  890 |
| Alphabet 論文     |  896 |  654 |  **101** |  101 |
| Alphabet AI 專利  | 1219 | 1139 | **1186** | 1377 |
| Nvidia 論文       |   99 |   80 |   **24** |   26 |
| Nvidia AI 專利    |  242 |  318 |  **352** |  445 |

三家公司在 2022 年都出現明顯的論文數下降，但 AI 專利數並沒有同步下降，也沒有觀察到特別明顯的結構性跳升。

因此，目前資料不支持「企業在 2022 年後由發表論文轉向申請專利」的解釋。由於專利資料與 OpenAlex 獨立，這項結果比較支持論文資料在 2022 年後受到機構隸屬連結缺漏影響。

---

## 輸出檔案

| 檔案                                  | 內容                                                       |
| ----------------------------------- | -------------------------------------------------------- |
| `out/raw_publications.csv`          | 母體 144,826 件，含 title / abstract / CPC / assignee（135 MB） |
| `out/ai_patents_detail.csv`         | AI 專利明細，包含判定依據 `ai_basis`（70 MB）                         |
| `out/ai_patents_yearly.csv`         | 公司 × filing year × 版本的件數                                 |
| `out/patent_stock_paper_annual.csv` | 最終面板：專利 + 股票報酬 + 論文數                                     |
| `out/alignment_report.txt`          | 涵蓋率、AI 佔比、交叉檢驗表與已知限制                                     |
| `out/concordance_report.txt`        | CPC 對照推導過程與候選共現率                                         |
| `config/cpc_concordance.json`       | 廢止碼 → 現行碼對照表，包含來源與共現率                                    |

---

## 已知限制

1. **`filing_year >= 2024` 的專利數尚不完整。** 美國 pre-grant publication 通常在申請日起約 18 個月後公開，因此近兩年的申請案尚未全部進入資料。時間序列分析時應截斷這段期間，或明確標註資料不完整。`patent_truncated` 欄位已提供相應標記。

2. **論文資料自 2022 年起有系統性缺漏。** 目前判斷主要與 OpenAlex 機構隸屬連結有關。專利資料可以作為獨立對照，但 2022 年後的論文件數不宜直接視為完整觀測值。

3. **專利文字檢索僅包含 title + abstract。** WIPO 原始方法另外包含 claims 與 description，因此目前 AI 專利件數可能低估。

4. **C3 / C4 不適用。** WIPO 方法中的 FI 與 F-term 屬於 JPO 分類，美國 pre-grant publication 沒有相對應欄位。

5. **部分子公司只能取得交易宣布日。** `date_basis = announced` 的公司（例如 ZOOX）使用 announced date，而不是 completed date，因此歸屬時間可能存在數月誤差。

6. **目前範圍僅包含 Group A 八家公司。** 若要擴大到 `stock_and_paper_count` 中約 355 家公司的完整範圍，需要另外建立大規模 assignee 名稱對照表，這會是主要的人工處理成本。

---

## 資料來源

| 來源                                                                                                                                                                                                  | 用途                   | 授權            |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------- |
| [Google Patents Public Data](https://console.cloud.google.com/marketplace/product/google_patents_public_datasets/google-patents-public-data) (BigQuery)                                             | 專利母體、CPC scheme 版本快照 | CC BY 4.0     |
| [WIPO Technology Trends 2019: Artificial Intelligence — Data collection method and clustering scheme](https://www.wipo.int/documents/d/technology-trends/docs-en-techtrends_ai_methodology.pdf) §7c | AI 判定檢索式             | CC BY 3.0 IGO |
| CRSP（經 `stock_and_paper_count/`）                                                                                                                                                                    | 月股價報酬與 S&P 500       | 其他資料夾中         |
| OpenAlex / arXiv（經 `analysis/out/`）                                                                                                                                                                 | 公司論文數                | 其他資料夾中         |

WIPO 專利判定規則的原始檢索式保存在 `config/wipo_search_strings_verbatim.txt`，並附取得日期與頁碼。
