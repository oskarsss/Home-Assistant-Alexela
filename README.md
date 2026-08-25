# Alexela for Home Assistant

Unofficial Home Assistant custom integration for electricity consumption data from the private API used by [Mana Alexela](https://my.alexela.lv/).

> [!WARNING]
> This project uses an undocumented/private Alexela API. Alexela can change the endpoints or authentication behavior at any time. This project is not affiliated with or endorsed by Alexela.

## Features

- Maintains Alexela's rotating JWT chain using `GET /login/refreshJwt`.
- Persists a replacement JWT when Alexela returns a new `Bearer` response header.
- Fetches electricity consumption every 15 minutes.
- Provides Home Assistant sensors for:
  - Electricity consumption YTD (`kWh`)
  - Electricity consumption this month (`kWh`)
  - Electricity cost YTD (`EUR`)
  - Electricity cost this month (`EUR`)
  - Electricity price this month (`EUR/kWh`)
  - Latest matched Nord Pool Latvia price incl. VAT (`EUR/kWh`)
  - Nord Pool plus provider-markup reference cost (`EUR`)
  - Alexela cost difference versus that comparison (`EUR`)
- Imports Alexela's published 15-minute readings into hourly Home Assistant
  long-term statistics for historical Energy Dashboard data.
- Matches each consumption interval to the official Nord Pool Latvia day-ahead
  price, adds the VAT-inclusive `0.0087 EUR/kWh` provider markup, and imports
  hourly spot-price, reference-cost and cost-difference statistics.
- Supports Home Assistant reauthentication if the stored JWT becomes invalid.

## Installation

### HACS (custom repository)

1. Open **HACS**.
2. Open the **three-dot menu** in the top-right corner.
3. Select **Custom repositories**.
4. Paste the repository URL of this project.
5. Select **Integration** as the repository type.
6. Click **Add**.
7. Search HACS for **Alexela**, open it and click **Download**.
8. Restart Home Assistant.

HACS installs the integration under `/config/custom_components/alexela`.

### Manual

1. Copy the `custom_components/alexela` directory into your Home Assistant configuration directory, so that you end up with `/config/custom_components/alexela/manifest.json`.
2. Restart Home Assistant.

## Adding the integration

1. Open **Settings -> Devices & services**.
2. Click **Add integration**.
3. Search for **Alexela**.
4. Enter the **CRM ID**.
5. Enter a current **Bearer token** from the Alexela portal.
6. Submit the form.

The token field accepts either:

```text
eyJ...
```

or:

```text
Bearer eyJ...
```

### Finding the CRM ID

The CRM ID is the number used in the Alexela API URL. For example:

```text
https://itk-api.alexela.ee/api/1234567/1234567/consumption
```

The CRM ID in this example is:

```text
1234567
```

### Finding the bearer token

1. Log in to [my.alexela.lv](https://my.alexela.lv/) in a browser.
2. Open the browser developer tools and go to the **Network** tab.
3. Open the consumption page and select any request to `itk-api.alexela.ee`.
4. Copy the value of the `Authorization` request header.

Do not publish your real bearer token, CRM-specific API responses, personal identity data, address, contract number, or EIC code in issues or logs.

## Data freshness

Alexela publishes consumption with about a day of delay, and the portal is not always available. The integration is built around that:

- Every period lookup is anchored on **yesterday**, not today. Asking for today's period would return nothing on the first day of a month or year.
- The sensors report the newest month Alexela has actually published. Right after a month rolls over, that is still the previous month; the `data_period_start` attribute on each sensor shows which period the value covers.
- If Alexela is unreachable or returns an empty response, the last successfully received values are kept instead of the sensors going unavailable. The reason is logged as a warning.
- If the current year is still empty (early January), the previous year is fetched instead.

If every sensor shows **Unknown** (as opposed to *Unavailable*), the poll succeeded but the response could not be parsed. Enable debug logging to see the raw payload:

```yaml
logger:
  default: warning
  logs:
    custom_components.alexela: debug
```

## Energy Dashboard

For **Grid consumption**, select:

- **Alexela electricity** (`alexela:<CRM ID>_electricity_energy`) for accurate
  historical hourly consumption. The integration backfills up to 40 published
  days per update and continues on later updates until caught up.

For cost configuration, use one of the following approaches:

- **Total costs** -> select **Alexela electricity cost**
  (`alexela:<CRM ID>_electricity_cost`) for historical hourly costs.
- **Current price** -> select **Alexela Electricity price this month** (`EUR/kWh`).

Do not select an `EUR` total-cost sensor in the **current price** field. Home Assistant expects a price-per-energy unit such as `EUR/kWh` there.

The monthly price sensor is calculated as Alexela's reported month energy cost divided by that month's kWh. It is an effective monthly average, not necessarily an instantaneous spot-market price.

## Nord Pool comparison

For every published Alexela consumption interval, the integration looks up the
Nord Pool Latvia (`LV`) day-ahead interval that covered the same moment. It
creates these external long-term statistics:

- `alexela:<CRM ID>_nord_pool_price` — the hourly average Nord Pool price,
  converted from `EUR/MWh` to `EUR/kWh` and including 21% Latvian VAT.
- `alexela:<CRM ID>_nord_pool_provider_reference_cost` — what the metered
  consumption would have cost at the VAT-inclusive spot price plus the
  provider's VAT-inclusive `0.0087 EUR/kWh` markup.
- `alexela:<CRM ID>_electricity_cost_difference_vs_nord_pool_provider` —
  Alexela's reported `priceWithVat` minus that provider-inclusive reference
  cost. A positive total means Alexela cost more; a negative total means it
  cost less.

The three Nord Pool sensors show the latest matched price and running totals
for all comparison history imported so far. The `data_through` attribute shows
the newest completed hour. During initial backfill those totals grow as older
days are imported. The public Nord Pool Data Portal exposes only about 60 days
of interval history, so a new installation starts there; Home Assistant keeps
those statistics indefinitely and the comparison history grows from then on.
Use the external statistics in a Statistics Graph card to view and total a
specific day, month or year covered by the imported history.

Nord Pool groups prices by the CET/CEST delivery date. Because Latvia is one
hour ahead, the integration combines the requested and previous Nord Pool
delivery dates so the first hour after Latvian midnight is included.

This is a spot-price-plus-provider-markup reference, not a reconstruction of a
complete alternative bill. It includes 21% VAT on the Nord Pool price and adds
the provider's already VAT-inclusive `0.0087 EUR/kWh` markup to make the
comparison compatible with Alexela's `priceWithVat`. It excludes
network/distribution charges and any other tariff component absent from that
Alexela field. Nord Pool changed the official day-ahead resolution from hourly
to 15 minutes; both forms are matched by their actual delivery start and end
times.

Versions before `0.3.2` created spot-only comparison statistic IDs. Version
`0.3.2` writes the provider-inclusive comparison to new statistic IDs so the
two formulas are never mixed; the new series backfill automatically from the
available Nord Pool history.

### Dashboard examples

HACS installs two ready-to-copy examples inside
`custom_components/alexela/dashboard_examples/`:

- [`nord_pool_comparison.yaml`](custom_components/alexela/dashboard_examples/nord_pool_comparison.yaml)
  is a complete native Home Assistant view with a date picker, selected-period
  totals, comparison bars and a spot-price graph. Replace
  `REPLACE_WITH_CRM_ID` with the CRM ID used by this integration before pasting
  it under `views:` in a dashboard's raw configuration.
- [`compact_summary_card.yaml`](custom_components/alexela/dashboard_examples/compact_summary_card.yaml)
  is a small entities card for the three live summary sensors. Check the
  generated entity IDs under **Settings -> Devices & services -> Alexela** if
  Home Assistant renamed or suffixed them.

HACS custom integrations are installed under `custom_components/`; they do not
automatically edit a user's dashboard. The examples use only built-in Home
Assistant cards, so no separate dashboard-card dependency is required.

## Authentication and token rotation

The integration owns the JWT rotation chain supplied during setup.

Observed behavior:

```text
current JWT
    |
    +--> GET /login/refreshJwt
            |
            +-- no Bearer header --> keep current JWT
            |
            +-- Bearer header ----> persist replacement JWT
    |
    +--> GET /consumption
```

A successful refresh request can return HTTP 200 without a new `Bearer` header. That is treated as a no-op rather than an error.

When Alexela does return a replacement JWT, the integration stores the replacement in the Home Assistant config entry so that future polls and Home Assistant restarts use the current token.

### Browser-session warning

Rotating a token obtained from an active browser session may invalidate the browser's previous token. For initial setup, obtain the token from a separate/private browser session that you do not mind losing.

The integration cannot create a new Alexela login session from username/password/Smart-ID. If Home Assistant remains offline long enough for the stored JWT to become unusable, Home Assistant will request reauthentication and you will need to paste a fresh bearer token.

## Known limitations

- Uses an undocumented private Alexela API.
- Uses the public JSON endpoint behind Nord Pool's Data Portal; Nord Pool may
  change it without notice. A Nord Pool failure does not stop Alexela data from
  updating and is retried later.
- Targets the Latvia Alexela portal/API behavior tested for this integration.
- Consumption data is a day or more behind. Summary sensors are monthly; the
  imported long-term statistics are hourly totals built from 15-minute data.
- Does not perform a fresh Alexela login.
- Backfill is limited to 40 days per update to avoid overwhelming the private
  API. Empty successful responses pause the import and are retried later.
- Exposes aggregate electricity data rather than a device per contract/consumption location.
- Gas consumption is not exposed yet.
- Alexela can change the API without notice.

## Security

The integration stores the token in Home Assistant's config-entry storage at runtime; there is no token in the source tree. If a bearer token is accidentally posted publicly, treat it as compromised and obtain a new Alexela session/token.

## License and affiliation

This project is unofficial and is not affiliated with, sponsored by, or endorsed by Alexela.

Alexela names and logos are trademarks of their respective owner.
