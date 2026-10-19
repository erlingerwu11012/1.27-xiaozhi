import Vue from 'vue'
import VueRouter from 'vue-router'

Vue.use(VueRouter)

const routes = [
  {
    path: '/',
    name: 'welcome',
    component: function () {
      return import('../views/login.vue')
    }
  },
  {
    path: '/role-config',
    name: 'RoleConfig',
    component: function () {
      return import('../views/roleConfig.vue')
    }
  },
  {
    path: '/voice-print',
    name: 'VoicePrint',
    redirect: to => ({ path: '/unified-user-management', query: to.query })
  },
  {
    path: '/face-management',
    name: 'FaceManagement',
    redirect: to => ({ path: '/unified-user-management', query: to.query })
  },
  {
    path: '/unified-user-management',
    name: 'UnifiedUserManagement',
    component: function () {
      return import('../views/UnifiedUserManagement.vue')
    }
  },
  {
    path: '/login',
    name: 'login',
    component: function () {
      return import('../views/login.vue')
    }
  },
  {
    path: '/home',
    name: 'home',
    component: function () {
      return import('../views/home.vue')
    }
  },
  {
    path: '/register',
    name: 'Register',
    component: function () {
      return import('../views/register.vue')
    }
  },
  {
    path: '/retrieve-password',
    name: 'RetrievePassword',
    component: function () {
      return import('../views/retrievePassword.vue')
    }
  },
  // 设备管理页面路由
  {
    path: '/device-management',
    name: 'DeviceManagement',
    component: function () {
      return import('../views/DeviceManagement.vue')
    }
  },
  // 添加用户管理路由
  {
    path: '/user-management',
    name: 'UserManagement',
    component: function () {
      return import('../views/UserManagement.vue')
    }
  },
  {
    path: '/model-config',
    name: 'ModelConfig',
    component: function () {
      return import('../views/ModelConfig.vue')
    }
  },
  { path: '/params-management',
    name: 'ParamsManagement',
    component: function () {
      return import('../views/ParamsManagement.vue')
    },
    meta: {
      requiresAuth: true,
      title: '参数管理'
    }
  },
  { path: '/memory-extract-config',
    name: 'MemoryExtractConfig',
    component: function () {
      return import('../views/MemoryExtractConfig.vue')
    },
    meta: {
      requiresAuth: true,
      title: '记忆提取配置'
    }
  },
  { path: '/habit-analyze-config',
    name: 'HabitAnalyzeConfig',
    component: function () {
      return import('../views/HabitAnalyzeConfig.vue')
    },
    meta: {
      requiresAuth: true,
      title: '习惯分析配置'
    }
  },
  { path: '/habit-management',
    name: 'HabitManagement',
    component: function () {
      return import('../views/HabitManagement.vue')
    },
    meta: {
      requiresAuth: true,
      title: '习惯管理'
    }
  },
  { path: '/role-pack-catalog',
    name: 'RolePackCatalog',
    component: function () {
      return import('../views/RolePackCatalog.vue')
    },
    meta: {
      requiresAuth: true,
      title: '视觉角色'
    }
  },
  { path: '/wallpaper-pack-catalog',
    name: 'WallpaperPackCatalog',
    component: function () {
      return import('../views/WallpaperPackCatalog.vue')
    },
    meta: {
      requiresAuth: true,
      title: '壁纸包'
    }
  },
  { path: '/memory-management',
    name: 'MemoryManagement',
    component: function () {
      return import('../views/MemoryManagement.vue')
    },
    meta: {
      requiresAuth: true,
      title: '记忆管理'
    }
  },
  { path: '/knowledge-base-management',
    name: 'KnowledgeBaseManagement',
    component: function () {
      return import('../views/KnowledgeBaseManagement.vue')
    },
    meta: {
      requiresAuth: true,
      title: '知识库管理'
    }
  },
  { path: '/knowledge-file-upload',
    name: 'KnowledgeFileUpload',
    component: function () {
      return import('../views/KnowledgeFileUpload.vue')
    },
    meta: {
      requiresAuth: true,
      title: '文档上传管理'
    }
  },

  {
    path: '/server-side-management',
    name: 'ServerSideManager',
    component: function () {
      return import('../views/ServerSideManager.vue')
    },
    meta: {
      requiresAuth: true,
      title: '服务端管理'
    }
  },
  {
    path: '/ota-management',
    redirect: { name: 'RolePackCatalog' }
  },
  {
    path: '/dict-management',
    name: 'DictManagement',
    component: function () {
      return import('../views/DictManagement.vue')
    }
  },
  {
    path: '/provider-management',
    name: 'ProviderManagement',
    component: function () {
      return import('../views/ProviderManagement.vue')
    }
  },
  // 添加默认角色管理路由
  {
    path: '/agent-template-management',
    name: 'AgentTemplateManagement',
    component: function () {
      return import('../views/AgentTemplateManagement.vue')
    }
  },
  // 添加模板快速配置路由
  {
    path: '/template-quick-config',
    name: 'TemplateQuickConfig',
    component: function () {
      return import('../views/TemplateQuickConfig.vue')
    }
  },
  { path: '/billing/packages',
    name: 'BillingPackages',
    component: function () {
      return import('../views/BillingPackages.vue')
    },
    meta: {
      requiresAuth: true,
      title: '充值套餐'
    }
  },
  { path: '/billing/result',
    name: 'BillingResult',
    component: function () {
      return import('../views/BillingResult.vue')
    },
    meta: {
      requiresAuth: true,
      title: '支付结果'
    }
  },
  { path: '/billing/orders',
    name: 'BillingOrders',
    component: function () {
      return import('../views/BillingOrders.vue')
    },
    meta: {
      requiresAuth: true,
      title: '账单'
    }
  },
  {
    path: '/official-tts/voices',
    name: 'OfficialTtsVoices',
    component: function () {
      return import('../views/OfficialTtsVoices.vue')
    },
    meta: { requiresAuth: true, title: '我的音色' }
  },
  {
    path: '/official-tts/dubbing',
    name: 'OfficialTtsDubbing',
    component: function () {
      return import('../views/OfficialTtsDubbing.vue')
    },
    meta: { requiresAuth: true, title: '配音工作台' }
  },
  {
    path: '/admin/official-tts',
    name: 'OfficialTtsAdmin',
    component: function () {
      return import('../views/OfficialTtsAdmin.vue')
    },
    meta: { requiresAuth: true, title: '官方TTS管理' }
  },
]
const router = new VueRouter({
  base: process.env.VUE_APP_PUBLIC_PATH || '/',
  routes
})

// 全局处理重复导航，改为刷新页面
const originalPush = VueRouter.prototype.push
VueRouter.prototype.push = function push(location) {
  return originalPush.call(this, location).catch(err => {
    if (err.name === 'NavigationDuplicated') {
      // 如果是重复导航，刷新页面
      window.location.reload()
    } else {
      // 其他错误正常抛出
      throw err
    }
  })
}

// 需要登录才能访问的路由
const protectedRoutes = ['home', 'RoleConfig', 'DeviceManagement', 'UserManagement', 'UnifiedUserManagement', 'ModelConfig', 'KnowledgeBaseManagement', 'KnowledgeFileUpload', 'HabitManagement', 'RolePackCatalog', 'WallpaperPackCatalog', 'FaceManagement', 'BillingPackages', 'BillingResult', 'BillingOrders', 'OfficialTtsVoices', 'OfficialTtsDubbing', 'OfficialTtsAdmin']

// 路由守卫
router.beforeEach((to, from, next) => {
  if (['HabitManagement', 'MemoryManagement', 'MemoryExtractConfig'].includes(to.name) && localStorage.getItem('isSuperAdmin') !== 'true') {
    next({ name: 'home' })
    return
  }
  // 检查是否是需要保护的路由
  if (protectedRoutes.includes(to.name)) {
    // 从localStorage获取token
    const token = localStorage.getItem('token')
    if (!token) {
      // 未登录，跳转到登录页
      next({ name: 'login', query: { redirect: to.fullPath } })
      return
    }
  }
  next()
})

export default router
