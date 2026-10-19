<template>
    <div class="welcome">
        <HeaderBar />

        <div class="operation-bar">
            <h2 class="page-title">{{ $t('memoryManagement.pageTitle') }}</h2>
            <div class="action-group">
                <div class="search-group">
                    <el-input
                        :placeholder="$t('memoryManagement.searchPlaceholder')"
                        v-model="searchDeviceId"
                        class="search-input"
                        clearable
                        @keyup.enter.native="handleSearch"
                        style="width: 260px"
                    />
                    <el-button class="btn-search" @click="handleSearch">
                        {{ $t('memoryManagement.search') }}
                    </el-button>
                </div>
                <el-button
                    v-if="searchDeviceId && tableData.length > 0"
                    type="danger"
                    class="btn-clear-device"
                    @click="handleClearDevice"
                >
                    {{ $t('memoryManagement.clearDevice') }}
                </el-button>
            </div>
        </div>

        <div class="main-wrapper">
            <div class="content-panel">
                <el-table
                    :data="tableData"
                    v-loading="loading"
                    style="width: 100%"
                    :header-cell-style="{ background: '#f5f7fb', color: '#606266' }"
                >
                    <el-table-column
                        prop="device_id"
                        :label="$t('memoryManagement.deviceId')"
                        min-width="200"
                        show-overflow-tooltip
                    />
                    <el-table-column
                        prop="category"
                        :label="$t('memoryManagement.category')"
                        width="130"
                        align="center"
                    >
                        <template slot-scope="scope">
                            <el-tag :type="getCategoryTag(scope.row.category)" size="small">
                                {{ $t('memoryManagement.category_' + scope.row.category) || scope.row.category }}
                            </el-tag>
                        </template>
                    </el-table-column>
                    <el-table-column
                        prop="fact"
                        :label="$t('memoryManagement.fact')"
                        min-width="300"
                        show-overflow-tooltip
                    />
                    <el-table-column
                        prop="updated_at"
                        :label="$t('memoryManagement.updatedAt')"
                        width="180"
                        align="center"
                    />
                    <el-table-column
                        :label="$t('memoryManagement.action')"
                        width="100"
                        align="center"
                        fixed="right"
                    >
                        <template slot-scope="scope">
                            <el-button
                                type="text"
                                class="btn-delete"
                                @click="handleDelete(scope.row)"
                            >
                                {{ $t('memoryManagement.delete') }}
                            </el-button>
                        </template>
                    </el-table-column>
                </el-table>

                <div class="pagination-wrapper">
                    <el-pagination
                        background
                        layout="total, prev, pager, next"
                        :total="total"
                        :page-size="pageSize"
                        :current-page="currentPage"
                        @current-change="handlePageChange"
                    />
                </div>
            </div>
        </div>
    </div>
</template>

<script>
import HeaderBar from "@/components/HeaderBar.vue";
import Api from "@/apis/api";

export default {
    name: "MemoryManagement",
    components: { HeaderBar },
    data() {
        return {
            loading: false,
            tableData: [],
            total: 0,
            currentPage: 1,
            pageSize: 20,
            searchDeviceId: "",
            activeDeviceId: "",
        };
    },
    mounted() {
        this.loadData();
    },
    methods: {
        loadData() {
            this.loading = true;
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
                    } else {
                        this.tableData = [];
                        this.total = 0;
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

        handleClearDevice() {
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
    },
};
</script>

<style scoped>
.welcome {
    min-height: 100vh;
    background: #f5f7fb;
}

.operation-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 32px 0;
}

.page-title {
    font-size: 20px;
    font-weight: 600;
    color: #1a1a2e;
    margin: 0;
}

.action-group {
    display: flex;
    align-items: center;
    gap: 12px;
}

.search-group {
    display: flex;
    align-items: center;
    gap: 8px;
}

.btn-search {
    background: #4f6ef6;
    border-color: #4f6ef6;
    color: #fff;
    border-radius: 8px;
}

.btn-search:hover {
    background: #3a5bd9;
    border-color: #3a5bd9;
}

.btn-clear-device {
    border-radius: 8px;
}

.main-wrapper {
    padding: 24px 32px;
}

.content-panel {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    overflow: hidden;
    padding: 0 0 16px;
}

.pagination-wrapper {
    display: flex;
    justify-content: flex-end;
    padding: 16px 24px 0;
}

.btn-delete {
    color: #f56c6c;
}

.btn-delete:hover {
    color: #d9363e;
}
</style>
