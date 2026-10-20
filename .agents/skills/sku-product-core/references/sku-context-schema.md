# SKU_CONTEXT V1

使用下面的 YAML 结构在公共核心、路由和平台 Skill 之间传递状态。保留未知字段为空，不得猜测填充。

```yaml
sku_context_version: 1

product_identity:
  category: null
  product_name: null
  source_images: []
  visible_structure: []
  primary_colors: []
  included_items: []
  packaging: null
  logo_status: null

facts:
  verified: []
  cautious_inferences: []
  prohibited_claims: []
  missing_evidence: []
  evidence_sources: []

production:
  handling_mode: null
  handling_reason: null
  allowed_edits: []
  prohibited_edits: []
  fidelity_requirements: []

visual_memory_points:
  - point: null
    product_evidence: null
    suitable_uses: []

target:
  platform: null
  marketplace_site: null
  language: null
  seller_type: null
  category: null
  asset_slots: []
  brand_status: null
  current_rule_source: null
  current_rule_checked_at: null

decisions:
  selected_direction: null
  confirmed_assumptions: []
  rejected_directions: []
  pending_decision: null
```

## 合并规则

1. 平台 Skill 继承 `facts` 和 `production`，不得无证据覆盖。
2. 新证据可以把谨慎推断升级为事实，但必须记录来源。
3. 用户切换平台时只替换 `target`，保留产品身份和事实。
4. 多平台任务从同一基础上下文派生多个 target 副本。
5. 任何默认值都写入 `confirmed_assumptions`，不能伪装成用户事实。

