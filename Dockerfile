FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ ./app/
COPY backend/llm_benchmark/ ./llm_benchmark/
COPY backend/agent_swarm/ ./agent_swarm/
COPY backend/market_intelligence/ ./market_intelligence/
COPY backend/agent_evolution/ ./agent_evolution/
COPY backend/training_data/ ./training_data/
COPY backend/evolution/ ./evolution/
COPY backend/scripts/ ./scripts/
COPY backend/tenant/ ./tenant/

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
