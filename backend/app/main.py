"""FastAPI application: exactly three endpoints."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .chat_service import ChatService
from .config import Settings
from .db import Database
from .gateway import AllProvidersUnavailable, LLMGateway
from .schemas import ChatRequest, ChatResponse, HealthResponse, HistoryResponse
from .simulation import FailureSimulation, SimulationHeaderError, parse_simulation_header

logger = logging.getLogger("app")

ALL_PROVIDERS_UNAVAILABLE = "all providers unavailable"


def create_app(settings: Settings, gateway: LLMGateway) -> FastAPI:
    db = Database(settings.database_path)
    service = ChatService(settings, db, gateway)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init()
        yield

    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    # Registered BEFORE CORSMiddleware so CORS is the outer layer and adds its
    # headers to this 500 response too. (A plain exception_handler(Exception)
    # runs in ServerErrorMiddleware, outside CORS, and the browser would see a
    # CORS failure instead of the JSON.)
    @app.middleware("http")
    async def internal_error_guard(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            logger.error("unhandled error: %s", type(exc).__name__)
            return JSONResponse({"detail": "internal server error"}, status_code=500)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
    )

    @app.get("/health", response_model=HealthResponse)
    def health():
        problems = list(settings.config_problems())
        if not db.ping():
            problems.append("database unreachable")
        if gateway.keys_configured < 1:
            problems.append("no API keys configured")
        if not gateway.cache_enabled:
            problems.append("cache not enabled")
        if problems:
            return JSONResponse({"detail": "; ".join(problems)}, status_code=503)
        return HealthResponse(
            status="ok", keys_configured=gateway.keys_configured, cache_enabled=True
        )

    # Sync def: FastAPI runs it in the threadpool, so a slow provider call
    # never blocks the event loop (and /health).
    @app.post("/chat", response_model=ChatResponse)
    def chat(body: ChatRequest, request: Request):
        simulation: Optional[FailureSimulation] = None
        # Flag not exactly "true" -> the header is ignored completely (never parsed).
        if settings.enable_failure_simulation:
            try:
                simulation = parse_simulation_header(request.headers.get("x-simulate-failure"))
            except SimulationHeaderError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        try:
            return service.chat(body, simulation)
        except AllProvidersUnavailable:
            raise HTTPException(status_code=503, detail=ALL_PROVIDERS_UNAVAILABLE)

    @app.get("/sessions/{session_id}/messages", response_model=HistoryResponse)
    def session_messages(session_id: str):
        history = db.get_history(session_id)
        if not history:
            raise HTTPException(status_code=404, detail="session not found")
        return {"session_id": session_id, "messages": history}

    return app
