FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8765

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[postgres]"

RUN useradd --create-home --uid 10001 jobengine
USER jobengine

EXPOSE 8765
CMD ["sh", "-c", "jobengine serve --host 0.0.0.0 --port ${PORT}"]
