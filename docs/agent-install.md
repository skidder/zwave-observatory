# Agent-guided install

Paste the prompt below into any capable LLM agent that has shell access to the host where zwave-observatory will run. The agent will interview you, write `.env`, and bring the stack up. It is instructed to never echo your secrets back to the screen or into its own output.

---

```text
You are helping me install zwave-observatory, a Docker-based Z-Wave network
health dashboard. Work on this host. Follow these rules strictly:

SECRETS HANDLING (most important):
- When I type a token or key, do not repeat it back in any output, log line,
  echo, or summary. Refer to it only by its variable name, for example
  "HASS_TOKEN is set (length 42)".
- Never print the contents of .env, even partially. If you need to verify a
  value, test it with a live request and report only success or failure and
  the HTTP status.
- Never commit .env anywhere. It is already gitignored; do not change that.
- If a command would print a secret (for example cat .env or env), do not run
  it.

INTERVIEW:
Ask me these questions one group at a time. For each, tell me exactly where
I can find the value before asking:

1. Home Assistant: base URL (for example http://homeassistant.local:8123) and
   a long-lived access token. Tell me how to create one: Profile, Security,
   Long-Lived Access Tokens, Create Token.
2. Z-Wave JS: the zwave-js-server WebSocket URL. If I use the official Home
   Assistant Z-Wave JS add-on, tell me how to find the websocket ingress URL;
   otherwise ask for my ws:// URL and optional token.
3. InfluxDB: URL, organization, and an API token with read access to the
   buckets holding my Z-Wave or Home Assistant history.
4. LLM advisor (optional): whether I want it, which provider (anthropic
   default, or openai_compatible for Ollama or other local servers), model,
   and API key. If I choose a local Ollama setup, enable the local-llm
   profile in docker-compose.yml instead of asking for an API key.
5. Runtime: the host port I want (default 8088) and my timezone.

INSTALL STEPS:
After the interview:
1. Clone https://github.com/scottkidder/zwave-observatory.git into the
   directory I specify (ask me first if I have not given one).
2. Copy .env.example to .env and fill it in with the values I gave, writing
   the file non-interactively so values are not echoed to the terminal.
3. Set DOCKERHUB_USERNAME in .env to my Docker Hub username (ask me for it),
   or if I prefer, uncomment build: . in docker-compose.yml to build locally.
4. Run docker compose up -d.
5. Verify each connection and report only pass/fail per upstream:
   - curl http://localhost:8088/api/version
   - the Health panel in the UI at http://localhost:8088
   - docker compose logs --tail 50 zwave-observatory (redact any token-looking
     strings before showing me anything)
6. Give me a short summary of what is running, on which port, and where the
   audit log lives (./data). Remind me that the UI has no authentication and
   must stay on the LAN.

If any upstream connection fails, show me the error and the exact variable
that needs fixing, and help me correct it in .env using a scripted edit (for
example sed with the value piped, not typed into the transcript).
```
