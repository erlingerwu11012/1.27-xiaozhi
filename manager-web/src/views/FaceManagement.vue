<template>
    <div class="welcome">

        <div class="operation-bar">
            <h2 class="page-title">{{ $t('faceManagement.pageTitle') }}</h2>
            <el-button type="primary" class="btn-add" @click="openCreateDialog">
                + {{ $t('faceManagement.addMember') }}
            </el-button>
            <el-button type="text" @click="openUnifiedUserManagement">统一用户管理</el-button>
        </div>

        <div class="main-wrapper">
            <p class="hint-banner">{{ $t('faceManagement.freezeHint') }}</p>
            <el-alert title="人脸 profile 请在“用户管理”中显式绑定到 user_id；本页保留采集和维护功能。" type="info" :closable="false" show-icon style="margin-bottom:12px" />

            <!-- 设备采集：待命名草稿（与正式用户表分离） -->
            <div class="content-panel draft-panel">
                <div class="content-area">
                    <h3 class="section-title">{{ $t('faceManagement.enrollmentTitle') }}</h3>
                    <p class="section-hint">{{ $t('faceManagement.enrollmentHint') }}</p>
                    <el-table
                        :data="enrollmentDrafts"
                        v-loading="draftLoading"
                        class="transparent-table"
                        style="width: 100%"
                        :empty-text="$t('faceManagement.enrollmentEmpty')"
                    >
                        <el-table-column
                            :label="$t('faceManagement.col.preview')"
                            width="100"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                <img
                                    v-if="row.previewUrl"
                                    :src="row.previewUrl"
                                    class="draft-preview"
                                    alt=""
                                />
                                <span v-else class="muted">—</span>
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.col.collectedAt')"
                            min-width="150"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                {{ formatTime(row.created_at) }}
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.col.faceCount')"
                            width="110"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                {{ row.accepted_count || 0 }}
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.col.status')"
                            width="120"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                <el-tag
                                    :type="enrollmentStatusType(row.status)"
                                    size="small"
                                >
                                    {{ enrollmentStatusLabel(row.status) }}
                                </el-tag>
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.form.name')"
                            min-width="140"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                <el-input
                                    v-model="row._name"
                                    size="small"
                                    :disabled="row.status !== 'draft_ready'"
                                    :placeholder="$t('faceManagement.form.namePlaceholder')"
                                    maxlength="64"
                                />
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.col.actions')"
                            width="220"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                <el-button
                                    type="text"
                                    :disabled="row.status !== 'draft_ready' || row._saving"
                                    @click="confirmEnrollment(row)"
                                >
                                    {{ $t('faceManagement.confirmEnable') }}
                                </el-button>
                                <el-button
                                    type="text"
                                    class="btn-delete"
                                    :disabled="row._saving"
                                    @click="discardEnrollment(row)"
                                >
                                    {{ $t('faceManagement.discardDraft') }}
                                </el-button>
                            </template>
                        </el-table-column>
                    </el-table>
                </div>
            </div>

            <div class="content-panel">
                <div class="content-area">
                    <h3 class="section-title">{{ $t('faceManagement.activeTitle') }}</h3>
                    <el-table
                        :data="faceList"
                        v-loading="loading"
                        class="transparent-table"
                        :element-loading-text="$t('faceManagement.loading')"
                        element-loading-spinner="el-icon-loading"
                        style="width: 100%"
                        :empty-text="$t('faceManagement.empty')"
                    >
                        <el-table-column
                            type="index"
                            :label="$t('faceManagement.col.index')"
                            width="70"
                            align="center"
                        />
                        <el-table-column
                            :label="$t('faceManagement.col.name')"
                            min-width="120"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                <span class="face-name">{{ row.display_name }}</span>
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.col.status')"
                            width="100"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                <el-tag
                                    :type="row.status === 'active' ? 'success' : 'warning'"
                                    size="small"
                                >
                                    {{ row.status === 'active'
                                        ? $t('faceManagement.statusActive')
                                        : $t('faceManagement.statusDraft') }}
                                </el-tag>
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.col.faceCount')"
                            width="100"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                {{ row.face_count }}
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.col.createdAt')"
                            min-width="160"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                {{ formatTime(row.created_at) }}
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('faceManagement.col.actions')"
                            width="260"
                            align="center"
                        >
                            <template slot-scope="{ row }">
                                <!-- active：仅查看与删除，不可改名 -->
                                <template v-if="row.status === 'draft'">
                                    <el-button type="text" @click="openDraftDialog(row)">
                                        {{ $t('faceManagement.uploadPhotos') }}
                                    </el-button>
                                    <el-button type="text" @click="handleActivate(row)">
                                        {{ $t('faceManagement.activate') }}
                                    </el-button>
                                </template>
                                <el-button
                                    type="text"
                                    class="btn-delete"
                                    @click="handleDelete(row)"
                                >
                                    {{ $t('faceManagement.delete') }}
                                </el-button>
                            </template>
                        </el-table-column>
                    </el-table>
                </div>
            </div>
        </div>

        <!-- 新增 / 草稿录入 -->
        <el-dialog
            :title="dialogMode === 'create'
                ? $t('faceManagement.createTitle')
                : $t('faceManagement.uploadTitle')"
            :visible.sync="dialogVisible"
            width="520px"
            :close-on-click-modal="false"
            @close="resetDialog"
        >
            <el-alert
                :title="$t('faceManagement.freezeHint')"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 16px"
            />
            <el-form label-width="100px">
                <el-form-item :label="$t('faceManagement.form.name')" required>
                    <el-input
                        v-model="form.displayName"
                        :disabled="dialogMode !== 'create' || !!form.userId"
                        :placeholder="$t('faceManagement.form.namePlaceholder')"
                        maxlength="64"
                        show-word-limit
                    />
                </el-form-item>
                <el-form-item :label="$t('faceManagement.form.photos')">
                    <input
                        ref="fileInput"
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        multiple
                        @change="onFilesSelected"
                    />
                    <p class="form-tip">{{ $t('faceManagement.form.photoTip') }}</p>
                    <div v-if="previews.length" class="preview-row">
                        <div
                            v-for="(p, idx) in previews"
                            :key="idx"
                            class="preview-item"
                        >
                            <img :src="p.url" alt="" />
                            <span>{{ p.name }}</span>
                        </div>
                    </div>
                    <p class="form-tip">
                        {{ $t('faceManagement.form.uploadedCount', { count: form.faceCount }) }}
                    </p>
                </el-form-item>
            </el-form>
            <span slot="footer" class="dialog-footer">
                <el-button @click="dialogVisible = false">
                    {{ $t('faceManagement.cancel') }}
                </el-button>
                <el-button
                    v-if="dialogMode === 'create' && !form.userId"
                    type="primary"
                    :loading="saving"
                    @click="createDraft"
                >
                    {{ $t('faceManagement.createDraft') }}
                </el-button>
                <el-button
                    v-if="form.userId"
                    type="primary"
                    :loading="saving"
                    :disabled="!pendingFiles.length"
                    @click="uploadPending"
                >
                    {{ $t('faceManagement.uploadPhotos') }}
                </el-button>
                <el-button
                    v-if="form.userId && form.faceCount > 0"
                    type="success"
                    :loading="saving"
                    @click="activateCurrent"
                >
                    {{ $t('faceManagement.activate') }}
                </el-button>
            </span>
        </el-dialog>
    </div>
</template>

<script>
import Api from "@/apis/api";

export default {
    name: "FaceManagement",
    data() {
        return {
            loading: false,
            draftLoading: false,
            saving: false,
            faceList: [],
            enrollmentDrafts: [],
            dialogVisible: false,
            dialogMode: "create",
            form: {
                userId: "",
                displayName: "",
                faceCount: 0,
                status: "draft",
            },
            pendingFiles: [],
            previews: [],
        };
    },
    mounted() {
        this.loadFaces();
        this.loadEnrollmentDrafts();
    },
    beforeDestroy() {
        this.clearPreviews();
        this.clearEnrollmentPreviews();
    },
    methods: {
        openUnifiedUserManagement() {
            this.$router.push({
                path: '/unified-user-management',
                query: { agentId: this.$route.query.agentId || '' }
            });
        },
        formatTime(value) {
            if (!value) return "-";
            try {
                const d = new Date(value);
                if (Number.isNaN(d.getTime())) return value;
                return d.toLocaleString();
            } catch (e) {
                return value;
            }
        },

        enrollmentStatusLabel(status) {
            if (status === "draft_ready") {
                return this.$t("faceManagement.statusWaitingName");
            }
            if (status === "collecting") {
                return this.$t("faceManagement.statusCollecting");
            }
            if (status === "expired") {
                return this.$t("faceManagement.statusExpired");
            }
            return status || "-";
        },

        enrollmentStatusType(status) {
            if (status === "draft_ready") return "success";
            if (status === "collecting") return "warning";
            if (status === "expired") return "info";
            return "";
        },

        clearEnrollmentPreviews() {
            (this.enrollmentDrafts || []).forEach((d) => {
                if (d.previewUrl) URL.revokeObjectURL(d.previewUrl);
            });
        },

        loadEnrollmentDrafts() {
            this.draftLoading = true;
            Api.face.listEnrollmentSessions((res) => {
                this.draftLoading = false;
                this.clearEnrollmentPreviews();
                if (res && res.code === 0) {
                    const payload = res.data || {};
                    const list = payload.sessions || [];
                    this.enrollmentDrafts = (Array.isArray(list) ? list : []).map((s) => ({
                        ...s,
                        _name: "",
                        _saving: false,
                        previewUrl: "",
                    }));
                    this.enrollmentDrafts.forEach((row) => {
                        if (row.has_preview) {
                            Api.face.fetchEnrollmentPreview(row.session_id, (pr) => {
                                if (pr && pr.code === 0 && pr.url) {
                                    this.$set(row, "previewUrl", pr.url);
                                }
                            });
                        }
                    });
                } else {
                    this.enrollmentDrafts = [];
                }
            });
        },

        confirmEnrollment(row) {
            const name = (row._name || "").trim();
            if (!name) {
                this.$message.warning(this.$t("faceManagement.form.nameRequired"));
                return;
            }
            if (row.status !== "draft_ready") {
                this.$message.warning(this.$t("faceManagement.enrollmentNotReady"));
                return;
            }
            this.$confirm(
                this.$t("faceManagement.activateConfirm"),
                this.$t("faceManagement.confirmEnable"),
                {
                    confirmButtonText: this.$t("faceManagement.confirmEnable"),
                    cancelButtonText: this.$t("faceManagement.cancel"),
                    type: "warning",
                }
            )
                .then(() => {
                    row._saving = true;
                    Api.face.confirmEnrollment(row.session_id, name, (res) => {
                        row._saving = false;
                        if (res && res.code === 0) {
                            this.$message.success(
                                this.$t("faceManagement.activateSuccess")
                            );
                            this.loadEnrollmentDrafts();
                            this.loadFaces();
                        } else {
                            this.$message.error(
                                (res && res.msg) ||
                                    this.$t("faceManagement.activateFail")
                            );
                        }
                    });
                })
                .catch(() => {});
        },

        discardEnrollment(row) {
            this.$confirm(
                this.$t("faceManagement.discardConfirm"),
                this.$t("faceManagement.discardDraft"),
                {
                    confirmButtonText: this.$t("faceManagement.discardDraft"),
                    cancelButtonText: this.$t("faceManagement.cancel"),
                    type: "warning",
                }
            )
                .then(() => {
                    row._saving = true;
                    Api.face.discardEnrollment(row.session_id, (res) => {
                        row._saving = false;
                        if (res && (res.code === 0 || (res.data && res.data.status === "ok"))) {
                            this.$message.success(
                                this.$t("faceManagement.discardSuccess")
                            );
                            this.loadEnrollmentDrafts();
                        } else {
                            this.$message.error(
                                (res && res.msg) ||
                                    this.$t("faceManagement.discardFail")
                            );
                        }
                    });
                })
                .catch(() => {});
        },

        loadFaces() {
            this.loading = true;
            Api.face.listProfiles(true, (res) => {
                this.loading = false;
                if (res && res.code === 0) {
                    const payload = res.data || {};
                    const list = payload.profiles || payload.faces || [];
                    this.faceList = Array.isArray(list) ? list : [];
                } else if (res && Array.isArray(res.profiles)) {
                    this.faceList = res.profiles;
                } else {
                    this.$message.error(
                        (res && res.msg) || this.$t("faceManagement.loadFail")
                    );
                }
            });
        },

        openCreateDialog() {
            this.resetDialog();
            this.dialogMode = "create";
            this.dialogVisible = true;
        },

        openDraftDialog(row) {
            this.resetDialog();
            this.dialogMode = "upload";
            this.form.userId = row.user_id;
            this.form.displayName = row.display_name;
            this.form.faceCount = row.face_count || 0;
            this.form.status = row.status;
            this.dialogVisible = true;
        },

        resetDialog() {
            this.clearPreviews();
            this.pendingFiles = [];
            this.form = {
                userId: "",
                displayName: "",
                faceCount: 0,
                status: "draft",
            };
            this.saving = false;
            if (this.$refs.fileInput) {
                this.$refs.fileInput.value = "";
            }
        },

        clearPreviews() {
            this.previews.forEach((p) => {
                if (p.url) URL.revokeObjectURL(p.url);
            });
            this.previews = [];
        },

        onFilesSelected(e) {
            const files = Array.from((e.target && e.target.files) || []);
            this.clearPreviews();
            this.pendingFiles = files;
            this.previews = files.map((f) => ({
                name: f.name,
                url: URL.createObjectURL(f),
            }));
        },

        createDraft() {
            const name = (this.form.displayName || "").trim();
            if (!name) {
                this.$message.warning(this.$t("faceManagement.form.nameRequired"));
                return;
            }
            this.saving = true;
            Api.face.createProfile(name, (res) => {
                this.saving = false;
                if (res && res.code === 0 && res.data) {
                    this.form.userId = res.data.user_id;
                    this.form.displayName = res.data.display_name;
                    this.form.faceCount = res.data.face_count || 0;
                    this.form.status = res.data.status;
                    this.$message.success(this.$t("faceManagement.createDraftSuccess"));
                    this.loadFaces();
                    if (this.pendingFiles.length) {
                        this.uploadPending();
                    }
                } else {
                    this.$message.error(
                        (res && res.msg) || this.$t("faceManagement.createFail")
                    );
                }
            });
        },

        uploadPending() {
            if (!this.form.userId || !this.pendingFiles.length) return;
            this.saving = true;
            const files = [...this.pendingFiles];
            let idx = 0;
            const next = () => {
                if (idx >= files.length) {
                    this.saving = false;
                    this.pendingFiles = [];
                    this.clearPreviews();
                    if (this.$refs.fileInput) this.$refs.fileInput.value = "";
                    this.$message.success(this.$t("faceManagement.uploadSuccess"));
                    this.loadFaces();
                    return;
                }
                const file = files[idx++];
                Api.face.uploadFace(this.form.userId, file, (res) => {
                    if (res && res.code === 0 && res.data) {
                        this.form.faceCount = res.data.face_count || this.form.faceCount + 1;
                        next();
                    } else {
                        this.saving = false;
                        this.$message.error(
                            (res && res.msg) || this.$t("faceManagement.uploadFail")
                        );
                        this.loadFaces();
                    }
                });
            };
            next();
        },

        activateCurrent() {
            if (!this.form.userId) return;
            this.$confirm(
                this.$t("faceManagement.activateConfirm"),
                this.$t("faceManagement.activateTitle"),
                {
                    confirmButtonText: this.$t("faceManagement.activate"),
                    cancelButtonText: this.$t("faceManagement.cancel"),
                    type: "warning",
                }
            )
                .then(() => {
                    this.saving = true;
                    Api.face.activateProfile(this.form.userId, (res) => {
                        this.saving = false;
                        if (res && res.code === 0) {
                            this.$message.success(
                                this.$t("faceManagement.activateSuccess")
                            );
                            this.dialogVisible = false;
                            this.loadFaces();
                        } else {
                            this.$message.error(
                                (res && res.msg) ||
                                    this.$t("faceManagement.activateFail")
                            );
                        }
                    });
                })
                .catch(() => {});
        },

        handleActivate(row) {
            this.form.userId = row.user_id;
            this.form.faceCount = row.face_count || 0;
            this.activateCurrent();
        },

        handleDelete(row) {
            const name = row.display_name;
            const isActive = row.status === "active";
            const message = isActive
                ? this.$t("faceManagement.deleteActiveConfirm", { name })
                : this.$t("faceManagement.deleteConfirm", { name });
            this.$confirm(message, this.$t("faceManagement.deleteTitle"), {
                confirmButtonText: this.$t("faceManagement.confirmDelete"),
                cancelButtonText: this.$t("faceManagement.cancel"),
                type: "warning",
            })
                .then(() => {
                    Api.face.deleteProfile(row.user_id, (res) => {
                        if (res && (res.code === 0 || res.status === "ok")) {
                            this.$message.success(
                                this.$t("faceManagement.deleteSuccess")
                            );
                            this.loadFaces();
                        } else {
                            this.$message.error(
                                (res && res.msg) ||
                                    this.$t("faceManagement.deleteFail")
                            );
                        }
                    });
                })
                .catch(() => {});
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

.hint-banner {
    margin: 0 0 12px;
    color: #606266;
    font-size: 13px;
}

.main-wrapper {
    padding: 16px 32px 32px;
}

.content-panel {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    overflow: hidden;
    margin-bottom: 16px;
}

.draft-panel {
    border: 1px solid #e8eef5;
}

.content-area {
    padding: 24px;
}

.section-title {
    margin: 0 0 6px;
    font-size: 16px;
    font-weight: 600;
    color: #1a1a2e;
}

.section-hint {
    margin: 0 0 16px;
    font-size: 12px;
    color: #909399;
}

.draft-preview {
    width: 56px;
    height: 56px;
    object-fit: cover;
    border-radius: 6px;
}

.muted {
    color: #c0c4cc;
}

.face-name {
    font-size: 14px;
    color: #303133;
}

.btn-delete {
    color: #f56c6c;
}

.btn-delete:hover {
    color: #d9363e;
}

.form-tip {
    margin: 6px 0 0;
    font-size: 12px;
    color: #909399;
}

.preview-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 8px;
}

.preview-item {
    width: 72px;
    text-align: center;
    font-size: 11px;
    color: #606266;
}

.preview-item img {
    width: 72px;
    height: 72px;
    object-fit: cover;
    border-radius: 6px;
    display: block;
    margin-bottom: 4px;
}
</style>
