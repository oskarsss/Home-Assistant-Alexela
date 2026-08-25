"""Constants for the Alexela integration."""

from datetime import timedelta

DOMAIN = "alexela"

CONF_CRM_ID = "crm_id"
CONF_TOKEN = "token"

API_HOST = "https://itk-api.alexela.ee"
PORTAL_ORIGIN = "https://my.alexela.lv"

# Public endpoint used by Nord Pool's own Data Portal. Prices are returned in
# EUR/MWh for the Latvian bidding area.
NORD_POOL_API_HOST = "https://dataportal-api.nordpoolgroup.com"
NORD_POOL_DELIVERY_AREA = "LV"

# The unauthenticated Data Portal endpoint exposes only about two months of
# interval history. A Latvian local day also needs the previous CET/CEST
# delivery date for its first hour, so leave that extra day inside the window.
# Home Assistant keeps every imported hour indefinitely after the first import.
NORD_POOL_INITIAL_BACKFILL_DAYS = 59

# Alexela exposes priceWithVat, while Nord Pool's day-ahead price excludes VAT.
# Use the Latvian standard VAT rate so the reference costs share the same tax
# basis. Network charges are not part of the Nord Pool reference cost.
LATVIA_VAT_MULTIPLIER = 1.21

# Alexela JWTs observed in August 2026 are short-lived and can be rotated by
# /login/refreshJwt. Poll often enough to refresh well before token expiry.
UPDATE_INTERVAL = timedelta(minutes=15)
REQUEST_TIMEOUT = 30

# Alexela publishes consumption only up to the previous day, so every period
# lookup is anchored on yesterday instead of today. Without this the first day
# of a month (and of a year) would ask for a period Alexela has no data for.
DATA_LAG = timedelta(days=1)

# Alexela reports timestamps in Latvian local time without an offset.
PORTAL_TIME_ZONE = "Europe/Riga"

# Statistics are imported one day per request. Cap how many days a single
# update may backfill so a long gap does not hammer the portal in one go;
# the remaining days are picked up by later updates.
MAX_BACKFILL_DAYS = 40
