"""FastAPI app assembly: routers, SPA statics, nightly 03:00 advisor scheduler."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .advisor import Advisor, LLMClient, build_context_packet
from .config import get_config, reload_config_with_secrets
from .db import Database
from .routers import api, ws_router
from .state import AppState

log = logging.getLogger("zwave-observatory")


def create_app() -> FastAPI:
    cfg = reload_config_with_secrets(Path(get_config().data_dir) / "secrets.env")
    db = Database(Path(cfg.data_dir) / "observatory.db")
    llm = LLMClient(cfg.llm_provider, cfg.llm_model, cfg.llm_api_key,
                    cfg.llm_base_url, cfg.llm_max_tokens, cfg.llm_daily_token_cap)
    advisor = Advisor(db, llm)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = AppState(db)
        app.state.state = state
        app.state.db = db
        app.state.advisor = advisor
        task = asyncio.create_task(_nightly_scheduler(app))
        yield
        task.cancel()

    app = FastAPI(title="Z-Wave Health Observatory", lifespan=lifespan)
    app.include_router(api)
    app.include_router(ws_router)
    _mount_statics(app)
    return app


def _mount_statics(app: FastAPI) -> None:
    cfg = get_config()
    static_dir = Path(cfg.static_dir)
    if static_dir.is_dir() and (static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="spa")
    else:
        index = static_dir / "index.html" if static_dir.is_dir() else None

        @app.get("/")
        async def fallback_index():
            if index and index.is_file():
                return FileResponse(index)
            return {"app": "zwave-observatory",
                    "status": "no SPA built; API available under /api"}


async def _nightly_scheduler(app: FastAPI) -> None:
    """Nightly advisor analyze at 03:00 local."""
    while True:
        now = datetime.now()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            advisor: Advisor = app.state.advisor
            st = app.state.state
            if not st.nodes:
                await st.refresh()
            packet = build_context_packet(
                st.nodes, st.get_problems(), st.network_score,
                st.db.get_ledger(days=7), sorted(st.db.active_dismissals()))
            await advisor.analyze(packet)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("nightly analyze failed: %s", e)
            await asyncio.sleep(60)


app = create_app()
