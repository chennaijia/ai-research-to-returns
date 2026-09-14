# 八家科技公司 R&D 支出 — 依實際財務期間對齊自然時間軸
# 單位：billion USD（將原始單位 million 單位轉換成 billion）

# 路徑相對於 repo 根目錄，執行方式：Rscript 04_rnd/scripts/01_plot_rd.R
OUT_DIR <- "04_rnd/out"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

library(tidyverse)
library(lubridate)

rd_annual    <- read_csv("data/compustat/rnd_8comp.csv")
rd_quarterly <- read_csv("data/compustat/rnd_8comp_month.csv")

rd_annual_clean <- rd_annual |>
  filter(fyear >= 2010, fyear <= 2026) |>
  mutate(
    apdedate = as.Date(apdedate),
    # 財年結束日往前推 12 個月 = 財年開始日
    fy_start = apdedate %m-% months(12) + days(1),
    fy_end   = apdedate,
    xrd_billion = xrd / 1000   # million → billion USD
  )

rd_quarterly_clean <- rd_quarterly |>
  filter(fyearq >= 2010, fyearq <= 2026) |>
  mutate(
    apdedateq = as.Date(apdedateq),
    # 財季結束日往前推 3 個月 = 財季開始日
    fq_start = apdedateq %m-% months(3) + days(1),
    fq_end   = apdedateq,
    xrdq_billion = xrdq / 1000   # million → billion USD
  )

# 圖 1：年度 R&D，以實際財年期間為 x 軸，用「實際財務期間」畫階梯線（每家公司一條）
ggplot(rd_annual_clean) +
  geom_segment(
    aes(x = fy_start, xend = fy_end,
        y = xrd_billion, yend = xrd_billion,
        color = tic),
    size = 1.2
  ) +
  scale_x_date(
    date_breaks = "1 year", date_labels = "%Y",
    limits = c(as.Date("2010-01-01"), as.Date("2026-01-01")),
    expand = c(0, 0)
  ) +
  labs(
    title = "Annual R&D Expenditure of Eight Technology Firms",
    subtitle = "Each horizontal segment spans the actual fiscal reporting period, not a calendar year",
    x = "Calendar Date",
    y = "R&D Expenditure (Billion USD)",
    color = "Company"
  ) +
  theme_minimal(base_size = 12) +
  theme(legend.position = "right")

ggsave(file.path(OUT_DIR, "fig_rd_annual_segments.png"), width = 12, height = 6, dpi = 300)

# 圖 2：季度 R&D，以實際財季期間為 x 軸
ggplot(rd_quarterly_clean) +
  geom_segment(
    aes(x = fq_start, xend = fq_end,
        y = xrdq_billion, yend = xrdq_billion,
        color = tic),
    size = 1
  ) +
  scale_x_date(
    date_breaks = "1 year", date_labels = "%Y",
    limits = c(as.Date("2010-01-01"), as.Date("2026-01-01")),
    expand = c(0, 0)
  ) +
  labs(
    title = "Quarterly R&D Expenditure of Eight Technology Firms",
    subtitle = "Each horizontal segment spans the actual fiscal quarter",
    x = "Calendar Date",
    y = "Quarterly R&D Expenditure (Billion USD)",
    color = "Company"
  ) +
  theme_minimal(base_size = 12) +
  theme(legend.position = "right")

ggsave(file.path(OUT_DIR, "fig_rd_quarterly_segments.png"), width = 12, height = 6, dpi = 300)

# 圖 3：用季度資料去畫8家公司加總的r&d expense，point-in-time 加總
# 步驟：對每個日曆日期，找出「該日期落在哪家公司的哪個財年區間內」，
# 然後把所有仍在生效的公司 R&D 值加總

# 建立日曆日期序列（每月第一天當代表點，減少計算量；要更精細改成 "day"）
calendar_dates <- tibble(
  cal_date = seq(as.Date("2010-01-01"), as.Date("2026-01-01"), by = "3 months")
)

# 對每個日曆日期，找出當下每家公司仍在生效的「季度」R&D 值
rd_pit_q <- calendar_dates |>
  crossing(rd_quarterly_clean |> select(tic, fq_start, fq_end, xrdq_billion)) |>
  filter(
    cal_date >= fq_start,
    cal_date <= fq_end,
    cal_date <= as.Date("2026-01-01"),
    cal_date >= as.Date("2010-01-01")
  ) |>
  group_by(cal_date) |>
  summarise(
    total_rdq_billion = sum(xrdq_billion, na.rm = TRUE),
    n_firms  = n(),
    .groups = "drop"
  )

# 畫圖
ggplot(rd_pit_q, aes(x = cal_date, y = total_rdq_billion)) +
  geom_line(size = 1, color = "steelblue") +
  geom_point(size = 1.5, color = "steelblue") +
  scale_x_date(
    date_breaks = "1 year", date_labels = "%Y",
    limits = c(as.Date("2010-01-01"), as.Date("2026-01-01")),
    expand = c(0, 0)
  ) +
  labs(
    title = "Aggregate Quarterly R&D Expenditure of Eight Technology Firms (2010-2025)",
    subtitle = "Point-in-time sum of quarterly R&D expenditure across all eight firms",
    x = "Calendar Date",
    y = "Aggregate Quarterly R&D Expenditure (Billion USD)"
  ) +
  theme_minimal(base_size = 12)

ggsave(file.path(OUT_DIR, "fig_rd_aggregate_pit.png"), width = 12, height = 6, dpi = 300)

# 圖 4：8 家公司分面圖
ggplot(rd_annual_clean) +
  geom_segment(
    aes(x = fy_start, xend = fy_end,
        y = xrd_billion, yend = xrd_billion),
    size = 1.2, color = "steelblue"
  ) +
  facet_wrap(~ tic, scales = "free_y", ncol = 4) +
  scale_x_date(
    date_breaks = "3 years", date_labels = "%Y",
    limits = c(as.Date("2010-01-01"), as.Date("2026-01-01")),
    expand = c(0, 0)
  ) +
  labs(
    title = "Firm-Level Annual R&D Expenditure (2010-2025)",
    subtitle = "Each segment spans the actual fiscal reporting period",
    x = "Calendar Date",
    y = "R&D Expenditure (Billion USD)"
  ) +
  theme_minimal(base_size = 11)

ggsave(file.path(OUT_DIR, "fig_rd_annual_facet_segments.png"), width = 14, height = 6, dpi = 300)
