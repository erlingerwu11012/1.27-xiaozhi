# 4.30 完整代码公开快照

创建日期：2026-10-20（Asia/Shanghai）。
来源工作区：E:/github/github_code/all/4.30
原本地分支：codex/spine-render-v2-20261002
原本地 HEAD：c1ea54ba9796e1ba872c5c6b4d5f30183896cd43

本分支包含上述工作区当前的代码、未提交修改、已存在的删除、新增工具、文档、产品素材和 skills，是独立的当前文件快照；不带入未审查的本地历史。本地工作区、原分支和远程 main 均未修改。

## 上传边界

- 延续原仓库忽略规则：outputs/、build/、managed_components/、releases/、私钥、真实 .env、日志和生成的二进制等不上传。
- 另外排除可重装的 node_modules、机器本地权限配置、原始硬件/服务器抓取和可重新构建的网页 dist；本地原文件保留。
- 部分历史工具副本中硬编码的天气服务 key、access token 和网关 token 已替换为 REPLACE_WITH_* 占位符，压缩包内的对应值同步替换。实际运行时需要自行提供凭据。
- 源文件中的旧部署清单和哈希表示当时版本；已脱敏副本的最新哈希以 SNAPSHOT_MANIFEST.json 为准。
- 本次只做公开备份，没有重新编译固件、刷机或部署服务器，不能据此视为整仓回归测试通过。

## 其他现有分支

服务器前端交接代码：codex/server-frontend-claude-20261019。
Claude 第一版原型：claude/console-prototype-v1。
以上分支继续独立保留，不自动合并到本次快照。
