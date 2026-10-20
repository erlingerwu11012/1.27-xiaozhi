/**
 * PM2 进程管理配置
 * 使用前请先安装: npm install -g pm2
 * 启动: pm2 start ecosystem.config.js
 * 重启: pm2 restart xiaozhi-server
 *
 * 环境变量 PYTHONIOENCODING/LANG/LC_ALL 用于强制 UTF-8，避免 ascii codec 错误
 */
module.exports = {
  apps: [
    {
      name: 'xiaozhi-server',
      script: 'app.py',
      interpreter: 'python',
      cwd: __dirname,
      env: {
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
        LANG: 'C.UTF-8',
        LC_ALL: 'C.UTF-8',
      },
      merge_logs: true,
      max_restarts: 10,
      min_uptime: '10s',
    },
  ],
};
