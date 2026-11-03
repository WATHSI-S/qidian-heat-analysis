#!/usr/bin/env bash
set -euo pipefail
base=/opt/qidian-workbench
install -d "$base/releases" /var/www/qidian-acme
release="$base/releases/$(date -u +%Y%m%dT%H%M%SZ)"
install -d "$release"
tar xzf /tmp/qidian-workbench-release.tgz -C "$release"
if [ ! -e "$base/nginx-before-workbench.conf" ]; then
    cp -a /etc/nginx/sites-available/default "$base/nginx-before-workbench.conf"
fi
# This directory contains only the verified public publication artifact.
chmod -R a+rX /var/www/qidian-heat-analysis
id qidian-workbench >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/qidian-workbench qidian-workbench
install -d -m 700 -o qidian-workbench -g qidian-workbench /var/lib/qidian-workbench
echo 'Installing workbench dependencies'
python3 -m venv "$base/venv"
"$base/venv/bin/pip" install --quiet -r "$release/workbench/requirements.txt"
echo 'Installing certificate client'
python3 -m venv /opt/qidian-certbot
/opt/qidian-certbot/bin/pip install --quiet 'certbot>=5.4,<6'
cat >/etc/nginx/conf.d/qidian-acme-temp.conf <<'EOF'
server {
    listen 80;
    server_name 47.102.40.95;
    root /var/www/qidian-heat-analysis;
    location ^~ /.well-known/acme-challenge/ { root /var/www/qidian-acme; }
    location / { try_files $uri $uri/ =404; }
}
EOF
nginx -t
systemctl reload nginx
echo 'Requesting trusted IP certificate'
/opt/qidian-certbot/bin/certbot certonly --non-interactive --agree-tos --register-unsafely-without-email --preferred-profile shortlived --webroot --webroot-path /var/www/qidian-acme --ip-address 47.102.40.95 --cert-name 47.102.40.95
echo 'Preparing private access credentials'
python3 - <<'PY'
import os, pathlib, secrets, subprocess
credentials = pathlib.Path('/root/qidian-workbench-access.txt')
if not credentials.exists():
    password = secrets.token_urlsafe(24)
    result = subprocess.run(['openssl', 'passwd', '-6', '-stdin'], input=password+'\n', text=True, check=True, capture_output=True)
    auth = pathlib.Path('/etc/nginx/qidian-workbench.htpasswd')
    auth.write_text('author:'+result.stdout.strip()+'\n')
    os.chmod(auth, 0o640)
    credentials.write_text('URL: https://47.102.40.95/\nUsername: author\nPassword: '+password+'\n')
    os.chmod(credentials, 0o600)
PY
chown root:www-data /etc/nginx/qidian-workbench.htpasswd
if [ -d /root/.cache/ms-playwright ]; then
    install -d "$base/browsers"
    cp -a /root/.cache/ms-playwright/. "$base/browsers/"
    chmod -R a+rX "$base/browsers"
else
    PLAYWRIGHT_BROWSERS_PATH="$base/browsers" "$base/venv/bin/python" -m playwright install chromium
fi
ln -sfn "$release" "$base/current"
install -m 644 "$release/deploy/qidian-workbench.service" /etc/systemd/system/
install -m 644 "$release/deploy/qidian-cert-renew.service" /etc/systemd/system/
install -m 644 "$release/deploy/qidian-cert-renew.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now qidian-workbench.service
systemctl restart qidian-workbench.service
for attempt in $(seq 1 20); do
    if curl --fail --silent http://127.0.0.1:8765/ >/dev/null; then break; fi
    sleep 1
done
curl --fail --silent http://127.0.0.1:8765/ >/dev/null
install -m 644 "$release/deploy/nginx-workbench.conf" /etc/nginx/sites-available/default
mv /etc/nginx/conf.d/qidian-acme-temp.conf /etc/nginx/conf.d/qidian-acme-temp.conf.disabled
nginx -t
systemctl reload nginx
systemctl enable --now qidian-cert-renew.timer
echo 'DEPLOYED: service and HTTPS authentication enabled'
systemctl is-active qidian-workbench nginx
curl --silent --output /dev/null --write-out 'Unauthenticated HTTPS status: %{http_code}\n' https://47.102.40.95/
