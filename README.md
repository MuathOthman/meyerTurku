# Keel: compliance checking for ship drawings

**AI reads, code measures, engineer decides.** Built for the Meyer Turku challenge at Since AI
Hackathon 2026.

| Folder | What | Stack |
|---|---|---|
| [`backend/`](backend/README.md) | Reads drawings, measures, checks rules, gives verdicts | Python, FastAPI |
| [`frontend/`](frontend/README.md) | The web app. Shows the backend's results, holds no compliance logic | React, Vite |

## Run it

First time only:

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
scripts/get_data.sh
.venv/bin/keel extract data/decks/rcrv_01_level.yaml --out data/processed/deck01.json
cd ..
cp .env.example .env     # optional: add an LLM key. Measurements and verdicts never use it
```

User accounts are stored in MongoDB, so logging in needs one running. On a Mac:

```bash
brew tap mongodb/brew
brew trust --formula mongodb/brew/mongodb-community
brew install mongodb-community --without-mongodb-database-tools
brew services start mongodb-community
```

Or set `MONGODB_URI` in `.env` to use a database elsewhere.

Then, from the project folder:

```bash
./dev.sh                 # http://localhost:5173
```

## Run it as one server

The backend can host the built frontend, so a demo needs one process and one port:

```bash
npm --prefix frontend install && npm --prefix frontend run build
cd backend && .venv/bin/keel serve    # http://127.0.0.1:8000
```

Or with Docker: `cd backend && docker compose up --build`. See
[backend/docs/DEPLOYMENT.md](backend/docs/DEPLOYMENT.md).

## Tests

```bash
cd backend && .venv/bin/python -m pytest
cd frontend && npm test
```
