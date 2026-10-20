<template>
  <div class="xn-page">
    <page-header :title="$t('header.userManagement')" :description="$t('xn.admin.users.desc')" />

    <div class="xn-toolbar">
      <el-input v-model="searchPhone" :placeholder="$t('user.searchPhone')" clearable
        @keyup.enter.native="handleSearch" @clear="handleSearch">
        <xn-icon slot="prefix" name="search" class="xa-search-icon" />
      </el-input>
      <el-button @click="handleSearch">{{ $t('user.search') }}</el-button>
      <span class="xn-toolbar__grow"></span>
      <template v-if="selectedCount">
        <span class="xn-muted">{{ $t('xn.admin.selected', { n: selectedCount }) }}</span>
        <el-button size="small" @click="handleBatchStatusChange(1)">{{ $t('user.enable') }}</el-button>
        <el-button size="small" @click="handleBatchStatusChange(0)">{{ $t('user.disable') }}</el-button>
        <el-button type="danger" plain size="small" @click="batchDelete"><xn-icon name="trash" /> {{ $t('user.delete') }}</el-button>
      </template>
    </div>

    <div class="xn-panel xn-panel--flush xa-panel">
      <xn-empty v-if="loadFailed && !loading" error @retry="fetchUsers" />
      <template v-else>
        <el-table ref="userTable" :data="userList" v-loading="loading" row-key="userid">
          <el-table-column width="52" align="center">
            <template slot="header">
              <el-checkbox :value="isAllSelected" :indeterminate="selectedCount > 0 && !isAllSelected"
                :disabled="!userList.length" :aria-label="$t('user.selectAll')" @change="handleSelectAll" />
            </template>
            <template slot-scope="scope"><el-checkbox v-model="scope.row.selected" /></template>
          </el-table-column>
          <el-table-column :label="$t('xn.admin.users.account')" min-width="180">
            <template slot-scope="{ row }"><span class="xa-strong">{{ row.mobile }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('user.userid')" min-width="150">
            <template slot-scope="{ row }"><span class="xn-num xn-muted">{{ row.userid }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('user.deviceCount')" prop="deviceCount" width="100" align="right" class-name="xn-num" />
          <el-table-column :label="$t('user.createDate')" min-width="160">
            <template slot-scope="{ row }"><span class="xn-num">{{ row.createDate }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('user.status')" width="100">
            <template slot-scope="{ row }">
              <span v-if="row.status === 1" class="xn-tag xn-tag--success"><i class="dot"></i>{{ $t('user.normal') }}</span>
              <span v-else class="xn-tag xn-tag--danger"><i class="dot"></i>{{ $t('user.disabled') }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('modelConfig.action')" width="240" align="right">
            <template slot-scope="scope">
              <el-button type="text" @click="resetPassword(scope.row)">{{ $t('user.resetPassword') }}</el-button>
              <el-button v-if="scope.row.status === 1" type="text" @click="handleChangeStatus(scope.row, 0)">{{ $t('user.disableAccount') }}</el-button>
              <el-button v-else type="text" @click="handleChangeStatus(scope.row, 1)">{{ $t('user.enableAccount') }}</el-button>
              <el-button type="text" class="xa-danger" @click="deleteUser(scope.row)">{{ $t('user.deleteUser') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty v-if="lastSearch" icon="search" :title="$t('xn.admin.users.noMatch')" :description="$t('xn.admin.noMatchDesc')" />
            <xn-empty v-else icon="users" :title="$t('xn.admin.users.empty')" :description="$t('xn.admin.users.emptyDesc')" />
          </template>
        </el-table>
        <div v-if="total" class="xa-foot">
          <el-pagination background layout="total, sizes, prev, pager, next" :total="total" :page-size="pageSize"
            :page-sizes="pageSizeOptions" :current-page="currentPage" @size-change="handlePageSizeChange" @current-change="goToPage" />
        </div>
      </template>
    </div>

    <view-password-dialog :visible.sync="showViewPassword" :password="currentPassword" />
  </div>
</template>

<script>
import Api from "@/apis/api";
import ViewPasswordDialog from "@/components/ViewPasswordDialog.vue";
import { IS_MOCK } from "@/utils/media";

export default {
  components: { ViewPasswordDialog },
  data() {
    return {
      showViewPassword: false,
      currentPassword: "",
      searchPhone: "",
      lastSearch: "",
      userList: [],
      pageSizeOptions: [10, 20, 50, 100],
      currentPage: 1,
      pageSize: 10,
      total: 0,
      loading: false,
      loadFailed: false,
    };
  },
  created() {
    this.fetchUsers();
  },
  beforeDestroy() {
    clearTimeout(this._loadTimer);
  },
  computed: {
    pageCount() {
      return Math.ceil(this.total / this.pageSize);
    },
    selectedCount() {
      return this.userList.filter((u) => u.selected).length;
    },
    isAllSelected() {
      return this.userList.length > 0 && this.userList.every((u) => u.selected);
    },
  },
  methods: {
    handlePageSizeChange(val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.fetchUsers();
    },
    // 业务错误由请求层统一提示且不回调；超过 8 秒仍无结果时显示失败状态
    startLoading() {
      this.loading = true;
      this.loadFailed = false;
      clearTimeout(this._loadTimer);
      this._loadTimer = setTimeout(() => {
        if (this.loading) { this.loading = false; this.loadFailed = true; }
      }, 8000);
    },
    fetchUsers() {
      this.startLoading();
      Api.admin.getUserList(
        {
          page: this.currentPage,
          limit: this.pageSize,
          mobile: this.searchPhone,
        },
        ({ data }) => {
          this.loading = false; // 结束加载
          clearTimeout(this._loadTimer);
          if (data.code === 0) {
            this.lastSearch = this.searchPhone;
            this.userList = data.data.list.map(item => ({
              ...item,
              selected: false
            }));
            this.total = data.data.total;
          } else {
            this.loadFailed = true;
          }
        }
      );
    },
    handleSearch() {
      this.currentPage = 1;
      this.fetchUsers();
    },
    handleSelectAll() {
      const next = !this.isAllSelected;
      this.userList.forEach(row => {
        row.selected = next;
      });
    },
    batchDelete() {
      const selectedUsers = this.userList.filter(user => user.selected);
      if (selectedUsers.length === 0) {
        this.$message.warning(this.$t('user.selectUsersFirst'));
        return;
      }

      this.$confirm(this.$t('user.confirmDeleteSelected', { count: selectedUsers.length }), this.$t('common.warning'), {
        confirmButtonText: this.$t('common.confirm'),
        cancelButtonText: this.$t('common.cancel'),
        type: "warning",
      })
        .then(async () => {
          this.loading = true;
          try {
            const results = await Promise.all(
              selectedUsers.map((user) => {
                return new Promise((resolve) => {
                  Api.admin.deleteUser(user.userid, ({ data }) => {
                    if (data.code === 0) {
                      resolve({ success: true, userid: user.userid });
                    } else {
                      resolve({ success: false, userid: user.userid, msg: data.msg });
                    }
                  });
                  // 业务错误时请求层不回调：短暂等待后按失败计
                  setTimeout(() => resolve({ success: false, userid: user.userid }), 8000);
                });
              })
            );

            const successCount = results.filter((r) => r.success).length;
            const failCount = results.length - successCount;

            if (failCount === 0) {
              this.$message.success({
                message: this.$t('user.deleteSuccess', { count: successCount }),
                showClose: true
              });
            } else if (successCount === 0) {
              this.$message.error({
                message: this.$t('user.deleteFailed'),
                showClose: true
              });
            } else {
              this.$message.warning(
                this.$t('user.partialDelete', { successCount: successCount, failCount: failCount })
              );
            }

            this.fetchUsers();
          } catch (error) {
            this.$message.error(this.$t('user.deleteError'));
            this.loading = false;
          }
        })
        .catch(() => {
          this.$message.info(this.$t('user.deleteCancelled'));
        });
    },
    batchEnable() {
      this.handleBatchStatusChange(1);
    },
    batchDisable() {
      this.handleBatchStatusChange(0);
    },
    resetPassword(row) {
      this.$confirm(this.$t('user.confirmResetPassword'), this.$t('user.resetPassword'), {
        confirmButtonText: this.$t('xn.admin.users.resetConfirm'),
        cancelButtonText: this.$t('common.cancel'),
        type: 'warning'
      }).then(() => {
        Api.admin.resetUserPassword(row.userid, ({ data }) => {
          if (data.code === 0) {
            // 新密码只放在弹窗里显示（不再用可注入 HTML 的提示框）
            this.currentPassword = String(data.data || '');
            this.showViewPassword = true;
            this.fetchUsers();
          } else {
            this.$message.error(data.msg || this.$t('user.operationFailed'));
          }
        });
      }).catch(() => {
        this.$message.info(this.$t('xn.admin.cancelled'));
      });
    },
    deleteUser(row) {
      this.$confirm(this.$t('user.confirmDeleteUser'), this.$t('user.deleteUser'), {
        confirmButtonText: this.$t('user.deleteUser'),
        cancelButtonText: this.$t('common.cancel'),
        type: 'warning'
      }).then(() => {
        Api.admin.deleteUser(row.userid, ({ data }) => {
          if (data.code === 0) {
            this.$message.success(this.$t('user.deleteUserSuccess'));
            this.fetchUsers();
          } else {
            this.$message.error(data.msg || this.$t('user.operationFailed'));
          }
        });
      }).catch(() => {
        this.$message.info(this.$t('common.deleteCancelled'));
      });
    },
    goToPage(page) {
      this.currentPage = page;
      this.fetchUsers();
    },
    handleChangeStatus(row, status) {
      // 处理单个用户或用户数组
      const users = Array.isArray(row) ? row : [row];
      const actionText = status === 0 ? this.$t('user.disable') : this.$t('user.enable');
      const userCount = users.length;

      this.$confirm(this.$t('user.confirmStatusChange', { action: actionText, count: userCount }), this.$t('common.warning'), {
        confirmButtonText: actionText,
        cancelButtonText: this.$t('common.cancel'),
        type: 'warning'
      }).then(() => {
        const userIds = users.map(user => user.userid);
        // 真实账号 ID 为数字；演示数据的 ID 是 demo-u-xxxx，只在 mock 模式下放宽数字校验
        if (userIds.some(id => !id || (!IS_MOCK && isNaN(id)))) {
          this.$message.error(this.$t('user.invalidUserId'));
          return;
        }

        Api.user.changeUserStatus(status, userIds, ({ data }) => {
          if (data.code === 0) {
            this.$message.success({
              message: this.$t('user.statusChangeSuccess', { action: actionText, count: userCount }),
              showClose: true
            });
            this.fetchUsers(); // 刷新用户列表
          } else {
            this.$message.error({
              message: this.$t('user.operationFailed'),
              showClose: true
            });
          }
        });
      }).catch(() => {
        // 用户取消操作
      });
    },
    // 这个方法已被batchDelete替代，保留用于向后兼容
    handleBatchDelete() {
      this.batchDelete();
    },
    handleBatchStatusChange(status) {
      const selectedUsers = this.userList.filter(user => user.selected);
      if (selectedUsers.length === 0) {
        this.$message.warning(this.$t('xn.admin.selectFirst'));
        return;
      }
      this.handleChangeStatus(selectedUsers, status);
    },
  },
};
</script>

<style scoped>
.xa-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.xa-panel { overflow: hidden; }
.xa-strong { font-weight: 500; }
.xa-danger { color: var(--xn-danger); }
.xa-danger:hover, .xa-danger:focus { color: #8D3523; }
.xa-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
</style>
