# 版本与证据映射

181轮业务证据按原执行记录复用，不能当成同一最终版本全量重跑。

- final04：10轮，完整源哈希见evidence/final04-freeze.json。
- final06：23轮，完整源哈希见evidence/final06-freeze.json。
- final07：26轮，完整源哈希见evidence/final07-freeze.json。
- final08：30轮，完整源哈希见evidence/final08-freeze.json。
- final09：92轮，完整源哈希见evidence/final09-freeze.json。

部署冻结见evidence/final-source-freeze.json。final09之后仅runtime.py与reply_composer.py两处回复保护变更，18个受影响位置单独补验；其他业务证据未重新标记为新执行。

quality01–07记录的是逐步修复中的上下文／可信结果回放；没有各批完整独立源码冻结包。最终部署源码已冻结，后续保护不影响所复用的通过回复；补验方法和源日志逐项保留。

6段保留集不再宣称未见：原样保留失败，没有换样本冲抵。