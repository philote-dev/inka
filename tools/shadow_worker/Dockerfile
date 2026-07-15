FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /worker
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY worker.py ./
ENTRYPOINT ["/worker/.venv/bin/python", "/worker/worker.py"]
