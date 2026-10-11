# Build from the repo root:  docker build -f backend/Dockerfile .
# The gateway launches the bundled MCP servers (mcp_servers/) and runs the Research Crew (agents/),
# so both are copied next to backend/, matching the repo layout.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    MALLOC_ARENA_MAX=2

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
COPY agents /app/agents
COPY mcp_servers /app/mcp_servers

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
