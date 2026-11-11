# Install guide

There are three ways to configure zwave-observatory. Pick one:

- Path A: first-run wizard in the web UI (easiest)
- Path B: agent-guided install (an LLM agent interviews you and writes the config)
- Path C: manual edit of `.env`

All three paths end in the same place: a configured `.env` (or `/data/secrets.env`) and a running container on port 8088.

## Prerequisites

- A Home Assistant instance with the Z-Wave JS integration running
- An InfluxDB v2 instance with Home Assistant or Z-Wave history in it
- Docker and the Docker Compose plugin on the host running the observatory
- Network reachability from the observatory host to Home Assistant, zwave-js-server, and InfluxDB

## Path A: first-run wizard

1. Clone and start with an empty config:

   ```bash
   git clone https://github.com/scottkidder/zwave-observatory.git
   cd zwave-observatory
   docker compose up -d
   ```

   No `.env` is required to boot; the container starts in setup mode.

2. Open `http://<host>:8088`. The first-run wizard walks through:

   - Home Assistant base URL and a long-lived access token (create one under Profile, then Security, then Long-Lived Access Tokens)
   - The zwave-js-server WebSocket URL (for the official add-on, use the websocket ingress URL; for a standalone zwave-js-server, use its `ws://` URL)
   - InfluxDB URL, organization, and an API token with read access to the relevant buckets
   - Optional LLM advisor settings (provider, model, API key, daily token cap)

3. The wizard tests each connection as you go, then writes the values to `/data/secrets.env` on the mounted volume and reloads the backend. Nothing is written to the git-tracked `.env`.

4. To change settings later, re-run the wizard from Settings, or edit `/data/secrets.env` directly and restart the container.

## Path B: agent-guided install

You paste a prepared prompt into any capable LLM agent with shell access to the host. The agent asks you questions, fills in `.env` for you, and never echoes your secrets back. See [agent-install.md](agent-install.md) for the paste-ready prompt.

## Path C: manual install

1. Clone the repo and create your config:

   ```bash
   git clone https://github.com/scottkidder/zwave-observatory.git
   cd zwave-observatory
   cp .env.example .env
   ```

2. Edit `.env` and fill in every required variable:

   | Variable | Where to get it |
   |---|---|
   | `HASS_URL` | Your Home Assistant base URL, for example `http://homeassistant.local:8123` |
   | `HASS_TOKEN` | Home Assistant long-lived access token |
   | `ZWJS_WS_URL` | zwave-js-server WebSocket URL, for example `ws://homeassistant.local:3000` |
   | `ZWJS_TOKEN` | Only if your zwave-js-server requires auth |
   | `INFLUXDB_URL` | InfluxDB v2 base URL |
   | `INFLUXDB_ORG` | Your InfluxDB organization name |
   | `INFLUXDB_TOKEN` | InfluxDB API token with read access |
   | `LLM_API_KEY` | Optional; your Anthropic or OpenAI-compatible key |
   | `DOCKERHUB_USERNAME` | Your Docker Hub username so `docker compose` resolves the image |

3. Set your Docker Hub username so compose can pull the published image:

   ```bash
   # in .env
   DOCKERHUB_USERNAME=your-username
   ```

   Or build locally by uncommenting `build: .` in `docker-compose.yml`.

4. Start and verify:

   ```bash
   docker compose up -d
   docker compose ps
   curl http://localhost:8088/api/version
   ```

## Verifying the installation

- `http://<host>:8088` shows the mesh map once your Z-Wave JS connection is healthy
- The Health panel in the UI reports connectivity to Home Assistant, zwave-js-server, and InfluxDB independently, so you can see exactly which upstream is misconfigured
- Logs: `docker compose logs -f zwave-observatory`

## Updating

```bash
git pull
docker compose pull
docker compose up -d
```

State (audit log, wizard-written secrets) lives in `./data` and survives updates.
