# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.lock ./requirements.lock
RUN python -m pip wheel --wheel-dir=/wheels -r requirements.lock

FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WATCHLISTGUARD_DB=/app/data/watchlistguard.db \
    APP_ENV=production \
    PORT=5000
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/data && chown -R app:app /app
COPY --from=dependencies /wheels /wheels
COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-index --find-links=/wheels -r requirements.lock \
    && rm -rf /wheels
COPY --chown=app:app app.py main.py ./
COPY --chown=app:app container_entrypoint.py ./
COPY --chown=app:app watchlistguard ./watchlistguard
COPY --chown=app:app templates ./templates
COPY --chown=app:app static ./static
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app alembic.ini ./alembic.ini
USER app
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT','5000') + '/live', timeout=2)" || exit 1
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "container_entrypoint.py"]
