"""HTTP API for the web UI.

An inbound adapter like the CLI: it renders errors and owns transport, and
computes nothing. The engines already return Pydantic models, so a route's
response schema is the domain model itself — `ScoutReport` and `TradeVerdict`
cross the wire exactly as the CLI renders them, with no second representation
to keep in step.

Serves the built front end from `web/dist` when it exists, so one process on one
port covers both. In development the front end runs its own dev server and calls
back here across the proxy configured in `web/vite.config.ts`.
"""

import logging
import uuid
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from the_front_office.adapters.inbound.web import data
from the_front_office.bootstrap import SportEntry, all_sports, scout_engine, trade_engine
from the_front_office.config import env_file
from the_front_office.config.logging import setup_logging
from the_front_office.config.settings import PROJECT_ROOT, settings
from the_front_office.config.telemetry import setup_telemetry
from the_front_office.domain.errors import FrontOfficeError
from the_front_office.domain.models import ScoutReport, TradeVerdict
from the_front_office.domain.ports import ChatSession

logger = logging.getLogger(__name__)

DIST = PROJECT_ROOT / "web" / "dist"


# ── wire types ──────────────────────────────────────────────────────────
# Only for shapes the domain has no model for. Anything the domain does model
# is returned as-is rather than copied into a parallel type that can drift.


class Sport(BaseModel):
    """One entry in the sport picker."""

    sport: str
    label: str
    supports_trades: bool
    configured: bool
    requires: str


class League(BaseModel):
    league_id: str
    name: str
    detail: str


class RunRequest(BaseModel):
    mock: bool = False
    """Skip the model and return a canned report. League data stays live."""


class TradeRequest(RunRequest):
    text: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class Reply(BaseModel):
    answer: str


class Setting(BaseModel):
    """One configurable value, described without ever carrying a secret."""

    key: str
    field: str
    secret: bool
    present: bool
    value: str = ""
    """Empty for a secret. Presence is all the UI needs, and all it should hold."""

    shadowed: bool = False
    """A shell variable is overriding .env, so an edit here will not take effect."""


class SettingsUpdate(BaseModel):
    values: dict[str, str]


class Analysis(BaseModel):
    """A finished report plus the handle for asking about it."""

    report: ScoutReport
    chat_id: str


class Evaluation(BaseModel):
    verdict: TradeVerdict
    chat_id: str


# ── follow-up chats ─────────────────────────────────────────────────────
# A chat is a live object holding conversation state, so it cannot cross the
# wire. It stays here and the client refers to it by id. In-process because
# this serves exactly one person on one machine; a second worker would need
# somewhere shared to put these.

_chats: dict[str, ChatSession] = {}

# A module-level singleton rather than a call in the signature, which would
# build a fresh instance per request and trips ruff's B008.
_DEFAULT_RUN = Body(default=RunRequest())


def _remember(chat: ChatSession) -> str:
    chat_id = uuid.uuid4().hex
    _chats[chat_id] = chat
    return chat_id


def create_app() -> FastAPI:
    """The application, wired and ready to serve."""
    setup_logging()
    setup_telemetry("front-office-web")

    app = FastAPI(title="The Front Office", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(FrontOfficeError)
    async def _domain_error(_: Request, exc: FrontOfficeError) -> JSONResponse:
        """Every expected failure reaches the client as a readable message.

        400 rather than 500: these are all conditions the user can act on — a
        credential that is not set, a league they do not own, a misspelled
        player — not faults in the server.
        """
        logger.info(f"Domain error: {exc}")
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    _register_routes(app)
    _serve_frontend(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/api/sports", response_model=list[Sport])
    def list_sports() -> list[Sport]:
        """Every sport, including ones this machine has no credentials for.

        Unconfigured sports are returned rather than hidden so the UI can say
        what to set instead of silently offering less than it could.
        """
        return [
            Sport(
                sport=entry.sport,
                label=entry.label,
                supports_trades=entry.supports_trades,
                configured=entry.is_configured(),
                requires=entry.requires,
            )
            for entry in all_sports()
        ]

    @app.get("/api/settings", response_model=list[Setting])
    def read_settings() -> list[Setting]:
        """Every configurable value, with secrets reported as present or absent.

        A secret's contents never leave the process. There is nothing the UI can
        do with the characters of an API key that it cannot do with the fact
        that one is set, and a page that renders them puts them in screenshots.
        """
        stored = env_file.read_values()
        return [
            Setting(
                key=key,
                field=field,
                secret=key in env_file.SECRET_KEYS,
                present=bool(getattr(settings, field, None)),
                value="" if key in env_file.SECRET_KEYS else str(stored.get(key, "")),
                shadowed=env_file.is_shadowed(key),
            )
            for key, field in env_file.declared().items()
        ]

    @app.put("/api/settings", response_model=list[Setting])
    def save_settings(update: SettingsUpdate) -> list[Setting]:
        """Write values to .env and re-read configuration into the running app.

        Rejects any key no setting reads rather than writing it: a line nothing
        picks up looks saved and changes nothing, which is the exact failure
        this endpoint exists to prevent.
        """
        try:
            env_file.write_values(update.values)
        except env_file.UnknownSettingError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OSError as e:
            logger.error(f"Could not write .env: {e}")
            raise HTTPException(status_code=500, detail=f"Could not write .env: {e}") from e
        return read_settings()

    @app.get("/api/{sport}/leagues", response_model=list[League])
    def list_leagues(sport: str) -> list[League]:
        provider = data.build_provider(sport)
        return [League(league_id=r.league_id, name=r.name, detail=r.detail) for r in provider.list_leagues()]

    @app.get("/api/{sport}/leagues/{league_id}/roster")
    def roster(sport: str, league_id: str) -> list[dict[str, str]]:
        """Table rows, with per-sport columns the client renders generically.

        The shape is the sport's own vocabulary — an FPL row carries Price and
        xPts, an NFL row carries Slot — so the client reads the keys of the
        first row rather than being taught each sport's columns.
        """
        return data.build_provider(sport).roster_rows(league_id)

    @app.post("/api/{sport}/leagues/{league_id}/scout", response_model=Analysis)
    def scout(sport: str, league_id: str, request: RunRequest = _DEFAULT_RUN) -> Analysis:
        provider = data.build_provider(sport)
        report, chat = scout_engine(provider, request.mock).start_analysis(league_id)
        return Analysis(report=report, chat_id=_remember(chat))

    @app.post("/api/{sport}/leagues/{league_id}/trade", response_model=Evaluation)
    def trade(sport: str, league_id: str, request: TradeRequest) -> Evaluation:
        entry = _tradeable(sport)
        provider = data.build_provider(entry.sport)
        verdict, chat = trade_engine(provider, request.mock).evaluate(league_id, request.text)
        return Evaluation(verdict=verdict, chat_id=_remember(chat))

    @app.post("/api/chat/{chat_id}", response_model=Reply)
    def ask(chat_id: str, request: ChatRequest) -> Reply:
        """Ask a follow-up about a report that is already on screen."""
        chat = _chats.get(chat_id)
        if chat is None:
            # The server restarted, or the report predates it. Saying so is
            # better than an empty answer the user cannot explain.
            raise HTTPException(status_code=404, detail="That conversation has expired. Re-run the report.")
        try:
            answer = getattr(chat.send_message(request.message), "text", "") or ""
        except Exception as e:  # the model SDK raises its own error types
            logger.error(f"Follow-up failed: {e}")
            raise HTTPException(status_code=502, detail=f"The model did not answer: {e}") from e
        return Reply(answer=answer or "(no answer)")


def _tradeable(sport: str) -> SportEntry:
    """The entry for `sport`, refusing one that cannot evaluate trades.

    Checked here rather than left to the provider: a sport without trade
    support has no `build_trade_context` at all, so the failure would otherwise
    be an AttributeError rather than something the user can read.
    """
    entry = next((e for e in all_sports() if e.sport == sport.lower()), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown sport {sport!r}.")
    if not entry.supports_trades:
        raise HTTPException(status_code=400, detail=f"{entry.label} does not support trade evaluation.")
    return entry


def _serve_frontend(app: FastAPI) -> None:
    """Serve the built UI, if it has been built.

    Mounted last so it never shadows `/api`. Missing `dist/` is the normal
    state during front-end development and while the API is under test, so it
    is not an error — the routes above work either way.
    """
    if not DIST.is_dir():
        logger.info("web/dist not built; serving the API only. Run `just ui` for the dev server.")
        return

    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Any:
        """Any non-API path returns index.html; the client owns routing."""
        candidate = DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")


app = create_app()


def main() -> None:
    """Run the server. `just serve`."""
    import uvicorn

    uvicorn.run("the_front_office.adapters.inbound.web.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
