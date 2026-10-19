# 源码来源与线上关系

- 提取日期：2026 年 10 月 19 日。
- 服务器：用户已有阿里云服务器，使用既有 SSH 凭据只读提取。
- 源目录：`/root/prjs/xiaozhi-esp32-server/main/manager-web`。
- 服务器 Git HEAD：`fd745788cb756a31df1d778714ea30aa96c082b5`。
- 此快照包含当前工作区修改，并非只提取 Git HEAD。共有 6 个网页端文件在服务端 Git 中显示为已修改，名单见 `DEPLOYMENT_EVIDENCE.json`。
- 实际网站静态目录：`/var/www/realecho-www`。
- 当前源码目录的编译产物目录：`main/manager-web/dist`。

## 线上比对

只读逐文件 SHA-256 比对当前 `dist` 中的文件与线上同名文件：

- 一致：96 个。
- 内容不同：0 个。
- 线上缺失：0 个。

线上可能仍有旧构建遗留的额外文件；本检查不将这些当成当前源码。编译产物匹配能说明部署目录关系，不能单独证明每一个尚未提交的源文件都已重新编译。这里交接的是提取时的当前源码工作区。

## 旧发布目录

另发现 `/root/prjs/releases/login-wallpaper-20261010/web`，其编译首页与当前线上首页不同。它与当前开发目录存在以下源码或辅助文件差异，因此未将旧目录混入本交接包：

- `.npmrc`
- `README.md`
- `package-lock.json`
- `scripts/check-i18n-ota.js`
- `src/components/AddDeviceDialog.vue`
- `src/i18n/en.js`
- `src/i18n/zh_CN.js`
- `src/views/DeviceManagement.vue`

## 上传范围

保留 `manager-web` 的 Vue、JS、SCSS、i18n、构建配置、锁文件和原始静态图像。`SOURCE_MANIFEST.json` 记录提取时原文件 SHA-256，新增说明和 `.env.example` 不属于服务器原文件。

未上传 One-API、移动端、服务端代码、数据库、用户数据、生产环境文件、npm 配置、编译产物和缓存。`public/pc_executor_update.zip`、`.tar.gz` 属于额外执行器分发包，本轮网页视觉修改不包含它们；网页资源源码本身保留。

本次没有修改服务器源码、启动或停止服务、修改 Nginx、部署构建产物，也没有读取业务数据库或用户记忆。
