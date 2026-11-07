# Alexela dashboard examples

HACS installs these maintained examples with the integration, but it does not
alter an existing Home Assistant dashboard automatically.

## Full electricity dashboard

`nord_pool_comparison.yaml` is a responsive, two-view dashboard based on the
current Home Assistant `sections` layout:

- **Overview** — an estimated month-end bill, current-month and seven-day totals with matching period-total averages, a
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

1. Install **ApexCharts Card** from HACS. It renders the native 15-minute chart
   in Wh and the rolling daily chart in kWh, including both smooth profiles.
2. Open `nord_pool_comparison.yaml` and replace every
   `REPLACE_WITH_CRM_ID` with the CRM ID configured in Alexela.
3. Create or open a dashboard, choose **Edit dashboard -> Raw configuration
   editor**, and paste the complete file.
4. If Home Assistant suffixed or renamed a normal `sensor.alexela_*` entity,
   replace that entity ID with the one shown under
   **Settings -> Devices & services -> Alexela**.
   Older installs may name the difference sensor
   `sensor.alexela_electricity_cost_difference_vs_nord_pool` instead of
   `sensor.alexela_electricity_cost_difference_vs_comparison`; the two
   comparison badges at the top use it to pick their wording.

The template deliberately excludes installation-specific `alexela_price:*`
statistics. Every referenced external statistic is created by this integration.

## Compact summary

`compact_summary_card.yaml` is a responsive two-column tile grid containing
current-month usage, current-month cost, the estimated month-end bill, the
month's effective fixed price, and the latest matched Nord Pool spot price.
Paste it into a manual card's YAML editor and adjust locally renamed sensor
entity IDs if necessary.

## Estimated bill

`sensor.alexela_electricity_estimated_bill_this_month` projects the latest
recorded month's invoice total. It takes Alexela's energy cost (fixed price incl
VAT), fills unrecorded days at the month's daily average, and adds the other
invoice lines plus 21% VAT: distribution 0.03962 EUR/kWh, balancing capacity
0.00201 EUR/kWh, capacity maintenance 0.34 EUR/A for 20 A, and the 1.24 EUR
monthly fee (all excl VAT, from 2026 PAMATA-1 1F invoices). If your connection
or tariffs differ, set them under **Settings → Devices & services → Alexela →
Configure**. A
partial first contract month, which Alexela prorates, is not modelled.

## Unpaid bills

`unpaid_bills_card.yaml` displays unpaid amounts and payment deadlines using the
new billing sensors in v0.3.12. The complete dashboard includes this card too.
From v0.3.13, the Unpaid bills category appears above Cost only when the
unpaid count is positive. Both its heading and details disappear at zero
(or when billing data is unknown).
