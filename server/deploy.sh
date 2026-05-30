#!/bin/bash
# 一键部署 xhs-collect-api 到 14.22.112.147
# 用法：在本机 (Mac) 运行 bash deploy.sh
set -e

SERVER="root@14.22.112.147"
REMOTE_DIR="/opt/xhs-collect"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "===== 步骤 1/6：上传代码 ====="
rsync -avz --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'config.json' \
  --exclude 'venv' --exclude 'logs' \
  --exclude 'data.db' --exclude 'data.db-journal' \
  --exclude 'data.db.bak.*' \
  --exclude '.DS_Store' \
  --exclude 'secrets.js' \
  "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"

echo "===== 步骤 2/6：上传 config.json（包含密钥，单独传） ====="
if [ -f "$LOCAL_DIR/config.json" ]; then
  scp "$LOCAL_DIR/config.json" "$SERVER:$REMOTE_DIR/config.json"
  ssh "$SERVER" "chmod 600 $REMOTE_DIR/config.json"
else
  echo "⚠️ 警告：本地没有 config.json，跳过。请确认服务器上已存在 $REMOTE_DIR/config.json"
fi

echo "===== 步骤 3/6：装 Python 依赖（如果还没装） ====="
ssh "$SERVER" "cd $REMOTE_DIR && ./venv/bin/pip install -q -U fastapi 'uvicorn[standard]' requests lark-oapi"

echo "===== 步骤 4/6：部署 nginx 站点配置 ====="
ssh "$SERVER" "cp $REMOTE_DIR/nginx-xhs-collect.conf /etc/nginx/sites-available/xhs-collect && \
  ln -sf /etc/nginx/sites-available/xhs-collect /etc/nginx/sites-enabled/xhs-collect && \
  nginx -t && nginx -s reload"

echo "===== 步骤 5/6：启动 / 重启 PM2 服务 ====="
ssh "$SERVER" "cd $REMOTE_DIR && pm2 describe xhs-collect-api > /dev/null 2>&1 \
  && pm2 restart xhs-collect-api \
  || pm2 start ecosystem.config.js"
ssh "$SERVER" "pm2 save"

echo "===== 步骤 6/6：健康检查 ====="
sleep 2
echo "本机 (uvicorn) → "
ssh "$SERVER" "curl -s http://127.0.0.1:8765/api/health"
echo
echo "经 nginx 8866 → "
curl -s http://14.22.112.147:8866/api/health
echo
echo
echo "✅ 部署完成。API 地址：http://14.22.112.147:8866"
echo "   /api/health 无需鉴权，其他接口需 Header: X-Auth-Token: <config.json 里的 auth_token>"
