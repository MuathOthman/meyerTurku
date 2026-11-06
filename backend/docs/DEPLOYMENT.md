# Deploying Keel

Keel needs no database and no GPU. It runs on an engineer's laptop or an internal server.

## Option 1: Python

Requires Python 3.11 or newer.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
scripts/get_data.sh                       # downloads the public RCRV drawing
.venv/bin/keel extract data/decks/rcrv_01_level.yaml --out data/processed/deck01.json
.venv/bin/keel serve                      # http://127.0.0.1:8000
```

## Option 2: Docker

```bash
cd backend
docker compose up --build                 # http://localhost:8000
```

The first start downloads the drawing and builds the ship model, which takes about a minute.

## Choosing the LLM

Measurements and verdicts never use an LLM, so Keel works with none. The LLM only names rooms
the keyword table does not know, and writes optional notes on findings.

| `KEEL_LLM_PROVIDER` | Where data goes | Use for |
|---|---|---|
| `none` | Nowhere | Air-gapped use. Unknown rooms go to review |
| `ollama` | Your machine or server | Production, on your own or European compute |
| `openai` | OpenAI | Hackathon demo, with public data only. The default if `api_chatgpt` is set |
| `gemini` | Google | Alternative for the demo, with public data only |

What an LLM receives: OCR label text, the text of finished findings, and for `keel analyze`, **images
of the drawing** when spaces have no readable label. Use `--no-ai`, `none` or `ollama` for private
drawings. OCR itself runs locally through ONNX Runtime.

The Gemini free tier allows 20 requests per model per day, and one `analyze` run can use several.
Answers are cached in `data/processed/llm_cache`, so repeating a run costs nothing. Use a paid key
for anything beyond light testing.

Uploads are stored in `data/processed/analyses`, and are not deleted automatically.

For a local model:

```bash
KEEL_LLM_PROVIDER=ollama docker compose --profile local up --build
docker compose exec ollama ollama pull mistral
```

## Adding a deck

Copy `data/decks/rcrv_01_level.yaml` and set the PDF, page, plan region, the two known dimensions
for calibration, and the reviewed labels. Calibration refuses to run if the two dimensions disagree
by more than 0.5%.

Wall and text line weights in `keel/rooms.py` and `keel/labels.py` are specific to this drawing's
CAD standard. A drawing from another CAD standard needs them reviewed.

## Not included

Login and role-based access are out of scope, as agreed with Meyer. The server has no
authentication, so keep it on a trusted network.

## Tests

```bash
.venv/bin/python -m pytest
```
