# 03_patents

**268 家上市公司** 2010–2025 年 AI 專利的抽取、判定與對齊管線。

公司母體取自母專案 `01_universe/out/` 的四個 group 檔全部公司（268 permco / 308 ticker），
不是只有核心科技股。管線先在 Group A 的 8 家跑通並逐一人工查證，再擴大到全體；那 8 家保留成
回歸測試的基準（見 §執行順序）。

建立目的是檢驗一個假說：**「2022 年後企業改發專利、不發論文」**。母專案觀察到公司論文數
在 2022 年集體暴跌約 75%，若企業真的把揭露管道從論文轉向專利，專利數應同期上升。專利資料
與 OpenAlex 完全獨立，可以當作獨立證人。

> **結論先講：假說的前提不成立。** 論文腰斬的同時 AI 專利穩定成長，沒有出現「此消彼長」。
> 這支持論文崩塌來自 OpenAlex 機構隸屬連結斷裂（資料瑕疵），而非企業行為改變。
> 見 [對齊結果](#6-對齊股票與論文)。

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

母體共 **838,405** 件 publication（**838,320** 個相異申請案），判定為 AI 者 **108,494** 件（12.9%，
含子公司版）；僅母公司本體為 **87,806** 件。

> AI 佔比從 8 家版的 25.6% 掉到 12.9% 是**預期內**的：母體從純科技股擴大到 268 家全產業
> （含能源、零售、製造、醫療），這些公司有大量與 AI 無關的專利。佔比下降反映母體組成改變，
> 不是判定規則變鬆或變嚴。

---

## 執行順序

九支腳本照編號跑就是完整管線。分成兩段：**建名單**（01–04）決定「要撈哪些 assignee
名稱」，**跑資料**（05–09）才真的去 BigQuery 抓件數。兩段的先後不能顛倒：05 的 SQL 是拿
alias 檔組出 `IN` 清單的，名單沒先蓋好就抓，漏掉的名稱在下游永遠救不回來（這個順序踩過坑，
見下）。

```bash
cd 03_patents

# ── 第一段：建立公司名冊與 assignee 對照 ──
.venv/bin/python scripts/01_build_roster.py --yes   # CRSP 四個 group 檔 -> 268 家名冊 + 下載 assignee 字典
.venv/bin/python scripts/02_match_names.py          # 三層比對 + 產生 T3 待審清單
.venv/bin/python scripts/03_adjudicate.py           # 人工裁決 -> assignee_manual.csv（逐筆回驗字典）
.venv/bin/python scripts/04_build_alias.py          # 組裝 company_alias / subsidiary_alias_auto

# ── 第二段：抓取、判定、對齊 ──
.venv/bin/python scripts/05_fetch.py --yes          # 送出查詢，需 gcloud 認證，掃 251 GB
.venv/bin/python scripts/05_fetch.py --download     # 分頁取回結果（見下）
.venv/bin/python scripts/06_concordance.py          # CPC 改編診斷 + 推導新舊對照表
.venv/bin/python scripts/07_classify.py             # 套用 WIPO AI 規則 -> ai_patents_*.csv
.venv/bin/python scripts/08_align.py                # 對齊股票與論文 -> 平衡面板
.venv/bin/python scripts/09_verify.py               # 事後檢查，新版不得低於舊版
```

WIPO 規則檔（`config/wipo_ai_rules.json`）由 `scripts/common/wipo.py` 直接執行產生，
只在修改 WIPO 檢索式原文時才需要重跑：

```bash
.venv/bin/python scripts/common/wipo.py
```

### 腳本一覽

| 腳本 | 做什麼 | 主要輸出 |
|---|---|---|
| `01_build_roster.py` | 左表：CRSP 268 家公司名冊（含歷史更名）；右表：BigQuery assignee 名稱字典 | `firm_roster.csv`、`assignee_dict.csv` |
| `02_match_names.py` | 名稱正規化、個人發明者過濾、三層比對、替 T3 產生裁決建議 | `assignee_match_auto.csv`、`assignee_match_review.csv` |
| `03_adjudicate.py` | 人工裁決（零命中公司 + T3 大量候選），每筆回頭對照字典驗證 | `assignee_manual.csv` |
| `04_build_alias.py` | 合併自動比對與人工裁決，處理併購換手的生效日切分 | `company_alias.csv`、`subsidiary_alias_auto.csv` |
| `05_fetch.py` | 送出 BigQuery 查詢（`--yes`）、分頁取回結果（`--download`） | `raw_publications.csv` |
| `06_concordance.py` | CPC 改編逐年診斷 + 推導廢止碼的現行替代碼 | `cpc_concordance.json`、`concordance_report.txt` |
| `07_classify.py` | 套用 WIPO AI 判定規則、去重、歸屬公司 | `ai_patents_detail.csv`、`ai_patents_yearly.csv` |
| `08_align.py` | 與 CRSP 股價、OpenAlex 論文對齊成平衡面板 | `patent_stock_paper_annual.csv` |
| `09_verify.py` | 判定命中結構診斷 + 8 家回歸比對（有下降則 exit 1） | 僅印出，不寫檔 |
| `common/firmkeys.py` | permco / ticker 收斂的唯一真相來源 | （模組） |
| `common/wipo.py` | WIPO AI 判定規則：CPC 比對器 + Orbit 語法轉譯 + K1/K2 關鍵詞 | `wipo_ai_rules.json` |

> ⚠️ **改了 alias 就必須重跑 05。** `05_fetch.py` 在抓取當下才把 alias 展開成 SQL 的
> `IN` 清單，所以 `out/raw_publications.csv` 只含「當時名單裡有的名稱」。後來才補進名單的
> 公司（例如 `AMAZON TECH INC`，5,844 件）在原始檔裡根本不存在，07/08 再怎麼跑也生不
> 出來——症狀是某家大公司莫名其妙只有個位數專利。這個坑實際發生過。

> 🔴 **`bq query` 在這個資料量會卡死，所以 05 拆成 `--yes` 與 `--download` 兩步。** 查詢
> 本身在伺服器端只花 7 秒（job 紀錄可查），但 `bq` CLI 把 83 萬列 / 0.8 GB 結果透過 REST
> API 拉回本機時會**停住不動**——0% CPU、RSS 十幾 MB、放二十分鐘也不前進。更糟的是 `bq`
> 會把輸出緩衝到最後才寫檔，過程中檔案一直是 0 bytes，**看起來和當掉完全一樣**。實測分頁
> 2,000 列 6 秒正常、50,000 列直接卡死。
>
> `--yes` 因此只負責把 job 送出去（結果留在 BigQuery 暫存表），`--download` 再用
> `bq head --start_row` 小批次分頁取回。暫存表保留 24 小時，所以 `--download` 可以反覆重跑
> 而**不必重掃 251 GB**；它會自己去找最近一個欄位相符的成功 job。三道防線：每頁單獨落檔
> 可續傳、逐頁用 CSV parser 驗列數（abstract 內含換行，數行數會得到錯的數字）、合併後
> 總列數必須等於暫存表的 `numRows` 才寫出正式檔。
>
> 分頁暫存放在 `out/_parts/`（420 個檔、約 0.8 GB）。它是**續傳用的**，中途失敗再跑一次
> 會從這裡接續，所以不要在管線跑完前刪。確認 07/08 都跑通之後就可以整個刪掉釋出磁碟
> （已列入 `.gitignore`）。

`09_verify.py` 的第二段是這條管線的安全網：擴大版換掉了整套 alias，而原本 8 家是逐一人工
查證過的，**新版件數只該增加、不該減少**。任何下降都代表新名單漏了舊名單有的東西，腳本會
以 exit code 1 擋下。它曾抓出 4 家公司因為丟失拼錯變體而少算（見 §1）。第一段則是唯讀的
命中結構診斷（各 Block 貢獻、Block3 的噪音來源），是下面兩個關鍵決策的證據來源，建議在
改動規則後重跑。

---

## 1. 公司名稱對照

專利資料中的 `assignee` 為自由文字欄位，同一家公司可能有多種名稱、標點或拼寫方式。這裡的名稱對照表都是根據 BigQuery 中實際出現的字串建立，沒有額外加入未觀察到的名稱。

### 1.1 公司名冊以 permco 為鍵，不是 ticker

母體是 `01_universe/out/` 四個 group 檔的全部公司：**268 家（permco）、308 個 ticker**。
兩個數字不同，是因為 ticker 根本不是公司的識別碼：

- **一家公司同時有多個股票代號**（Alphabet 的 GOOG/GOOGL、Moog A/B、Shell A/B、Zillow Z/ZG）
- **一家公司會換代號**（FB → META、GOOG → GOOGL）

CRSP 的 `permco`（公司）與 `permno`（個別證券）分得很清楚，**`permco` 是唯一穩定的公司層級
鍵**。`scripts/common/firmkeys.py` 是全管線唯一的收斂點，任何地方拿到 ticker 都先過 `canon()` 換回
標準公司，載入 alias 時也一樣。

> 🔴 **不收斂會把一家公司劈成兩家。** 舊版用 ticker 當鍵，結果 Alphabet 同時以
> `Alphabet`/GOOGL 與 `ALPHABET INC`/GOOGL 兩個標籤存在，Meta 則被 FB 與 META 拆開。
> 修正後三家實測合併：ALPHABET INC 12,636 件（= 10,717 + 1,920 − 1 跨標籤重複）、
> FACEBOOK INC 2,765（= 2,731 + 34）、NVIDIA 2,427（= 2,354 + 73）。

多股別在**報酬**與**論文**上要用相反的聚合方式，這點在 §6 另外說明。

### 1.2 三層比對 + 人工裁決

268 家公司對上 BigQuery 的 assignee 字典，`02_match_names.py` 依可信度分三層：

| Tier | 判準 | 處置 |
|---|---|---|
| `T1_EXACT` | 正規化後與公司名完全相同 | 自動採用，歸**母公司** |
| `T2_PREFIX` | 以公司名為完整前綴、後面多出詞（`QUALCOMM ATHEROS`） | 自動採用，歸**子公司** |
| `T3_REVIEW` | 只有第一個詞相同 | **一律人工裁決**，預設不採用 |

T3 是偽陽性溫床，因為「第一個詞相同」太便宜：`GEN DYNAMICS` vs `GEN ELECTRIC` 毫不相干，
`AMAZON COM` vs `AMAZON TECH` 卻是同一家。差別不在字串距離，而在**第一個詞是不是該公司獨有
的品牌詞**。`02_match_names.py` 用兩個資料驅動的訊號量化這件事，不憑記憶：

- `head_firms`：名冊裡有幾家公司的核心名以這個詞開頭。`GEN` → 5 家（共用詞，品牌在第二個
  詞，必須整串前綴相同）；`AMAZON` → 1 家（獨有品牌詞）。
- `head_orgs`：字典裡有幾個不同核心名以這個詞開頭。數字大代表被無數不相干機構共用
  （`UNIV`、`NAT`、`KOREA`…）。

「品牌詞 + 功能詞」（`TECH`、`RES`、`IP`、`LICENSING`…）幾乎一定是同集團持有實體，建議
INCLUDE；「品牌詞 + 另一個實詞」可能是另一家獨立公司（`TOYOTA JIDOSHOKKI` 是另外上市的豐田
自動織機），一律丟回人工。**腳本只給建議與理由，不下最終判斷。**

T3 共 4,854 筆 / 360,516 件。實際裁決件數 ≥100 的 **266 筆**（已涵蓋待審量的 87%），結果
45 INCLUDE、221 EXCLUDE。排除理由分四類並逐筆記錄：A 同名不同公司、B 分拆後另立門戶、
C 另行上市的集團關係企業、D 合資公司。

> **裁決不能有幻覺。** `03_adjudicate.py` 會把每一筆人工裁決**回頭對照 BigQuery 字典**：
> INCLUDE 的名稱必須真的存在於字典，EXCLUDE 的也必須存在（排除一個不存在的名稱，代表記錯
> 了）。任何對不上就 exit 1 且不寫檔。實測擋下過一次我自己從截斷的終端機輸出複製錯的字串
> （`...AMERICA LL` 少了結尾的 `C`）。目前 84 INCLUDE、247 EXCLUDE 全數通過。

### 1.3 拼錯的變體只能靠人工表

最終 alias **1,595 列**，來源分布 `T2_PREFIX 1036 / T1_EXACT 294 / CURATED8 182 / MANUAL 83`，
涵蓋 258/268 家，其餘 10 家經查證確實沒有美國 pre-grant 專利。

`CURATED8` 是原本 8 家的人工表，**不能因為有了自動比對就丟掉**。它收錄大量 OCR／打字錯誤的
變體——`MICROSOFT TECH LICESNING LLC`、`GOOGLE ELLC`、`APPLE LNC`、`NVIDIA CORPRATION`、
`AMAZON TECHOLOGEIS INC`，光 Microsoft Technology Licensing 就有約 45 種拼法。自動比對是
「以公司名開頭」，拼錯的一個都接不到。移除後回歸測試立刻抓到 GOOGL −6、NVDA −2、AAPL −1、
TSLA −1。

它同時也決定 tier：這些是母公司**本體**的持有實體（`AMAZON TECH INC`、
`MICROSOFT TECH LICENSING LLC`），自動比對會因為多一個詞判成 T2_PREFIX 子公司，害
parent_only 版暴跌（實測 MSFT −75%、AMZN −99.9%）。

### 1.4 檔案

- `config/company_alias.csv` —— 母公司層級（T1_EXACT + MANUAL + CURATED8）。
- `config/subsidiary_alias.csv`（50 列）—— 原 8 家人工子公司表，附 `effective_from` /
  `effective_to` / `date_basis` / `source_url`，**優先序最高**。
- `config/subsidiary_alias_auto.csv` —— 自動比對掃到的 T2_PREFIX 子公司。
- `config/assignee_manual.csv` —— 人工裁決總表，由 `03_adjudicate.py` 單一產出。

> 自動比對的列沒有生效日（等同「全期間持有」）。若與人工列並存，併購**前**的專利會從沒有
> 日期的那一列漏進來——`GOOGLE TECHNOLOGY HOLDINGS`（Motorola 來源）會被回溯到 2010 年，而
> 人工表正確地從收購日才起算。所以人工表存在時，自動列一律讓位。

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

**這點很容易搞錯。** Block 2 的 K1 是「人工智慧」「神經網路」「深度學習」這類**本身就足以
判定**的詞，不需要再要求 CPC 同時命中。若寫成 `CPC AND 關鍵詞`，Block 2 會被整個吃掉。

各 Block 命中的**相異申請案數**（268 家擴大版，母體 838,320 件；Block 間可重疊，數字由
`ai_patents_detail.csv` 的 `ai_basis` 欄反推，亦可用 `09_verify.py` 重算）：

| Block | 命中 | 佔母體 | 其中「只有這條抓到」 |
|---|---|---|---|
| Block1（CPC） | 104,516 | 12.5% | 77,106 |
| Block2（K1 關鍵詞） | 26,597 | 3.2% | **3,242** |
| Block3（C1/C2 + K2） | 7,150 | 0.9% | **658** |
| **聯集（實際採用）** | **108,494** | **12.9%** | — |

最右欄是「拿掉這條就會憑空消失」的件數，也就是**寫成 AND 的代價**：Block 2 獨有 3,242 件、
Block 3 獨有 658 件。三條可重疊，**不可相加**。

### Orbit 檢索語法轉換

WIPO 使用 Questel Orbit 的檢索語法，因此需要先轉換成 Python 正規表示式。相關實作位於 `scripts/common/wipo.py` §2。

| 運算子     | 意義             | 對應 regex             |
| ------- | -------------- | -------------------- |
| `+`     | 任意長度截斷         | `\w*`                |
| `?`     | 0 或 1 個字元      | `\w?`                |
| `#`     | 恰好 1 個字元       | `\w`                 |
| `nW`    | 有序鄰近，中間至多 n 個詞 | `(?:\W+\w+){0,n}\W+` |
| `nD`    | 無序鄰近           | 同上，但另外產生反向排列         |
| `_` `-` | 詞內連接           | `[-_\s]`             |

`scripts/common/wipo.py` §3 將 K1（45 條）與 K2（18 條）逐條編碼，每一條規則旁都保留對應的 WIPO 原文註解，方便人工檢查。

### 規則限制

目前有兩項已知限制：

1. **檢索欄位較 WIPO 原始方法少。** WIPO 搜尋 title、abstract、claims 與 description，目前資料只使用 title + abstract，因此 AI 專利數會有系統性低估。只要低估程度沒有在特定年份突然改變，對時間趨勢的影響相對有限。
2. **C3（FI）與 C4（F-term）無法使用。** 兩者屬於日本特許廳的分類系統，美國 pre-grant publication 沒有對應欄位。目前已在 `wipo_ai_rules.json` 中標記為 `applicable: false` 並記錄原因。

---

## 3. CPC 重分類漂移

直接將 WIPO 2019 年公布的 CPC 代碼套用到後續年份，會對時間序列造成明顯偏差。

CPC 分類體系會定期改版。WIPO 的代碼清單建立於 2019 年，其中部分代碼後來被廢止或重新分類，因此舊代碼在較新的專利中可能直接降到 0。這種下降代表分類方式改變，不代表相關技術活動停止。

`06_concordance.py` §1 的輸出如下，每一格表示該 filing year 至少包含一個該家族代碼的專利件數：

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

`09_verify.py` §1 顯示主要問題來自 Block 1。當時命中數最高的 CPC 包含：

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

* 推導階段：共現率 `>= 0.30`（`06_concordance.py`）
* 實際採用階段：共現率 `>= 0.50`（`07_classify.py`）

375 個廢止碼中，有 349 個找到替代候選，最終納入 383 個相異替代碼。

完整推導結果與各候選共現率保存在 `out/concordance_report.txt`，可供後續人工複核。

---

## 5. 分類與去重

判定為 AI 專利後，再依 `matched_ai_cpc` 所屬家族指定 `ai_category`：

| 領域 | 件數 | 佔比 |
|---|---|---|
| computer_vision | 29,419 | 27.1% |
| neural_network | 22,368 | 20.6% |
| information_retrieval | 16,030 | 14.8% |
| machine_learning | 10,862 | 10.0% |
| control_robotics | 7,572 | 7.0% |
| other | 7,196 | 6.6% |
| speech | 7,149 | 6.6% |
| nlp | 5,399 | 5.0% |
| probabilistic_reasoning | 2,094 | 1.9% |
| bioinformatics_health | 405 | 0.4% |

（with_subs 版 108,494 個相異申請案。`control_robotics` 佔比從 8 家版的 2.9% 升到 7.0%，
是擴大母體後汽車與工業製造業者進來的結果，符合預期。）

去重鍵為 `(歸屬公司, application_number)`，保留 `publication_number` 最小者（最早公開）。
**「歸屬公司」是 permco 不是 ticker**——用 ticker 會讓同一家公司的兩個標籤各自去重，
同一件專利被算兩次（見 §1.1）。

`ai_patents_detail.csv` 保留 title、abstract、完整 CPC 列表，以及 `ai_basis`。因此每一筆被判定為 AI 的專利都可以回頭檢查是由哪一個 Block 命中。

### 原 8 家的 with_subs 版逐年件數（依 filing year）

這張表是**回歸測試的基準**：擴大版重跑後，`09_verify.py` 驗證這 8 家的每一個
公司-年度數字都與下表完全一致（16 年 × 8 家 × 2 版本，零下降、零上升）。

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

`08_align.py` 輸出 `out/patent_stock_paper_annual.csv`，**4,288 列 = 268 家 × 16 年的平衡面板**。

欄位覆蓋率（4,288 列）：專利與論文 100%（缺值一律補 0，見下），報酬三欄 83.3%
（缺的是尚未上市或已下市的公司-年度，屬真實缺值）。`months_in_year` 有 126 個
公司-年度不足 12（上市/下市當年），**迴歸時建議只用 `months_in_year == 12` 的列**。

### 保留 AI 專利為 0 的公司年度

例如 Tesla 在 2010–2016 年仍有一般專利，每年約 25–74 件，但其中沒有被判定為 AI 的專利，因此這些年份的 AI 專利數應為 0，而不是缺值。

如果只從「至少有一件 AI 專利」的資料建立面板，這些公司年度會直接消失，後續分析便會將 0 錯誤處理為 missing value。

目前已補回 12 筆這類資料。

### 股票資料來源

股票資料不使用第一代的 `LEVEL4/panel_monthly.csv`（該檔已隨第一代移出 main，只保留在 `archive/v1-level1-4` 分支）。

該檔案中的月份是由「該月是否有論文」決定，並不是完整的股票月資料。例如 AVGO 全期只有 3 個月、TSLA 只有 1 個月，NVDA 部分年份也只有 7–10 個月。

因此，如果直接將該檔案的月報酬複利成年報酬，結果無法代表完整年度的股票表現。

### ⚠️ 四個 group 檔要全部讀，而且要以 permco 聚合

初版報酬覆蓋率只有 **6.6%**，兩個原因疊在一起：

1. `STOCK_FILES` 只列了 4 個 group 檔中的 2 個，另外兩個檔的公司全部對不到。
2. 用了一張手寫的 `TICKER_HISTORY` 對照表來處理換代號，而它與 CRSP 名冊不一致——名冊給
   Meta 的主 ticker 是 **FB**（FB 有約 10 年月份，META 只有 3.5 年），手寫表卻寫 META。

兩者都靠「改用 permco 當鍵、四個檔全讀」一次解決，手寫的 `TICKER_HISTORY` 整張刪掉。
覆蓋率 6.6% → **83.3%**。剩下的缺值是真實的：公司尚未上市或已下市的年度。

**同一家公司在同一個月可能有多個 permno（多股別），報酬與論文要用相反的聚合方式：**

| 欄位 | 聚合方式 | 理由 |
|---|---|---|
| 報酬 | 取 **`mthcap` 最大的那個 permno** | 各股別的報酬**不能相加**——加總不對應任何可實際持有的部位。取主要股別才是一個真實可買的標的 |
| 論文 | **加總所有 permno** | CRSP 只把 `n_papers` 掛在其中一個 permno 上，不加總會整段遺失 |

這個區別很容易寫反。寫反的症狀是報酬變成兩倍上下的荒謬數字，或論文數莫名腰斬。

其餘處理細節：

- **CRSP 分割月份有重複列**，以 `(permno, yyyymm)` 去重（AAPL 2020-08、NVDA 2024-06）
- **超額報酬定義**為 buy-and-hold 差額（個股年報酬 − S&P500 年報酬），而非逐月超額報酬的
  複利——後者沒有可實際持有的投資組合與之對應

驗證（Meta，端到端）：2012 年月份數 = 8（5 月 IPO，正確）、2022 −64.2%、2023 +194%、
論文 2022 從 269 掉到 23。均與實際相符。

驗證：NVDA 2023 +239%、2024 +171%、2022 −50%；META 2022 −64%、2023 +194%；S&P 2022 −19.4%
—— 均與市場實際數字相符。

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

| 檔案 | 內容 | 大小 | 版控 |
|---|---|---|---|
| `out/raw_publications.csv` | 母體 838,405 件，含 title/abstract/CPC/assignee | 804 MB | ignore |
| `out/ai_patents_detail.csv` | 判定為 AI 的專利明細，含判定依據 `ai_basis` | 219 MB | LFS |
| `out/ai_patents_detail_8firms.csv` | 原 8 家版明細，`09_verify.py` 的回歸基準 | 73 MB | LFS |
| `out/assignee_dict.csv` | BigQuery assignee 名稱字典，人工裁決的查證依據 | 11 MB | LFS |
| `out/ai_patents_yearly.csv` | 公司 × filing year × 版本的件數 | 167 KB | git |
| `out/patent_stock_paper_annual.csv` | **最終面板**：專利 + 股票報酬 + 論文數 | 314 KB | git |
| `out/alignment_report.txt` | 涵蓋率、AI 佔比、交叉檢驗表、已知限制 | — | git |
| `out/concordance_report.txt` | CPC 對照推導的完整過程，供人工複核 | — | git |
| `config/cpc_concordance.json` | 廢止碼 → 現行碼對照表，含來源與共現率 | — | git |

### 版控與儲存

超過 5 MB 的輸出走 **git LFS**（規則在 repo 根的 `.gitattributes`，與 `01_universe/`
沿用同一套）。`ai_patents_detail.csv` 219 MB 本身就超過 GitHub 單檔 100 MB 的硬上限，非走
不可；另外兩個雖然沒破上限，但這種檔每改一次就在物件庫留一份完整副本，也一併納入。

`out/raw_publications.csv`（804 MB）**不入版控**，它是可重新產生的中間檔。但重跑代價不低：
BigQuery 的結果暫存表只留 24 小時，過期後 01b 找不到 job，就得回頭跑 01 重掃 251 GB。
換機器或清磁碟前先想清楚。

`out/*.log`、`*.bak`、`out/_parts/` 一律 ignore——是執行紀錄和暫存，不是資料。

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
6. **T3_REVIEW 只裁決到件數 ≥100 者。** 4,854 筆待審中裁決了 266 筆，涵蓋待審量的 87%；
   剩下 13%（約 4.7 萬件，散在 4,588 個名稱）一律**未採用**。方向是保守的——只會少算、
   不會多算，且漏掉的都是小量名稱。若日後要補，降低 `02_match_names.py` 的 `MIN_PUB` 即可。
7. **非美國公司的專利會被系統性低估。** 母體限定美國 pre-grant publication，只在美國申請的
   外國公司（尤其日韓台歐廠商）本國專利不計入。跨國比較時要留意。
8. **公司層級歸屬到 permco 為止，不處理集團關係企業。** 另行上市的關係企業（如豐田自動織機
   之於 Toyota）視為獨立公司並排除，這是刻意的——它們在 CRSP 裡也是獨立的 permco。

---

## 資料來源

| 來源                                                                                                                                                                                                  | 用途                   | 授權            |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------- |
| [Google Patents Public Data](https://console.cloud.google.com/marketplace/product/google_patents_public_datasets/google-patents-public-data) (BigQuery)                                             | 專利母體、CPC scheme 版本快照 | CC BY 4.0     |
| [WIPO Technology Trends 2019: Artificial Intelligence — Data collection method and clustering scheme](https://www.wipo.int/documents/d/technology-trends/docs-en-techtrends_ai_methodology.pdf) §7c | AI 判定檢索式             | CC BY 3.0 IGO |
| CRSP（經 `01_universe/out/`）                                                                                                                                                                    | 月股價報酬與 S&P 500       | 其他資料夾中         |
| OpenAlex / arXiv（經 `02_returns/out/`）                                                                                                                                                                 | 公司論文數                | 其他資料夾中         |

WIPO 專利判定規則的原始檢索式保存在 `config/wipo_search_strings_verbatim.txt`，並附取得日期與頁碼。
