# Sync In Backend Deployment Handoff

## 1. Project Overview

Sync In Backend is the Django backend for Sync In attendance.

- Production domain: `https://syncin.ua-cit.com`
- API base: `https://syncin.ua-cit.com/api`
- QR scan URL format: `https://syncin.ua-cit.com/scan/<qr_token>`

## 2. Required Server Packages

- Python 3.12
- `python3.12-venv`
- PostgreSQL
- Nginx
- Git
- `build-essential` if native packages need compilation
- Certbot if SSL is managed with Let's Encrypt

## 3. Fresh Deploy Path

```bash
/var/www/syncin/backend/attendance-backend
```

## 4. PostgreSQL Setup

Database: `syncin_db`

User: `syncin_user`

Run inside `psql` as a privileged PostgreSQL user:

```sql
CREATE USER syncin_user WITH PASSWORD '<STRONG_PASSWORD>';
CREATE DATABASE syncin_db OWNER syncin_user;
GRANT ALL PRIVILEGES ON DATABASE syncin_db TO syncin_user;
```

## 5. Backend Setup Commands

```bash
cd /var/www/syncin/backend
git clone <BACKEND_REPO_URL> attendance-backend
cd attendance-backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.production.example .env
nano .env
python manage.py check
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

Fill `.env` with real server values. Do not commit real `.env` files.

## 6. Gunicorn/Systemd Example

Service name: `syncin-backend`

Create `/etc/systemd/system/syncin-backend.service`:

```ini
[Unit]
Description=Sync In Django Backend
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/syncin/backend/attendance-backend
EnvironmentFile=/var/www/syncin/backend/attendance-backend/.env
ExecStart=/var/www/syncin/backend/attendance-backend/.venv/bin/gunicorn core.wsgi:application --bind 127.0.0.1:8005
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable syncin-backend
sudo systemctl start syncin-backend
```

## 7. Nginx Reverse Proxy Example

Domain: `syncin.ua-cit.com`

Proxy target: `http://127.0.0.1:8005`

```nginx
server {
    listen 80;
    server_name syncin.ua-cit.com;

    location /static/ {
        alias /var/www/syncin/backend/attendance-backend/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

After saving:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 8. SSL/Certbot Example

```bash
sudo certbot --nginx -d syncin.ua-cit.com
sudo certbot renew --dry-run
```

After HTTPS is active, confirm `.env` contains:

```env
BACKEND_BASE_URL=https://syncin.ua-cit.com
FRONTEND_URL=https://syncin.ua-cit.com
WEB_APP_BASE_URL=https://syncin.ua-cit.com
```

## 9. Required Verification Commands

Run from the project directory with the virtualenv active:

```bash
python manage.py check
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart syncin-backend
sudo systemctl status syncin-backend
sudo journalctl -u syncin-backend -n 100 --no-pager
```

HTTP checks:

```bash
curl -I https://syncin.ua-cit.com/scan/test
curl -I https://syncin.ua-cit.com/.well-known/assetlinks.json
curl -I https://syncin.ua-cit.com/api/
```

Expected:

- `/scan/test` should be `400` or `404`, not `500`.
- `/.well-known/assetlinks.json` should be `200`.
- `/api/` should not return `500`.

## 10. Troubleshooting Code 500

Likely causes:

- `SECRET_KEY` missing.
- `DATABASE_URL` wrong.
- Migrations not applied.
- PostgreSQL user/password wrong.
- `DSA_PRIVATE_KEY` or `DSA_PUBLIC_KEY` malformed.
- `ALLOWED_HOSTS` missing `syncin.ua-cit.com`.
- CORS/CSRF missing production domain or localhost dev origins.
- Systemd service not loading `.env`.
- Gunicorn not restarted after env changes.

Useful commands:

```bash
sudo journalctl -u syncin-backend -n 100 --no-pager
python manage.py check
python manage.py showmigrations
```

## 11. Frontend/Mobile Dependency Notes

Web app:

```env
VITE_API_BASE_URL=https://syncin.ua-cit.com/api
```

Mobile app:

```env
EXPO_PUBLIC_API_BASE_URL=https://syncin.ua-cit.com/api
EXPO_PUBLIC_SYNCIN_LINK_BASE_URL=https://syncin.ua-cit.com
```

Mobile App Links require:

```text
https://syncin.ua-cit.com/.well-known/assetlinks.json
```

QR output should be:

```text
https://syncin.ua-cit.com/scan/<qr_token>
```

## 12. Production Environment Notes

Use `.env.production.example` as the template. Required URL settings should be:

```env
BACKEND_BASE_URL=https://syncin.ua-cit.com
FRONTEND_URL=https://syncin.ua-cit.com
WEB_APP_BASE_URL=https://syncin.ua-cit.com
CORS_ALLOWED_ORIGINS=https://syncin.ua-cit.com,http://localhost:5173,http://127.0.0.1:5173
CSRF_TRUSTED_ORIGINS=https://syncin.ua-cit.com,http://localhost:5173,http://127.0.0.1:5173
```

DSA key env values may use escaped newline format:

```env
DSA_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
DSA_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
```

Never expose the real private key in source control, logs, frontend code, or mobile code.
