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
# basis. Network charges are not part of the comparison reference.
LATVIA_VAT_MULTIPLIER = 1.21

# Alexela's provider markup is already VAT-inclusive. Add it after applying
# VAT to the Nord Pool price; multiplying it by VAT again would overstate the
# comparison reference.
PROVIDER_MARKUP_EUR_PER_KWH = 0.0087

# Invoice charges besides the energy itself, all excl VAT, as itemised on
# 2026 bills for a PAMATA-1 1F connection. Used only for the bill estimate,
# and only as defaults: other tariffs set their own in the integration options.
CONF_BILL_MONTHLY_FEE = "bill_monthly_fee"
CONF_BILL_CAPACITY_EUR_PER_AMP = "bill_capacity_eur_per_amp"
CONF_BILL_CONNECTION_AMPS = "bill_connection_amps"
CONF_BILL_DISTRIBUTION_EUR_PER_KWH = "bill_distribution_eur_per_kwh"
CONF_BILL_BALANCING_EUR_PER_KWH = "bill_balancing_eur_per_kwh"
BILL_MONTHLY_FEE_EUR = 1.24
BILL_CAPACITY_EUR_PER_AMP = 0.34
BILL_CONNECTION_AMPS = 20
BILL_DISTRIBUTION_EUR_PER_KWH = 0.03962
# Balancing capacity varies monthly (0.00122-0.00201 so far); use the latest.
BILL_BALANCING_EUR_PER_KWH = 0.00201
BILL_DEFAULTS = {
    CONF_BILL_MONTHLY_FEE: BILL_MONTHLY_FEE_EUR,
    CONF_BILL_CAPACITY_EUR_PER_AMP: BILL_CAPACITY_EUR_PER_AMP,
    CONF_BILL_CONNECTION_AMPS: BILL_CONNECTION_AMPS,
    CONF_BILL_DISTRIBUTION_EUR_PER_KWH: BILL_DISTRIBUTION_EUR_PER_KWH,
    CONF_BILL_BALANCING_EUR_PER_KWH: BILL_BALANCING_EUR_PER_KWH,
}

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

# Alexela may publish or revise consumption with a long delay. Once the
# historical backfill is contiguous, re-read the latest 30 calendar days
# periodically so gaps such as a late-published day are eventually repaired.
RECONCILE_DAYS = 30
# Re-reading 30 days costs about 60 requests to Alexela and Nord Pool, and
# Alexela answers bursts with empty payloads. Do it a few times a day; other
# polls re-read only the latest days, which may still be incomplete.
FULL_RECONCILE_INTERVAL = timedelta(hours=6)
QUICK_RECONCILE_DAYS = 2

# Coordinator data key describing how fresh the consumption values are.
SNAPSHOT_KEY = "consumption_snapshot"
