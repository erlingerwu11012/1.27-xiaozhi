# 小智硬件实际计费交付

用户已授权准确且测试通过后自动部署。Aimi隔离、画像关闭、无固件OTA、无自动观察。

最新报告：docs/HARDWARE_BILLING70_TEST_REPORT_20261001.md。

- tests/full-validation.json：58步全量隔离回归。
- tests/real-auth-relay-ledger.json：真实令牌、原生/兼容、流式及四类模型新账本。
- tests/real-audio-ledger.json：真实ASR/TTS官方单位及新账本。
- tests/real-memory-ledger.json：临时人物、云端存取与精确结算。
- tests/ui：前端检查结果。

候选源在tmp/hardware-billing70；delivery及manifest已按最终91个源文件生成。新付费售价=官方成本/0.30；旧余额及赠点不承诺70%毛利。所有凭据仅留在服务器受控环境，不进入Git。

已正式发布至 www.realecho.cn / api.realecho.cn，凭据见 published.json。

最终证据：tests/final-java.json（211项）、formal-domain-smoke.json（8项真实调用）、published-financial-audit.json（26笔独立账本重算）。前端7项检查、Python753项及58步全量回归通过。

实机体验、真实支付宝支付和自然小时存储观察尚未验收；画像保持关闭。发布中原生服务构建入口错误已修复并复测，恢复方法见实施记录。
