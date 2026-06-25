FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY auraorderflow ./auraorderflow
COPY config.yaml .

# Always-on host: keep the process alive (no max runtime).
ENV MAX_RUNTIME_SECONDS=0

CMD ["python", "-m", "auraorderflow"]
