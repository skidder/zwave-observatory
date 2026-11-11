"""Configuration read from environment. Plain os.environ, no pydantic-settings.

Secrets are never returned by any endpoint; config only exposes booleans/masks.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    # secrets.env (written by the setup wizard) is merged over os.environ at startup
    return os.environ.get(name, default)


@dataclass
class Config:
    hass_url: str = ""
    hass_token: str | None = None
    zwjs_ws_url: str = ""
    zwjs_token: str | None = None
    influx_url: str = ""
    influx_org: str = ""
    influx_bucket: str = "homeassistant"
    influx_token: str | None = None
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-5"
    llm_api_key: str | None = None
    llm_base_url: str | None = None  # for openai_compatible / ollama
    llm_max_tokens: int = 4096
    llm_daily_token_cap: int = 200_000
    data_dir: Path = Path("./data")
    port: int = 8088
    static_dir: Path = Path("/app/static")

    @property
    def data_dir_abs(self) -> Path:
        return Path(self.data_dir)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            hass_url=_env("HASS_URL", "") or "",
            hass_token=_env("HASS_TOKEN"),
            zwjs_ws_url=_env("ZWJS_WS_URL", "") or "",
            zwjs_token=_env("ZWJS_TOKEN"),
            influx_url=_env("INFLUXDB_URL", "") or "",
            influx_org=_env("INFLUXDB_ORG", "") or "",
            influx_bucket=_env("INFLUXDB_BUCKET", "") or "homeassistant",
            influx_token=_env("INFLUXDB_TOKEN"),
            llm_provider=_env("LLM_PROVIDER", "anthropic") or "anthropic",
            llm_model=_env("LLM_MODEL", "claude-sonnet-4-5") or "claude-sonnet-4-5",
            llm_api_key=_env("LLM_API_KEY"),
            llm_base_url=_env("LLM_BASE_URL"),
            llm_max_tokens=int(_env("LLM_MAX_TOKENS", "4096") or 4096),
            llm_daily_token_cap=int(_env("LLM_DAILY_TOKEN_CAP", "200000") or 200_000),
            data_dir=Path(_env("DATA_DIR", "./data") or "./data"),
            port=int(_env("PORT", "8088") or 8088),
            static_dir=Path(_env("STATIC_DIR", "/app/static") or "/app/static"),
        )

    # --- safe introspection for setup/status endpoints (never return secrets) ---
    def hass_configured(self) -> bool:
        return bool(self.hass_url and self.hass_token)

    def zwjs_configured(self) -> bool:
        return bool(self.zwjs_ws_url)

    def influx_configured(self) -> bool:
        return bool(self.influx_url and self.influx_org)

    def llm_configured(self) -> bool:
        return bool(self.llm_api_key) or self.llm_provider in ("ollama",)

    def secrets(self) -> dict[str, str]:
        """Secret values for internal use only. Never serialized to responses/logs."""
        s: dict[str, str] = {}
        if self.hass_url:
            s["HASS_URL"] = self.hass_url
        if self.hass_token:
            s["HASS_TOKEN"] = self.hass_token
        if self.zwjs_ws_url:
            s["ZWJS_WS_URL"] = self.zwjs_ws_url
        if self.zwjs_token:
            s["ZWJS_TOKEN"] = self.zwjs_token
        if self.influx_url:
            s["INFLUXDB_URL"] = self.influx_url
        if self.influx_org:
            s["INFLUXDB_ORG"] = self.influx_org
        if self.influx_token:
            s["INFLUXDB_TOKEN"] = self.influx_token
        if self.llm_provider:
            s["LLM_PROVIDER"] = self.llm_provider
        if self.llm_model:
            s["LLM_MODEL"] = self.llm_model
        if self.llm_api_key:
            s["LLM_API_KEY"] = self.llm_api_key
        if self.llm_base_url:
            s["LLM_BASE_URL"] = self.llm_base_url
        return s


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def set_config(cfg: Config) -> None:
    global _config
    _config = cfg


def reload_config_with_secrets(secrets_path: Path) -> Config:
    """Merge data/secrets.env over os.environ, then rebuild config. Called at startup."""
    if secrets_path.is_file():
        for line in secrets_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k:
                os.environ[k] = v
    cfg = Config.from_env()
    set_config(cfg)
    return cfg
