# 20万上下文与近期记忆增量

已发布版本的需求、测试、费用限制和回滚步骤见：

- `docs/CONTEXT_MEMORY_IMPLEMENTATION_20260929.md`
- `docs/BAILIAN_MEMORY_PRD_20260928.md`第18节
- `docs/BAILIAN_MEMORY_IMPLEMENTATION_20260929.md`第11节

## 交付文件

`delivery/overlay.tar.gz`含28个生产源码与6个测试文件，叠加在此前已经上线的百炼服务端版本；不是完整服务仓库。`manifest.json`记录每个文件的SHA-256。`delivery-report.json`为脱敏的测试、用量和生产聚合报告，`published.json`、`final-patch-published.json`与`business-patch-published.json`分别记录主发布、摘要保护和业务召回补充，`baseline.json`记录发布前逐文件版本。图和界面检查另存JSON。

源码包不含生产配置、密钥、用户记忆、音频或画像。原本的本地开发镜像仍在`tmp/bailian-memory-product/server`；临时目录被清理时，可从交付源码包恢复本次增量。

远端生产：`/root/prjs/xiaozhi-esp32-server`。

远端候选：`/root/prjs/tmp/bailian-memory-product`。

远端发布与恢复记录：`/root/prjs/tmp/context-memory-release-20260929`。

2026-09-30 身份归属补丁：`delivery/identity-fix-20260930` 保存部署后的两份语音服务源码；`install_identity_fix_20260930.py` 带原始版本哈希保护和回滚备份。部署结果与待实机验证项见实施记录第10节。

首位声纹绑定后热刷新：`delivery/voiceprint-refresh-20260930` 和 `install_voiceprint_refresh_20260930.py`；见实施记录第11节。默认人物的测试事实按既定规则退役，不会移入新成员。

## 脚本用途

| 文件 | 用途 |
|---|---|
| package.py | 本地按明确名单打包源码，不包含数据 |
| stage.py | 首次候选准备和生产基线记录；发布后不能重跑覆盖基线 |
| run_tests.py | 候选目录、结构克隆测试数据库、合成数据回归及Java构建 |
| boot_smoke.py | 空白测试数据库撤回本次结构，再由Liquibase重演迁移；使用独立Redis |
| real_model_test.py | 独立合成钱包的真实长输入、缓存字段和摘要测试；会产生模型费用 |
| check_frontend.cjs | 无头Chrome、合成API、原Vue页面兼容检查 |
| check_visual.cjs | 原四场景图的宽度、越界及错误检查 |
| deploy.py | 只允许首次发布，已有published.json时拒绝执行 |
| finalize_patch.py | 最后两文件摘要保护补丁；不可在当前已完成补丁上重跑 |
| finalize_business_recall.py | 后续Java业务记录召回补丁；已有发布记录时拒绝重跑 |
| check_release.py | 人工只读核查、生产哈希和脱敏报告，不创建自动观察 |
| verify_delivery.py | 本地核验交付源码包、逐文件哈希与验收记录，生成verification.json及checksums.json |

远端测试依赖`tools/bailian-memory-product`中的迁移结构克隆、Python回归与启动演练助手，对应部署到`/tmp/migration_fixture.py`、`/tmp/run_python_regression.py`、`/tmp/run_boot_smoke.py`。核查复用`/tmp/observe_release.py`。

`boot_smoke.py`的DROP/ALTER只作用于刚创建且聊天表为空、名称以`bailian_memory_test_`开头的隔离数据库，不得替换成生产库。模型和百炼测试使用合成临时账号；不要改为客户钱包运行。

复跑测试不会发布服务。回滚按实施记录操作，保留新增数据库、删除/抑制/退役及财务账本，不恢复删除的用户正文。不得将初次发布脚本作为日常升级脚本。
