FROM python:3.11-slim

WORKDIR /app

# Install system deps (psycopg2 build deps not needed — using asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Copy API source
COPY api/ /app/api/

# Run Alembic migrations then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload"]
