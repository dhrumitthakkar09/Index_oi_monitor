# NSE / BSE OI Spike Monitor 🚨

A production-ready Python application that continuously monitors Open Interest (OI) changes across NIFTY, SENSEX, BANKNIFTY, and MIDCAP SELECT option chains and fires real-time Telegram alerts when thresholds are breached.

---

## Folder Structure

```
oi_monitor/
├── main.py                   # Entry point
├── monitor.py                # Core monitoring engine
├── config.py                 # All settings (reads from .env)
├── .env.example              # Environment variable template
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── data_sources/
│   ├── __init__.py           # Factory — returns correct adapter
│   ├── base.py               # Abstract base class
│   ├── yahoo_source.py       # Yahoo Finance (yfinance)
│   ├── angel_source.py       # Angel One SmartAPI + WebSocket
│   └── dhan_source.py        # Dhan API + WebSocket
│
├── alerts/
│   ├── __init__.py
│   └── telegram_alert.py     # Telegram bot dispatcher
│
├── utils/
│   ├── __init__.py
│   ├── logger.py             # Rotating file + console logger
│   ├── expiry_utils.py       # Weekly/monthly expiry detection
│   ├── strike_utils.py       # ATM/ITM/OTM strike computation
│   └── csv_logger.py         # OI history CSV writer
│
├── logs/                     # Auto-created at runtime
│   └── oi_monitor.log
└── data/                     # Auto-created at runtime
    └── NIFTY_2026-02-21.csv
```

---

## Alert Thresholds

| Index         | OI Change Alert Threshold |
|---------------|--------------------------|
| NIFTY         | ≥ 500%                   |
| SENSEX        | ≥ 500%                   |
| BANKNIFTY     | ≥ 100%                   |
| MIDCAP SELECT | ≥ 100%                   |

For each index, the system monitors **ATM, 1 ITM, and 1 OTM** strikes for both **CE and PE**.

---

## Quick Start

### 1. Clone & Install

```bash
git clone <repo>
cd oi_monitor

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
nano .env                       # fill in your values
```

Minimum required for Yahoo + Telegram:

```env
DATA_SOURCE=YAHOO
TELEGRAM_BOT_TOKEN=7123456789:AAxxxxxx...
TELEGRAM_CHAT_ID=-1001234567890
```

### 3. Run

```bash
python main.py
```

---

## Data Source Configuration

### Yahoo Finance (Default — No API Key Needed)

```env
DATA_SOURCE=YAHOO
POLL_INTERVAL_SECONDS=60
```

> ⚠️ Yahoo Finance option data has ~15-minute delay and may not reflect live OI.

---

### Angel One SmartAPI

```bash
pip install smartapi-python pyotp websocket-client
```

```env
DATA_SOURCE=ANGEL
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_password
ANGEL_TOTP_SECRET=your_totp_secret
```

**How to get credentials:**
1. Register at [Angel One Developer](https://smartapi.angelbroking.com/)
2. Create an app → get API key
3. Enable TOTP in your account → copy the secret

---

### Dhan API

```bash
pip install dhanhq
```

```env
DATA_SOURCE=DHAN
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

**How to get credentials:**
1. Log in to [Dhan](https://dhan.co/)
2. Go to My Profile → API Token → Generate

---

## Telegram Bot Setup

1. Open Telegram → search `@BotFather`
2. Send `/newbot` → follow instructions → copy the **token**
3. Add the bot to a group/channel
4. Get your **chat ID**:
   - For personal: message `@userinfobot`
   - For group: add `@getidsbot` to the group

```env
TELEGRAM_BOT_TOKEN=7123456789:AAxxxxxx
TELEGRAM_CHAT_ID=-1001234567890   # negative = group/channel
```

### Alert Format

```
🚨 OI SPIKE ALERT
Index: NIFTY
Strike: 22600 CE
OI Change: 542.0%
Old OI: 12,000
New OI: 77,040
Time: 2026-02-21 11:45:02
```

---

## Docker Deployment

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

Logs and CSV data are persisted in `./logs/` and `./data/` on the host.

---

## Configuration Reference

| Variable                  | Default  | Description                          |
|---------------------------|----------|--------------------------------------|
| `DATA_SOURCE`             | `YAHOO`  | `YAHOO` / `ANGEL` / `DHAN`           |
| `POLL_INTERVAL_SECONDS`   | `60`     | How often to poll OI (REST sources)  |
| `TELEGRAM_BOT_TOKEN`      | —        | Telegram bot token                   |
| `TELEGRAM_CHAT_ID`        | —        | Target chat/group ID                 |
| `LOG_LEVEL`               | `INFO`   | `DEBUG` / `INFO` / `WARNING`         |
| `CSV_ENABLED`             | `true`   | Write OI snapshots to CSV            |
| `RESPECT_MARKET_HOURS`    | `true`   | Skip polling outside 9:15–15:30 IST  |
| `WS_RECONNECT_DELAY`      | `5`      | Seconds between reconnect attempts   |
| `WS_MAX_RECONNECT_ATTEMPTS` | `10`  | Max WS reconnect tries               |

---

## Adding a New Index

In `config.py`, add an entry to `INDEX_CONFIG`:

```python
"FINNIFTY": {
    "alert_threshold": 200,
    "strike_step": 50,
    "lot_size": 40,
    "expiry_type": "weekly",
    "yahoo_symbol": "NIFTY_FIN_SERVICE.NS",
    "angel_symbol": "FINNIFTY",
    "dhan_symbol": "FINNIFTY",
    "option_prefix": "FINNIFTY",
},
```

No other code changes needed — the engine picks it up automatically.

---

## Adding a New Data Source

1. Create `data_sources/my_source.py` extending `BaseDataSource`
2. Implement `get_spot_price()` and `get_option_oi()`
3. Register in `data_sources/__init__.py`:

```python
elif source == "MY_SOURCE":
    from data_sources.my_source import MyDataSource
    return MyDataSource()
```

4. Set `DATA_SOURCE=MY_SOURCE` in `.env`

---

## CSV OI History

When `CSV_ENABLED=true`, daily CSV files are written to `./data/`:

```
data/NIFTY_2026-02-21.csv
data/BANKNIFTY_2026-02-21.csv
```

Columns: `timestamp, index, expiry, strike, option_type, oi, prev_oi, oi_change_pct`

---

## Logs

Rotating log files in `./logs/oi_monitor.log` (10 MB max, 5 backups):

```
2026-02-21 11:45:01 | INFO     | monitor | NIFTY  spot=22543.10  ATM=22550  ITM=22500  OTM=22600
2026-02-21 11:45:02 | WARNING  | monitor | 🚨 ALERT NIFTY 22600 CE  OI +542.0%  old=12000  new=77040
2026-02-21 11:45:02 | INFO     | telegram_alert | Telegram alert sent: NIFTY 22600 CE OI +542.0%
```
# Index_oi_monitor
