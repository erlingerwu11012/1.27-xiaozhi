/* 小念控制台 · 界面原型逻辑
 * 纯前端演示：不发请求、不读写服务器、不使用登录凭据。所有“保存/绑定/删除”只改动本页内存中的演示数据，
 * 并以提示说明“未提交到服务器”。路由名称与原 Vue 项目 router/index.js 保持一致，便于后续落到 Vue 2。 */
(function () {
  'use strict';

  /* ---------- 图标（线性，1.6–1.8 描边） ---------- */
  const I = {
    agents: '<svg viewBox="0 0 24 24"><circle cx="12" cy="9" r="4"/><path d="M4 20c1.5-3.5 4.5-5 8-5s6.5 1.5 8 5"/></svg>',
    device: '<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="13" rx="2.5"/><path d="M8 20h8M12 16v4"/><circle cx="12" cy="6" r=".6"/></svg>',
    people: '<svg viewBox="0 0 24 24"><circle cx="9" cy="9" r="3.2"/><path d="M3.5 19c1-3 3-4.5 5.5-4.5S13.5 16 14.5 19"/><path d="M15.5 6.2a3 3 0 0 1 0 5.6M17 14.6c1.8.6 3 2 3.5 4.4"/></svg>',
    role: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="12" cy="10.5" r="3"/><path d="M7.5 17.5c1-2 2.6-3 4.5-3s3.5 1 4.5 3"/></svg>',
    wallpaper: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M3.5 15l4.5-4 4 3.5 3-2.5 5.5 4.5"/><circle cx="15.5" cy="9" r="1.4"/></svg>',
    voice: '<svg viewBox="0 0 24 24"><path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 11v2"/></svg>',
    book: '<svg viewBox="0 0 24 24"><path d="M5 4.5h9.5a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h9.5"/></svg>',
    wallet: '<svg viewBox="0 0 24 24"><rect x="3.5" y="6" width="17" height="13" rx="2.5"/><path d="M3.5 10h17M16 14.5h1.5"/></svg>',
    receipt: '<svg viewBox="0 0 24 24"><path d="M6 3.5h12v17l-3-2-3 2-3-2-3 2z"/><path d="M9 8.5h6M9 12h6"/></svg>',
    model: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9z"/></svg>',
    users: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/></svg>',
    memory: '<svg viewBox="0 0 24 24"><path d="M12 4a6 6 0 0 0-6 6c0 2.4 1.3 3.8 2.5 4.8V18h7v-3.2c1.2-1 2.5-2.4 2.5-4.8a6 6 0 0 0-6-6z"/><path d="M10 21h4"/></svg>',
    gear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4L18 18M6 18l1.6-1.6M16.4 7.6L18 6"/></svg>',
    tts: '<svg viewBox="0 0 24 24"><rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/></svg>',
    chev: '<svg class="chev" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>',
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/></svg>',
    grid: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/></svg>',
    rows: '<svg viewBox="0 0 24 24"><path d="M4 6.5h16M4 12h16M4 17.5h16"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    trash: '<svg viewBox="0 0 24 24"><path d="M5 7h14M10 7V4.8h4V7M7 7l.8 12.2h8.4L17 7"/></svg>',
    close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    menu: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.2"/></svg>',
    link: '<svg viewBox="0 0 24 24"><path d="M10 14l4-4M8.5 16.5l-1 1a3.5 3.5 0 0 1-5-5l3-3a3.5 3.5 0 0 1 5 0M15.5 7.5l1-1a3.5 3.5 0 0 1 5 5l-3 3a3.5 3.5 0 0 1-5 0"/></svg>',
  };

  /* ---------- 页面与导航（与原路由一一对应） ---------- */
  const PAGES = {
    home: { title: '我的智能体', group: '我的小念', route: '/home' },
    devices: { title: '设备管理', group: '我的小念', route: '/device-management',
      desc: '查看每台设备绑定到哪个智能体，管理备注、解绑与设备视觉资源。' },
    people: { title: '人员身份', group: '我的小念', route: '/unified-user-management',
      desc: '统一管理识别对象：人脸与声纹归属到同一个人员身份，按智能体分别配置。',
      keep: ['人脸录入与声纹录入归属到同一人员', '旧路由 /face-management、/voice-print 继续重定向到这里', '按 agentId 进入'] },
    rolePack: { title: '视觉角色', group: '屏幕与声音', route: '/role-pack-catalog',
      desc: '选择官方 Spine 视觉角色并下载到您绑定的设备（非 LLM 人设配置）。智能体提示词与音色请前往“配置角色”。',
      keep: ['角色包列表、版本与描述', '选择设备并确认下发（创建 OTA 任务）', '下发状态与失败提示'] },
    wallpaper: { title: '壁纸包', group: '屏幕与声音', route: '/wallpaper-pack-catalog',
      desc: '选择官方壁纸包并下载到您绑定的设备（独立单槽壁纸 OTA）。设备自定义图片仍走“设备资源”，与此无关。',
      keep: ['壁纸包列表与版本', '选择设备并确认下发', '与 Spine 角色 OTA 相互独立'] },
    tts: { title: '官方语音', group: '屏幕与声音', route: '/official-tts/voices',
      desc: '我的音色与配音工作台：试听、合成与下载。',
      keep: ['我的音色 /official-tts/voices', '配音工作台 /official-tts/dubbing', '音色权限、试听、合成、下载、等待与失败状态'] },
    knowledge: { title: '知识库', group: '资料', route: '/knowledge-base-management',
      desc: '为智能体整理可检索的资料。',
      keep: ['知识库列表与编辑', '文档上传管理 /knowledge-file-upload'] },
    billing: { title: '充值套餐', group: '账户', route: '/billing/packages',
      desc: '选择套餐并使用支付宝完成支付。充值购买的是可用额度（点），不是月租订阅。',
      keep: ['当前可用余额（one-api 实时 / 缓存 / 暂无记录三种来源）', '创建订单与支付结果 /billing/result', '用量趋势'] },
    orders: { title: '账单记录', group: '账户', route: '/billing/orders',
      desc: '充值订单、调用费用与记忆账单。',
      keep: ['订单列表与状态', '硬件调用账单', '记忆账单'] },
    // 管理员
    modelConfig: { title: '模型配置', group: '管理员', route: '/model-config', admin: true, desc: '配置可供智能体选择的 ASR、LLM、TTS 等模型。' },
    userAdmin: { title: '用户管理', group: '管理员', route: '/user-management', admin: true, desc: '全站账号管理，仅管理员可见。与智能体内的“人员身份”不同。' },
    ttsAdmin: { title: '官方TTS管理', group: '管理员', route: '/admin/official-tts', admin: true, desc: '维护官方音色与权限。' },
    memory: { title: '记忆管理', group: '管理员 · 记忆与习惯', route: '/memory-management', admin: true,
      desc: '后台记忆条目核查（独立 Python API）。普通用户没有此入口，本原型也不提供个人记忆查看或导出。' },
    memoryExtract: { title: '记忆提取配置', group: '管理员 · 记忆与习惯', route: '/memory-extract-config', admin: true, desc: '后台记忆提取策略。' },
    habit: { title: '习惯管理', group: '管理员 · 记忆与习惯', route: '/habit-management', admin: true, desc: '后台习惯资料，仅供管理员核查。' },
    habitAnalyze: { title: '习惯分析配置', group: '管理员 · 记忆与习惯', route: '/habit-analyze-config', admin: true, desc: '习惯分析参数。' },
    params: { title: '参数管理', group: '管理员 · 系统参数', route: '/params-management', admin: true, desc: '系统参数。' },
    dict: { title: '字典管理', group: '管理员 · 系统参数', route: '/dict-management', admin: true, desc: '字典类型与字典数据。' },
    provider: { title: '字段管理', group: '管理员 · 系统参数', route: '/provider-management', admin: true, desc: '模型供应器字段。' },
    agentTemplate: { title: '默认角色模板', group: '管理员 · 系统参数', route: '/agent-template-management', admin: true, desc: '新建智能体时使用的默认人设模板。' },
    serverSide: { title: '服务端管理', group: '管理员 · 系统参数', route: '/server-side-management', admin: true, desc: '服务端节点与配置。' },
  };
  const NAV = [
    { head: '我的小念', items: [['home', 'agents'], ['devices', 'device'], ['people', 'people']] },
    { head: '屏幕与声音', items: [['rolePack', 'role'], ['wallpaper', 'wallpaper'], ['tts', 'voice']] },
    { head: '资料', items: [['knowledge', 'book']] },
    { head: '账户', items: [['billing', 'wallet'], ['orders', 'receipt']] },
    { head: '管理员', admin: true, items: [['modelConfig', 'model'], ['userAdmin', 'users'], ['ttsAdmin', 'tts']],
      subs: [
        { key: 'mem', label: '记忆与习惯', icon: 'memory', items: ['memory', 'memoryExtract', 'habit', 'habitAnalyze'] },
        { key: 'sys', label: '系统参数', icon: 'gear', items: ['params', 'dict', 'provider', 'agentTemplate', 'serverSide'] },
      ] },
  ];

  /* ---------- 状态 ---------- */
  const S = {
    role: 'user', page: 'home', view: 'card', filter: 'all', query: '',
    deviceAgent: 'all', deviceQuery: '',
    subsOpen: { mem: false, sys: false },
    agents: JSON.parse(JSON.stringify(window.DEMO.agents), (k, v) => (k === 'lastConnectedAt' || k === 'lastConversation') && v ? new Date(v) : v),
    peopleAgent: null,
  };
  let lastFocus = null;
  let seq = 100;

  /* ---------- 工具 ---------- */
  const $ = (s, r = document) => r.querySelector(s);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad = (n) => String(n).padStart(2, '0');
  const fmtDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  // 与 DeviceItem.vue formattedLastConnectedTime 相同的分段规则
  function rel(d) {
    if (!d) return '暂未对话';
    const m = Math.floor((Date.now() - d.getTime()) / 60000);
    if (m <= 1) return '刚刚';
    if (m < 60) return `${m}分钟前`;
    if (m < 1440) return `${Math.floor(m / 60)}小时${m % 60}分钟前`;
    return fmtDate(d);
  }
  const memLabel = (id) => (window.DEMO.memoryModes.find((x) => x.value === id) || {}).label || id;
  const findAgent = (id) => S.agents.find((a) => a.id === id);
  const allDevices = () => S.agents.flatMap((a) => a.devices.map((d) => ({ ...d, agentId: a.id, agentName: a.agentName })));
  function hi(text, q) {
    const t = esc(text);
    if (!q) return t;
    const i = String(text).toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return t;
    return esc(String(text).slice(0, i)) + '<mark>' + esc(String(text).slice(i, i + q.length)) + '</mark>' + esc(String(text).slice(i + q.length));
  }
  function avatar(a, cls = 'avatar') {
    return a.avatar ? `<span class="${cls}"><img src="${esc(a.avatar)}" alt=""></span>` : `<span class="${cls}" aria-hidden="true">${esc(a.agentName.slice(0, 1))}</span>`;
  }
  function bindTag(n) {
    return n > 0 ? `<span class="bind bind--yes"><i></i>已绑定 <span class="num">${n}</span> 台设备</span>` : '<span class="bind bind--no"><i></i>未绑定设备</span>';
  }
  function toast(msg) {
    const el = document.createElement('div');
    el.className = 'toast'; el.innerHTML = `<i></i><span>${esc(msg)}</span>`;
    const box = $('#toasts'); box.appendChild(el);
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => el.remove(), 3600);
  }
  const DEMO_NOTE = '（演示：仅更新本页数据，未提交到服务器）';

  /* ---------- 导航 ---------- */
  function renderNav() {
    const isAdmin = S.role === 'admin';
    const item = (key, icon, extra = '') => `<button type="button" class="nav__item${S.page === key ? ' is-on' : ''}" data-go="${key}"${S.page === key ? ' aria-current="page"' : ''}>${I[icon]}<span>${esc(PAGES[key].title)}</span>${extra}</button>`;
    $('#nav').innerHTML = NAV.filter((g) => !g.admin || isAdmin).map((g) => {
      let html = `<div class="nav__group${g.admin ? ' nav__group--admin' : ''}"><div class="nav__head">${esc(g.head)}</div>`;
      html += g.items.map(([k, ic]) => item(k, ic, k === 'devices' ? `<span class="badge num">${allDevices().length}</span>` : '')).join('');
      (g.subs || []).forEach((sub) => {
        const open = S.subsOpen[sub.key] || sub.items.includes(S.page);
        html += `<button type="button" class="nav__item nav__toggle" data-sub="${sub.key}" aria-expanded="${open}">${I[sub.icon]}<span>${esc(sub.label)}</span>${I.chev}</button>`;
        if (open) html += `<div class="nav__sub">${sub.items.map((k) => `<button type="button" class="nav__item${S.page === k ? ' is-on' : ''}" data-go="${k}">${esc(PAGES[k].title)}</button>`).join('')}</div>`;
      });
      return html + '</div>';
    }).join('');
  }

  /* ---------- 首页：智能体 ---------- */
  function matchAgent(a, q) {
    if (!q) return { ok: true, dev: [] };
    const ql = q.toLowerCase();
    const dev = a.devices.filter((d) => [d.macAddress, d.model, d.remark].some((v) => String(v || '').toLowerCase().includes(ql))).map((d) => d.id);
    return { ok: a.agentName.toLowerCase().includes(ql) || dev.length > 0, dev };
  }
  function visibleAgents() {
    return S.agents.filter((a) => (S.filter === 'all' || (S.filter === 'bound' ? a.devices.length > 0 : a.devices.length === 0)) && matchAgent(a, S.query).ok);
  }
  function chatBtn(a, sm) {
    return a.memModelId === 'Memory_nomem'
      ? `<button type="button" class="btn btn--text" aria-disabled="true" data-action="chat" data-id="${a.id}" title="请先在“配置角色”界面开启记忆">聊天记录</button>`
      : `<button type="button" class="btn btn--text" data-action="chat" data-id="${a.id}">聊天记录</button>`;
  }
  function agentCard(a) {
    const m = matchAgent(a, S.query);
    const dev = a.devices.length
      ? `<div class="devstrip">${a.devices.slice(0, 3).map((d) => `<div class="devstrip__row${m.dev.includes(d.id) ? ' is-match' : ''}">
          <span class="devstrip__id"><b>${hi(d.remark || d.model, S.query)}</b>${hi(d.macAddress, S.query)}</span>
          <span class="devstrip__time">${esc(rel(d.lastConversation))}</span></div>`).join('')}
          ${a.devices.length > 3 ? `<button type="button" class="btn btn--text" data-action="agentDevices" data-id="${a.id}">查看全部 ${a.devices.length} 台</button>` : ''}</div>`
      : `<div class="devstrip"><div class="devstrip--empty"><span>还没有绑定设备</span><button type="button" class="btn btn--text" data-action="addDevice" data-id="${a.id}">绑定设备</button></div></div>`;
    return `<article class="agent" aria-label="${esc(a.agentName)}">
      <div class="agent__body">
        <div class="agent__head">${avatar(a)}
          <div><h3 class="agent__name">${hi(a.agentName, S.query)}</h3>
            <div class="agent__meta">${bindTag(a.devices.length)}<span class="agent__last">最近对话 ${esc(rel(a.lastConnectedAt))}</span></div></div>
          <button type="button" class="icon-btn" data-action="deleteAgent" data-id="${a.id}" aria-label="删除智能体 ${esc(a.agentName)}" title="删除智能体">${I.trash}</button>
        </div>
        <p class="agent__prompt">${esc(a.systemPrompt)}</p>
        <dl class="params">
          <dt>语言模型</dt><dd title="${esc(a.llmModelName)}">${esc(a.llmModelName)}</dd>
          <dt>音色</dt><dd title="${esc(a.ttsModelName)}（${esc(a.ttsVoiceName)}）">${esc(a.ttsVoiceName)}<span style="color:var(--ink-3)"> · ${esc(a.ttsModelName)}</span></dd>
          <dt>记忆</dt><dd>${esc(memLabel(a.memModelId))}</dd>
        </dl>
        ${dev}
      </div>
      <div class="agent__foot">
        <button type="button" class="btn btn--primary btn--sm" data-action="config" data-id="${a.id}">配置角色</button>
        <button type="button" class="btn btn--text" data-action="agentDevices" data-id="${a.id}">设备 <span class="num">${a.devices.length}</span></button>
        <button type="button" class="btn btn--text" data-action="people" data-id="${a.id}">人员身份</button>
        ${chatBtn(a)}
      </div>
    </article>`;
  }
  function agentTable(list) {
    return `<div class="table-wrap"><table class="list"><thead><tr>
      <th>智能体</th><th>语言模型</th><th>音色</th><th>绑定设备</th><th>最近对话</th><th style="text-align:right">操作</th></tr></thead><tbody>
      ${list.map((a) => `<tr>
        <td><div class="who">${avatar(a)}<div><b>${hi(a.agentName, S.query)}</b><div class="sub">${esc(memLabel(a.memModelId))}</div></div></div></td>
        <td class="clip" title="${esc(a.llmModelName)}">${esc(a.llmModelName)}</td>
        <td class="clip">${esc(a.ttsVoiceName)}<div class="sub">${esc(a.ttsModelName)}</div></td>
        <td>${bindTag(a.devices.length)}</td>
        <td class="num">${esc(rel(a.lastConnectedAt))}</td>
        <td><div class="acts">
          <button type="button" class="btn btn--primary btn--sm" data-action="config" data-id="${a.id}">配置角色</button>
          <button type="button" class="btn btn--text" data-action="agentDevices" data-id="${a.id}">设备</button>
          <button type="button" class="btn btn--text" data-action="people" data-id="${a.id}">人员身份</button>
          ${chatBtn(a)}
          <button type="button" class="icon-btn" data-action="deleteAgent" data-id="${a.id}" aria-label="删除智能体 ${esc(a.agentName)}" title="删除智能体">${I.trash}</button>
        </div></td></tr>`).join('')}
      </tbody></table></div>`;
  }
  function renderHome() {
    const total = S.agents.length;
    const bound = S.agents.filter((a) => a.devices.length).length;
    const devCount = allDevices().length;
    const list = visibleAgents();
    const seg = (k, label, n) => `<button type="button" class="seg${S.filter === k ? ' is-on' : ''}" data-filter="${k}" aria-pressed="${S.filter === k}">${label}<span class="cnt num">${n}</span></button>`;
    const body = list.length ? (S.view === 'card' ? `<div class="agents">${list.map(agentCard).join('')}</div>` : agentTable(list))
      : total === 0
        ? '<div class="empty"><h3>还没有智能体</h3><p>先创建一个智能体，再把设备绑定到它。</p><button type="button" class="btn btn--primary" data-action="addAgent">添加智能体</button></div>'
        : `<div class="empty"><h3>没有符合条件的智能体</h3><p>${S.query ? `没有找到包含“${esc(S.query)}”的智能体或设备。` : '当前筛选下没有智能体。'}</p><button type="button" class="btn" data-action="resetFilter">清除搜索与筛选</button></div>`;
    $('#content').innerHTML = `
      <div class="page-head">
        <div><h1 class="page-title">我的智能体</h1>
          <div class="page-sub"><span class="num">${total}</span> 个智能体 · <span class="num">${devCount}</span> 台设备已绑定
            <span class="hint" tabindex="0" data-tip="“已绑定”表示设备已关联到该智能体，不代表设备当前在线。">?</span></div></div>
        <div class="page-head__actions">
          <button type="button" class="btn" data-action="addDevice">${I.device}添加设备</button>
          <button type="button" class="btn btn--primary" data-action="addAgent">${I.plus}添加智能体</button>
        </div>
      </div>
      <div class="home${S.view === 'list' ? ' is-list' : ''}">
        <section aria-label="智能体列表">
          <div class="toolbar">
            <label class="search">${I.search}<input id="q" type="search" placeholder="搜索智能体名称、设备 MAC 或备注" value="${esc(S.query)}" aria-label="搜索智能体或设备">
              ${S.query ? '<button type="button" class="clear" data-action="clearQuery" aria-label="清除搜索">×</button>' : ''}</label>
            <div class="segs" role="group" aria-label="按绑定状态筛选">${seg('all', '全部', total)}${seg('bound', '已绑定设备', bound)}${seg('unbound', '未绑定', total - bound)}</div>
            <span class="spacer"></span>
            <div class="segs view-toggle" role="group" aria-label="切换视图">
              <button type="button" class="seg${S.view === 'card' ? ' is-on' : ''}" data-view="card" aria-pressed="${S.view === 'card'}" aria-label="卡片视图" title="卡片视图">${I.grid}</button>
              <button type="button" class="seg${S.view === 'list' ? ' is-on' : ''}" data-view="list" aria-pressed="${S.view === 'list'}" aria-label="列表视图" title="列表视图">${I.rows}</button>
            </div>
          </div>
          ${body}
        </section>
        ${renderRail()}
      </div>`;
  }
  function renderRail() {
    const b = window.DEMO.balance;
    const src = { oneapi: '实时余额（one-api）', cache: '缓存余额', none: '暂无余额记录' }[b.source];
    const sc = (k, ic, t, d) => `<li><button type="button" data-go="${k}">${I[ic]}<b>${t}</b><small>${d}</small></button></li>`;
    return `<aside class="rail" aria-label="账户与常用操作">
      <div class="panel">
        <div class="panel__row"><h2 style="margin:0">当前可用余额</h2><span class="tag-demo">演示数据</span></div>
        <div class="balance" style="margin-top:10px"><b>${b.points.toLocaleString('zh-CN')}</b><span>点</span></div>
        <p class="panel__note">来源：${src}。正式版读取账户额度接口；one-api 暂不可用时显示最近一次同步的缓存余额。</p>
        <div class="panel__btns"><button type="button" class="btn btn--sm" data-go="billing">充值</button><button type="button" class="btn btn--text" data-go="orders">账单记录</button></div>
      </div>
      <div class="panel">
        <h2>绑定新设备</h2>
        <p class="panel__note" style="margin-top:0">让设备播报 6 位验证码，再在这里输入完成绑定。</p>
        <div class="panel__btns"><button type="button" class="btn btn--sm" data-action="addDevice">输入验证码</button><button type="button" class="btn btn--text" data-action="recover">恢复设备连接</button></div>
      </div>
      <div class="panel">
        <h2>常用</h2>
        <ul class="shortcuts">
          ${sc('rolePack', 'role', '视觉角色', '屏幕上的 Spine 形象，与人设分开')}
          ${sc('wallpaper', 'wallpaper', '壁纸包', '下发官方壁纸到设备')}
          ${sc('tts', 'voice', '官方语音', '我的音色与配音工作台')}
          ${sc('knowledge', 'book', '知识库', '给智能体整理资料')}
        </ul>
      </div>
    </aside>`;
  }

  /* ---------- 设备管理 ---------- */
  function renderDevices() {
    const q = S.deviceQuery.toLowerCase();
    const list = allDevices().filter((d) => (S.deviceAgent === 'all' || d.agentId === S.deviceAgent) &&
      (!q || [d.model, d.macAddress, d.remark].some((v) => String(v || '').toLowerCase().includes(q))));
    $('#content').innerHTML = `
      <div class="page-head">
        <div><h1 class="page-title">设备管理</h1><div class="page-sub">设备与智能体的绑定关系 · 绑定不代表在线</div></div>
        <div class="page-head__actions">
          <button type="button" class="btn" data-action="manualAdd">手动添加</button>
          <button type="button" class="btn" data-action="recover">恢复设备连接</button>
          <button type="button" class="btn btn--primary" data-action="addDevice">${I.plus}6位验证码绑定</button>
        </div>
      </div>
      <div class="notice">${I.info}<span>设备列表接口提供型号、固件版本、MAC、绑定时间、最后对话和备注，没有实时在线状态；本页不显示“在线/离线”。</span></div>
      <div class="toolbar">
        <label class="search">${I.search}<input id="dq" type="search" placeholder="请输入设备型号、Mac 地址或备注" value="${esc(S.deviceQuery)}" aria-label="搜索设备"></label>
        <select class="select" id="dagent" style="width:200px;height:36px" aria-label="按智能体筛选">
          <option value="all">全部智能体</option>${S.agents.map((a) => `<option value="${a.id}"${S.deviceAgent === a.id ? ' selected' : ''}>${esc(a.agentName)}</option>`).join('')}
        </select>
        <span class="spacer"></span><span class="page-sub" style="margin:0"><span class="num">${list.length}</span> 台</span>
      </div>
      ${list.length ? `<div class="table-wrap"><table class="list"><thead><tr><th>设备型号</th><th>所属智能体</th><th>固件版本</th><th>Mac 地址</th><th>绑定时间</th><th>最后对话</th><th>备注</th><th style="text-align:right">操作</th></tr></thead><tbody>
        ${list.map((d) => `<tr><td>${hi(d.model, S.deviceQuery)}</td><td>${esc(d.agentName)}</td><td class="num">${esc(d.firmwareVersion)}</td><td class="num">${hi(d.macAddress, S.deviceQuery)}</td>
          <td class="num">${esc(d.bindTime)}</td><td class="num">${esc(rel(d.lastConversation))}</td>
          <td><input class="remark-input" data-remark="${d.id}" data-agent="${d.agentId}" value="${esc(d.remark)}" maxlength="64" placeholder="添加备注" aria-label="备注"></td>
          <td><div class="acts"><button type="button" class="btn btn--text" data-action="assets" data-id="${d.id}">视觉资源</button>
            <button type="button" class="btn btn--text btn--danger" data-action="unbind" data-id="${d.id}" data-agent="${d.agentId}">解绑</button></div></td></tr>`).join('')}
        </tbody></table></div>`
        : `<div class="empty"><h3>${S.deviceQuery || S.deviceAgent !== 'all' ? '没有符合条件的设备' : '还没有绑定设备'}</h3><p>让设备播报 6 位验证码，再输入完成绑定。</p><button type="button" class="btn btn--primary" data-action="addDevice">6位验证码绑定</button></div>`}`;
  }

  /* ---------- 占位页 ---------- */
  function renderPlaceholder(key) {
    const p = PAGES[key];
    let extra = '';
    if (key === 'people') {
      const a = findAgent(S.peopleAgent) || S.agents[0];
      extra = `<div class="field" style="max-width:280px;margin-top:16px"><label for="pagent">智能体</label><select class="select" id="pagent">${S.agents.map((x) => `<option value="${x.id}"${a && x.id === a.id ? ' selected' : ''}>${esc(x.agentName)}</option>`).join('')}</select></div>`;
    }
    $('#content').innerHTML = `
      <div class="page-head"><div><h1 class="page-title">${esc(p.title)}</h1><div class="page-sub">${esc(p.group)}</div></div></div>
      <div class="placeholder">
        <h2>此页面在原型中仅保留入口</h2>
        <p>${esc(p.desc || '')}</p>
        ${p.keep ? `<ul>${p.keep.map((k) => `<li>${esc(k)}</li>`).join('')}</ul>` : ''}
        ${extra}
        <p style="margin-top:16px;color:var(--ink-3);font-size:13px">原型不连接后台，不显示任何真实数据。正式接入时沿用原页面与接口。</p>
        <span class="route">原路由 ${esc(p.route)}</span>
      </div>`;
  }

  /* ---------- 渲染入口 ---------- */
  function render() {
    if (PAGES[S.page].admin && S.role !== 'admin') S.page = 'home';  // 普通用户不能停留在管理员页
    renderNav();
    $('#crumb').innerHTML = `${esc(PAGES[S.page].group)} / <b>${esc(PAGES[S.page].title)}</b>`;
    if (S.page === 'home') renderHome();
    else if (S.page === 'devices') renderDevices();
    else renderPlaceholder(S.page);
    document.querySelectorAll('.role-switch .seg').forEach((b) => { const on = b.dataset.role === S.role; b.classList.toggle('is-on', on); b.setAttribute('aria-pressed', on); });
  }
  function go(page) { S.page = page; closeSide(); render(); window.scrollTo(0, 0); }

  /* ---------- 抽屉：配置角色 ---------- */
  function openConfig(id) {
    const a = findAgent(id); if (!a) return;
    const M = window.DEMO.modelOptions;
    const sel = (name, label, opts, val) => `<div class="field"><label for="f-${name}">${label}</label><select class="select" id="f-${name}" name="${name}">${opts.map((o) => `<option${o === val ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select></div>`;
    const dr = $('#drawer');
    dr.innerHTML = `
      <div class="drawer__head">${avatar(a)}<div><h2 id="drawerTitle">配置角色 · ${esc(a.agentName)}</h2><p>人设与模型设置（LLM 行为），与屏幕上的视觉角色无关</p></div>
        <button type="button" class="icon-btn" data-action="closeDrawer" aria-label="关闭">${I.close}</button></div>
      <form class="drawer__body" id="cfgForm" data-id="${a.id}" novalidate>
        <div class="section-title">基础</div>
        <div class="grid-2">
          <div class="field"><label for="f-name">助手昵称</label><input class="input" id="f-name" name="agentName" value="${esc(a.agentName)}" maxlength="24" required>
            <span class="err" id="e-name" hidden>请输入助手昵称</span></div>
          <div class="field"><label for="f-nick">它对我的称呼</label><input class="input" id="f-nick" name="userNickname" value="${esc(a.userNickname)}" maxlength="24"></div>
        </div>
        <div class="field"><span class="label">角色模版</span>
          <div class="presets" role="group" aria-label="角色模版">${window.DEMO.personaPresets.map((p) => `<button type="button" class="preset" data-preset="${p.id}" aria-pressed="${a.preset === p.id}"><b>${esc(p.name)}</b><small>${esc(p.description)}</small></button>`).join('')}</div>
          <span class="help">选择模版会填入角色介绍，可继续修改。</span></div>
        <div class="field"><label for="f-prompt">角色介绍</label><textarea class="textarea" id="f-prompt" name="systemPrompt" maxlength="2000">${esc(a.systemPrompt)}</textarea>
          <span class="count num" id="promptCount">${a.systemPrompt.length} / 2000</span></div>
        <div class="grid-2">
          <div class="field"><label for="f-lc">语言编码</label><input class="input" id="f-lc" name="languageCode" value="${esc(a.languageCode)}" placeholder="如：zh_CN"></div>
          <div class="field"><label for="f-lang">交互语种</label><input class="input" id="f-lang" name="language" value="${esc(a.language)}" placeholder="如：中文"></div>
        </div>
        <div class="section-title">模型</div>
        <div class="grid-2">
          ${sel('VAD', '语音活动检测(VAD)', M.VAD, M.VAD[0])}${sel('ASR', '语音识别(ASR)', M.ASR, M.ASR[0])}
          ${sel('LLM', '大语言模型(LLM)', M.LLM, a.llmModelName)}${sel('VLLM', '视觉模型(VLM)', M.VLLM, M.VLLM[0])}
          ${sel('Intent', '意图识别(Intent)', M.Intent, M.Intent[0])}
          <div class="field"><label for="f-mem">记忆模式</label><select class="select" id="f-mem" name="memModelId">${window.DEMO.memoryModes.map((m) => `<option value="${m.value}"${m.value === a.memModelId ? ' selected' : ''}>${esc(m.label)}</option>`).join('')}</select></div>
          ${sel('TTS', '语音合成(TTS)', M.TTS, a.ttsModelName)}${sel('Voice', '声音音色(Voice)', M.Voice, a.ttsVoiceName)}
        </div>
        <div class="field"><span class="label">聊天记录上报</span>
          <div class="radio-row"><label><input type="radio" name="chatReport" value="1"${a.chatReport === 1 ? ' checked' : ''}>上报文字</label>
            <label><input type="radio" name="chatReport" value="2"${a.chatReport === 2 ? ' checked' : ''}>上报文字+语音</label></div>
          <span class="help">关闭记忆（无记忆）时，首页的“聊天记录”不可用。</span></div>
        <p class="help" style="color:var(--ink-3);font-size:12px">下拉选项为演示占位，正式版来自模型列表接口。</p>
      </form>
      <div class="drawer__foot"><span class="note">保存配置后，需要重启设备，新的配置才会生效。</span>
        <button type="button" class="btn" data-action="resetConfig" data-id="${a.id}">重置</button>
        <button type="button" class="btn btn--primary" data-action="saveConfig" data-id="${a.id}">保存配置</button></div>`;
    openLayer(dr);
    $('#f-name').focus();
  }
  function saveConfig(id) {
    const a = findAgent(id), f = $('#cfgForm');
    const name = f.agentName.value.trim();
    $('#e-name').hidden = !!name; f.agentName.classList.toggle('is-err', !name);
    if (!name) { f.agentName.focus(); return; }
    Object.assign(a, {
      agentName: name, userNickname: f.userNickname.value.trim(), systemPrompt: f.systemPrompt.value.trim(),
      languageCode: f.languageCode.value.trim(), language: f.language.value.trim(), memModelId: f.memModelId.value,
      llmModelName: f.LLM.value, ttsModelName: f.TTS.value, ttsVoiceName: f.Voice.value,
      chatReport: Number(f.querySelector('input[name=chatReport]:checked').value),
      preset: (f.querySelector('.preset[aria-pressed=true]') || {}).dataset?.preset || a.preset,
    });
    closeLayers(); render();
    toast('配置已保存' + DEMO_NOTE);
  }

  /* ---------- 弹窗 ---------- */
  function modal(title, body, foot) {
    const m = $('#modal');
    m.innerHTML = `<div class="modal__head"><h2 id="modalTitle">${esc(title)}</h2><button type="button" class="icon-btn" data-action="closeModal" aria-label="关闭">${I.close}</button></div>
      <div class="modal__body">${body}</div><div class="modal__foot">${foot}</div>`;
    openLayer($('#modalWrap'));
    const first = m.querySelector('input, select, textarea, .modal__foot .btn--primary, .modal__foot .btn--danger-solid');
    (first || m.querySelector('.icon-btn')).focus();
  }
  function agentSelect(id, sel) {
    return `<select class="select" id="${id}">${S.agents.map((a) => `<option value="${a.id}"${a.id === sel ? ' selected' : ''}>${esc(a.agentName)}</option>`).join('')}</select>`;
  }
  function openAddDevice(agentId, tab = 'code') {
    if (!S.agents.length) { toast('请先添加智能体，再绑定设备'); return; }
    const aid = agentId || S.agents[0].id;
    const code = `<div class="field"><label for="m-agent">绑定到智能体</label>${agentSelect('m-agent', aid)}</div>
      <div class="field"><label for="m-code">验证码</label><input class="input num" id="m-code" inputmode="numeric" maxlength="6" placeholder="请输入设备播报的6位数验证码" autocomplete="off">
        <span class="err" id="m-err" hidden>请输入 6 位数字验证码</span><span class="help">设备开机联网后会语音播报验证码。</span></div>`;
    const manual = `<div class="field"><label for="m-agent">绑定到智能体</label>${agentSelect('m-agent', aid)}</div>
      <div class="field"><label for="m-board">设备类型</label><select class="select" id="m-board"><option value="">请选择设备类型</option><option>小念桌面版（示例）</option></select></div>
      <div class="field"><label for="m-fw">固件版本</label><input class="input" id="m-fw" placeholder="请输入固件版本"></div>
      <div class="field"><label for="m-mac">Mac 地址</label><input class="input num" id="m-mac" placeholder="如 A4:CF:12:3B:7E:01"><span class="err" id="m-err" hidden></span></div>`;
    modal('添加设备', `<div class="tabs" role="tablist"><button type="button" role="tab" class="tab${tab === 'code' ? ' is-on' : ''}" aria-selected="${tab === 'code'}" data-action="devTab" data-tab="code" data-agent="${aid}">6位验证码绑定</button>
      <button type="button" role="tab" class="tab${tab === 'manual' ? ' is-on' : ''}" aria-selected="${tab === 'manual'}" data-action="devTab" data-tab="manual" data-agent="${aid}">手动添加</button></div>${tab === 'code' ? code : manual}`,
      `<button type="button" class="btn" data-action="closeModal">取消</button><button type="button" class="btn btn--primary" data-action="${tab === 'code' ? 'confirmBind' : 'confirmManual'}">确定</button>`);
  }
  function addDemoDevice(agentId, extra) {
    const a = findAgent(agentId);
    const hex = () => Math.floor(Math.random() * 256).toString(16).toUpperCase().padStart(2, '0');
    a.devices.push(Object.assign({ id: 'demo-d' + (++seq), model: '小念桌面版（示例）', firmwareVersion: '—', macAddress: ['A4', 'CF', hex(), hex(), hex(), hex()].join(':'),
      bindTime: fmtDate(new Date()), lastConversation: null, remark: '' }, extra));
    return a;
  }
  function confirmBind() {
    const v = $('#m-code').value.trim();
    if (!/^\d{6}$/.test(v)) { $('#m-err').hidden = false; $('#m-code').classList.add('is-err'); $('#m-code').focus(); return; }
    const a = addDemoDevice($('#m-agent').value);
    closeLayers(); render(); toast(`设备已绑定到「${a.agentName}」${DEMO_NOTE}`);
  }
  function confirmManual() {
    const board = $('#m-board').value, fw = $('#m-fw').value.trim(), mac = $('#m-mac').value.trim(), err = $('#m-err');
    let msg = '';
    if (!board) msg = '请选择设备类型'; else if (!fw) msg = '请输入固件版本';
    else if (!mac) msg = '请输入 Mac 地址'; else if (!/^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$/.test(mac)) msg = 'Mac 地址格式不正确';
    if (msg) { err.textContent = msg; err.hidden = false; return; }
    const a = addDemoDevice($('#m-agent').value, { model: board, firmwareVersion: fw, macAddress: mac.toUpperCase().replace(/-/g, ':') });
    closeLayers(); render(); toast(`设备已添加到「${a.agentName}」${DEMO_NOTE}`);
  }
  function openRecover() {
    modal('恢复设备连接', `<div class="field"><label for="m-code">设备上显示的6位确认码</label><input class="input num" id="m-code" inputmode="numeric" maxlength="6" autocomplete="off">
      <span class="err" id="m-err" hidden>请输入 6 位数字确认码</span><span class="help">确认后请保持设备在线，以领取新的连接凭据。</span></div>`,
      '<button type="button" class="btn" data-action="closeModal">取消</button><button type="button" class="btn btn--primary" data-action="confirmRecover">确认恢复</button>');
  }
  function openAddAgent() {
    modal('添加智能体', `<div class="field"><label for="m-name">助手昵称</label><input class="input" id="m-name" maxlength="24" placeholder="例如：小念"><span class="err" id="m-err" hidden>请输入助手昵称</span></div>
      <div class="field"><label for="m-preset">性格</label><select class="select" id="m-preset">${window.DEMO.personaPresets.map((p) => `<option value="${p.id}">${esc(p.name)} · ${esc(p.description)}</option>`).join('')}</select></div>
      <div class="field"><span class="label">记忆</span><div class="radio-row">
        <label><input type="radio" name="m-mem" value="Memory_mem_local_short" checked>本地短期记忆</label>
        <label><input type="radio" name="m-mem" value="Memory_bailian">长期记忆 · 回响现实官方服务</label></div></div>
      <p class="help" style="font-size:12px;color:var(--ink-3)">正式版沿用原“唤醒向导”的多步流程（名字、羁绊与性格、音色、记忆）。此处为简化占位。</p>`,
      '<button type="button" class="btn" data-action="closeModal">取消</button><button type="button" class="btn btn--primary" data-action="confirmAgent">创建</button>');
  }
  function confirmAgent() {
    const name = $('#m-name').value.trim();
    if (!name) { $('#m-err').hidden = false; $('#m-name').classList.add('is-err'); $('#m-name').focus(); return; }
    const p = window.DEMO.personaPresets.find((x) => x.id === $('#m-preset').value);
    S.agents.unshift({ id: 'demo-a' + (++seq), agentName: name, avatar: null, llmModelName: window.DEMO.modelOptions.LLM[0], ttsModelName: window.DEMO.modelOptions.TTS[0],
      ttsVoiceName: window.DEMO.modelOptions.Voice[0], memModelId: document.querySelector('input[name=m-mem]:checked').value, lastConnectedAt: null,
      preset: p.id, userNickname: '你', languageCode: 'zh_CN', language: '中文', chatReport: 1, systemPrompt: p.description + '。', devices: [] });
    S.filter = 'all'; S.query = '';
    closeLayers(); go('home'); toast(`已创建智能体「${name}」${DEMO_NOTE}`);
  }
  function confirmDanger(title, text, action, attrs) {
    modal(title, `<p style="margin:0">${text}</p>`, `<button type="button" class="btn" data-action="closeModal">取消</button><button type="button" class="btn btn--danger-solid" data-action="${action}" ${attrs}>确定</button>`);
  }
  function placeholderModal(title, text) {
    modal(title, `<p style="margin:0 0 8px">${esc(text)}</p><p style="margin:0;font-size:13px;color:var(--ink-3)">原型不连接后台，这里不展示任何真实或虚构的记录。</p>`,
      '<button type="button" class="btn btn--primary" data-action="closeModal">知道了</button>');
  }

  /* ---------- 层级管理（抽屉 / 弹窗 / 移动端导航） ---------- */
  function openLayer(el) {
    lastFocus = document.activeElement;
    el.hidden = false;
    if (el.id === 'drawer') $('#scrim').hidden = false;
    document.body.style.overflow = 'hidden';
  }
  function closeLayers() {
    $('#drawer').hidden = true; $('#modalWrap').hidden = true; $('#scrim').hidden = true;
    document.body.style.overflow = '';
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }
  function closeModalOnly() {
    $('#modalWrap').hidden = true;
    if ($('#drawer').hidden) { document.body.style.overflow = ''; }
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }
  function closeSide() { $('#side').classList.remove('is-open'); if ($('#drawer').hidden) $('#scrim').hidden = true; }

  /* ---------- 事件 ---------- */
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-go],[data-action],[data-filter],[data-view],[data-sub],[data-role],[data-preset],[data-placeholder]');
    if (!t) { if (!e.target.closest('#userMenu,#userChip')) $('#userMenu').hidden = true; return; }
    if (t.dataset.go) { go(t.dataset.go); return; }
    if (t.dataset.filter) { S.filter = t.dataset.filter; render(); return; }
    if (t.dataset.view) { S.view = t.dataset.view; render(); return; }
    if (t.dataset.sub) { S.subsOpen[t.dataset.sub] = t.getAttribute('aria-expanded') !== 'true'; renderNav(); return; }
    if (t.dataset.role) { S.role = t.dataset.role; render(); toast(S.role === 'admin' ? '已切换为管理员视图（预览）' : '已切换为普通用户视图（预览）'); return; }
    if (t.dataset.preset) {
      document.querySelectorAll('.preset').forEach((b) => b.setAttribute('aria-pressed', b === t));
      const p = window.DEMO.personaPresets.find((x) => x.id === t.dataset.preset);
      const ta = $('#f-prompt'); ta.value = p.description + '。'; $('#promptCount').textContent = `${ta.value.length} / 2000`;
      return;
    }
    if (t.dataset.placeholder) {
      $('#userMenu').hidden = true; $('#userChip').setAttribute('aria-expanded', 'false');
      placeholderModal({ language: '语言', password: '修改密码', logout: '退出登录' }[t.dataset.placeholder], '正式版沿用原有语言切换、修改密码与退出登录流程。');
      return;
    }
    const id = t.dataset.id;
    switch (t.dataset.action) {
      case 'config': openConfig(id); break;
      case 'saveConfig': saveConfig(id); break;
      case 'resetConfig': openConfig(id); toast('已恢复为保存前的配置'); break;
      case 'closeDrawer': closeLayers(); break;
      case 'closeModal': closeModalOnly(); break;
      case 'addAgent': openAddAgent(); break;
      case 'confirmAgent': confirmAgent(); break;
      case 'addDevice': openAddDevice(id); break;
      case 'manualAdd': openAddDevice(null, 'manual'); break;
      case 'devTab': openAddDevice(t.dataset.agent, t.dataset.tab); break;
      case 'confirmBind': confirmBind(); break;
      case 'confirmManual': confirmManual(); break;
      case 'recover': openRecover(); break;
      case 'confirmRecover': {
        const v = $('#m-code').value.trim();
        if (!/^\d{6}$/.test(v)) { $('#m-err').hidden = false; $('#m-code').classList.add('is-err'); return; }
        closeModalOnly(); toast('恢复请求已确认（演示：未提交到服务器）'); break;
      }
      case 'agentDevices': S.deviceAgent = id; S.deviceQuery = ''; go('devices'); break;
      case 'people': S.peopleAgent = id; go('people'); break;
      case 'chat': {
        const a = findAgent(id);
        if (a.memModelId === 'Memory_nomem') { toast('请先在“配置角色”界面开启记忆'); break; }
        placeholderModal(`聊天记录 · ${a.agentName}`, '正式版按会话列出该智能体的聊天记录，并可回放上报的语音。'); break;
      }
      case 'deleteAgent': {
        const a = findAgent(id);
        confirmDanger('删除智能体', `确定要删除「${esc(a.agentName)}」吗？${a.devices.length ? `它名下的 ${a.devices.length} 台设备会失去关联。` : ''}`, 'doDeleteAgent', `data-id="${id}"`); break;
      }
      case 'doDeleteAgent': { const a = findAgent(id); S.agents = S.agents.filter((x) => x.id !== id); closeModalOnly(); render(); toast(`已删除「${a.agentName}」${DEMO_NOTE}`); break; }
      case 'unbind': confirmDanger('解绑设备', '确认要解绑该设备吗？', 'doUnbind', `data-id="${id}" data-agent="${t.dataset.agent}"`); break;
      case 'doUnbind': { const a = findAgent(t.dataset.agent); a.devices = a.devices.filter((d) => d.id !== id); closeModalOnly(); render(); toast('设备已解绑' + DEMO_NOTE); break; }
      case 'assets': placeholderModal('设备视觉资源', '正式版在这里管理该设备的自定义图片与资源下发（update_assets），与官方壁纸包、视觉角色 OTA 相互独立。'); break;
      case 'clearQuery': S.query = ''; render(); $('#q').focus(); break;
      case 'resetFilter': S.query = ''; S.filter = 'all'; render(); break;
    }
  });
  document.addEventListener('input', (e) => {
    if (e.target.id === 'q') {
      S.query = e.target.value; const pos = e.target.selectionStart; render();
      const q = $('#q'); q.focus(); q.setSelectionRange(pos, pos);
    } else if (e.target.id === 'dq') {
      S.deviceQuery = e.target.value; const pos = e.target.selectionStart; render();
      const q = $('#dq'); q.focus(); q.setSelectionRange(pos, pos);
    } else if (e.target.id === 'f-prompt') {
      $('#promptCount').textContent = `${e.target.value.length} / 2000`;
    } else if (e.target.id === 'm-code') {
      e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6);
      e.target.classList.remove('is-err'); const er = $('#m-err'); if (er) er.hidden = true;
    } else if (['m-name', 'f-name'].includes(e.target.id)) {
      e.target.classList.remove('is-err');
    }
  });
  document.addEventListener('change', (e) => {
    if (e.target.id === 'dagent') { S.deviceAgent = e.target.value; render(); }
    if (e.target.id === 'pagent') { S.peopleAgent = e.target.value; }
    if (e.target.dataset.remark) {
      const a = findAgent(e.target.dataset.agent), d = a.devices.find((x) => x.id === e.target.dataset.remark);
      d.remark = e.target.value.slice(0, 64); toast('备注已保存' + DEMO_NOTE);
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!$('#modalWrap').hidden) closeModalOnly();
      else if (!$('#drawer').hidden) closeLayers();
      else if (!$('#userMenu').hidden) { $('#userMenu').hidden = true; $('#userChip').focus(); }
      else closeSide();
    }
    if (e.key === 'Enter' && e.target.id === 'm-code') { e.preventDefault(); ($('[data-action=confirmBind]') || $('[data-action=confirmRecover]')).click(); }
    if (e.key === 'Tab') {   // 简单焦点圈定：弹窗或抽屉打开时 Tab 不离开它
      const layer = !$('#modalWrap').hidden ? $('#modal') : (!$('#drawer').hidden ? $('#drawer') : null);
      if (!layer) return;
      const f = [...layer.querySelectorAll('button, input, select, textarea')].filter((x) => !x.disabled && x.offsetParent !== null);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });
  $('#userChip').addEventListener('click', () => {
    const m = $('#userMenu'); m.hidden = !m.hidden; $('#userChip').setAttribute('aria-expanded', String(!m.hidden));
    if (!m.hidden) m.querySelector('button').focus();
  });
  $('#menuBtn').addEventListener('click', () => { $('#side').classList.add('is-open'); $('#scrim').hidden = false; });
  $('#scrim').addEventListener('click', () => { if (!$('#drawer').hidden) closeLayers(); else closeSide(); });
  $('#modalWrap').addEventListener('click', (e) => { if (e.target.id === 'modalWrap') closeModalOnly(); });

  /* ---------- 启动 ---------- */
  $('#menuBtn').innerHTML = I.menu;
  $('#userName').textContent = window.DEMO.user.username;
  $('#userMenu').lastElementChild.classList.add('danger');
  render();
  // 供自动化检查读取（不影响界面）
  window.__proto = { S, go, render };
})();
