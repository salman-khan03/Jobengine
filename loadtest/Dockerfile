# Load-test image for the API. Not the production image — this one is built
# from the working tree so a config change can be re-measured without a
# release, and it installs the postgres extra the SQLite default doesn't need.
FROM python:3.12-slim

WORKDIR /app

# Copy dependency metadata first so `pip install` is cached across source edits.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[postgres]"

EXPOSE 8765

CMD ["uvicorn", "jobengine.api:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "4"]
