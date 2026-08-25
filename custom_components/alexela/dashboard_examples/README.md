# Alexela dashboard examples

HACS installs these examples with the integration, but it cannot safely alter
an existing Home Assistant dashboard for you.

## Full comparison view

Open `nord_pool_comparison.yaml`, replace every `REPLACE_WITH_CRM_ID` with the
CRM ID configured in Alexela, and copy the view into a dashboard's raw YAML
configuration. It uses only built-in Home Assistant cards and includes a date
picker, selected-period totals, cost graphs, the signed difference and the
historical Nord Pool spot price.

## Compact summary

Open `compact_summary_card.yaml` and paste it into a manual card's YAML editor.
If Home Assistant assigned different entity IDs, select the three Alexela Nord
Pool sensors shown under **Settings -> Devices & services -> Alexela** and
replace the example IDs.
