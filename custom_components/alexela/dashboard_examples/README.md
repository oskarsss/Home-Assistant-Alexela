# Alexela dashboard examples

HACS installs these maintained examples with the integration, but it does not
alter an existing Home Assistant dashboard automatically.

## Full electricity dashboard

`nord_pool_comparison.yaml` is a responsive, two-view dashboard based on the
current Home Assistant `sections` layout:

- **Overview** — current-month and seven-day totals with per-day averages, a
  native 15-minute chart for the latest available 48 hours with an all-history
  weekday/time-band profile, a 30-day daily-usage chart with the matching
  all-history calendar-month daily average, a same-period
  fixed-vs-Nord-Pool comparison, and clearly scoped price tiles.
- **Analytics** — clearly separated Historical consumption, Historical cost,
  Nord Pool comparison, and Nord Pool prices groups. Month-over-month and
  year-over-year statistic cards, plus monthly average/minimum/maximum cards,
  are paired with monthly, annual, daily, and cumulative graphs as history grows.

All comparison cards use the integration's external statistics. The three
current-month comparison cards use the same calendar-month period, so their
displayed difference reconciles with the two displayed totals.

### Install

1. Install **ApexCharts Card** and **Energy Custom Graph** from HACS. ApexCharts
   renders native 15-minute bars and a smooth expected profile; Energy Custom
   Graph renders the mixed daily bar/calendar-month-average chart.
2. Open `nord_pool_comparison.yaml` and replace every
   `REPLACE_WITH_CRM_ID` with the CRM ID configured in Alexela.
3. Create or open a dashboard, choose **Edit dashboard -> Raw configuration
   editor**, and paste the complete file.
4. If Home Assistant suffixed or renamed a normal `sensor.alexela_*` entity,
   replace that entity ID with the one shown under
   **Settings -> Devices & services -> Alexela**.

The template deliberately excludes installation-specific `alexela_price:*`
statistics. Every referenced external statistic is created by this integration.

## Compact summary

`compact_summary_card.yaml` is a responsive two-column tile grid containing
current-month usage, current-month cost, the month's effective fixed price, and
the latest matched Nord Pool spot price. Paste it into a manual card's YAML
editor and adjust locally renamed sensor entity IDs if necessary.
