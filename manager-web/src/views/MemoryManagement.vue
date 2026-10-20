<template>
    <div class="xn-page">
        <page-header :title="$t('memoryManagement.pageTitle')" :description="$t('xn.knowledge.memoryDesc')" />

        <div class="xn-toolbar">
            <el-input v-model="searchDeviceId" :placeholder="$t('memoryManagement.searchPlaceholder')" clearable
                @keyup.enter.native="handleSearch" @clear="handleSearch">
                <xn-icon slot="prefix" name="search" class="mm-search-icon" />
            </el-input>
            <el-button @click="handleSearch">{{ $t('memoryManagement.search') }}</el-button>
            <span v-if="activeDeviceId" class="xn-tag xn-tag--lake mm-filter">
                {{ $t('xn.knowledge.memoryFilter', { id: activeDeviceId }) }}
                <button type="button" class="mm-filter__x" :aria-label="$t('xn.knowledge.clearFilter')" @click="resetFilter"><xn-icon name="close" /></button>
            </span>
            <span class="xn-toolbar__grow"></span>
            <el-button v-if="activeDeviceId && tableData.length > 0" type="danger" plain size="small" @click="handleClearDevice">
                <xn-icon name="trash" /> {{ $t('memoryManagement.clearDevice') }}
            </el-button>
        </div>

        <div class="xn-panel xn-panel--flush mm-panel">
            <xn-empty v-if="loadFailed && !loading" error @retry="loadData" />
            <template v-else>
                <el-table :data="tableData" v-loading="loading" row-key="id">
                    <el-table-column prop="device_id" :label="$t('memoryManagement.deviceId')" min-width="150" show-overflow-tooltip>
                        <template slot-scope="{ row }"><span class="xn-num">{{ row.device_id }}</span></template>
                    </el-table-column>
                    <el-table-column prop="category" :label="$t('memoryManagement.category')" width="100">
                        <template slot-scope="{ row }">
                            <span class="xn-tag" :class="'mm-cat--' + getCategoryTag(row.category)">{{ categoryText(row.category) }}</span>
                        </template>
                    </el-table-column>
                    <el-table-column prop="fact" :label="$t('memoryManagement.fact')" min-width="300" show-overflow-tooltip />
                    <el-table-column prop="updated_at" :label="$t('memoryManagement.updatedAt')" width="185" class-name="mm-nowrap">
                        <template slot-scope="{ row }"><span class="xn-num">{{ row.updated_at }}</span></template>
                    </el-table-column>
                    <el-table-column :label="$t('memoryManagement.action')" width="90" align="right">
                        <template slot-scope="scope">
                            <el-button type="text" class="mm-danger" @click="handleDelete(scope.row)">{{ $t('memoryManagement.delete') }}</el-button>
                        </template>
                    </el-table-column>
                    <template slot="empty">
                        <!-- 接口业务错误时原 API 模块不回调，外壳会提示错误；加载未结束前不显示“没有数据” -->
                        <span v-if="loading"></span>
                        <xn-empty v-else-if="activeDeviceId" icon="search" :title="$t('xn.knowledge.memoryNoMatch')"
                            :description="$t('xn.knowledge.memoryNoMatchDesc')" />
                        <xn-empty v-else icon="memory" :title="$t('xn.knowledge.memoryEmptyTitle')"
                            :description="$t('xn.knowledge.memoryEmptyDesc')" />
                    </template>
                </el-table>
                <div v-if="total > 0" class="mm-foot">
                    <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="pageSize"
                        :current-page="currentPage" @current-change="handlePageChange" />
                </div>
            </template>
        </div>
    </div>
</template>

<script>
import Api from "@/apis/api";

export default {
    name: "MemoryManagement",
    data() {
        return {
            loading: false,
            loadFailed: false,
            tableData: [],
            total: 0,
            currentPage: 1,
            pageSize: 20,
            searchDeviceId: "",
            activeDeviceId: "",
        };
    },
    mounted() {
        window.addEventListener('xn:request-failed', this.onRequestFailed);
        this.loadData();
    },
    beforeDestroy() {
        window.removeEventListener('xn:request-failed', this.onRequestFailed);
    },
    methods: {
        // memory.js 的列表方法没有 fail 回调：业务错误时由请求层广播事件，这里结束加载并显示失败状态
        onRequestFailed({ detail }) {
            if (!this.loading || !/\/admin\/memory\?/.test(detail.url)) return;
            this.loading = false;
            this.loadFailed = true;
        },
        loadData() {
            this.loading = true;
            this.loadFailed = false;
            Api.memory.getMemoryList(
                {
                    device_id: this.activeDeviceId,
                    page: this.currentPage,
                    limit: this.pageSize,
                },
                (res) => {
                    this.loading = false;
                    if (res && res.code === 0 && res.data) {
                        this.tableData = res.data.list || [];
                        this.total = res.data.total || 0;
                        // 删除最后一页的最后一条后回到上一页
                        if (!this.tableData.length && this.total > 0 && this.currentPage > 1) {
                            this.currentPage = Math.max(1, Math.ceil(this.total / this.pageSize));
                            this.loadData();
                        }
                    } else {
                        this.tableData = [];
                        this.total = 0;
                        this.loadFailed = true;
                        this.$message.error(this.$t("memoryManagement.loadFail"));
                    }
                }
            );
        },

        handleSearch() {
            this.activeDeviceId = this.searchDeviceId.trim();
            this.currentPage = 1;
            this.loadData();
        },

        handlePageChange(page) {
            this.currentPage = page;
            this.loadData();
        },

        handleDelete(row) {
            this.$confirm(
                this.$t("memoryManagement.deleteConfirm"),
                this.$t("memoryManagement.deleteTitle"),
                { type: "warning" }
            ).then(() => {
                Api.memory.deleteMemory(row.id, (res) => {
                    if (res && res.code === 0) {
                        this.$message.success(this.$t("memoryManagement.deleteSuccess"));
                        this.loadData();
                    } else {
                        this.$message.error(this.$t("memoryManagement.deleteFail"));
                    }
                });
            }).catch(() => {});
        },

        resetFilter() {
            this.searchDeviceId = "";
            this.handleSearch();
        },

        handleClearDevice() {
            if (!this.activeDeviceId) return;
            this.$confirm(
                this.$t("memoryManagement.clearDeviceConfirm", { id: this.activeDeviceId }),
                this.$t("memoryManagement.clearDeviceTitle"),
                { type: "warning" }
            ).then(() => {
                Api.memory.clearDeviceMemory(this.activeDeviceId, (res) => {
                    if (res && res.code === 0) {
                        this.$message.success(this.$t("memoryManagement.clearDeviceSuccess"));
                        this.loadData();
                    } else {
                        this.$message.error(this.$t("memoryManagement.clearDeviceFail"));
                    }
                });
            }).catch(() => {});
        },

        getCategoryTag(category) {
            const map = {
                personal: "primary",
                preference: "success",
                work: "warning",
                relationship: "danger",
                general: "info",
            };
            return map[category] || "info";
        },
        categoryText(category) {
            const key = "memoryManagement.category_" + category;
            return this.$te(key) ? this.$t(key) : category;
        },
    },
};
</script>

<style scoped>
.mm-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.mm-filter { height: 28px; padding-right: 4px; font-size: 13px; }
.mm-filter__x {
    display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; padding: 0;
    border: 0; border-radius: 4px; background: none; color: inherit; cursor: pointer;
}
.mm-filter__x:hover { background: rgba(47, 111, 149, 0.14); }
.mm-panel { overflow: hidden; }
.mm-panel ::v-deep .mm-nowrap .cell { white-space: nowrap; }
.mm-cat--primary { background: var(--xn-lake-soft); color: var(--xn-lake-ink); }
.mm-cat--success { background: var(--xn-success-soft); color: var(--xn-success); }
.mm-cat--warning { background: var(--xn-warning-soft); color: var(--xn-warning); }
.mm-cat--danger { background: var(--xn-mist-2); color: var(--xn-ink-2); box-shadow: inset 0 0 0 1px var(--xn-line); }
.mm-cat--info { background: var(--xn-mist-2); color: var(--xn-ink-2); }
.mm-danger { color: var(--xn-danger); }
.mm-danger:hover, .mm-danger:focus { color: #8D3523; }
.mm-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
</style>
