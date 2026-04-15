"""
stock_config.py — F&O stock configurations for OI monitoring.

All F&O stocks use:
  - Monthly expiry  (last Thursday of the month)
  - Alert threshold: OI change ≥ 100%

Strike steps and lot sizes are as per NSE circulars (verify current values at
https://www.nseindia.com/regulations/content/fo_underlying_instruments.htm
as NSE revises these periodically).

To add a new stock: copy any existing entry, update all fields, done.
To disable a stock: comment out its entry or remove from the dict.
"""

STOCK_CONFIG: dict = {

    # ── Banking & Finance ─────────────────────────────────────────────────────
    "HDFCBANK": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        550,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "HDFCBANK.NS",
        "angel_symbol":    "HDFCBANK",
        "dhan_symbol":     "HDFCBANK",
    },
    "ICICIBANK": {
        "alert_threshold": 100,
        "strike_step":     20,
        "lot_size":        1375,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "ICICIBANK.NS",
        "angel_symbol":    "ICICIBANK",
        "dhan_symbol":     "ICICIBANK",
    },
    "SBIN": {
        "alert_threshold": 100,
        "strike_step":     20,
        "lot_size":        1500,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "SBIN.NS",
        "angel_symbol":    "SBIN",
        "dhan_symbol":     "SBIN",
    },
    "KOTAKBANK": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        400,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "KOTAKBANK.NS",
        "angel_symbol":    "KOTAKBANK",
        "dhan_symbol":     "KOTAKBANK",
    },
    "AXISBANK": {
        "alert_threshold": 100,
        "strike_step":     20,
        "lot_size":        1200,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "AXISBANK.NS",
        "angel_symbol":    "AXISBANK",
        "dhan_symbol":     "AXISBANK",
    },
    "BAJFINANCE": {
        "alert_threshold": 100,
        "strike_step":     100,
        "lot_size":        125,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "BAJFINANCE.NS",
        "angel_symbol":    "BAJFINANCE",
        "dhan_symbol":     "BAJFINANCE",
    },
    "BAJAJFINSV": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        500,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "BAJAJFINSV.NS",
        "angel_symbol":    "BAJAJFINSV",
        "dhan_symbol":     "BAJAJFINSV",
    },
    "INDUSINDBK": {
        "alert_threshold": 100,
        "strike_step":     20,
        "lot_size":        1000,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "INDUSINDBK.NS",
        "angel_symbol":    "INDUSINDBK",
        "dhan_symbol":     "INDUSINDBK",
    },

    # ── IT ────────────────────────────────────────────────────────────────────
    "TCS": {
        "alert_threshold": 100,
        "strike_step":     100,
        "lot_size":        150,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "TCS.NS",
        "angel_symbol":    "TCS",
        "dhan_symbol":     "TCS",
    },
    "INFY": {
        "alert_threshold": 100,
        "strike_step":     40,
        "lot_size":        400,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "INFY.NS",
        "angel_symbol":    "INFY",
        "dhan_symbol":     "INFY",
    },
    "HCLTECH": {
        "alert_threshold": 100,
        "strike_step":     40,
        "lot_size":        700,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "HCLTECH.NS",
        "angel_symbol":    "HCLTECH",
        "dhan_symbol":     "HCLTECH",
    },
    "WIPRO": {
        "alert_threshold": 100,
        "strike_step":     10,
        "lot_size":        1500,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "WIPRO.NS",
        "angel_symbol":    "WIPRO",
        "dhan_symbol":     "WIPRO",
    },
    "TECHM": {
        "alert_threshold": 100,
        "strike_step":     40,
        "lot_size":        600,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "TECHM.NS",
        "angel_symbol":    "TECHM",
        "dhan_symbol":     "TECHM",
    },

    # ── Energy & Commodities ──────────────────────────────────────────────────
    "RELIANCE": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        250,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "RELIANCE.NS",
        "angel_symbol":    "RELIANCE",
        "dhan_symbol":     "RELIANCE",
    },
    "ONGC": {
        "alert_threshold": 100,
        "strike_step":     5,
        "lot_size":        2975,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "ONGC.NS",
        "angel_symbol":    "ONGC",
        "dhan_symbol":     "ONGC",
    },
    "BPCL": {
        "alert_threshold": 100,
        "strike_step":     10,
        "lot_size":        3900,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "BPCL.NS",
        "angel_symbol":    "BPCL",
        "dhan_symbol":     "BPCL",
    },
    "NTPC": {
        "alert_threshold": 100,
        "strike_step":     10,
        "lot_size":        3900,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "NTPC.NS",
        "angel_symbol":    "NTPC",
        "dhan_symbol":     "NTPC",
    },
    "COALINDIA": {
        "alert_threshold": 100,
        "strike_step":     10,
        "lot_size":        4200,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "COALINDIA.NS",
        "angel_symbol":    "COALINDIA",
        "dhan_symbol":     "COALINDIA",
    },

    # ── Auto ──────────────────────────────────────────────────────────────────
    "MARUTI": {
        "alert_threshold": 100,
        "strike_step":     200,
        "lot_size":        100,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "MARUTI.NS",
        "angel_symbol":    "MARUTI",
        "dhan_symbol":     "MARUTI",
    },
    "M&M": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        700,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "M&M.NS",
        "angel_symbol":    "M&M",
        "dhan_symbol":     "M&M",
    },

    # ── Metals & Mining ───────────────────────────────────────────────────────
    "TATASTEEL": {
        "alert_threshold": 100,
        "strike_step":     5,
        "lot_size":        5500,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "TATASTEEL.NS",
        "angel_symbol":    "TATASTEEL",
        "dhan_symbol":     "TATASTEEL",
    },
    "HINDALCO": {
        "alert_threshold": 100,
        "strike_step":     20,
        "lot_size":        2150,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "HINDALCO.NS",
        "angel_symbol":    "HINDALCO",
        "dhan_symbol":     "HINDALCO",
    },
    "JSWSTEEL": {
        "alert_threshold": 100,
        "strike_step":     20,
        "lot_size":        1350,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "JSWSTEEL.NS",
        "angel_symbol":    "JSWSTEEL",
        "dhan_symbol":     "JSWSTEEL",
    },

    # ── Pharma ────────────────────────────────────────────────────────────────
    "DRREDDY": {
        "alert_threshold": 100,
        "strike_step":     100,
        "lot_size":        125,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "DRREDDY.NS",
        "angel_symbol":    "DRREDDY",
        "dhan_symbol":     "DRREDDY",
    },
    "CIPLA": {
        "alert_threshold": 100,
        "strike_step":     20,
        "lot_size":        650,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "CIPLA.NS",
        "angel_symbol":    "CIPLA",
        "dhan_symbol":     "CIPLA",
    },

    # ── Infra / Industrials ───────────────────────────────────────────────────
    "LT": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        300,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "LT.NS",
        "angel_symbol":    "LT",
        "dhan_symbol":     "LT",
    },
    "ADANIENT": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        625,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "ADANIENT.NS",
        "angel_symbol":    "ADANIENT",
        "dhan_symbol":     "ADANIENT",
    },
    "BHARTIARTL": {
        "alert_threshold": 100,
        "strike_step":     40,
        "lot_size":        1851,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "BHARTIARTL.NS",
        "angel_symbol":    "BHARTIARTL",
        "dhan_symbol":     "BHARTIARTL",
    },

    # ── Consumer ─────────────────────────────────────────────────────────────
    "ITC": {
        "alert_threshold": 100,
        "strike_step":     10,
        "lot_size":        3200,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "ITC.NS",
        "angel_symbol":    "ITC",
        "dhan_symbol":     "ITC",
    },
    "TITAN": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        375,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "TITAN.NS",
        "angel_symbol":    "TITAN",
        "dhan_symbol":     "TITAN",
    },
    "ASIANPAINT": {
        "alert_threshold": 100,
        "strike_step":     50,
        "lot_size":        300,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "ASIANPAINT.NS",
        "angel_symbol":    "ASIANPAINT",
        "dhan_symbol":     "ASIANPAINT",
    },
    "NESTLEIND": {
        "alert_threshold": 100,
        "strike_step":     100,
        "lot_size":        400,
        "expiry_type":     "monthly",
        "yahoo_symbol":    "NESTLEIND.NS",
        "angel_symbol":    "NESTLEIND",
        "dhan_symbol":     "NESTLEIND",
    },
}
