# Aegis — Autonomous AI Browser Agent

Aegis is a Python-based autonomous browser agent that drives real Chromium via Playwright and uses AI reasoning to complete tasks described in plain English. It observes, reasons, and acts step-by-step — adapting to whatever page state it encounters.

## Features

- **Autonomous browsing** — Give it a task in English, watch it navigate, click, type, and extract data
- **Real browser** — Drives Chromium via Playwright (not a scraper or HTML parser)
- **Safety layer** — Destructive actions (purchases, deletions, form submissions) require explicit human confirmation
- **Dual interface** — Both CLI and Web UI, sharing the same core engine
- **Loop detection** — Automatically stops if stuck repeating actions or hitting errors
- **Session history** — All tasks and steps stored in SQLite for review

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### Installation

```bash
# Clone and enter the project
cd aegis

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Set up configuration
cp .env.example .env
# Edit .env if needed (defaults work out of the box)
```

### CLI Usage

```bash
# Run a task
python -m cli.main run "search DuckDuckGo for 'Playwright Python' and tell me the first result"

# Run with visible browser (non-headless)
python -m cli.main run "find the weather in New York" --no-headless

# Run with custom step limit
python -m cli.main run "extract the top 3 headlines from news.ycombinator.com" --max-steps 15

# View past sessions
python -m cli.main history

# View details of a specific session
python -m cli.main history <session_id>
```

### Web UI Usage

```bash
# Start the server
uvicorn web.backend.app:app --reload

# Open http://localhost:8000 in your browser
```

The Web UI provides:
- Chat-style task input
- Live step-by-step agent log
- Screenshot viewer updating each step
- Confirmation dialogs for destructive actions
- Headless/headed toggle and max-steps control

## Example Tasks

1. **Search & Extract:**
   ```
   search DuckDuckGo for 'best Python frameworks 2024' and extract the first 3 result titles
   ```

2. **Navigate & Read:**
   ```
   go to news.ycombinator.com and tell me the top 5 headlines
   ```

3. **Multi-step Interaction:**
   ```
   go to wikipedia.org, search for 'artificial intelligence', and extract the first paragraph of the article
   ```

## Configuration

All settings in `.env` (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `SPECTRIX_WORKER_URL` | `https://spectrix-worker.tariqmtaezeem.workers.dev/` | AI reasoning backend |
| `AI_MODEL` | `moonshotai/kimi-k2.6:free` | Model for AI reasoning |
| `MAX_STEPS_DEFAULT` | `25` | Default max steps per task |
| `HEADLESS_DEFAULT` | `true` | Default browser visibility |
| `DB_PATH` | `./data/aegis.db` | SQLite database path |
| `SCREENSHOT_MAX_WIDTH` | `1280` | Screenshot downscale width |
| `DOM_TOKEN_BUDGET` | `3000` | Max tokens for DOM summary |

## Architecture

```
aegis/
├── core/                    # Core engine (shared by CLI and Web UI)
│   ├── agent.py             # Main agent loop orchestrator
│   ├── browser.py           # Playwright wrapper + condensed DOM extraction
│   ├── ai_client.py         # Spectrix Worker client + prompt construction
│   ├── actions.py           # Action schema + defensive JSON parsing
│   ├── history.py           # SQLite session/action storage
│   └── safety.py            # Destructive action classifier
├── cli/
│   └── main.py              # CLI entrypoint (aegis run / aegis history)
├── web/
│   ├── backend/
│   │   ├── app.py           # FastAPI + WebSocket server
│   │   └── routes.py        # REST + WebSocket endpoints
│   └── frontend/
│       ├── index.html        # Single-page UI
│       ├── style.css         # Dark theme
│       └── app.js            # WebSocket client
├── config/
│   └── settings.py          # Centralized configuration
├── tests/                   # Test suite
├── data/                    # SQLite DB (created at runtime)
├── requirements.txt
└── .env.example
```

## Safety

Aegis includes a mandatory safety layer that **cannot be bypassed**:

- **Non-destructive** actions (navigate, click, scroll, type, read, screenshot) execute automatically
- **Destructive** actions (purchase, delete, submit, transfer, payment) pause and require explicit confirmation
- The safety classifier runs independently of the AI's own assessment — it never trusts the AI's `is_destructive` flag
- Default confirmation answer is **No** (you must explicitly type `y` or click Confirm)

## Running Tests

```bash
python -m pytest tests/ -v
```

## Deviations from Spec

None. All architecture decisions follow the spec exactly:
- Playwright (not Selenium)
- FastAPI backend
- All AI calls through Spectrix Worker (no direct API calls)
- SQLite for storage
- Safety layer cannot be globally disabled

## Built By

Muhammad Taezeem Tariq (Tony) — extending the agent-loop architecture from Ultron into browser-scoped autonomous operation.
