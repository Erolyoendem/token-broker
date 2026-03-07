# Cache-Buster: 2026-03-08
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ABSOLUTES MINIMUM – nur diese drei Ordner werden kopiert
COPY backend/app/ ./app/
COPY backend/llm_benchmark/ ./llm_benchmark/
COPY backend/tenant/ ./tenant/

# ALLE ANDEREN ORDNER (agent_swarm, agent_evolution, training_data, ...) werden NICHT kopiert!

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
