## 外壳 · 首页 · 设备 · 登录

| 原页面 / 组件 | 新对应 | 后端接口 | 状态 |
|---|---|---|---|
| `HeaderBar.vue`（顶部导航、搜索、余额、用户菜单） | `layout/AppLayout.vue`：分组侧栏 + 顶栏（面包屑、添加设备、余额、账户菜单、语言、修改密码、退出） | `GET /user/info`、`GET /pay/quota/me` | 完成（mock）；首页搜索移到首页工具栏 |
| `VersionFooter.vue` | 侧栏底部版本信息 | `GET /user/pub-config` | 完成（mock） |
| `/home` 首页 `home.vue` + `DeviceItem.vue` | 智能体卡片 / 列表视图；搜索（名称 / 设备备注 / MAC）、绑定状态筛选；统计分开显示智能体数、已绑定设备数、在线设备（暂不可查） | `GET /agent/list`、`DELETE /agent/:id`、`GET /device/bind/:agentId`、`GET /models/names`、`GET /admin/dict/data/type/FIRMWARE_TYPE` | 完成（mock）；在线状态待后端 |
| 首页余额卡片 | 移除；余额改到顶栏右侧，点击进入充值 / 账单 | `GET /pay/quota/me` | 完成（mock） |
| 首页“绑定新设备”卡片、`AddDeviceDialog.vue`、`ManualAddDeviceDialog.vue` | 顶栏“添加设备” → `DeviceBindDialog.vue`（验证码绑定 / 恢复连接 / 手动添加三个标签页）；首页卡片与设备管理页也能打开同一弹窗 | `POST /device/bind/:agentId/:code`、`POST /device/manual-add`、`GET /agent/list`、`GET /admin/dict/data/type/FIRMWARE_TYPE` | 完成（mock）；原两个组件已删除 |
| 新建智能体（`AwakeningWizard`） | 首页标题区“添加智能体”；没有智能体时自动打开 | `POST /agent`、`GET`/`PUT /agent/:agentId`、`GET /models/names`、`GET /models/:modelId/voices`（与原组件相同） | 完成（mock） |
| `/device-management` `DeviceManagement.vue` | 表格（多选、行内备注、资源、解绑二次确认、分页）；智能体切换同步 `?agentId` | `GET /device/bind/:agentId`、`POST /device/unbind`、`PUT /device/update/:id`、`/device/assets/*` | 完成（mock）；资源字段形状待确认 |
| `/login` `login.vue` | `AuthLayout` 单卡片；账号 / 手机号登录 | `GET /user/captcha`、`GET /user/pub-config`、`POST /user/login`、`POST /user/smsVerification` | 完成（mock） |
| `/register` `register.vue` | `AuthLayout` 单卡片 | `POST /user/register`、`POST /user/smsVerification` | 完成（mock） |
| `/retrieve-password` `retrievePassword.vue` | `AuthLayout` 单卡片 | `PUT /user/retrieve-password`、`POST /user/smsVerification` | 完成（mock） |
| `ChangePasswordDialog.vue` | 账户菜单 → 修改密码（表单弹窗） | `PUT /user/change-password` | 完成（mock） |
| 无 | `layout/NoPermission.vue`：普通用户访问管理员路由时显示 | 无 | 新增状态页（不是新功能） |
| 无 | `layout/MockPanel.vue`：演示模式（切换演示身份、数据场景、余额状态、重置演示数据） | 无（只在 mock 构建中存在） | 演示工具，非授权机制 |
| `/`（welcome） | 保持原跳转逻辑 | 无 | 未改 |
