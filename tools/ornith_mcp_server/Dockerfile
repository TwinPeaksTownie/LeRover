FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends     git     openssh-client     curl     ca-certificates     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY __init__.py /app/
COPY server.py /app/
COPY tools_audit.py /app/
COPY tools_hardware.py /app/
COPY tools_computer_use.py /app/
COPY tools_speech.py /app/
COPY ornith_daemon.py /app/

ENV PYTHONUNBUFFERED=1
ENV REPO_PATH=/workspace
ENV BRAIN_DIR=/brain
ENV LM_STUDIO_URL=http://host.docker.internal:1234/v1/chat/completions
ENV POCKET_TTS_HOST=host.docker.internal
ENV POCKET_TTS_PORT=8057
ENV HOST_BRIDGE_URL=http://host.docker.internal:8059/inject

CMD ["python", "/app/ornith_daemon.py", "--repo-path", "/workspace", "--brain-dir", "/brain"]
