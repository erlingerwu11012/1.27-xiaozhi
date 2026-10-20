# 改版开发约定（设计规范 · 页面骨架 · Mock 层 · 文案）

本文件是 manager-web 改版的工作约定，给后续维护者和联调同学看。原有路由、业务逻辑、API 契约与权限边界保持不变；改动集中在“外观”和“演示数据层”。

## 1. 设计规范

规范的唯一来源是 `src/styles/tokens.scss`（SCSS 变量）与 `src/styles/global.scss`（CSS 变量 `--xn-*`、页面骨架类、Element 细化）。Element UI 主题由 `src/styles/element-variables.scss` 从 theme-chalk 源码编译。

| 角色 | 值 | 用途 |
|---|---|---|
| 雾白 `--xn-mist` | `#EEF2F5` | 页面底色 |
| 纯白 | `#FFFFFF` | 面板、卡片、弹窗 |
| 深墨蓝 `--xn-ink` | `#1E2B40` | 正文、标题、**主按钮** |
| 次级文字 `--xn-ink-2 / -3` | `#44546A / #66748A` | 表单标签 / 辅助说明 |
| 湖蓝 `--xn-lake` | `#2F6F95`（底 `#E4EEF4`） | 链接、选中、“已绑定”、焦点环、Element 的 primary 强调 |
| 线 `--xn-line / -2` | `#DCE3EA / #E8EDF2` | 面板描边 / 内部分隔 |
| 成功 / 警告 / 危险 | `#2F7A55` / `#9A6212` / `#A3402C`（各有 `-soft` 底色） | 状态标签、危险操作 |
| 演示标记 `--xn-demo` | `#874C1B` on `#FBEEDF` | **只**用于“演示数据”标记，不用于业务状态 |

- 字体：界面用系统无衬线（PingFang SC / 微软雅黑 / Noto Sans SC）；**页面标题和智能体名称**用 `var(--xn-serif)`（Noto Serif SC 常用字子集，`src/assets/fonts`）。其他地方不用衬线。
- 字号：正文 14px；辅助 13px；标签 12px（最小）；区块标题 16px；页面标题 24px。不要为了“精致”缩小正文。
- 圆角：标签 6 · 控件 8 · 面板 / 卡片 12 · 弹窗 / 抽屉 16。
- 阴影：面板与卡片**不加阴影**，用 1px `--xn-line` 描边；阴影只给浮层（下拉、弹窗、提示）。
- 禁止：渐变背景、发光、彩虹描边、毛玻璃大光斑、旋转动画、全大写英文标签、“A · B · C”式中点拼接、按钮文字后面加“→”。
- 图标：`<xn-icon name="..." />`（24 网格、1.7 描边）。不要再引入 PNG 图标或 `el-icon-*` 作为主要导航图标；Element 组件内部自带的图标可以保留。

## 2. 页面骨架

外壳（侧栏 + 顶栏 + 演示模式入口）由 `App.vue` → `components/layout/AppLayout.vue` 统一提供。**页面里不要再放 `<HeaderBar />` 或 `<version-footer />`**，也不要设置整页背景。

```vue
<template>
  <div class="xn-page">
    <page-header :title="$t('...')" :description="$t('...')">
      <!-- 右侧操作：主操作用 type="primary"（深墨蓝），每页最多一个 -->
      <el-button type="primary" @click="..."><xn-icon name="plus" /> 新建</el-button>
    </page-header>

    <div class="xn-toolbar">           <!-- 搜索 / 筛选 / 批量操作 -->
      <el-input v-model="kw" clearable placeholder="..." />
      <span class="xn-toolbar__grow"></span>
      <el-button>次要操作</el-button>
    </div>

    <div class="xn-panel xn-panel--flush">   <!-- 表格放在无内边距的面板里 -->
      <el-table :data="rows" v-loading="loading">...</el-table>
      <el-pagination background layout="total, sizes, prev, pager, next" ... />
    </div>
  </div>
</template>
```

- 密集信息用表格（`el-table`），不要把所有东西都做成一排排相同的卡片。卡片只用于确实需要“一项一块”的内容（智能体、角色包、壁纸包、音色）。
- 面板：`.xn-panel`（可选 `.xn-panel__head` / `.xn-panel__title` / `.xn-panel__body`）。
- 空状态与失败状态：`<xn-empty>`（`error` 属性显示失败样式并触发 `retry` 事件）。说明发生了什么、下一步做什么。
- 状态标签：`.xn-tag` + `--lake / --success / --warning / --danger / --muted`；演示数据用 `<demo-tag />`。
- 子页面返回：`<page-header :back="'/上级路由'">`。
- 删除 / 解绑等危险操作必须二次确认（`this.$confirm`，文案含“删除”时 main.js 会自动套用危险样式）。
- 窄窗口（≤960px）侧栏自动收起；页面不得出现横向滚动条（表格自身滚动可以）。

## 3. Mock 数据层（`src/mock`）

- 开关：`VUE_APP_DATA_MODE`，**默认 mock**；只有写成 `real` 才访问真实接口。判断都用构建期常量，real 构建不会打包 `src/mock`。
- 接入点：`src/apis/httpRequest.js` 的 `send()`。mock 模式下用 `mockRequest(url, data, options)` 代替 `fly.request`，返回结构与 flyio 相同（`{ status: 200, data }`），所以各 API 模块、回调、`code: 401` 跳登录等原逻辑都不变。**不要修改 `src/apis/module/*` 的 URL、方法、字段与回调。**
- 注册接口：`handlers/<模块>.js` 里 `route('GET', '/agent/:agentId', (req) => ok(data))`。`req` 含 `params / query / body / headers / user / db / scenario`。命中多条时取字面段最多的一条，与注册顺序无关。
- 响应：`ok(data, msg)` → `{ code: 0, msg, data }`；`fail(msg, code)` → 业务错误；`raw(body)` → 原样；`blob(Blob)` → 二进制；`networkError()` → 走 networkFail；管理员接口先 `requireAdmin(user)`。
- 数据：`seed/<模块>.js` 用 `seed(() => ({ ... }))` 提供初始数据；运行时数据在 `getDb()`，非 GET 请求后自动保存到 `localStorage['xn-mock-db-v1']`，演示模式面板可“重置演示数据”。
- 标注：用户自己的数据（名称、备注、订单、文件名……）带“（演示）”；MAC 用 `02:` 开头的本地地址段。
- 不得：发出任何网络请求；保存密码、密钥、真实账号信息；伪造“已支付 / 已下发 / 已上传”等不可逆结果而不标注“演示”。支付、上传、设备指令只更新本地演示数据，并在返回的 `msg` 或页面提示里写明是演示结果。
- 响应结构必须按**所有调用方**实际读取的字段来写（先 `grep -rn "Api.<模块>.<方法>"`，逐个看回调里用了 `res.data.data.xxx` 还是 `res.data.xxx`）。拿不准的接口行为写进集成文档的“待确认”，不要编造。
- 媒体与下载：用 `src/utils/media.js` 的 `playableUrl(url)`、`openDownload(url, filename, text)`、`imageUrl(url, label)`，它们在 real 模式下保持原行为。
- 演示场景：`scenario.data`（normal / empty / error）与 `scenario.balance`（realtime / stale / unavailable）。列表类接口在 `empty` 场景返回空列表即可；`error` 场景由适配器统一处理。

## 4. 文案（i18n）

- 新文案放在 `src/i18n/redesign/groups/<分组>.js`，导出 `{ zh_CN: {...}, en: {...} }`，key 一律以 `xn.` 开头（避开 OTA 文案检查的命名空间）。
- 可以覆盖原有 key 的取值（例如去掉界面上的 one-api / 缓存 / 接口等实现细节），key 不变。
- 写法：用户视角、主动语态、简短；按钮写清动作（“保存配置”，不是“提交”）；同一动作全流程同名；错误说明原因与解决办法，不道歉；空状态给出下一步。

## 5. 权限

- 管理员入口只在 `isSuperAdmin` 为 true 时出现（侧栏“管理员”分组）。
- 路由 `meta.adminOnly` 的页面，非管理员访问时外壳显示“没有访问权限”。这只是界面层拦截，真实权限以后端为准；原有 `HabitManagement / MemoryManagement / MemoryExtractConfig` 的跳转守卫保留。
- 演示模式里的“切换演示身份”只存在于 mock 构建，用于预览两种身份的界面，不是授权机制。
