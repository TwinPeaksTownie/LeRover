FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests

WORKDIR /app

COPY __init__.py /app/
COPY server.py /app/
COPY tools_audit.py /app/
COPY tools_hardware.py /app/
COPY tools_computer_use.py /app/
COPY tools_speech.py /app/
COPY tools_denoise.py /app/
COPY contract_scanner.py /app/
COPY ornith_config_loader.py /app/
COPY ornith_daemon.py /app/

ENV PYTHONUNBUFFERED=1
ENV REPO_PATH=/workspace
ENV BRAIN_DIR=/brain
ENV ORNITH_AUDIT_BACKEND=nim
ENV POCKET_TTS_HOST=host.docker.internal
ENV POCKET_TTS_PORT=8057
ENV HOST_BRIDGE_URL=http://host.docker.internal:8059/inject

CMD ["python", "/app/ornith_daemon.py", "--repo-path", "/workspace", "--brain-dir", "/brain"]
