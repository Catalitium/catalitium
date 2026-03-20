# Catalitium Deployment Guide

See `.env.example` for all required environment variables.

---

## 1. Server Setup (Ubuntu 22.04+)

```bash
# Create app user and directory
sudo useradd -r -s /bin/bash -d /opt/catalitium catalitium
sudo mkdir -p /opt/catalitium
sudo chown catalitium:catalitium /opt/catalitium

# Clone repo
sudo -u catalitium git clone https://github.com/your-org/catalitium /opt/catalitium

# Create virtualenv and install deps
sudo -u catalitium python3 -m venv /opt/catalitium/.venv
sudo -u catalitium /opt/catalitium/.venv/bin/pip install -r /opt/catalitium/requirements.txt
```

---

## 2. Environment Variables

Copy and fill in `.env.example`:

```bash
sudo -u catalitium cp /opt/catalitium/.env.example /opt/catalitium/.env
sudo -u catalitium nano /opt/catalitium/.env
```

Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Supabase pooler connection string |
| `SECRET_KEY` | Yes | 64-char random hex (use `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `SMTP_HOST` | Yes | SMTP server (smtp.gmail.com) |
| `SMTP_USER` | Yes | SMTP username |
| `SMTP_PASS` | Yes | SMTP app password |
| `BASE_URL` | Yes | Production URL (https://catalitium.com) |

---

## 3. Systemd Service

Create `/etc/systemd/system/catalitium.service`:

```ini
[Unit]
Description=Catalitium Flask App
After=network.target

[Service]
User=catalitium
Group=catalitium
WorkingDirectory=/opt/catalitium
EnvironmentFile=/opt/catalitium/.env
ExecStart=/opt/catalitium/.venv/bin/gunicorn \
    --workers 3 \
    --bind 0.0.0.0:5000 \
    --timeout 30 \
    --keepalive 5 \
    --access-logfile - \
    "run:app"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable catalitium
sudo systemctl start catalitium
```

---

## 4. Deploy Update

```bash
ssh root@<server-ip>
sudo -u catalitium -H bash -lc '
  cd /opt/catalitium &&
  git fetch --all --prune &&
  git reset --hard origin/main &&
  /opt/catalitium/.venv/bin/pip install -r requirements.txt
'
sudo systemctl restart catalitium
```

---

## 5. Weekly Digest Cron

Add to crontab for the `catalitium` user:

```bash
sudo -u catalitium crontab -e
```

```
# Weekly digest every Monday at 08:00 UTC
0 8 * * 1 /opt/catalitium/.venv/bin/python /opt/catalitium/scripts/send_weekly_digest.py >> /opt/catalitium/logs/digest.log 2>&1
```

---

## 6. Health Check

```bash
curl -f http://localhost:5000/health
# Expected: {"status": "ok"}
```

---

## 7. Nginx Reverse Proxy (recommended)

```nginx
server {
    listen 80;
    server_name catalitium.com www.catalitium.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name catalitium.com www.catalitium.com;

    ssl_certificate     /etc/letsencrypt/live/catalitium.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/catalitium.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

*See `deploy.txt` for the quick one-liner update command.*
