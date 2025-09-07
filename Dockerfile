FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8000

CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", \
     "--workers", "1", "--bind", "0.0.0.0:8000", \
     "--timeout", "0", "--graceful-timeout", "0", "--log-level", "info", \
     "-c", "gunicorn_conf.py"]