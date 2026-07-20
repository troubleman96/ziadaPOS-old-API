# Ziada POS — Deployment Guide

**Stack:** Django 5 API · Next.js 16 UI · PostgreSQL · MinIO object storage  
**API target:** `api.ziadapos.com` · Docker (§11a), port `8096` on the host · Nginx reverse proxy  
**UI target:** `www.ziadapos.com` (Vercel) — see the UI repo, not this one  
**Storage:** `media.camelcreatives.com` · MinIO bucket — confirm the real name with `manage.py test_minio`; this doc and some earlier notes disagree (`ziada` vs `ziada-pos`)

---

## 1. Server Prerequisites

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-contrib \
    nginx \
    certbot python3-certbot-nginx \
    git build-essential
```

---

## 2. PostgreSQL — Create Database & User

```bash
sudo -u postgres psql <<'SQL'
CREATE USER ziada WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
CREATE DATABASE ziada_db OWNER ziada;
GRANT ALL PRIVILEGES ON DATABASE ziada_db TO ziada;
SQL
```

> **Note:** Production settings use `ssl_require=True` for the DB connection.
> For a local PostgreSQL install on the same VPS, either configure SSL or set
> `ssl_require=False` and add `?sslmode=disable` to `DATABASE_URL`.

---

## 3. Application User & Directory

```bash
sudo useradd --system --create-home --shell /bin/bash ziada
sudo mkdir -p /var/www/ziada-api
sudo chown ziada:ziada /var/www/ziada-api
```

---

## 4. Clone & Install the API

```bash
sudo -u ziada git clone git@github.com:troubleman96/ziadaPOS-API.git /var/www/ziada-api
cd /var/www/ziada-api

sudo -u ziada python3.11 -m venv .venv
sudo -u ziada .venv/bin/python -m pip install --upgrade pip
sudo -u ziada .venv/bin/python -m pip install -r requirements.txt
sudo -u ziada .venv/bin/python -m pip install gunicorn
```

---

## 5. Environment File (API)

```bash
sudo -u ziada cp /var/www/ziada-api/.env.example /var/www/ziada-api/.env
sudo -u ziada nano /var/www/ziada-api/.env
sudo chmod 600 /var/www/ziada-api/.env
```

Production `.env` values:

```ini
# Django core
SECRET_KEY=<generate: python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
DEBUG=False
ALLOWED_HOSTS=api.ziadapos.com

# Database
DATABASE_URL=postgres://ziada:CHANGE_ME_STRONG_PASSWORD@localhost:5432/ziada_db

# CORS — allow the Next.js frontend
CORS_ALLOWED_ORIGINS=https://ziadapos.com

# JWT
JWT_ACCESS_TOKEN_LIFETIME_MINUTES=60
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

# AI (OpenRouter)
OPENROUTER_API_KEY=sk-or-v1-your-key-here
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_SITE_URL=https://ziadapos.com
OPENROUTER_SITE_NAME=Ziada POS

# Email (ZohoMail SMTP)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.zoho.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=noreply@ziadapos.com
EMAIL_HOST_PASSWORD=your-zoho-app-password
DEFAULT_FROM_EMAIL=Ziada POS <noreply@ziadapos.com>
SERVER_EMAIL=noreply@ziadapos.com
SITE_URL=https://ziadapos.com

# Daily report schedule (Africa/Dar_es_Salaam, 24h)
DAILY_REPORT_HOUR=22
DAILY_REPORT_MINUTE=0

# MinIO object storage — enable AFTER completing § MinIO below
USE_MINIO=True
MINIO_ENDPOINT_URL=https://media.camelcreatives.com
MINIO_ACCESS_KEY=camel
MINIO_SECRET_KEY=Camelcreatives@#2026
MINIO_BUCKET_NAME=ziada
MINIO_REGION=us-east-1
```

---

## 6. Django Setup

```bash
cd /var/www/ziada-api

# Create log and static directories
sudo -u ziada mkdir -p logs staticfiles media

# Apply all migrations
sudo -u ziada DJANGO_SETTINGS_MODULE=ziada.settings.production \
    .venv/bin/python manage.py migrate

# Collect static files (Django admin, etc.)
sudo -u ziada DJANGO_SETTINGS_MODULE=ziada.settings.production \
    .venv/bin/python manage.py collectstatic --noinput

# Create a superuser for Django admin
sudo -u ziada DJANGO_SETTINGS_MODULE=ziada.settings.production \
    .venv/bin/python manage.py createsuperuser
```

---

## 7. MinIO Object Storage

Product images and other uploaded files are stored in MinIO at `media.camelcreatives.com`.
MinIO implements the S3 protocol — `django-storages` / `boto3` handle it natively.

### 7a. Add the S3 API Nginx route on the MinIO server

The MinIO console (UI) runs on port **9001** and the S3 API runs on port **9000**.
Currently, Nginx on `media.camelcreatives.com` only proxies port 9001 (the console).
You need to add routing so that S3 API requests reach port 9000.

**SSH into the MinIO/Camel server and edit the Nginx config:**

```bash
sudo nano /etc/nginx/sites-available/media.camelcreatives.com
# or wherever the vhost file is
sudo nano /etc/nginx/conf.d/media.conf
```

Add a `map` block **outside** the `server {}` block and update the `location /`:

```nginx
# Route S3 API requests (AWS4 Authorization header) to MinIO API port 9000.
# Browser/console requests go to MinIO console port 9001.
map $http_authorization $minio_upstream {
    default                      http://127.0.0.1:9001;   # MinIO console
    "~^AWS4-HMAC-SHA256"         http://127.0.0.1:9000;   # MinIO S3 API
    "~^AWS4"                     http://127.0.0.1:9000;   # MinIO S3 API (any sig)
}

server {
    listen 443 ssl;
    server_name media.camelcreatives.com;

    ssl_certificate     /etc/letsencrypt/live/media.camelcreatives.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/media.camelcreatives.com/privkey.pem;

    client_max_body_size 50M;

    location / {
        proxy_pass         $minio_upstream;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout    30s;
        proxy_buffering        off;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 7b. Create the `ziada` bucket via the MinIO console

1. Open `https://media.camelcreatives.com` in your browser
2. Log in with user `camel` / password `Camelcreatives@#2026`
3. Click **Create Bucket** → name it `ziada`
4. In bucket settings → **Access Policy** → set to **Public** (public-read)

### 7c. Verify connectivity from the API server

```bash
cd /var/www/ziada-api
sudo -u ziada DJANGO_SETTINGS_MODULE=ziada.settings.production \
    .venv/bin/python manage.py test_minio
```

Expected output:
```
  Endpoint : https://media.camelcreatives.com
  Bucket   : ziada
  Key      : came****

① Connecting to MinIO… OK
② Checking bucket 'ziada'… exists
③ Uploading test object '_ziada_test_xxxxxxxx.txt'… OK
④ Downloading and verifying… OK
⑤ Public URL: https://media.camelcreatives.com/ziada/_ziada_test_xxxxxxxx.txt
⑥ Cleaning up… OK

✓ MinIO storage is working correctly.
```

### 7d. Enable MinIO in Django

Once `test_minio` passes, set in `.env`:

```ini
USE_MINIO=True
```

Then restart Gunicorn:

```bash
sudo systemctl restart ziada-api
```

Product images uploaded via the inventory API will now be stored in MinIO and
served from `https://media.camelcreatives.com/ziada/{path}`.

---

## 8. Gunicorn Systemd Service

```bash
sudo nano /etc/systemd/system/ziada-api.service
```

```ini
[Unit]
Description=Ziada POS API (Gunicorn)
After=network.target postgresql.service

[Service]
User=ziada
Group=ziada
WorkingDirectory=/var/www/ziada-api
Environment="DJANGO_SETTINGS_MODULE=ziada.settings.production"
ExecStart=/var/www/ziada-api/.venv/bin/gunicorn \
    --bind 127.0.0.1:8021 \
    --workers 3 \
    --worker-class sync \
    --timeout 120 \
    --access-logfile /var/www/ziada-api/logs/gunicorn_access.log \
    --error-logfile /var/www/ziada-api/logs/gunicorn_error.log \
    ziada.wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ziada-api
sudo systemctl start ziada-api
sudo systemctl status ziada-api
```

---

## 9. Nginx for the API (`api.ziadapos.com`)

```bash
sudo nano /etc/nginx/sites-available/ziada-api
```

```nginx
server {
    listen 80;
    server_name api.ziadapos.com;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    server_name api.ziadapos.com;

    ssl_certificate     /etc/letsencrypt/live/api.ziadapos.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.ziadapos.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 20M;

    location / {
        proxy_pass         http://127.0.0.1:8021;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # Static files (Django admin)
    location /static/ {
        alias /var/www/ziada-api/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Local media fallback (only used when USE_MINIO=False)
    location /media/ {
        alias /var/www/ziada-api/media/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/ziada-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 10. SSL Certificate (Let's Encrypt)

```bash
# Ensure DNS A record for api.ziadapos.com points to this server's IP first
sudo certbot --nginx -d api.ziadapos.com
sudo systemctl status certbot.timer   # auto-renewal check
```

---

## 11. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
# Port 8021 is NOT opened — Gunicorn binds to 127.0.0.1 only
```

---

## 11a. Alternative: Docker Deployment

Steps 3-11 above (venv, app user, gunicorn systemd unit) can be replaced
entirely by Docker Compose. § 2 (PostgreSQL) is also replaced — Compose runs
its own Postgres container instead. § 7 (MinIO) is unchanged either way; MinIO
runs on a separate server regardless of how the API itself is hosted.

This repo's `Dockerfile` + `docker-compose.yml` build a self-contained stack:
a `db` (Postgres 16) service and an `api` (Gunicorn, 3 workers) service.
Migrations and `collectstatic` run automatically on every container start
(see `entrypoint.sh`). Static files are served by WhiteNoise from inside the
container — no nginx static-file alias is required, only a reverse proxy.
The API listens on **host port 8096** (mapped to container port 8000).

### Prerequisites

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out/in (or `newgrp docker`) after this
```

### Deploy

```bash
cd /path/to/ziadaPOS-API   # wherever you cloned the repo
cp .env.example .env
nano .env
```

Fill in `.env` with real production values — same keys as § 5 above, plus:

```ini
DEBUG=False
ALLOWED_HOSTS=api.ziadapos.com
CORS_ALLOWED_ORIGINS=https://app.ziadapos.com
SITE_URL=https://app.ziadapos.com

# These provision the `db` container AND are used to build DATABASE_URL —
# docker-compose.yml overrides DATABASE_URL's host to `db` automatically,
# so the host/port in DATABASE_URL itself don't matter under Docker.
POSTGRES_DB=ziada_db
POSTGRES_USER=ziada
POSTGRES_PASSWORD=<generate a strong password>
```

```bash
docker compose up --build -d
docker compose logs -f api        # watch startup — migrate/collectstatic, then gunicorn
```

### Create the superuser

```bash
docker compose exec api python manage.py shell -c "
from apps.accounts.models import User
User.objects.create_superuser(
    username='ceo',
    email='ceo@camelcreatives.com',
    password='<the real password>',
    first_name='Ziada',
    last_name='Admin',
    phone='0700000000',   # placeholder — phone is unique+required; change later in /admin/
    role=User.ROLE_ADMIN,
)
"
```

(`phone` is the app's real login field and must be a unique 10-digit number —
the placeholder above just satisfies that constraint for an admin-only
account; change it to a real number from `/admin/` if this account should
also log in through the normal phone-based login.)

### Nginx reverse proxy (same as § 9, different port)

Use the exact Nginx server block from § 9, but change `proxy_pass` to the
Docker-mapped port and drop the `/static/`+`/media/` `alias` blocks (WhiteNoise
serves `/static/` itself; `/media/` is served by MinIO directly when
`USE_MINIO=True`):

```nginx
location / {
    proxy_pass         http://127.0.0.1:8096;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}
```

Then run certbot exactly as in § 10. Firewall (§ 11): same — port 8096 is
**not** opened externally, only reachable via the Nginx proxy on 127.0.0.1.

### Update / redeploy

```bash
git pull
docker compose up --build -d   # rebuilds the api image, re-runs migrate/collectstatic, zero-downtime restart of just that container
```

### Docker troubleshooting

| Symptom | Check |
|---|---|
| `api` container keeps restarting | `docker compose logs api` — usually a bad `.env` value or DB not ready yet |
| 502 from Nginx | `docker compose ps` — is `api` healthy? `curl http://127.0.0.1:8096/api/v1/auth/login/` locally on the server |
| Redirect loop over HTTPS | `SECURE_PROXY_SSL_HEADER` requires Nginx to send `X-Forwarded-Proto` — confirm the proxy block above is in place |
| DB connection refused | `docker compose logs db` — Postgres container failing to start, often a `POSTGRES_PASSWORD` mismatch with an existing `ziada_pgdata` volume from a prior run |

---

## 12. Connect the UI to the API

The Next.js frontend reads the API base URL from `NEXT_PUBLIC_API_URL`.

### Local development (already configured)

`UI/.env.local`:
```ini
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

### Production

Set the following environment variables in your UI hosting platform
(Vercel dashboard, Coolify, Docker Compose, etc.):

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.ziadapos.com` |
| `NEXT_PUBLIC_SITE_URL` | `https://app.ziadapos.com` |

**If self-hosting Next.js on a VPS:**

```bash
# Clone the UI repo
git clone git@github.com:troubleman96/ziadaPOS-UI.git /var/www/ziada-ui
cd /var/www/ziada-ui

# Create production env file
cat > .env.production.local <<'EOF'
NEXT_PUBLIC_API_URL=https://api.ziadapos.com
NEXT_PUBLIC_SITE_URL=https://app.ziadapos.com
EOF

# Install and build
npm install
npm run build

# Serve (add a systemd service or use PM2)
npm start   # runs on port 3000 by default
```

**Nginx for the UI (`app.ziadapos.com`):**

```nginx
server {
    listen 80;
    server_name app.ziadapos.com;
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    server_name app.ziadapos.com;

    ssl_certificate     /etc/letsencrypt/live/app.ziadapos.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.ziadapos.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:3000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo certbot --nginx -d app.ziadapos.com
```

---

## 13. Verify Full Deployment

```bash
# API health check
curl -I https://api.ziadapos.com/api/v1/auth/login/

# MinIO storage test
cd /var/www/ziada-api
sudo -u ziada DJANGO_SETTINGS_MODULE=ziada.settings.production \
    .venv/bin/python manage.py test_minio

# Application logs
tail -f /var/www/ziada-api/logs/ziada.log
tail -f /var/www/ziada-api/logs/gunicorn_error.log

# Gunicorn status
sudo systemctl status ziada-api
sudo ss -tlnp | grep 8021
```

---

## 14. Updates / Redeploy

```bash
# API
cd /var/www/ziada-api
sudo -u ziada git pull
sudo -u ziada DJANGO_SETTINGS_MODULE=ziada.settings.production \
    .venv/bin/python -m pip install -r requirements.txt
sudo -u ziada DJANGO_SETTINGS_MODULE=ziada.settings.production \
    .venv/bin/python manage.py migrate --noinput
sudo -u ziada DJANGO_SETTINGS_MODULE=ziada.settings.production \
    .venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart ziada-api

# UI
cd /var/www/ziada-ui
git pull
npm install
npm run build
# restart PM2 or systemd service
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| 502 Bad Gateway (API) | `systemctl status ziada-api` — Gunicorn not running |
| 400 Bad Request | `ALLOWED_HOSTS` doesn't include `api.ziadapos.com` |
| CORS errors in UI | `CORS_ALLOWED_ORIGINS` must include `https://app.ziadapos.com` |
| Static/media 404 | Nginx `alias` paths correct? `collectstatic` run? |
| DB connection error | `DATABASE_URL` in `.env` · check `ssl_require` flag |
| APScheduler not firing | Check `logs/ziada.log` — scheduler starts in `NotificationsConfig.ready()` |
| Email not sending | Verify ZohoMail app password · port 587 open outbound |
| MinIO: "API port" error | Nginx S3 API proxy block not configured — see § 7a |
| MinIO: timeout | MinIO port 9000 not running or firewalled on the storage server |
| Product images 404 | `USE_MINIO=True` set in `.env`? Bucket `ziada` is public-read? |
| UI can't reach API | `NEXT_PUBLIC_API_URL` set to `https://api.ziadapos.com` in UI env? |
