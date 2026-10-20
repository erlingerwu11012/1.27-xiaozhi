<template>
  <div class="xn-page">
    <div class="xn-panel">
      <xn-empty icon="lock" :title="$t('xn.perm.title')" :description="$t('xn.perm.desc')">
        <el-button type="primary" @click="$router.push('/home')">{{ $t('xn.perm.back') }}</el-button>
      </xn-empty>
    </div>
  </div>
</template>

<script>
/* 权限不足：路由 meta.adminOnly 且当前账号不是管理员时，外壳显示这里而不渲染页面（界面层拦截，真实权限以后端为准）。 */
export default { name: 'NoPermission' };
</script>
