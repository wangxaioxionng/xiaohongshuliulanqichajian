// PM2 配置 — 服务器上用 `pm2 start ecosystem.config.js` 启动
module.exports = {
  apps: [
    {
      name: 'xhs-collect-api',
      cwd: '/opt/xhs-collect',
      script: '/opt/xhs-collect/venv/bin/uvicorn',
      args: 'app:app --host 127.0.0.1 --port 8765 --workers 1',
      interpreter: 'none',
      env: {
        PYTHONUNBUFFERED: '1',
      },
      out_file: '/opt/xhs-collect/logs/out.log',
      error_file: '/opt/xhs-collect/logs/err.log',
      max_memory_restart: '500M',
      autorestart: true,
      restart_delay: 3000,
    },
  ],
};
