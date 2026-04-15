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
ANGEL_MPIN         = os.getenv("ANGEL_MPIN", "")   # 4-digit MPIN (password login is deprecated by Angel One)
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
        "alert_threshold": 500,     # % OI change to trigger alert
        "strike_step": 50,
        "lot_size": 25,
        "expiry_type": "weekly",
        "yahoo_symbol": "^NSEI",
        "angel_symbol": "NIFTY",
        "dhan_symbol": "NIFTY",
        "option_prefix": "NIFTY",   # NSE option symbol prefix
    },
    "SENSEX": {
        "alert_threshold": 500,
        "strike_step": 100,
        "lot_size": 10,
        "expiry_type": "weekly",
        "yahoo_symbol": "^BSESN",
        "angel_symbol": "SENSEX",
        "dhan_symbol": "SENSEX",
        "option_prefix": "SENSEX",
    },
    "BANKNIFTY": {
        "alert_threshold": 100,
        "strike_step": 100,
        "lot_size": 15,
        "expiry_type": "monthly",   # BANKNIFTY weekly discontinued; monthly only
        "yahoo_symbol": "^NSEBANK",
        "angel_symbol": "BANKNIFTY",
        "dhan_symbol": "BANKNIFTY",
        "option_prefix": "BANKNIFTY",
    },
    "MIDCAPSELECT": {
        "alert_threshold": 100,
        "strike_step": 25,
        "lot_size": 50,
        "expiry_type": "monthly",   # MIDCAPSELECT weekly discontinued; monthly only
        "yahoo_symbol": "NIFTY_MID_SELECT.NS",
        "angel_symbol": "MIDCPNIFTY",
        "dhan_symbol": "MIDCPNIFTY",
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
# WEBSOCKET RECONNECT
# ─────────────────────────────────────────────
WS_RECONNECT_DELAY    = int(os.getenv("WS_RECONNECT_DELAY", "5"))
WS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("WS_MAX_RECONNECT_ATTEMPTS", "10"))

# ─────────────────────────────────────────────
# MARKET HOURS (IST) — skip polling outside hours
# ─────────────────────────────────────────────
MARKET_OPEN_HOUR    = 9
MARKET_OPEN_MINUTE  = 15
MARKET_CLOSE_HOUR   = 15
MARKET_CLOSE_MINUTE = 30
RESPECT_MARKET_HOURS = os.getenv("RESPECT_MARKET_HOURS", "true").lower() == "true"
