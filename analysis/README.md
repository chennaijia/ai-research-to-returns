#  Is the AI-research effect specific to technology stocks?

This folder contains a self-contained re-analysis built on the CRSP full-market monthly stock file. It exists to answer a question that Levels 1–4 cannot: **not whether AI research output moves tech stocks, but whether it moves them more than it moves everything else.**

## Why this level was added

Levels 1–3 regress a mega-cap technology portfolio on AI paper growth. The problem is that this portfolio correlates 0.91 with the overall market. If AI paper growth happened to be high in months when the whole market rose, a positive coefficient would appear even with no tech-specific channel at all. Testing a treatment group without a control group cannot separate those two stories.

This section therefore splits the entire U.S. stock market into a technology group and a non-technology group and makes the **spread between them** the dependent variable. Since both portfolios are exposed to the same macro shocks, differencing them removes the common market component; whatever survives is specific to the technology sector.

Two questions are reported separately throughout, because they have different answers:

| | Question | Dependent variable |
|---|---|---|
| **Q1** | Does AI research output move technology stocks? | Value-weighted tech return |
| **Q2** | Is that effect *specific* to technology stocks? | Spread (tech − non-tech) |

**Q2 is the one that matters for this project's framing.** A significant Q1 alone is not a finding, because it is consistent with a market-wide effect.

A second motivation was data quality. The `is_ict` flag shipped with `stock_and_paper_count/` misclassifies firms in two independent ways (see below), which put Alphabet, Meta, and Amazon in the *non*-technology group. Under that flag the non-tech group held more AI papers than the tech group, which would invert the meaning of any spread built from it.

## Data and how to run

Requires, relative to the repository root:

- `stock_and_paper_count/crsp_all_classified_with_papers_detailed.csv` — CRSP monthly panel (~426 MB, stored via Git LFS): returns, market cap, NAICS codes, and merged company paper counts for 18,945 firms
- `LEVEL4/ai_monthly.csv` — monthly arXiv AI paper counts and citations

### Running the scripts in RStudio

**1. Install the packages.** In the RStudio console:

```r
install.packages(c("data.table", "sandwich", "lmtest"))
```

**2. Set the working directory to the repository root — not to `analysis/`.** Every path in these scripts is written relative to the repository root, so `analysis/00_common.R` will not be found if RStudio is pointed one level deeper. Check where you are and fix it if needed:

```r
getwd()                                    # should end in .../ai-research-to-returns
setwd("~/path/to/ai-research-to-returns")  # or Session ▸ Set Working Directory ▸ Choose Directory
```

The most reliable option is to open the repository as an RStudio Project (File ▸ New Project ▸ Existing Directory), which sets the working directory to the repository root every time the project is opened.

**3. Run the four scripts in order.** From the console:

```r
source("analysis/01_tech_classification.R", echo = TRUE)
source("analysis/02_build_panel.R",         echo = TRUE)
source("analysis/03_main_tests.R",          echo = TRUE)
source("analysis/04_structural_change.R",   echo = TRUE)
```

The order matters: 01 writes the classification that 02 reads, and 02 writes the panel that 03 and 04 read. Once 02 has been run, 03 and 04 can be re-run freely without touching the large CRSP file again.

### Things worth knowing before the first run

- **Encoding must be UTF-8.** The scripts and their diagnostic output are commented in Chinese. If the console shows garbled characters, set Tools ▸ Global Options ▸ Code ▸ Saving ▸ Default text encoding to `UTF-8`. This mostly affects Windows, where the default is often not UTF-8.
- **Script 02 reads a 426 MB file** and will hold several GB in memory while building the panel. It calls `rm()` and `gc()` when finished with the raw data, but if RStudio's Environment pane still shows large objects from a previous run, clear them first (the broom icon, or `rm(list = ls())`) so the two runs don't coexist in memory.
- **Script 04 takes a few minutes.** It bootstraps 2,000 replications of a full breakpoint scan. The others finish quickly. RStudio's console shows a stop-sign icon while it works; this is normal, not a hang.
- **Figures are written to `.png` files, not to the Plots pane.** The scripts open a `png()` device explicitly, so nothing appears in RStudio's Plots pane. Look in `analysis/out/`, or use the Files pane to click the images open.
- **If a script stops with an error partway, just re-run it from the top.** Because an RStudio session persists between runs, an interrupted script leaves its log file open; `start_log()` detects and closes a stale connection on the next run, so this is handled. If you have interrupted many runs and see `all connections are in use`, run `closeAllConnections()` once.
- **Every script mirrors its console output into a diagnostics file** under `analysis/out/`, so every number quoted below can be traced back to a logged run. Reading `analysis/out/main_tests.txt` is often easier than scrolling back through the console.

## Files

### `00_common.R`
Shared setup: file paths, a logger that writes to both console and a diagnostics file, and a `hac()` wrapper that fits an OLS regression and returns Newey-West HAC standard errors (lag 4). Sourced by every other script, so the estimator is defined once rather than re-implemented per test.

### `01_tech_classification.R`
Builds the firm-level technology indicator from CRSP NAICS codes and writes `tech_classification.csv` (one row per firm).

The classification is enumerated at the **6-digit** level and spans the NAICS 2007 / 2012 / 2017 / 2022 vintages simultaneously. Two properties of the data force this:

- **Vintage drift.** CRSP re-codes firms as NAICS is revised. Software Publishers moved from 511210 to 513210 in the 2022 revision, so a rule written against a single vintage silently drops software firms from the technology sector starting in 2023. Of the 686 firms that are ICT in 2022 and still listed in 2025, the shipped single-vintage flag classifies 246 of them (35.9%) as non-technology by 2025, purely because of the code revision.
- **Reused codes.** The same code can mean different things across vintages. `5161` was "Internet Publishing and Broadcasting" under NAICS 2007 but is "Radio and Television Broadcasting Stations" under NAICS 2022. A prefix rule would classify television stations as technology firms, which is why codes are listed individually rather than matched by prefix.

Two further details matter. CRSP encodes a missing NAICS as the integer `0`, not `NA`, so `is.na()` catches nothing — 1.63% of rows and 350 firms that are `0` throughout. Delisted firms are almost always `0` in their final months, so any "use the last observed code" rule classifies every delisted firm as non-technology unless zeros are excluded first. And because a firm's industry code changes over time, the firm-level label is assigned by majority vote across its valid months rather than by any single month: among the 229 firms that publish AI papers, 23.1% flip at least once under the shipped flag and 16.6% still flip under the corrected 6-digit rule.

Output: 1,604 technology firms, 16,991 non-technology firms, 350 unclassifiable. Three alternative collapse rules (majority vote, last valid code, ever-ICT) are computed and compared in the diagnostics file; they disagree on only 356 firms, so downstream results are not sensitive to the choice.

### `02_build_panel.R`
The only script that reads the 426 MB CRSP file. Produces the monthly analysis dataset.

- **Value weights use the *prior* month's market cap.** Month-end market cap already contains that month's return, so weighting by it would hand the best-performing stocks a mechanically higher weight and bias portfolio returns upward.
- **Lags are taken by explicit month index, not by row shift.** Firms have gaps in CRSP coverage, so `shift()` returns "the previous observation" rather than "the previous month." The script builds an integer month index and merges on `(permno, month − 1)`.
- **Value weighting is the main specification.** The non-tech group has 16,991 firms with a median market cap of $174M and monthly returns reaching +3,900%; an equal-weighted series is dominated by a handful of microcaps. Equal-weighted series are still computed for comparison.

It also builds the independent variable in four deseasonalized forms (raw, month-demeaned, year-over-year, STL) plus a no-lookahead rolling version, so that script 03 can compare them without recomputation.

Outputs: `analysis_monthly.csv` (one row per month), `size_spreads.csv` (spread within each size quintile), `company_papers_annual.csv`.

### `03_main_tests.R`
The main tests. Q1 and Q2 at lags 0–3 with Benjamini-Hochberg correction, the non-tech group as a control, a robustness table, a size-quintile decomposition, and a comparison of the deseasonalization methods.

### `04_structural_change.R`
Structural change, organized around a distinction that turns out to drive the result:

- **(A) Searched breakpoints.** When the break date is chosen after looking at the data, the search itself must be priced in. The script computes a Quandt-Andrews supF statistic and obtains its critical value by bootstrap — resampling residuals under the no-break null and re-running the *entire* scan 2,000 times.
- **(B) Pre-specified breakpoints.** A hypothesis stated before seeing the data tests only a couple of dates and needs no such penalty.

It also checks whether the premise behind the pre-specified hypothesis actually holds in the data, and runs nine fragility checks on the post-2022 subsample.

## Choice of independent variable

**Paper counts, not citations.** In this dataset citation counts are a proxy for paper *age*, not impact: papers from 2017 average 54.3 citations while papers from 2025 average 0.39, declining monotonically. Regressing returns on citation growth would manufacture a spurious downward trend. Citations are tested only on the 2017–2022 subsample, where every paper has had at least three years to accumulate them, and even there the sample is too short to conclude anything.

**Log first differences.** Monthly AI papers grew from an average of 1,322 in 2017 to 8,971 in 2025. Regressing in levels on a similarly trending return index is the textbook spurious regression.

**Deseasonalize X, not Y.** Conference submission deadlines give AI paper growth strong monthly seasonality; stock returns have none:

| Series | ANOVA F | p | Variance explained by calendar month |
|---|---:|---:|---:|
| X: AI paper growth | 9.91 | 9.6e-12 | 53.4% |
| Y1: tech return | 1.23 | 0.279 | 12.3% |
| Y2: spread | 0.88 | 0.564 | 9.1% |

Because the seasonality is entirely on the X side, the correction is to demean X by calendar month. Adding eleven month dummies to the regression would spend degrees of freedom removing a seasonality that Y does not have.

This is not a cosmetic step. Untreated, Q1's coefficient is +0.0023 (p = 0.926); month-demeaned, it is +0.0701 (p = 0.036). Seasonal noise accounts for 53.4% of the variance in X and swamps the signal completely.

---

## Results

Sample: 2017-01 to 2025-12, 108 months (107 after differencing), 761 technology and 7,258 non-technology firms per month on average.

### Portfolio construction checks

| Series | Mean monthly | Annualized | SD |
|---|---:|---:|---:|
| Tech (value-weighted) | 1.584% | 20.8% | 5.06% |
| Non-tech (value-weighted) | 0.956% | 12.1% | 4.14% |
| **Spread** | **0.628%** | **7.8%** | 2.81% |
| CRSP market | 1.112% | 14.2% | 4.22% |

The non-tech portfolio correlates 0.987 with the CRSP market index, confirming it behaves like the market as it should. The spread averages 0.628%/month (t = 3.09, p = 0.002) — but this is simply the technology premium over the sample period and has nothing to do with AI papers yet. Replacing the classification rule with "last valid NAICS code" produces a spread series correlated 0.991 with the main one.

The corrected classification also fixes the flag problem: under the shipped `is_ict` field the technology group held only 42.2% of company AI papers; under the rebuilt classification it holds 83.4%.

### Q1 — AI research and technology returns

| Lag | Coefficient | HAC SE | t | p | BH-adjusted p |
|---:|---:|---:|---:|---:|---:|
| 0 | +0.0701 | 0.0331 | +2.12 | 0.036 | 0.073 |
| 1 | −0.0488 | 0.0345 | −1.41 | 0.160 | 0.208 |
| 2 | +0.0655 | 0.0290 | +2.26 | 0.026 | 0.073 |
| 3 | −0.0501 | 0.0395 | −1.27 | 0.208 | 0.208 |

The contemporaneous coefficient is significant at 5% on its own, but **0 of 4 lags survive BH correction.** Treated as four tests of one hypothesis, this is at best marginal evidence.

### Q2 — Is the effect tech-specific?

| Lag | Coefficient | HAC SE | t | p | BH-adjusted p |
|---:|---:|---:|---:|---:|---:|
| 0 | +0.0466 | 0.0285 | +1.63 | 0.105 | 0.202 |
| 1 | −0.0368 | 0.0193 | −1.90 | 0.060 | 0.202 |
| 2 | +0.0268 | 0.0185 | +1.44 | 0.152 | 0.202 |
| 3 | −0.0152 | 0.0256 | −0.59 | 0.553 | 0.553 |

**Not significant.** Over the full sample, the evidence does not support the claim that AI research output affects technology stocks specifically.

The control group makes this interpretable. The non-tech portfolio's own coefficient is +0.0235 (p = 0.512) — a clean null. So Q2's insignificance is *not* the case where both groups respond and the difference cancels; the tech group's response simply is not strong enough to separate from zero at this sample size.

### Robustness (Q2, contemporaneous)

| Specification | Coefficient | t | p |
|---|---:|---:|---:|
| Main: value-weighted, majority-vote classification | +0.0466 | +1.63 | 0.105 |
| Equal-weighted | +0.0592 | +3.00 | 0.003 |
| Last-NAICS-code classification | +0.0491 | +1.70 | 0.092 |
| X not deseasonalized | +0.0286 | +1.55 | 0.125 |
| Controlling for market return | +0.0418 | +1.38 | 0.169 |

Equal weighting is significant while value weighting is not, which needs explaining rather than reporting selectively. Splitting the market into size quintiles and computing the spread within each:

| Size quintile | Coefficient | t | p | BH-adjusted p |
|---|---:|---:|---:|---:|
| Q1 (smallest) | +0.0751 | +1.77 | 0.079 | 0.131 |
| Q2 | +0.0666 | +3.12 | 0.002 | 0.012 |
| Q3 | +0.0698 | +2.39 | 0.019 | 0.047 |
| Q4 | +0.0349 | +1.30 | 0.197 | 0.197 |
| Q5 (largest) | +0.0470 | +1.63 | 0.105 | 0.132 |

All five coefficients are positive, of similar magnitude, and show no monotonic pattern in size. The equal-vs-value discrepancy is therefore a **statistical power** difference, not evidence that the effect lives only in microcaps — which would have been a reason to discount it.

### Deseasonalization method comparison

| Method | Q1 coefficient | Q1 p | Q2 coefficient | Q2 p | n |
|---|---:|---:|---:|---:|---:|
| 0 Raw (untreated) | +0.0023 | 0.926 | +0.0286 | 0.125 | 107 |
| 1 Month-demeaned (main) | +0.0701 | 0.036 | +0.0466 | 0.105 | 107 |
| 2 Year-over-year | +0.0271 | 0.568 | +0.0255 | 0.241 | 96 |
| 3 STL adjusted | +0.0702 | 0.037 | +0.0463 | 0.106 | 107 |
| 1b Month-demeaned, rolling | +0.0471 | 0.256 | +0.0553 | 0.048 | 71 |

Month-demeaning and STL correlate 0.999 and give effectively identical answers, so the choice between them does not drive any conclusion. Year-over-year differencing should not be used here: taking a 12-period difference flattens the series, pushing first-order autocorrelation from −0.26 to +0.47 and destroying the contemporaneous relationship.

Two cautions on reading this table. The residual-seasonality ANOVA reports F = 0 and p = 1 for method 1, but that is an *identity* — the monthly means were subtracted out by construction, not tested and found absent. And method 1b's apparent Q2 significance comes with a shortened sample (71 months, starting 2020-02), which is where the next section begins.

### Structural change

Method 1b requires three years of history before it can estimate a monthly mean, so it silently truncates the sample to 2020-02 onward — and in that subsample Q2 is significant. Testing 2020-02 directly as a breakpoint gives an interaction term with p = 0.037. That looks like a finding.

It is not:

| Approach | Result |
|---|---|
| Impose 2020-02 as the break date | interaction p = 0.037 (significant) |
| Scan all candidate break dates (supF) | supF = 4.36 at 2020-09, bootstrap p = 0.145 (not significant) |

Both computations are correct. The difference is where the date came from. 2020-02 was not predicted by any theory — it fell out of a sample-length artifact of one deseasonalization method. With 76 candidate break dates, some will produce p < 0.05 by chance, and the bootstrap supF prices that in. The correct statistic to report is the supF result. (For reference, neither GPT-3 in 2020-05 nor ChatGPT in 2022-11 lines up with 2020-02.) Q1 shows no break at all (supF = 0.91, p = 0.967).

### Pre-specified 2021 / 2022 breakpoints

A separate hypothesis was stated *before* looking at these data: that after 2021–2022 firms stopped publishing and shifted to patents and internal work, so the effect should **weaken**. Because the date was specified in advance and only two dates are tested, this needs BH correction across two tests, not a supF penalty.

The interaction is significant at both dates — but the direction is the opposite of the hypothesis:

| Break | Pre-period | Post-period | Interaction | BH-adjusted p |
|---|---|---|---|---:|
| 2021-01 | −0.0093 (p = 0.653, n = 47) | +0.1079 (p = 0.012, n = 60) | +0.1172, p = 0.013 | 0.019 |
| 2022-01 | +0.0007 (p = 0.975, n = 59) | +0.1332 (p = 0.011, n = 48) | +0.1325, p = 0.019 | 0.019 |

Decomposing the 2022 split into each group's own response gives the most informative table in this analysis:

| Period | Tech | Non-tech | Spread |
|---|---|---|---|
| Before (n = 59) | +0.0381 (p = 0.265) | +0.0373 (p = 0.307) | **+0.0007 (p = 0.975)** |
| After (n = 48) | +0.1283 (p = 0.070) | −0.0049 (p = 0.947) | **+0.1332 (p = 0.011)** |

In the pre-period the two groups respond almost identically (0.0381 vs 0.0373), so the spread is essentially exactly zero — a natural placebo test that the design passes. In the post-period only the technology group moves while the non-tech group sits at zero. That asymmetry is precisely the differential response Q2 was designed to detect. The rolling 36-month coefficient jumps in windows ending in early 2023, which lines up with ChatGPT's release in 2022-11.

Note that the same split on Q1 is *not* significant (interaction p = 0.211 and 0.243). The break shows up in the tech-versus-market difference, not in tech returns alone.

**This result is fragile and should be treated as a lead, not a conclusion.** With n = 48:

| Check | Coefficient | p |
|---|---:|---:|
| Main | +0.1332 | 0.011 |
| STL deseasonalization | +0.1308 | 0.013 |
| No deseasonalization | +0.0639 | 0.037 |
| Equal-weighted | +0.1010 | 0.015 |
| Last-NAICS-code classification | +0.1371 | 0.013 |
| Controlling for market return | +0.1246 | 0.040 |
| Excluding 2023 | +0.0893 | 0.070 |
| Excluding 2024 | +0.1182 | 0.095 |
| Excluding 3 most extreme months | +0.0697 | 0.072 |

It survives every change of specification but not the removal of three observations or a single year. Forty-eight months cannot support a strong claim.

### The hypothesis's premise does not hold

The 2021/2022 hypothesis assumed firms stopped publishing. The data disagree:

| Year | arXiv population (monthly avg) | Company papers | Population YoY | Company YoY |
|---|---:|---:|---:|---:|
| 2020 | 3,888 | 2,727 | +33% | +33% |
| 2021 | 4,306 | 2,114 | +11% | −22% |
| 2022 | 4,513 | 548 | +5% | **−74%** |
| 2023 | 5,624 | 513 | +25% | −6% |

Company-attributed papers collapse in 2022 while the arXiv population keeps growing. Firm by firm: GOOGL 654 → 101, MSFT 429 → 122, AMZN 182 → 49, NVDA 80 → 24, AAPL 22 → 10. Every firm halving in the same calendar year is the signature of a data break, not of independent corporate decisions — OpenAlex stopped attaching institutional affiliations to arXiv records in 2022, and this project's company-paper counts depend on exactly that link. Meta showing 0 papers for 2017–2021 confirms the linkage is unreliable, since FAIR published heavily in those years.

**The Q1/Q2 tests are unaffected**, because their independent variable is the arXiv population series, which has no such break. But any claim that firms "shifted to patents" would need patent data and a clean publication series; it cannot be established from this dataset.

## Conclusions

1. **Over the full 2017–2025 sample, the effect is not shown to be technology-specific.** Q2 gives +0.0466 (p = 0.105), and the non-tech control group is a clean null. Q1 is significant contemporaneously but does not survive multiple-testing correction.

2. **This null is now hard to attribute to sample size.** Extending the cross-section from 9 mega-cap firms to 18,595 classified CRSP firms did not change the answer, and the size-quintile decomposition rules out the "effect only exists in small caps" explanation.

3. **Deseasonalization is essential, not optional.** Conference deadlines account for 53.4% of the variance in AI paper growth. Untreated, Q1's coefficient is 30× smaller and nowhere near significant.

4. **The most methodologically instructive result is a contradiction.** The same data yield "significant" or "not significant" for the same break date depending only on whether the date was chosen before or after looking at the data. Reporting the imposed-breakpoint interaction rather than the supF statistic would have been p-hacking, and would have been invisible to a reader.

5. **The strongest positive result in the project is the post-2022 subsample** (+0.1332, p = 0.011), with a clean placebo in the pre-period and a control group that does not move. It is worth pursuing, but 48 months and its sensitivity to dropping three observations mean it cannot carry a strong claim on its own.

### Where this could go next

The binding constraint is statistical power in the time dimension: a monthly time series would need roughly 300 months — 25 years — to detect an effect this size reliably, and the AI-paper series only begins in 2017. The time dimension is exhausted. Any real improvement has to come from the cross-section (firm-level panel tests using within-firm variation), from higher-frequency data (weekly returns against weekly submission counts), or from a cleaner measure of corporate AI activity than affiliation-linked paper counts — patents, job postings, or product releases.
