# syntax=docker/dockerfile:1
# ---- build stage: install the hash-locked dependencies into a venv ----
FROM python:3.13.18-slim@sha256:6d68eb6310a906f26c7638eb6ea7557d4261662df3181af2f80f1f9a7e34c549 AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
# --require-hashes: every file must match the lock; --only-binary: no build scripts run.
RUN /opt/venv/bin/pip install --require-hashes --only-binary=:all: -r /tmp/requirements.txt

# ---- runtime stage: slim image, non-root, app code only ----
FROM python:3.13.18-slim@sha256:6d68eb6310a906f26c7638eb6ea7557d4261662df3181af2f80f1f9a7e34c549 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    DATABASE_URL=sqlite:////data/app.db \
    LLM_CACHE_DIR=/data/litellm-cache
# /data is created and chowned BEFORE `USER`, so a fresh named volume mounted
# there inherits writable ownership for the non-root user.
RUN groupadd --system app \
 && useradd --system --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /data/litellm-cache \
 && chown -R app:app /data
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
USER app
EXPOSE 8000
VOLUME ["/data"]
# One worker: the LiteLLM disk cache and SQLite file are shared in-process.
# PORT lets hosts such as Render inject their port; defaults to 8000.
CMD ["sh", "-c", "exec uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
