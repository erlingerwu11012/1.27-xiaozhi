/**
 * 侧栏导航与面包屑的唯一来源。
 * - adminOnly 的分组 / 页面只在 isSuperAdmin 为 true 时显示；路由层另有 meta.adminOnly 做界面级拦截（真实权限以后端为准）。
 * - match 列出归属同一导航项的其他路由（详情页、子页面），用于高亮与面包屑。
 */
export const NAV_GROUPS = [
  {
    key: 'mine', label: 'xn.nav.groupMine',
    items: [
      { key: 'agents', label: 'xn.nav.agents', path: '/home', icon: 'agent', match: ['/role-config'] },
      { key: 'devices', label: 'xn.nav.devices', path: '/device-management', icon: 'device' },
      { key: 'identities', label: 'xn.nav.identities', path: '/unified-user-management', icon: 'people' },
    ],
  },
  {
    key: 'screen', label: 'xn.nav.groupScreen',
    items: [
      { key: 'rolePack', label: 'xn.nav.rolePack', path: '/role-pack-catalog', icon: 'role' },
      { key: 'wallpaper', label: 'xn.nav.wallpaper', path: '/wallpaper-pack-catalog', icon: 'image' },
      { key: 'ttsVoices', label: 'xn.nav.ttsVoices', path: '/official-tts/voices', icon: 'voice' },
      { key: 'ttsDubbing', label: 'xn.nav.ttsDubbing', path: '/official-tts/dubbing', icon: 'mic' },
    ],
  },
  {
    key: 'data', label: 'xn.nav.groupData',
    items: [
      { key: 'knowledge', label: 'xn.nav.knowledge', path: '/knowledge-base-management', icon: 'book', match: ['/knowledge-file-upload'] },
    ],
  },
  {
    key: 'account', label: 'xn.nav.groupAccount',
    items: [
      { key: 'packages', label: 'xn.nav.packages', path: '/billing/packages', icon: 'wallet', match: ['/billing/result'] },
      { key: 'orders', label: 'xn.nav.orders', path: '/billing/orders', icon: 'receipt' },
    ],
  },
  {
    key: 'admin', label: 'xn.nav.groupAdmin', adminOnly: true,
    items: [
      { key: 'users', label: 'xn.nav.users', path: '/user-management', icon: 'users' },
      { key: 'modelConfig', label: 'xn.nav.modelConfig', path: '/model-config', icon: 'chip' },
      { key: 'provider', label: 'xn.nav.provider', path: '/provider-management', icon: 'plug' },
      { key: 'agentTemplate', label: 'xn.nav.agentTemplate', path: '/agent-template-management', icon: 'template', match: ['/template-quick-config'] },
      { key: 'ttsAdmin', label: 'xn.nav.ttsAdmin', path: '/admin/official-tts', icon: 'voice' },
    ],
    subs: [
      {
        key: 'adminMemory', label: 'xn.nav.groupAdminMemory', icon: 'memory',
        items: [
          { key: 'memory', label: 'xn.nav.memory', path: '/memory-management' },
          { key: 'memoryExtract', label: 'xn.nav.memoryExtract', path: '/memory-extract-config' },
          { key: 'habit', label: 'xn.nav.habit', path: '/habit-management' },
          { key: 'habitAnalyze', label: 'xn.nav.habitAnalyze', path: '/habit-analyze-config' },
        ],
      },
      {
        key: 'adminSystem', label: 'xn.nav.groupAdminSystem', icon: 'gear',
        items: [
          { key: 'params', label: 'xn.nav.params', path: '/params-management' },
          { key: 'dict', label: 'xn.nav.dict', path: '/dict-management' },
          { key: 'server', label: 'xn.nav.server', path: '/server-side-management' },
        ],
      },
    ],
  },
];

/** 不在侧栏里、但需要面包屑的页面 */
const EXTRA = {
  '/role-config': { group: 'xn.nav.groupMine', label: 'xn.nav.roleConfig', parent: '/home' },
  '/knowledge-file-upload': { group: 'xn.nav.groupData', label: 'xn.nav.knowledgeUpload', parent: '/knowledge-base-management' },
  '/billing/result': { group: 'xn.nav.groupAccount', label: 'xn.nav.billingResult', parent: '/billing/packages' },
  '/template-quick-config': { group: 'xn.nav.groupAdmin', label: 'xn.nav.templateQuick', parent: '/agent-template-management' },
};

/** 根据路径找到所属分组与导航项，用于高亮和面包屑 */
export function locate(path) {
  for (const g of NAV_GROUPS) {
    for (const it of g.items) {
      if (it.path === path) return { group: g.label, item: it.label, key: it.key };
    }
    for (const s of g.subs || []) {
      for (const it of s.items) if (it.path === path) return { group: s.label, item: it.label, key: it.key, sub: s.key };
    }
  }
  if (EXTRA[path]) {
    const parent = locate(EXTRA[path].parent);
    return { group: EXTRA[path].group, item: EXTRA[path].label, key: parent && parent.key, sub: parent && parent.sub, parentLabel: parent && parent.item, parentPath: EXTRA[path].parent };
  }
  return null;
}
