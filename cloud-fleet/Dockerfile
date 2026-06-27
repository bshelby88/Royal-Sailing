FROM python:3.11-slim

WORKDIR /app

COPY orchestrator.py .
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || true

ENV PYTHONUNBUFFERED=1

CMD ["python", "orchestrator.py", "cycle"]
