import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session
from starlette.routing import Route

from app.a2a.routes import router as a2a_router
from app.auth.routes import router as auth_router
from app.config import get_settings
from app.db import engine, init_db
from app.gateway.mcp_endpoint import AuthenticatedMcpApp, create_mcp_manager
from app.gateway.mcp_pool import McpPool, connect_all
from app.gateway.pii import get_analyzer
from app.gateway.ratelimit import RateLimiter
from app.gateway.routes import router as gateway_router
from app.observability.routes import router as observability_router
from app.registry.routes import router as registry_router
from app.runs.routes import router as runs_router
from app.runs.service import RunManager
from app.seed import seed
from app.tracing.routes import router as tracing_router

logger = logging.getLogger("agenthub")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.demo_mode and settings.jwt_secret.startswith("dev-only"):
        logger.warning("AGENTHUB_JWT_SECRET is the insecure default. Set a long random value.")
    # Demo deployments start from a clean, freshly seeded database every boot.
    init_db(reset=settings.demo_mode)
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
    # Load the NLP model now so the first masked call isn't slow.
    await asyncio.to_thread(get_analyzer)
    with Session(engine) as session:
        seed(session, settings)
        app.state.pool = McpPool()
        await connect_all(app.state.pool, session)
    app.state.mcp_manager = create_mcp_manager(app)  # a manager can only run once, so one per start
    app.state.runs = RunManager(app)
    async with app.state.mcp_manager.run():
        yield
    await app.state.runs.shutdown()
    await app.state.pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Open-source MCP gateway & agent registry: RBAC, PII masking, audit and tracing.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": settings.version, "demo_mode": settings.demo_mode}

    app.include_router(auth_router)
    app.include_router(registry_router)
    app.include_router(gateway_router)
    app.include_router(observability_router)
    app.include_router(a2a_router)
    app.include_router(tracing_router)
    app.include_router(runs_router)

    # Aggregated MCP endpoint for Claude Desktop, IDEs and other MCP clients.
    app.router.routes.append(Route("/mcp", AuthenticatedMcpApp(app), methods=["GET", "POST", "DELETE"]))
    return app


app = create_app()
