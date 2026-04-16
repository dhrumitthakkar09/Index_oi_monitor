# NSE / BSE OI Spike Monitor

A Python application that continuously monitors Open Interest (OI) changes across **NIFTY, SENSEX, BANKNIFTY, and MIDCAP SELECT** option chains and fires real-time Telegram alerts when thresholds are breached.

Two alert types run simultaneously:
- **OI Spike Alert** — fires when OI on a single strike crosses a % threshold vs the previous day's close
- **Trending OI Alert** — fires when the aggregate Calls/Puts OI across 4 strikes fixed at the day's open price trends consistently in one direction across N consecutive polls

---

## Prerequisites

- Python 3.11+
- A Telegram bot token and chat ID
- Credentials for your chosen data source (Yahoo, Angel One, or Dhan)

---

## Quick Start

### 1. Clone & Set Up Virtual Environment

```bash
git clone <repo-url>
cd oi_monitor

python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values. Minimum required for **Yahoo Finance + Telegram**:

```env
DATA_SOURCE=YAHOO
TELEGRAM_BOT_TOKEN=7123456789:AAxxxxxx...
TELEGRAM_CHAT_ID=-1001234567890
```

### 3. Install Dependencies

Uncomment the lines in `requirements.txt` that match your `DATA_SOURCE`, then:

```bash
pip install -r requirements.txt
```

| DATA_SOURCE | Packages to uncomment |
|-------------|----------------------|
| `YAHOO`     | `yfinance`, `pandas` |
| `ANGEL`     | `smartapi-python`, `pyotp`, `websocket-client`, `logzero` |
| `DHAN`      | `websocket-client` (already uncommented) |

### 4. Run

```bash
python main.py
```

Stop with **Ctrl+C** — the monitor sends a Telegram shutdown alert and exits cleanly.

---

## Data Source Setup

### Yahoo Finance (Default — No API Key Required)

```env
DATA_SOURCE=YAHOO
POLL_INTERVAL_SECONDS=60
```

> Yahoo Finance option data has a ~15-minute delay and may not reflect live OI.

---

### Angel One SmartAPI

```env
DATA_SOURCE=ANGEL
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_MPIN=your_4_digit_mpin
ANGEL_TOTP_SECRET=your_totp_secret
```

**How to get credentials:**
1. Register at [Angel One Developer Portal](https://smartapi.angelbroking.com/)
2. Create an app to get your API key
3. Enable TOTP in your Angel One account and copy the secret

> Use your 4-digit **MPIN** — password login is deprecated.

---

### Dhan API

```env
DATA_SOURCE=DHAN
DHAN_ACCESS_TOKEN=your_access_token
DHAN_CLIENT_ID=your_client_id
```

**How to get credentials:**
1. Log in to [Dhan](https://dhan.co/)
2. Go to **My Profile → API Token → Generate**
3. Copy the access token and your client ID

---

## Telegram Bot Setup

1. Open Telegram → search `@BotFather`
2. Send `/newbot` → follow the steps → copy the **token**
3. Add your bot to a group or channel
4. Get the **chat ID**:
   - Personal chat: message `@userinfobot`
   - Group: add `@getidsbot` to the group

```env
TELEGRAM_BOT_TOKEN=7123456789:AAxxxxxx
TELEGRAM_CHAT_ID=-1001234567890   # negative number = group/channel
```

---

## Alert Types

### 1. OI Spike Alert

Fires the **first time** a single strike's OI crosses the configured threshold vs the previous day's close OI.

```
🚨 Long Buildup
──────────────────────────────
Index   : NIFTY
Strike  : 22600 CE
OI Chg  : ▲ +542.0%
Prev OI : 12,000
Curr OI : 77,040
Spot    : 22,543
Time    : 2026-03-17 11:45:02
```

**Patterns detected** (price direction vs prev-day close × OI direction):

| Pattern         | Price | OI  | Meaning                      |
|-----------------|-------|-----|------------------------------|
| Long Buildup    | ↑     | ↑   | Bulls adding fresh longs     |
| Short Covering  | ↑     | ↓   | Shorts exiting               |
| Short Buildup   | ↓     | ↑   | Bears adding fresh shorts    |
| Long Unwinding  | ↓     | ↓   | Longs exiting                |

---

### 2. Trending OI Alert *(Indices only — NIFTY, SENSEX, BANKNIFTY, MIDCAP SELECT)*

Tracks aggregate Calls OI and Puts OI across **4 strikes fixed at the day's open price**. Fires when `DIFF = Calls OI − Puts OI` moves consistently in the same direction for N consecutive polls.

**How the 4 strikes are chosen:**
- At the first poll after warm-up (effectively ~9:15 AM or monitor start), the spot price is rounded to the nearest strike step → `open_atm`
- The 4 fixed strikes for the day are: `open_atm`, `open_atm + step`, `open_atm + 2×step`, `open_atm + 3×step`
- A startup message is sent to Telegram confirming the chosen strikes
- Strikes reset at midnight

**Alert format:**
```
📈 NIFTY OI Trending Rising
──────────────────────────────
Open Price : 24,231.30
Strikes    : 24,200 · 24,250 · 24,300 · 24,350
Calls OI   : 1,35,98,975
Puts OI    : 1,35,13,695
DIFF       : +85,280  (+0.3%)
PCR        : 0.997
Polls      : 3 consecutive rising ticks
DIFF path  : +60,000 → +72,000 → +85,280
Sentiment  : 🟢 Bullish
Spot       : 24,231
Time       : 2026-04-16 15:10:00
```

**Sentiment logic:**

| DIFF direction | Meaning                              | Sentiment |
|----------------|--------------------------------------|-----------|
| DIFF rising    | Calls OI growing faster than Puts OI | 🟢 Bullish |
| DIFF falling   | Puts OI growing faster than Calls OI | 🔴 Bearish |

The alert fires **once per direction change** — a sustained trend does not repeat. If the trend reverses, a new alert fires for the opposite direction.

---

## OI Spike Thresholds

| Index         | Alert Threshold |
|---------------|-----------------|
| NIFTY         | ≥ 500%          |
| SENSEX        | ≥ 500%          |
| BANKNIFTY     | ≥ 100%          |
| MIDCAP SELECT | ≥ 100%          |

Thresholds can be changed in the `INDEX_CONFIG` section of `config.py`.

---

## Docker Deployment

```bash
# First-time setup
cp .env.example .env
# Edit .env with your credentials

# Build and start
docker-compose up -d --build

# View live logs
docker-compose logs -f

# Stop
docker-compose down

# Restart without rebuild
docker-compose restart
```

Logs and CSV data are persisted in `./logs/` and `./data/` on the host machine.

---

## Configuration Reference

| Variable                    | Default | Description                                        |
|-----------------------------|---------|----------------------------------------------------|
| `DATA_SOURCE`               | `YAHOO` | `YAHOO` / `ANGEL` / `DHAN`                         |
| `POLL_INTERVAL_SECONDS`     | `60`    | How often to poll OI (REST-based sources)          |
| `TELEGRAM_BOT_TOKEN`        | —       | Telegram bot token                                 |
| `TELEGRAM_CHAT_ID`          | —       | Target chat / group ID                             |
| `ANGEL_API_KEY`             | —       | Angel One API key                                  |
| `ANGEL_CLIENT_ID`           | —       | Angel One client ID                                |
| `ANGEL_MPIN`                | —       | Angel One 4-digit MPIN                             |
| `ANGEL_TOTP_SECRET`         | —       | Angel One TOTP secret                              |
| `DHAN_ACCESS_TOKEN`         | —       | Dhan access token                                  |
| `DHAN_CLIENT_ID`            | —       | Dhan client ID                                     |
| `LOG_LEVEL`                 | `INFO`  | `DEBUG` / `INFO` / `WARNING`                       |
| `CSV_ENABLED`               | `true`  | Write OI snapshots to CSV files                    |
| `RESPECT_MARKET_HOURS`      | `true`  | Skip polling outside 9:15–15:30 IST                |
| `WS_RECONNECT_DELAY`        | `5`     | Seconds between WebSocket reconnect attempts       |
| `WS_MAX_RECONNECT_ATTEMPTS` | `10`    | Max WebSocket reconnect retries                    |
| `STOCK_POLL_INTERVAL_SECONDS` | `600` | Poll interval for F&O stock monitor                |
| `TREND_CONSECUTIVE_POLLS`   | `3`     | Polls in same direction needed to confirm a trend  |
| `TREND_MIN_OI_CHANGE_PCT`   | `0.5`   | Min % OI shift per poll to count (noise filter)    |

---

## Project Structure

```
oi_monitor/
├── main.py               # Entry point — starts index + stock monitors
├── monitor.py            # Index OI monitoring engine (spike + trending alerts)
├── stock_monitor.py      # Stock F&O OI monitor (daemon thread)
├── config.py             # All settings (reads from .env)
├── stock_config.py       # F&O stock list and per-stock config
├── .env.example          # Environment variable template
├── requirements.txt      # Python dependencies
├── Dockerfile
├── docker-compose.yml
│
├── data_sources/
│   ├── __init__.py       # Factory — returns correct data source adapter
│   ├── base.py           # Abstract base class
│   ├── yahoo_source.py   # Yahoo Finance adapter
│   ├── angel_source.py   # Angel One SmartAPI + WebSocket adapter
│   └── dhan_source.py    # Dhan API + WebSocket adapter
│
├── alerts/
│   └── telegram_alert.py # Telegram bot dispatcher (spike + trending alerts)
│
├── utils/
│   ├── logger.py         # Rotating file + console logger
│   ├── expiry_utils.py   # Weekly/monthly expiry detection
│   ├── strike_utils.py   # ATM/ITM/OTM and open-price strike computation
│   └── csv_logger.py     # OI history CSV writer
│
├── logs/                 # Auto-created — rotating log files
└── data/                 # Auto-created — CSV OI snapshots
```

---

## Logs & CSV Output

**Logs** are written to `./logs/oi_monitor.log` (10 MB max, 5 backups):

```
2026-04-16 09:16:01 | INFO    | monitor | NIFTY: open price captured=24231.30  open_strikes=[24200, 24250, 24300, 24350]
2026-04-16 09:16:01 | INFO    | monitor | AGG OI NIFTY          calls= 81,18,630  puts= 84,86,530  diff=  -3,67,900  diff%=-2.2%  pcr=1.045
2026-04-16 11:45:02 | WARNING | monitor | 🚨 ALERT NIFTY 22600 CE  OI +542.0% (crossed 500%)
2026-04-16 11:45:02 | WARNING | monitor | 📊 AGG TREND NIFTY  dir=BULLISH  calls=135987500  puts=135136950  pcr=0.994  diff=+850550
```

**CSV snapshots** (when `CSV_ENABLED=true`) are written to `./data/`:

```
data/NIFTY_2026-04-16.csv
data/BANKNIFTY_2026-04-16.csv
```

Columns: `timestamp, index, expiry, strike, option_type, oi, prev_oi, oi_change_pct`

---

## Adding a New Index

Add an entry to `INDEX_CONFIG` in `config.py`:

```python
"FINNIFTY": {
    "alert_threshold": 200,
    "strike_step": 50,
    "lot_size": 40,
    "expiry_type": "weekly",
    "yahoo_symbol": "NIFTY_FIN_SERVICE.NS",
    "angel_symbol": "FINNIFTY",
    "dhan_symbol":  "FINNIFTY",
    "dhan_security_id": "XX",   # look up from Dhan instrument master
    "option_prefix": "FINNIFTY",
},
```

No other code changes needed. Spike alerts and trending OI tracking both activate automatically for the new index.
