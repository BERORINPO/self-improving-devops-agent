# Python 3.12 slim base for Google ADK + Vertex AI compatibility.
# ADK requires Python 3.10+; 3.12 has the broadest ecosystem support.
# 3.13 / 3.14 are not explicitly supported by ADK at the time of writing.
FROM python:3.12-slim

WORKDIR /app

# System deps (curl for healthcheck, ca-certificates for HTTPS to Vertex AI)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps (separate layer for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# App source
COPY src ./src

# Cloud Run best practice: non-root user
RUN groupadd -r app && useradd -r -g app app && chown -R app:app /app
USER app

# Cloud Run default port
ENV PORT=8080
ENV PYTHONPATH=/app/src
EXPOSE 8080

# Cloud Run entry point: FastAPI (AutoSRE agent-service) via uvicorn on $PORT.
# server.py lives at src/agents/server.py; PYTHONPATH=/app/src -> module agents.server.
CMD ["sh", "-c", "uvicorn agents.server:app --host 0.0.0.0 --port ${PORT}"]
