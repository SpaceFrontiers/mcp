# Use a slim Python base image
FROM python:3.13-slim AS base
FROM base AS builder
RUN apt update && apt install -y git && apt clean
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY uv.lock pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Final stage for deployment
FROM base
COPY --from=builder /app /app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

# Command to run the application using uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
