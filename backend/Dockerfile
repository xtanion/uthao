FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /srv/fihy

# Dependencies resolve from the lockfile alone, so this layer survives every
# change that does not touch it.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra postgres --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# Nothing here needs to write to the image, and a compromised process should
# not be able to.
RUN useradd --system --uid 10001 fihy && chown -R fihy:fihy /srv/fihy
USER fihy

EXPOSE 8000

# One worker per container: scale with replicas, so AUTO_MIGRATE stays off and
# the crons stay out of the web process. X-Forwarded-For is not trusted from
# everyone, or any caller could set their own address: the app reads the one
# header CLIENT_IP_HEADER names instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
