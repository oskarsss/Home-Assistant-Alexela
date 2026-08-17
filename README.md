# Alexela for Home Assistant

Unofficial Home Assistant custom integration for electricity consumption data from the private API used by [Mana Alexela](https://my.alexela.lv/).

> [!WARNING]
> This project uses an undocumented/private Alexela API. Alexela can change the endpoints or authentication behavior at any time. This project is not affiliated with or endorsed by Alexela.

## Features

- Validates the Alexela CRM ID and bearer token against the contracts endpoint.
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
- Includes Home Assistant local brand-image support.

## Repository layout

```text
.
├── README.md
├── hacs.json
├── brand/
├── scripts/
│   ├── fetch-brand-assets.sh
│   └── prepare-repo.sh
└── custom_components/
    └── alexela/
        ├── __init__.py
        ├── api.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── manifest.json
        ├── sensor.py
        ├── brand/
        └── translations/
            └── en.json
```

# Publishing this repository and installing it with HACS

The repository is already laid out as a HACS custom integration. You only need to create a public GitHub repository, replace the template GitHub metadata, push the files, and add the repository to HACS.

## 1. Create an empty GitHub repository

In GitHub:

1. Click **New repository**.
2. Choose a repository name, for example `alexela-home-assistant`.
3. Set the repository to **Public**.
4. Do **not** initialize it with a README, `.gitignore`, or license if you are uploading this prepared folder.
5. Click **Create repository**.

## 2. Prepare this folder for your GitHub account

From the root of this repository run:

```bash
./scripts/prepare-repo.sh YOUR_GITHUB_USERNAME YOUR_REPOSITORY_NAME
```

Example:

```bash
./scripts/prepare-repo.sh oskars alexela-home-assistant
```

This does two things:

1. Updates `custom_components/alexela/manifest.json` with your GitHub repository URL, issue tracker, and GitHub username as code owner.
2. Downloads the current Alexela brand image from Alexela Latvia's own website and puts it into both Home Assistant's local `custom_components/alexela/brand/` directory and the root `brand/` directory used by HACS tooling.

Review the result:

```bash
cat custom_components/alexela/manifest.json
find brand custom_components/alexela/brand -type f -maxdepth 2 -print
```

Do not leave `REPLACE_ME` anywhere before publishing:

```bash
 grep -R 'REPLACE_ME' . --exclude-dir=.git
```

The command should print nothing.

## 3. Initialize Git and push the repository

Still from the repository root:

```bash
git init
git add .
git commit -m "Initial Alexela Home Assistant integration"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY_NAME.git
git push -u origin main
```

Replace `YOUR_GITHUB_USERNAME` and `YOUR_REPOSITORY_NAME` with the values from step 2.

Your GitHub repository should have this structure at its root:

```text
custom_components/alexela/manifest.json
hacs.json
README.md
```

Do **not** put the entire project inside another top-level directory in GitHub.

## 4. Add your GitHub repository to HACS

In Home Assistant:

1. Open **HACS**.
2. Open the **three-dot menu** in the top-right corner.
3. Select **Custom repositories**.
4. Paste your GitHub repository URL, for example:

   ```text
   https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY_NAME
   ```

5. Select **Integration** as the repository type.
6. Click **Add**.
7. Search HACS for **Alexela** and open it.
8. Click **Download**.
9. Restart Home Assistant.

HACS will install the integration under:

```text
/config/custom_components/alexela
```

## 5. Add Alexela in Home Assistant

After restarting Home Assistant:

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

Do not publish your real bearer token, CRM-specific API responses, personal identity data, address, contract number, or EIC code in GitHub issues or logs.

# Updating through HACS

For a private/custom HACS repository you do not need to publish a GitHub Release. HACS can track the repository's default branch.

For each new integration version:

1. Change `version` in:

   ```text
   custom_components/alexela/manifest.json
   ```

2. Commit and push your changes:

   ```bash
   git add .
   git commit -m "Release 0.1.3"
   git push
   ```

3. HACS will detect the newer version after it refreshes repository information.
4. Update Alexela from HACS and restart Home Assistant when requested.

GitHub Releases are optional for a custom repository, but creating tagged releases is recommended once you start sharing the integration with other users.

Example:

```bash
git tag v0.1.3
git push origin v0.1.3
```

Then create a GitHub Release from that tag in the GitHub UI.

# Optional: prepare for public HACS inclusion

Adding the repository manually as a **Custom repository** is enough for your own Home Assistant installation. You do not need to submit the project to HACS's default repository list.

If you later want users to discover Alexela directly in HACS without manually entering the repository URL, first make the repository production-ready: keep it public, enable GitHub Issues, add repository topics/description, add HACS and Hassfest validation workflows, publish a GitHub Release, and then follow the HACS inclusion process.

# Brand images

The repository does not use a hand-made Alexela lookalike. Run:

```bash
./scripts/fetch-brand-assets.sh
```

The script downloads the current Alexela image directly from:

```text
https://www.alexela.lv/themes/public/images/Alexela_Duallogo_fallback.png
```

and writes:

```text
custom_components/alexela/brand/icon.png
custom_components/alexela/brand/dark_icon.png
custom_components/alexela/brand/logo.png
custom_components/alexela/brand/dark_logo.png
brand/icon.png
brand/dark_icon.png
brand/logo.png
brand/dark_logo.png
```

Re-run the script if Alexela updates its branding. Alexela names, logos and trademarks remain the property of their respective owner and are included only to identify the service integrated by this project.

# Energy Dashboard

For **Grid consumption**, select:

- **Alexela Electricity consumption YTD** as the energy-consumption statistic.

For cost configuration, use one of the following approaches:

- **Total costs** -> select **Alexela Electricity cost YTD** (`EUR`).
- **Current price** -> select **Alexela Electricity price this month** (`EUR/kWh`).

Do not select an `EUR` total-cost sensor in the **current price** field. Home Assistant expects a price-per-energy unit such as `EUR/kWh` there.

The monthly price sensor is calculated as Alexela's current-month energy cost divided by current-month kWh. It is an effective monthly average, not necessarily an instantaneous spot-market price.

# Authentication and token rotation

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

## Browser-session warning

Rotating a token obtained from an active browser session may invalidate the browser's previous token. For initial setup, obtain the token from a separate/private browser session that you do not mind losing.

The integration currently cannot create a new Alexela login session from username/password/Smart-ID. If Home Assistant remains offline long enough for the stored JWT to become unusable, Home Assistant will request reauthentication and you will need to paste a fresh bearer token.

# Known limitations

- Uses an undocumented private Alexela API.
- Currently targets the Latvia Alexela portal/API behavior tested for this integration.
- Does not perform a fresh Alexela login.
- Does not backfill historical Home Assistant long-term statistics.
- Exposes aggregate electricity data rather than a device per contract/consumption location.
- Gas consumption is not exposed yet.
- Alexela can change the API without notice.

# Security

Never commit a bearer token to this repository. The integration stores the token in Home Assistant's config-entry storage at runtime; there is no token in the source tree.

If a bearer token is accidentally posted publicly, treat it as compromised and obtain a new Alexela session/token.

# License and affiliation

This project is unofficial and is not affiliated with, sponsored by, or endorsed by Alexela.

Alexela names and logos are trademarks of their respective owner.
