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

## Energy Dashboard

For **Grid consumption**, select:

- **Alexela Electricity consumption YTD** as the energy-consumption statistic.

For cost configuration, use one of the following approaches:

- **Total costs** -> select **Alexela Electricity cost YTD** (`EUR`).
- **Current price** -> select **Alexela Electricity price this month** (`EUR/kWh`).

Do not select an `EUR` total-cost sensor in the **current price** field. Home Assistant expects a price-per-energy unit such as `EUR/kWh` there.

The monthly price sensor is calculated as Alexela's reported month energy cost divided by that month's kWh. It is an effective monthly average, not necessarily an instantaneous spot-market price.

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
- Targets the Latvia Alexela portal/API behavior tested for this integration.
- Consumption data is a day or more behind, and monthly rather than hourly.
- Does not perform a fresh Alexela login.
- Does not backfill historical Home Assistant long-term statistics.
- Exposes aggregate electricity data rather than a device per contract/consumption location.
- Gas consumption is not exposed yet.
- Alexela can change the API without notice.

## Security

The integration stores the token in Home Assistant's config-entry storage at runtime; there is no token in the source tree. If a bearer token is accidentally posted publicly, treat it as compromised and obtain a new Alexela session/token.

## License and affiliation

This project is unofficial and is not affiliated with, sponsored by, or endorsed by Alexela.

Alexela names and logos are trademarks of their respective owner.
