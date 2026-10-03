FROM python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app --shell /usr/sbin/nologin app

COPY pyproject.toml ./
COPY app ./app
COPY tests ./tests

RUN pip install --no-cache-dir ".[dev]" \
    && mkdir -p /data \
    && chown -R app:app /app /data

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
