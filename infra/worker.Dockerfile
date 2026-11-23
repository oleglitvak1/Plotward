FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" HF_HOME=/hf

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps
RUN uv sync --frozen --no-dev --package plotward-worker

# The real embedding model needs PyTorch. Install the CPU-only build (no CUDA, a few hundred MB)
# outside the lockfile so the lockfile and the tests stay light.
RUN uv pip install --python /app/.venv/bin/python \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    --index-strategy unsafe-best-match \
    torch torchvision open_clip_torch

# Model weights (about 600 MB) download on first start into the /hf volume, then are reused.
CMD ["python", "-m", "plotward_worker"]
