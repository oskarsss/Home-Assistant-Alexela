"""Constants for the Alexela integration."""

from datetime import timedelta

DOMAIN = "alexela"

CONF_CRM_ID = "crm_id"
CONF_TOKEN = "token"

API_HOST = "https://itk-api.alexela.ee"
PORTAL_ORIGIN = "https://my.alexela.lv"

# Alexela JWTs observed in August 2026 are short-lived and can be rotated by
# /login/refreshJwt. Poll often enough to refresh well before token expiry.
UPDATE_INTERVAL = timedelta(minutes=15)
REQUEST_TIMEOUT = 30
