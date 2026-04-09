FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY agentsociety2 /app/agentsociety2
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

RUN pip install --upgrade pip setuptools wheel && \
    pip install . && \
    chmod +x /app/docker-entrypoint.sh

EXPOSE 8001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "agentsociety2.backend.app:app", "--host", "0.0.0.0", "--port", "8001"]
