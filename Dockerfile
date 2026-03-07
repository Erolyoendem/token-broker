FROM python:3.12-slim AS builder

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Nur minimale Systempakete
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Nur die unbedingt nötigen Module kopieren
COPY backend/app/ ./app/
COPY backend/llm_benchmark/ ./llm_benchmark/
COPY backend/agent_swarm/ ./agent_swarm/
COPY backend/market_intelligence/ ./market_intelligence/
# agent_evolution auskommentieren (spart PyTorch)
# COPY backend/agent_evolution/ ./agent_evolution/
# COPY backend/evolution/ ./evolution/
COPY backend/training_data/ ./training_data/
COPY backend/scripts/ ./scripts/
COPY backend/tenant/ ./tenant/

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
