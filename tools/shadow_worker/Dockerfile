FROM ghcr.io/astral-sh/uv:0.9.17@sha256:5cb6b54d2bc3fe2eb9a8483db958a0b9eebf9edff68adedb369df8e7b98711a2 AS uv
FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f

COPY --from=uv /uv /uvx /bin/
WORKDIR /worker
ENV UV_PROJECT_ENVIRONMENT=/worker/.venv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY worker.py ./
ENTRYPOINT ["/worker/.venv/bin/python", "/worker/worker.py"]
