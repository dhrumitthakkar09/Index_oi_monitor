"""
stock_config.py — F&O stock configurations for OI monitoring.

All angel_symbol values verified against Angel One instrument master (March 2026).
Run utils/debug_missing.py to confirm zero MISSING entries.

Lot sizes per NSE circulars. Strike steps = approximate ATM band width.
alert_threshold: 100% OI change vs day-open baseline.
"""

def _s(angel_symbol, strike_step, lot_size):
    return {
        "alert_threshold": 100,
        "strike_step":     strike_step,
        "lot_size":        lot_size,
        "expiry_type":     "monthly",
        "yahoo_symbol":    f"{angel_symbol}.NS",
        "angel_symbol":    angel_symbol,
        "dhan_symbol":     angel_symbol,
    }

STOCK_CONFIG: dict = {

    # ── Banking ───────────────────────────────────────────────────────────────
    "HDFCBANK":    _s("HDFCBANK",    50,   550),
    "ICICIBANK":   _s("ICICIBANK",   20,  1375),
    "SBIN":        _s("SBIN",        20,  1500),
    "KOTAKBANK":   _s("KOTAKBANK",   50,   400),
    "AXISBANK":    _s("AXISBANK",    20,  1200),
    "INDUSINDBK":  _s("INDUSINDBK",  20,   500),
    "BANKBARODA":  _s("BANKBARODA",  10,  4350),
    "PNB":         _s("PNB",          5,  8000),
    "CANBK":       _s("CANBK",       10,  2800),
    "UNIONBANK":   _s("UNIONBANK",    5,  8000),
    "IDFCFIRSTB":  _s("IDFCFIRSTB",   5,  5000),
    "FEDERALBNK":  _s("FEDERALBNK",   5,  5000),
    "BANDHANBNK":  _s("BANDHANBNK",  10,  3200),
    "RBLBANK":     _s("RBLBANK",     10,  3000),
    "YESBANK":     _s("YESBANK",      1, 40000),
    "AUBANK":      _s("AUBANK",      20,  1000),
    "INDIANB":     _s("INDIANB",     10,  4000),   # Indian Bank
    "BANKINDIA":   _s("BANKINDIA",   10,  4000),   # Bank of India

    # ── Finance / NBFC / Insurance ────────────────────────────────────────────
    "BAJFINANCE":  _s("BAJFINANCE",  100,   125),
    "BAJAJFINSV":  _s("BAJAJFINSV",  50,   500),
    "BAJAJHLDNG":  _s("BAJAJHLDNG", 500,    25),
    "CHOLAFIN":    _s("CHOLAFIN",    20,  1000),
    "SHRIRAMFIN":  _s("SHRIRAMFIN",  50,   400),
    "MUTHOOTFIN":  _s("MUTHOOTFIN",  50,   750),
    "LICHSGFIN":   _s("LICHSGFIN",   20,  2000),
    "ABCAPITAL":   _s("ABCAPITAL",    5,  8000),
    "MANAPPURAM":  _s("MANAPPURAM",  10,  3000),
    "SBICARD":     _s("SBICARD",     20,  1000),
    "SBILIFE":     _s("SBILIFE",     50,   750),
    "HDFCLIFE":    _s("HDFCLIFE",    20,  1000),
    "ICICIPRULI":  _s("ICICIPRULI",  20,  1500),
    "ICICIGI":     _s("ICICIGI",    100,   125),
    "LICI":        _s("LICI",        20,   700),   # LIC of India
    "HDFCAMC":     _s("HDFCAMC",   100,   150),   # HDFC AMC
    "ANGELONE":    _s("ANGELONE",    50,   400),
    "CDSL":        _s("CDSL",        50,   250),
    "BSE":         _s("BSE",         50,   250),
    "MCX":         _s("MCX",        100,   200),
    "CAMS":        _s("CAMS",        50,   250),
    "MFSL":        _s("MFSL",        20,  1000),
    "360ONE":      _s("360ONE",      50,   300),   # 360 One WAM
    "KFINTECH":    _s("KFINTECH",    10,  1500),
    "NUVAMA":      _s("NUVAMA",     100,   200),
    "PNBHOUSING":  _s("PNBHOUSING",  20,  1000),
    "LTF":         _s("LTF",          5,  7000),   # L&T Finance
    "JIOFIN":      _s("JIOFIN",      10,  3000),   # Jio Financial Services

    # ── IT / Technology ───────────────────────────────────────────────────────
    "TCS":         _s("TCS",        100,   175),
    "INFY":        _s("INFY",        40,   400),
    "HCLTECH":     _s("HCLTECH",     40,   350),
    "WIPRO":       _s("WIPRO",       10,  3000),
    "TECHM":       _s("TECHM",       40,   600),
    "LTM":         _s("LTM",        100,   150),   # LTIMindtree (angel_symbol = LTM)
    "MPHASIS":     _s("MPHASIS",    100,   175),
    "PERSISTENT":  _s("PERSISTENT", 100,   130),
    "COFORGE":     _s("COFORGE",    100,   150),
    "OFSS":        _s("OFSS",       100,   100),
    "KPITTECH":    _s("KPITTECH",    20,  1200),
    "NYKAA":       _s("NYKAA",        5,  7500),
    "PAYTM":       _s("PAYTM",       10,  2000),
    "POLICYBZR":   _s("POLICYBZR",   20,  1000),
    "NAUKRI":      _s("NAUKRI",     100,   125),
    "TATAELXSI":   _s("TATAELXSI",  200,   100),
    "TATATECH":    _s("TATATECH",    20,   800),
    "DIXON":       _s("DIXON",      100,   100),
    "KAYNES":      _s("KAYNES",     100,   100),
    "AMBER":       _s("AMBER",      100,   200),

    # ── Energy & Oil & Gas ────────────────────────────────────────────────────
    "RELIANCE":    _s("RELIANCE",    50,   250),
    "ONGC":        _s("ONGC",        10,  3850),
    "BPCL":        _s("BPCL",        10,  3750),
    "IOC":         _s("IOC",         10,  6250),
    "NTPC":        _s("NTPC",        10,  3750),
    "POWERGRID":   _s("POWERGRID",   10,  3400),
    "TATAPOWER":   _s("TATAPOWER",    5,  4500),
    "ADANIENSOL":  _s("ADANIENSOL",  10,  2800),   # Adani Energy Solutions (was ADANIPOWER)
    "ADANIGREEN":  _s("ADANIGREEN",  50,   400),
    "GAIL":        _s("GAIL",        10,  5625),
    "PETRONET":    _s("PETRONET",    10,  3000),
    "HINDPETRO":   _s("HINDPETRO",   10,  2700),
    "OIL":         _s("OIL",         20,   875),   # Oil India
    "TORNTPOWER":  _s("TORNTPOWER",  50,   500),
    "JSWENERGY":   _s("JSWENERGY",   10,  2500),
    "NHPC":        _s("NHPC",         5,  8000),
    "SUZLON":      _s("SUZLON",       5, 14000),
    "INOXWIND":    _s("INOXWIND",    10,  3000),
    "IREDA":       _s("IREDA",        5, 10000),
    "WAAREEENER":  _s("WAAREEENER",  50,   400),
    "PREMIERENE":  _s("PREMIERENE",  50,   500),
    "SOLARINDS":   _s("SOLARINDS",  100,   125),
    "INDUSTOWER":  _s("INDUSTOWER",   5,  2800),   # Indus Towers
    "POWERINDIA":  _s("POWERINDIA", 100,   100),   # Hitachi Energy India

    # ── Metals & Mining ───────────────────────────────────────────────────────
    "TATASTEEL":   _s("TATASTEEL",    5,  5500),
    "HINDALCO":    _s("HINDALCO",    10,  2100),
    "JSWSTEEL":    _s("JSWSTEEL",    20,  1350),
    "SAIL":        _s("SAIL",         5,  8500),
    "COALINDIA":   _s("COALINDIA",   10,  2700),
    "NATIONALUM":  _s("NATIONALUM",   5,  8000),
    "HINDZINC":    _s("HINDZINC",    20,  1350),
    "VEDL":        _s("VEDL",        10,  2756),
    "NMDC":        _s("NMDC",        10,  4000),
    "JINDALSTEL":  _s("JINDALSTEL",  20,   750),
    "APLAPOLLO":   _s("APLAPOLLO",   50,   400),
    "SRF":         _s("SRF",        100,   125),

    # ── Auto & Ancillaries ────────────────────────────────────────────────────
    "MARUTI":      _s("MARUTI",     200,    50),
    "M&M":         _s("M&M",         50,   350),
    "BAJAJ-AUTO":  _s("BAJAJ-AUTO",  50,   125),
    "HEROMOTOCO":  _s("HEROMOTOCO", 100,   100),
    "EICHERMOT":   _s("EICHERMOT",  100,   150),
    "TVSMOTOR":    _s("TVSMOTOR",    50,   350),
    "ASHOKLEY":    _s("ASHOKLEY",    10,  5500),
    "MOTHERSON":   _s("MOTHERSON",    5,  7500),
    "BOSCHLTD":    _s("BOSCHLTD",   500,    25),
    "BHARATFORG":  _s("BHARATFORG",  50,   500),
    "EXIDEIND":    _s("EXIDEIND",    10,  3600),
    "TIINDIA":     _s("TIINDIA",     50,   300),
    "SONACOMS":    _s("SONACOMS",    10,  2000),   # Sona BLW Precision
    "UNOMINDA":    _s("UNOMINDA",    10,  1000),   # Uno Minda
    "INDIGO":      _s("INDIGO",     100,   150),   # IndiGo / InterGlobe Aviation

    # ── FMCG & Consumer ───────────────────────────────────────────────────────
    "ITC":         _s("ITC",         10,  3200),
    "NESTLEIND":   _s("NESTLEIND",  100,   100),
    "HINDUNILVR":  _s("HINDUNILVR",  50,   300),
    "BRITANNIA":   _s("BRITANNIA",  100,   125),
    "DABUR":       _s("DABUR",       20,  1250),
    "MARICO":      _s("MARICO",      20,  1500),
    "GODREJCP":    _s("GODREJCP",    20,  1000),
    "COLPAL":      _s("COLPAL",      50,   350),
    "VBL":         _s("VBL",         20,  1000),
    "TATACONSUM":  _s("TATACONSUM",  20,   900),
    "JUBLFOOD":    _s("JUBLFOOD",    50,   750),
    "UNITDSPR":    _s("UNITDSPR",    50,   400),   # United Spirits
    "UPL":         _s("UPL",         20,  1300),
    "PATANJALI":   _s("PATANJALI",   50,   500),

    # ── Pharma & Healthcare ───────────────────────────────────────────────────
    "SUNPHARMA":   _s("SUNPHARMA",   50,   350),
    "DRREDDY":     _s("DRREDDY",    100,   125),
    "CIPLA":       _s("CIPLA",       20,  1300),
    "DIVISLAB":    _s("DIVISLAB",   100,   100),
    "BIOCON":      _s("BIOCON",       5,  4375),
    "AUROPHARMA":  _s("AUROPHARMA",  20,   700),
    "TORNTPHARM":  _s("TORNTPHARM", 100,   150),
    "LUPIN":       _s("LUPIN",       50,   400),
    "ALKEM":       _s("ALKEM",      100,   100),
    "MAXHEALTH":   _s("MAXHEALTH",   20,  1000),
    "APOLLOHOSP":  _s("APOLLOHOSP",  50,   200),
    "FORTIS":      _s("FORTIS",      10,  2000),
    "GLENMARK":    _s("GLENMARK",    20,   600),
    "ZYDUSLIFE":   _s("ZYDUSLIFE",   20,  1000),
    "MANKIND":     _s("MANKIND",     50,   300),
    "LAURUSLABS":  _s("LAURUSLABS",  10,  2000),
    "SYNGENE":     _s("SYNGENE",     20,  1500),
    "PPLPHARMA":   _s("PPLPHARMA",   10,  2000),   # Piramal Pharma

    # ── Paints & Chemicals ────────────────────────────────────────────────────
    "ASIANPAINT":  _s("ASIANPAINT",  50,   200),
    "PIDILITIND":  _s("PIDILITIND",  50,   200),
    "PIIND":       _s("PIIND",       50,   500),

    # ── Capital Goods & Defence ───────────────────────────────────────────────
    "LT":          _s("LT",          50,   175),
    "BHEL":        _s("BHEL",         5,  7500),
    "SIEMENS":     _s("SIEMENS",    100,   100),
    "ABB":         _s("ABB",        100,   100),
    "HAVELLS":     _s("HAVELLS",     20,   500),
    "VOLTAS":      _s("VOLTAS",      20,   500),
    "BLUESTARCO":  _s("BLUESTARCO",  50,   250),
    "CUMMINSIND":  _s("CUMMINSIND",  50,   300),
    "BEL":         _s("BEL",         10,  3750),
    "HAL":         _s("HAL",        100,   100),
    "MAZDOCK":     _s("MAZDOCK",    100,   100),   # Mazagon Dock
    "BDL":         _s("BDL",         50,   300),   # Bharat Dynamics
    "CGPOWER":     _s("CGPOWER",     10,  1500),
    "POLYCAB":     _s("POLYCAB",     50,   175),
    "KEI":         _s("KEI",         25,   750),
    "SUPREMEIND":  _s("SUPREMEIND",  50,   250),
    "PGEL":        _s("PGEL",        50,   500),   # PG Electroplast

    # ── Infrastructure & Real Estate ──────────────────────────────────────────
    "ADANIENT":    _s("ADANIENT",    50,   350),
    "ADANIPORTS":  _s("ADANIPORTS",  50,   625),
    "DLF":         _s("DLF",         10,  3750),
    "OBEROIRLTY":  _s("OBEROIRLTY",  50,   400),
    "GODREJPROP":  _s("GODREJPROP",  50,   325),
    "PRESTIGE":    _s("PRESTIGE",    20,  1000),
    "PHOENIXLTD":  _s("PHOENIXLTD",  50,   350),
    "LODHA":       _s("LODHA",       20,  1200),   # Macrotech Developers
    "PFC":         _s("PFC",         10,  2700),
    "RECLTD":      _s("RECLTD",      10,  2580),
    "IRFC":        _s("IRFC",         5,  8000),
    "GMRAIRPORT":  _s("GMRAIRPORT",   5, 10000),  # GMR Airports (was GMRINFRA)
    "HUDCO":       _s("HUDCO",       10,  5000),
    "NBCC":        _s("NBCC",         5,  4000),
    "GRASIM":      _s("GRASIM",      50,   275),

    # ── Telecom ───────────────────────────────────────────────────────────────
    "BHARTIARTL":  _s("BHARTIARTL",  40,   500),
    "IDEA":        _s("IDEA",         1, 71250),

    # ── Retail & Consumer ─────────────────────────────────────────────────────
    "TITAN":       _s("TITAN",        50,   375),
    "TRENT":       _s("TRENT",        50,   275),
    "DMART":       _s("DMART",        50,   175),
    "PAGEIND":     _s("PAGEIND",     500,    15),
    "KALYANKJIL":  _s("KALYANKJIL",   5,  5600),

    # ── Cement ───────────────────────────────────────────────────────────────
    "ULTRACEMCO":  _s("ULTRACEMCO",  100,   100),
    "SHREECEM":    _s("SHREECEM",    200,    25),
    "AMBUJACEM":   _s("AMBUJACEM",   10,  3800),
    "DALBHARAT":   _s("DALBHARAT",   50,   200),

    # ── Hotels & Leisure ─────────────────────────────────────────────────────
    "INDHOTEL":    _s("INDHOTEL",    10,  2000),

    # ── Logistics ────────────────────────────────────────────────────────────
    "CONCOR":      _s("CONCOR",      10,   600),
    "DELHIVERY":   _s("DELHIVERY",   10,  2800),
    "RVNL":        _s("RVNL",        10,  4500),

    # ── Diversified ───────────────────────────────────────────────────────────
    "ASTRAL":      _s("ASTRAL",      50,   300),
    "CROMPTON":    _s("CROMPTON",    20,  1000),
    "SAMMAANCAP":  _s("SAMMAANCAP",   5, 10000),
    "IEX":         _s("IEX",          5,  3750),   # Indian Energy Exchange
    "SWIGGY":      _s("SWIGGY",      10,  3500),
    "ETERNAL":     _s("ETERNAL",     10,  4500),   # Zomato (renamed to Eternal)
    "TMPV":        _s("TMPV",         5,  3000),   # Tata Motors PV (passenger vehicles subsidiary)
}
