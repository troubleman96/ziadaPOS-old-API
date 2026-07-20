# Ziada POS API — production image
# Build:  docker build -t ziada-api .
# Run:    see docker-compose.yml (handles DB + env vars)

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=ziada.settings.production

WORKDIR /app

# libpq-dev + build-essential: psycopg2-binary occasionally needs these on
# slim images; curl: used by the container healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs staticfiles media \
    && adduser --system --group --no-create-home ziada \
    && chown -R ziada:ziada /app

USER ziada

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "ziada.wsgi:application"]
