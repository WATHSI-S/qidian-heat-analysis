# 阿里云工作台部署

线上入口：`https://47.102.40.95/`。全站通过 nginx HTTP Basic 登录保护，80 端口跳转 HTTPS；ACME 验证路径单独开放。密码不放入源代码。初始用户名是 `author`，凭据保存在服务器 `/root/qidian-workbench-access.txt`，本机副本为被 Git 忽略的 `private/server-access.txt`。

## 运行结构

- `/opt/qidian-workbench/current`：指向独立代码发布目录。
- `/opt/qidian-workbench/venv`：独立 Python 环境。
- `/var/lib/qidian-workbench`：SQLite 与缓存，仅服务用户可读写，不在 nginx 静态目录内。
- `/var/www/qidian-heat-analysis`：现有周度发布产物，工作台只读使用它的榜单页与数据。
- `qidian-workbench.service`：以受限用户在 `127.0.0.1:8765` 运行，开机启动、失败自动重启。
- `qidian-cert-renew.timer`：每日两次检查短期 IP 证书续期，成功后重新加载 nginx。

本机研究记录没有自动上传。需要时通过工作台 JSON 导出、登录线上后导入。

## 更新代码

在项目根目录打包并通过现有 SSH 密钥上传（不要包含 `private/` 或 `.env`）：

```powershell
tar -czf private/workbench-release.tgz --exclude=__pycache__ workbench scraper deploy
scp -i "$env:USERPROFILE/.ssh/qidian_vps_deploy" private/workbench-release.tgz root@47.102.40.95:/tmp/qidian-workbench-release.tgz
scp -i "$env:USERPROFILE/.ssh/qidian_vps_deploy" deploy/install-workbench.sh root@47.102.40.95:/tmp/install-qidian-workbench.sh
ssh -i "$env:USERPROFILE/.ssh/qidian_vps_deploy" root@47.102.40.95 "bash /tmp/install-qidian-workbench.sh"
```

安装脚本使用 Certbot 5.4+ 的 IP 证书支持，保留首次部署前的 nginx 配置和既有凭据。周度任务仍负责榜单采集与静态发布，不会更新 Python 服务代码；点击“刷新本地书目”或重启服务可重读更新后的快照。

## 模型与运维

AI 密钥需要单独配置在服务器 `/etc/qidian-workbench.env`，格式为 `OPENAI_API_KEY=...`，权限设为 root `0600`，再重启服务。未配置时人工研究、榜单和导出正常使用。不要在聊天、提交或日志中粘贴密钥。

```bash
systemctl status qidian-workbench
journalctl -u qidian-workbench -n 50 --no-pager
systemctl restart qidian-workbench
systemctl list-timers qidian-cert-renew.timer
/opt/qidian-certbot/bin/certbot renew --dry-run --run-deploy-hooks --no-random-sleep-on-renew
```

若需恢复原静态站，复制 `/opt/qidian-workbench/nginx-before-workbench.conf` 到 `/etc/nginx/sites-available/default`，执行 `nginx -t` 后 reload nginx。私有数据库无需删除；回滚代码可将 `current` 指向之前的 release 并重启工作台。
