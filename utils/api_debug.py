"""
utils/api_debug.py — Targeted OI pipeline diagnostic.
Run: python utils/api_debug.py
"""
from __future__ import annotations
import os, sys, json, re, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
import config

BASE      = "https://apiconnect.angelone.in"
QUOTE_URL = f"{BASE}/rest/secure/angelbroking/market/v1/quote/"
MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
SEP = "─" * 65

def strip_bearer(t):
    return t[len("Bearer "):] if t.startswith("Bearer ") else t

def login():
    print(f"\n{SEP}\nSTEP 1: Login\n{SEP}")
    import pyotp
    from SmartApi import SmartConnect
    s    = SmartConnect(api_key=config.ANGEL_API_KEY)
    totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
    d    = s.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_MPIN, totp)
    tok  = strip_bearer(d["data"]["jwtToken"])
    print(f"  ✓ Login OK")
    return tok, config.ANGEL_API_KEY

def hdrs(tok, key):
    return {
        "Authorization": f"Bearer {tok}", "Content-Type": "application/json",
        "Accept": "application/json", "X-UserType": "USER", "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "AA:BB:CC:DD:EE:FF", "X-PrivateKey": key
    }

# ── Step 2: Show what expiries the monitor is currently using ─────────────────
def show_active_expiries():
    print(f"\n{SEP}\nSTEP 2: Active expiries right now\n{SEP}")
    import stock_config as sc
    from utils.expiry_utils import get_current_expiry, expiry_to_nse_str
    from data_sources.angel_source import AngelDataSource

    for sym, cfg in config.INDEX_CONFIG.items():
        exp = get_current_expiry(sym, cfg["expiry_type"])
        nse = expiry_to_nse_str(exp)
        nfo = AngelDataSource._normalise_expiry(nse)
        print(f"  {sym:15s}  type={cfg['expiry_type']:8s}  NSE={nse:12s}  NFO_key={nfo}")

    print()
    for sym in list(sc.STOCK_CONFIG.keys())[:5]:
        cfg = sc.STOCK_CONFIG[sym]
        exp = get_current_expiry(sym, cfg["expiry_type"])
        nse = expiry_to_nse_str(exp)
        nfo = AngelDataSource._normalise_expiry(nse)
        print(f"  {sym:15s}  type={cfg['expiry_type']:8s}  NSE={nse:12s}  NFO_key={nfo}")
    print(f"  (+ {len(sc.STOCK_CONFIG)-5} more stocks, all monthly)")

# ── Step 3: Download master and show what expiries exist per symbol ───────────
def show_master_expiries():
    print(f"\n{SEP}\nSTEP 3: What expiries exist in master for each symbol\n{SEP}")
    import stock_config as sc
    from data_sources.angel_source import _NFO_SYMBOL_RE

    print("  Downloading master...")
    r      = requests.get(MASTER_URL, timeout=45)
    master = r.json()
    print(f"  ✓ {len(master):,} records")

    all_cfg = {v["angel_symbol"].upper(): k
               for k, v in {**config.INDEX_CONFIG, **sc.STOCK_CONFIG}.items()}

    # Collect all expiries per symbol from the master
    from collections import defaultdict
    expiries_by_sym = defaultdict(set)
    tokens_by_key   = {}

    for rec in master:
        sym = str(rec.get("symbol", ""))
        m   = _NFO_SYMBOL_RE.match(sym)
        if not m:
            continue
        underlying = m.group(1)
        if underlying not in all_cfg:
            continue
        expiry_nfo = m.group(2)
        strike     = int(m.group(3))
        opt_type   = m.group(4)
        cfg_key    = all_cfg[underlying]
        exch       = str(rec.get("exch_seg", "")).upper()
        expiries_by_sym[cfg_key].add(expiry_nfo)
        tokens_by_key[(cfg_key, expiry_nfo, strike, opt_type)] = (rec.get("token"), exch)

    print(f"\n  {'Symbol':15s}  Expiries available in master")
    for sym in list(config.INDEX_CONFIG.keys()) + ["HDFCBANK","BANKNIFTY","SBIN","TCS"]:
        expiries = sorted(expiries_by_sym.get(sym, []))
        print(f"  {sym:15s}  {expiries}")

    return tokens_by_key

# ── Step 4: For each failing symbol, check if the lookup key exists ───────────
def check_token_map_mismatches(tokens_by_key):
    print(f"\n{SEP}\nSTEP 4: Token lookup mismatch check\n{SEP}")
    import stock_config as sc
    from utils.expiry_utils import get_current_expiry, expiry_to_nse_str
    from data_sources.angel_source import AngelDataSource

    # Simulate the exact lookup keys the monitor uses
    test_cases = [
        # (config_key, strike)  — use a plausible strike
        ("NIFTY",        24600),
        ("BANKNIFTY",    58700),
        ("SENSEX",       79400),
        ("MIDCAPSELECT", 13100),
        ("HDFCBANK",     850),
        ("ICICIBANK",    1360),
        ("SBIN",         1160),
        ("TCS",          2600),
    ]

    for cfg_key, strike in test_cases:
        cfg     = {**config.INDEX_CONFIG, **sc.STOCK_CONFIG}.get(cfg_key, {})
        exp     = get_current_expiry(cfg_key, cfg.get("expiry_type", "monthly"))
        nse_str = expiry_to_nse_str(exp)
        nfo_key_str = AngelDataSource._normalise_expiry(nse_str)
        lookup_key  = (cfg_key, nfo_key_str, strike, "CE")
        found       = lookup_key in tokens_by_key
        token_info  = tokens_by_key.get(lookup_key, ("MISSING", "?"))
        print(f"  {'✓' if found else '✗'} {cfg_key:15s}  key=({nfo_key_str},{strike},CE)  "
              f"token={token_info[0]}  exch={token_info[1]}")

# ── Step 5: Live API test for a found token ───────────────────────────────────
def test_live_oi(tok, key, tokens_by_key):
    print(f"\n{SEP}\nSTEP 5: Live Quote FULL test for failing symbols\n{SEP}")
    import stock_config as sc
    from utils.expiry_utils import get_current_expiry, expiry_to_nse_str
    from data_sources.angel_source import AngelDataSource

    h = hdrs(tok, key)
    test_syms = ["NIFTY", "BANKNIFTY", "SENSEX", "HDFCBANK", "SBIN"]

    for cfg_key in test_syms:
        cfg     = {**config.INDEX_CONFIG, **sc.STOCK_CONFIG}.get(cfg_key, {})
        exp     = get_current_expiry(cfg_key, cfg.get("expiry_type", "monthly"))
        nse_str = expiry_to_nse_str(exp)
        nfo_key = AngelDataSource._normalise_expiry(nse_str)

        # Find ANY token for this symbol+expiry
        candidates = [(k, v) for k, v in tokens_by_key.items()
                      if k[0] == cfg_key and k[1] == nfo_key]
        if not candidates:
            # Try any expiry
            candidates = [(k, v) for k, v in tokens_by_key.items() if k[0] == cfg_key]
            if not candidates:
                print(f"  {cfg_key:15s}  NO TOKENS IN MAP AT ALL")
                continue
            # Use first available expiry
            (cfg_k, exp_k, strike_k, type_k), (token, exch) = candidates[0]
            print(f"  {cfg_key:15s}  WARNING: using expiry={exp_k} (monitor wants {nfo_key})")
        else:
            (cfg_k, exp_k, strike_k, type_k), (token, exch) = candidates[0]

        print(f"  Testing {cfg_key} {exp_k} {strike_k}{type_k} token={token} exch={exch}")
        try:
            r    = requests.post(QUOTE_URL, headers=h, timeout=10,
                                 json={"mode":"FULL","exchangeTokens":{exch:[str(token)]}})
            print(f"    HTTP {r.status_code}")
            body    = r.json()
            fetched = body.get("data",{}).get("fetched",[])
            if fetched:
                row = fetched[0]
                oi  = row.get("opnInterest") or row.get("openInterest") or row.get("oi","NOT_FOUND")
                print(f"    ✓ OI={oi}  ltp={row.get('ltp')}  keys={list(row.keys())}")
            else:
                print(f"    ✗ Empty fetched. Full body: {json.dumps(body)[:300]}")
        except Exception as e:
            print(f"    ✗ Exception: {e}")
        print()

if __name__ == "__main__":
    show_active_expiries()
    tokens_by_key = show_master_expiries()
    check_token_map_mismatches(tokens_by_key)
    tok, key = login()
    test_live_oi(tok, key, tokens_by_key)
    print(f"\n{SEP}\nDONE\n{SEP}")
