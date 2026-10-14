FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/app/out/leadflow.db

WORKDIR /app

# Optional extras, e.g. --build-arg EXTRAS="[anthropic]" or "[openai,sheets]"
ARG EXTRAS=""
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".${EXTRAS}"

COPY data ./data
RUN useradd --create-home --uid 10001 app && mkdir -p /app/out && chown app /app/out
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "leadflow.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
