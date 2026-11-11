"""First-run wizard: setup status, live validation per step, secrets.env completion."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import httpx

from .config import Config, get_config, reload_config_with_secrets
from .ha import HAClient
from .zwjs import ZwjsClient


def setup_status(cfg: Config) -> dict[str, Any]:
    return {
        "steps": {
            "hass": {"configured": cfg.hass_configured(),
                     "missing": [k for k, v in {"HASS_URL": cfg.hass_url,
                                                "HASS_TOKEN": cfg.hass_token}.items() if not v]},
            "zwjs": {"configured": cfg.zwjs_configured(),
                     "missing": [k for k, v in {"ZWJS_WS_URL": cfg.zwjs_ws_url}.items() if not v]},
            "influx": {"configured": cfg.influx_configured(),
                       "missing": [k for k, v in {"INFLUXDB_URL": cfg.influx_url,
                                                  "INFLUXDB_ORG": cfg.influx_org,
                                                  "INFLUXDB_TOKEN": cfg.influx_token}.items() if not v]},
            "llm": {"configured": cfg.llm_configured(),
                    "missing": [k for k, v in {"LLM_API_KEY": cfg.llm_api_key}.items()
                                if not v and cfg.llm_provider != "ollama"]},
        },
        "complete": cfg.hass_configured() and cfg.zwjs_configured(),
    }


async def test_step(step: str, values: dict[str, Any]) -> dict[str, Any]:
    """Live validation for hass / zwjs / influx / llm. Secrets in `values` are
    used transiently and never echoed back."""
    try:
        if step == "hass":
            client = HAClient(values.get("HASS_URL", ""), values.get("HASS_TOKEN", ""))
            await client.get_states(force=True)
            return {"ok": True, "detail": "states fetched"}
        if step == "zwjs":
            client = ZwjsClient(values.get("ZWJS_WS_URL", ""), values.get("ZWJS_TOKEN"))
            state = await client.get_state()
            return {"ok": True, "detail": f"{len(state.get('nodes', []))} nodes"}
        if step == "influx":
            from .influx import InfluxClient
            client = InfluxClient(values.get("INFLUXDB_URL", ""),
                                  values.get("INFLUXDB_ORG", ""),
                                  values.get("INFLUXDB_TOKEN", ""))
            rows = await client.query('buckets() |> limit(n:1)')
            return {"ok": True, "detail": f"query returned {len(rows)} rows"}
        if step == "llm":
            from .advisor import LLMClient
            client = LLMClient(values.get("LLM_PROVIDER", "anthropic"),
                               values.get("LLM_MODEL", "claude-sonnet-4-5"),
                               values.get("LLM_API_KEY"),
                               values.get("LLM_BASE_URL"), max_tokens=64)
            r = await client.chat([{"role": "user", "content": "Reply with the single word: ok"}])
            return {"ok": True, "detail": f"reply: {r['text'][:40]}"}
        return {"ok": False, "detail": f"unknown step: {step}"}
    except Exception as e:
        # never echo secrets from the exception
        msg = str(e).replace(values.get("HASS_TOKEN", "***"), "***") \
                    .replace(values.get("LLM_API_KEY", "***"), "***") \
                    .replace(values.get("INFLUXDB_TOKEN", "***"), "***")
        return {"ok": False, "detail": msg[:200]}


def complete_setup(values: dict[str, Any]) -> dict[str, Any]:
    """Write merged env values to DATA_DIR/secrets.env, chmod 600, reload config."""
    cfg = get_config()
    data_dir = Path(cfg.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "secrets.env"
    lines = []
    for k, v in values.items():
        k = k.strip().upper()
        if not k or not isinstance(v, str):
            continue
        v = v.replace("\n", "")
        lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600
    reload_config_with_secrets(path)
    return {"ok": True, "path": str(path)}
