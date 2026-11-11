# Z-Wave Observatory

A browser-based Z-Wave network health observatory. It builds an interactive mesh map of your Z-Wave network, scores the health of each node from Z-Wave JS statistics and InfluxDB history, ranks the problems it finds, and offers guarded remediation actions you confirm before anything runs. An optional LLM advisor reviews the same data and proposes fixes as schema-validated actions, always with a human in the loop.

## Features

- Interactive mesh map of your Z-Wave network, with routing neighbors and signal quality
- Per-node health scoring computed from Z-Wave JS statistics (failed pings, command timeouts, retransmits) and InfluxDB history (battery levels, flapping, offline windows)
- Ranked problem list: the worst nodes and links first, with the evidence behind each finding
- Guarded remediation actions: every change requires an explicit confirmation, one mutation runs at a time, and every action is written to an audit log
- Optional LLM advisor: provider-agnostic, proposes schema-validated fixes, and never acts on its own
- Single container, one port, no external database to run

## Quick start

```bash
git clone https://github.com/scottkidder/zwave-observatory.git
cd zwave-observatory
cp .env.example .env
# Fill in HASS_URL, HASS_TOKEN, ZWJS_WS_URL, INFLUXDB_*, and (optionally) LLM_API_KEY
docker compose up -d
```

Then open `http://<host>:8088`.

Prefer not to edit `.env` by hand? On first run the web UI offers a setup wizard that walks through the same settings and writes them to `/data`. See [docs/install.md](docs/install.md) for all three installation paths (wizard, agent-guided, manual).

## Architecture

The backend is a FastAPI service that bridges three upstreams: the Home Assistant REST API plus its WebSocket connection for entity state and events, the zwave-js-server WebSocket for raw Z-Wave statistics and mesh topology, and InfluxDB via Flux queries for historical trends. The React single-page app talks only to the backend; it never contacts Home Assistant, zwave-js-server, InfluxDB, or any LLM provider directly. Everything ships in one container exposing one port, so the only ingress you need is the single HTTP port mapped by `docker compose`.

## Configuration

All configuration is environment variables. Copy `.env.example` to `.env` and fill in the values.

| Variable | Required | Default | Description |
|---|---|---|---|
| `HASS_URL` | yes | | Base URL of your Home Assistant instance |
| `HASS_TOKEN` | yes | | Long-lived access token from Home Assistant |
| `ZWJS_WS_URL` | yes | | WebSocket URL of your zwave-js-server |
| `ZWJS_TOKEN` | no | | Token if your zwave-js-server requires auth |
| `INFLUXDB_URL` | yes | | InfluxDB v2 base URL |
| `INFLUXDB_ORG` | yes | | InfluxDB organization |
| `INFLUXDB_TOKEN` | yes | | InfluxDB API token with read access |
| `LLM_PROVIDER` | no | `anthropic` | `anthropic` or `openai_compatible` |
| `LLM_MODEL` | no | `claude-sonnet-4-5` | Model name for the advisor |
| `LLM_API_KEY` | no | | Provider API key; empty disables the advisor |
| `LLM_MAX_TOKENS` | no | | Max tokens per advisor request |
| `LLM_DAILY_TOKEN_CAP` | no | `200000` | Hard daily cap on advisor tokens |
| `DATA_DIR` | no | `/data` | Persistent state directory (audit log, caches) |
| `PORT` | no | `8088` | Host port for the web UI |
| `TZ` | no | `UTC` | Container timezone |
| `DOCKERHUB_USERNAME` | no | `local` | Docker Hub username used by `docker-compose.yml` to resolve the image |

Secrets can also be provided in `/data/secrets.env` inside the container; the entrypoint sources it and exports the variables over the defaults at startup. That file lives on the mounted volume, so it survives image updates without re-editing `.env`.

## LLM advisor

The advisor is provider-agnostic. The default is Anthropic (`LLM_PROVIDER=anthropic`). Any OpenAI-compatible endpoint works through `LLM_PROVIDER=openai_compatible`; for a fully local setup, enable the commented `local-llm` profile in `docker-compose.yml`, which starts Ollama, and set:

```bash
LLM_PROVIDER=openai_compatible
LLM_MODEL=qwen3:8b
LLM_BASE_URL=http://ollama:11434/v1
```

Note that qwen3:8b needs roughly 8GB of free RAM.

The advisor only ever proposes fixes. Each proposal is validated against a strict schema, shown in the UI, and applied only after you confirm it. Advisor usage is bounded by `LLM_DAILY_TOKEN_CAP`; when the cap is reached the advisor stops answering until the next day.

## Actions and safety

Remediation actions are deliberately conservative:

- Every action shows a confirmation modal describing exactly what will happen before it runs
- One mutation is in flight at a time; the UI and backend both enforce this
- Every accepted or rejected action is written to an append-only audit log under `DATA_DIR`
- Risky network-wide operations are not exposed; the strongest offered action is a per-node heal

## Development

Backend: Python 3.12 with FastAPI and pytest.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest tests
```

Frontend: Node 20, npm, Vitest.

```bash
cd frontend
npm ci
npm run build
npm test
```

Full container build (multi-platform):

```bash
docker build -t zwave-observatory:dev .
```

CI runs backend pytest, the frontend build, and a leak scan (private IPs, Z-Wave home-id-like numbers, forbidden device names) on every push. Docker Hub publishing to `linux/amd64` and `linux/arm64` happens only after all three jobs pass, on `v*` tags and `main`.

## Security

- This application is designed for your LAN. Do not expose it to the internet; there is no authentication layer in front of the UI.
- Home Assistant, Z-Wave JS, and InfluxDB tokens stay inside the container and are never sent to any LLM provider. Only aggregated, redacted health summaries reach the advisor.
- Tokens in `.env` never leave the host; the file is gitignored and docker-ignored.

## License

[MIT](LICENSE)
