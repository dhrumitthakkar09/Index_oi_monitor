"""
config.py — Central configuration for OI Monitor
Modify this file to configure your environment.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# DATA SOURCE SELECTION
# Options: "YAHOO" | "ANGEL" | "DHAN"
# ─────────────────────────────────────────────
DATA_SOURCE = os.getenv("DATA_SOURCE", "YAHOO")

# ─────────────────────────────────────────────
# POLLING INTERVAL (seconds) — used for REST/Yahoo
# ─────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))

# ─────────────────────────────────────────────
# TELEGRAM CONFIGURATION
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ─────────────────────────────────────────────
# ANGEL ONE SMARTAPI
# ─────────────────────────────────────────────
ANGEL_API_KEY      = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID    = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_MPIN         = os.getenv("ANGEL_MPIN", "")
ANGEL_TOTP_SECRET  = os.getenv("ANGEL_TOTP_SECRET", "")

# ─────────────────────────────────────────────
# DHAN API
# ─────────────────────────────────────────────
DHAN_ACCESS_TOKEN  = os.getenv("DHAN_ACCESS_TOKEN", "")
DHAN_CLIENT_ID     = os.getenv("DHAN_CLIENT_ID", "")

# ─────────────────────────────────────────────
# INDEX CONFIGURATION
# alert_threshold: minimum OI % change to trigger alert
# strike_step:     distance between strikes
# lot_size:        standard lot size
# expiry_type:     "weekly" or "monthly"
# ─────────────────────────────────────────────
INDEX_CONFIG = {
    "NIFTY": {
        "alert_threshold": 500,
        "strike_step": 50,
        "lot_size": 25,
        "expiry_type": "weekly",
        "yahoo_symbol": "^NSEI",
        "angel_symbol": "NIFTY",
        "dhan_symbol":  "NIFTY",
        "dhan_security_id": "13",        # Dhan security ID for NIFTY index
        "option_prefix": "NIFTY",
    },
    "SENSEX": {
        "alert_threshold": 500,
        "strike_step": 100,
        "lot_size": 10,
        "expiry_type": "weekly",
        "yahoo_symbol": "^BSESN",
        "angel_symbol": "SENSEX",
        "dhan_symbol":  "SENSEX",
        "dhan_security_id": "51",        # Dhan security ID for SENSEX index
        "option_prefix": "SENSEX",
    },
    "BANKNIFTY": {
        "alert_threshold": 100,
        "strike_step": 100,
        "lot_size": 15,
        "expiry_type": "monthly",
        "yahoo_symbol": "^NSEBANK",
        "angel_symbol": "BANKNIFTY",
        "dhan_symbol":  "BANKNIFTY",
        "dhan_security_id": "25",        # Dhan security ID for BANKNIFTY index
        "option_prefix": "BANKNIFTY",
    },
    "MIDCAPSELECT": {
        "alert_threshold": 100,
        "strike_step": 25,
        "lot_size": 50,
        "expiry_type": "monthly",
        "yahoo_symbol": "NIFTY_MID_SELECT.NS",
        "angel_symbol": "MIDCPNIFTY",
        "dhan_symbol":  "MIDCPNIFTY",
        "dhan_security_id": "27",        # Dhan security ID for MIDCPNIFTY index
        "option_prefix": "MIDCPNIFTY",
    },
}

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
LOG_LEVEL     = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR       = os.getenv("LOG_DIR", "logs")
LOG_FILE      = os.path.join(LOG_DIR, "oi_monitor.log")

# ─────────────────────────────────────────────
# CSV OI HISTORY
# ─────────────────────────────────────────────
CSV_ENABLED   = os.getenv("CSV_ENABLED", "true").lower() == "true"
CSV_DIR       = os.getenv("CSV_DIR", "data")

# ─────────────────────────────────────────────
# STOCK MONITOR POLL INTERVAL
# Stocks use a longer cycle — 200 option-chain API calls at 3s each
# takes ~600s, so anything under 10 minutes is effectively continuous.
# ─────────────────────────────────────────────
STOCK_POLL_INTERVAL_SECONDS = int(os.getenv("STOCK_POLL_INTERVAL_SECONDS", "600"))

# ─────────────────────────────────────────────
# TRENDING OI DETECTION
# TREND_CONSECUTIVE_POLLS: number of consecutive polls that must show OI
#   moving in the same direction before a "Trending OI" alert fires.
# TREND_MIN_OI_CHANGE_PCT: minimum % change per poll to count as a move
#   (filters out noise / rounding artefacts).
# ─────────────────────────────────────────────
TREND_CONSECUTIVE_POLLS  = int(os.getenv("TREND_CONSECUTIVE_POLLS", "3"))
TREND_MIN_OI_CHANGE_PCT  = float(os.getenv("TREND_MIN_OI_CHANGE_PCT", "0.5"))

# ─────────────────────────────────────────────
# WEBSOCKET RECONNECT
# ─────────────────────────────────────────────
WS_RECONNECT_DELAY         = int(os.getenv("WS_RECONNECT_DELAY", "5"))
WS_MAX_RECONNECT_ATTEMPTS  = int(os.getenv("WS_MAX_RECONNECT_ATTEMPTS", "10"))

# ─────────────────────────────────────────────
# MARKET HOURS (IST) — skip polling outside hours
# ─────────────────────────────────────────────
MARKET_OPEN_HOUR    = 9
MARKET_OPEN_MINUTE  = 15
MARKET_CLOSE_HOUR   = 15
MARKET_CLOSE_MINUTE = 30
RESPECT_MARKET_HOURS = os.getenv("RESPECT_MARKET_HOURS", "true").lower() == "true"
