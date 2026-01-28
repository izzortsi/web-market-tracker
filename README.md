# Web Market Tracker (Kafka + Dash)

Python-only stack with Kafka ingestion + processing and a Dash UI.

## Structure
- `backend/`: Binance ingestion, Kafka processor, FastAPI summary API
- `dashboard/`: Dash UI
- `stored/`: Parquet output (raw + processed)
- `legacy-node/`: Previous Node/React implementation (archived)

## Prerequisites
- Kafka broker running at `localhost:9092`
- Python 3.11+ recommended

## Install
Backend:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dashboard:
```bash
cd dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run order
1) Start Kafka (broker + zookeeper or KRaft as configured locally).
2) Start ingestion (WebSocket → Kafka raw):
```bash
cd backend
./run_ingest.sh
```
3) Start processor + API (Kafka consumer + FastAPI):
```bash
cd backend
./run_api.sh
```
4) Start Dash UI:
```bash
cd dashboard
./run_dash.sh
```

Dash defaults to `http://localhost:8050`.  
API defaults to `http://localhost:8000/api/market/summary`.

## Notes
- Raw ticks are written to `stored/raw/` as Parquet.
- Processed features (5s bars + pandas_ta indicators) go to `stored/processed/`.
- Topics and partition counts are defined in `backend/app/config.py`.
