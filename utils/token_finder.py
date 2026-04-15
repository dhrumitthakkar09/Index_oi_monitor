"""
utils/token_finder.py — One-time diagnostic: find correct Angel One tokens.

Run this ONCE to see exactly what the instrument master contains for each
configured symbol. Output tells you:
  • Which token and exchange to expect for each symbol
  • Whether the symbol was found (and under what variant e.g. BHARTIARTL-EQ)
  • Sample of the option chain response to confirm underlyingValue field name

Usage (from project root):
    python utils/token_finder.py

No credentials needed — downloads a public file from Angel One.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import config
import stock_config


SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com"
    "/OpenAPI_File/files/OpenAPIScripMaster.json"
)


def main() -> None:
    print("=" * 65)
    print("  Angel One Token Finder")
    print("=" * 65)
    print(f"\nDownloading instrument master from:\n  {SCRIP_MASTER_URL}\n")

    try:
        resp   = requests.get(SCRIP_MASTER_URL, timeout=30)
        resp.raise_for_status()
        master = resp.json()
    except Exception as e:
        print(f"ERROR: Could not download master: {e}")
        sys.exit(1)

    print(f"Downloaded {len(master):,} records\n")

    all_cfg = {**config.INDEX_CONFIG, **stock_config.STOCK_CONFIG}

    print(f"{'Symbol':<18} {'Token':>8}  {'Exch':5} {'Type':12} {'Master symbol'}")
    print("─" * 65)

    not_found = []
    for cfg_key in sorted(all_cfg):
        angel_sym = all_cfg[cfg_key]["angel_symbol"].upper()

        # Try bare symbol AND symbol-EQ
        candidates = []
        for record in master:
            raw   = str(record.get("symbol", "")).upper()
            bare  = raw.replace("-EQ", "")
            exch  = str(record.get("exch_seg", "")).upper()
            itype = str(record.get("instrumenttype", "")).upper()

            if bare != angel_sym:
                continue
            if exch not in ("NSE", "BSE"):
                continue
            if itype not in ("", "EQ", "-", "EQUITIES", "AMXIDX"):
                continue

            candidates.append(record)

        if candidates:
            for r in candidates[:3]:
                eq_marker = " ← preferred" if r.get("symbol","").upper().endswith("-EQ") else ""
                print(f"  {cfg_key:<16} {r.get('token','?'):>8}  "
                      f"{r.get('exch_seg','?'):5} "
                      f"{r.get('instrumenttype','?'):12} "
                      f"{r.get('symbol','?')}{eq_marker}")
        else:
            print(f"  {cfg_key:<16} {'NOT FOUND':>8}  "
                  f"{'':5} {'':12} angel_symbol={angel_sym}")
            not_found.append(cfg_key)

    print()
    if not_found:
        print(f"⚠  Not found in master ({len(not_found)}): {not_found}")
        print("   Check the angel_symbol values in config.py / stock_config.py")
    else:
        print("✓  All symbols resolved in instrument master")

    print(f"\n{'=' * 65}")
    print("  Next step: restart the app — token map builds automatically.")
    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    main()
