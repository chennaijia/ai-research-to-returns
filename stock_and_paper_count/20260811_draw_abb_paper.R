library(tidyverse)
library(data.table)
library(lubridate)

# ---- 1. 讀資料 ----
A_stocks       <- fread("ai_groups_output/group_A_stocks.csv")
B_ict_stocks   <- fread("ai_groups_output/group_B_INFO_COMMU_TECH.csv")
B_other_stocks <- fread("ai_groups_output/group_B_OTHER.csv")

# ---- 2. A 組每年總論文數 ----
A_yearly <- A_stocks |>
  mutate(year = year(my(year_month))) |>
  filter(!is.na(year)) |>
  distinct(permno, year_month, .keep_all = TRUE) |>
  group_by(year) |>
  summarise(
    total_papers = sum(n_papers, na.rm = TRUE),
    n_firms = n_distinct(permno),
    .groups = "drop"
  ) |>
  mutate(group = "A (Mag7)")

# ---- 3. B_ICT 組每年總論文數 ----
B_ict_yearly <- B_ict_stocks |>
  mutate(year = year(parse_date_time(year_month, orders = c("my", "ym", "ymd")))) |>
  filter(!is.na(year)) |>
  distinct(permno, year_month, .keep_all = TRUE) |>
  group_by(year) |>
  summarise(
    total_papers = sum(n_papers, na.rm = TRUE),
    n_firms = n_distinct(permno),
    .groups = "drop"
  ) |>
  mutate(group = "B_ICT (Other Tech)")

# ---- 4. B_Other 組每年總論文數 ----
B_other_yearly <- B_other_stocks |>
  mutate(year = year(parse_date_time(year_month, orders = c("my", "ym", "ymd")))) |>
  filter(!is.na(year)) |>
  distinct(permno, year_month, .keep_all = TRUE) |>
  group_by(year) |>
  summarise(
    total_papers = sum(n_papers, na.rm = TRUE),
    n_firms = n_distinct(permno),
    .groups = "drop"
  ) |>
  mutate(group = "B_Other (Non-Tech)")

# ---- 5. 合併三組並限縮到樣本期 ----
all_yearly <- bind_rows(A_yearly, B_ict_yearly, B_other_yearly) |>
  filter(year >= 2017, year <= 2025)

# ---- 6. 檢視三組每年絕對論文數 ----
cat("=== 三組每年絕對論文數 ===\n")
all_yearly |>
  select(group, year, total_papers, n_firms) |>
  pivot_wider(names_from = group, values_from = total_papers) |>
  as_tibble() |>
  print(n = Inf)

# ---- 7. 計算「以 2020 為 100」的相對指數 ----
all_yearly_indexed <- all_yearly |>
  group_by(group) |>
  mutate(
    base_2020 = total_papers[year == 2020],
    index_2020 = total_papers / base_2020 * 100
  ) |>
  ungroup()

# ---- 8. 圖 A：絕對值（log scale）----
p1 <- ggplot(all_yearly, aes(x = year, y = total_papers, color = group, group = group)) +
  geom_line(size = 1.2) +
  geom_point(size = 2.5) +
  scale_y_log10(labels = scales::comma) +
  scale_x_continuous(breaks = 2017:2025) +
  scale_color_manual(values = c(
    "A (Mag7)" = "#d62728",
    "B_ICT (Other Tech)" = "#1f77b4",
    "B_Other (Non-Tech)" = "#2ca02c"
  )) +
  labs(
    title = "Annual AI Paper Output — Absolute Counts (Log Scale)",
    subtitle = "Mag7 vs. Other Tech vs. Non-Tech firms with AI publications",
    x = "Year",
    y = "Total AI Papers (log scale)",
    color = NULL
  ) +
  theme_minimal(base_size = 12) +
  theme(legend.position = "top")

ggsave("ai_groups_output/fig_papers_absolute_3groups.png", p1, width = 11, height = 6, dpi = 300)

# ---- 9. 圖 B：相對指數（2020 = 100）----
p2 <- ggplot(all_yearly_indexed, aes(x = year, y = index_2020, color = group, group = group)) +
  geom_line(size = 1.2) +
  geom_point(size = 2.5) +
  geom_hline(yintercept = 100, linetype = "dashed", color = "grey50") +
  annotate("text", x = 2017, y = 105, label = "2020 peak = 100",
           color = "grey40", size = 3.5, hjust = 0) +
  scale_x_continuous(breaks = 2017:2025) +
  scale_color_manual(values = c(
    "A (Mag7)" = "#d62728",
    "B_ICT (Other Tech)" = "#1f77b4",
    "B_Other (Non-Tech)" = "#2ca02c"
  )) +
  labs(
    title = "AI Paper Decline After 2020: Magnificent 7 vs. Other Sectors",
    subtitle = "Index = 100 at each group's 2020 level; downward slope indicates a decline",
    x = "Year",
    y = "Index (2020 = 100)",
    color = NULL
  ) +
  theme_minimal(base_size = 12) +
  theme(legend.position = "top")

ggsave("ai_groups_output/fig_papers_indexed_3groups.png", p2, width = 11, height = 6, dpi = 300)
