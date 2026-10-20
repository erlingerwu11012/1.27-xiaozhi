<template>
    <el-dialog :title="title" :visible.sync="dialogVisible" width="480px" append-to-body :close-on-click-modal="false" @close="handleClose">
        <el-form :model="form" :rules="rules" ref="form" label-position="top" @submit.native.prevent>
            <el-form-item :label="$t('dictDataDialog.dictLabel')" prop="dictLabel">
                <el-input v-model="form.dictLabel" maxlength="64" :placeholder="$t('dictDataDialog.dictLabelPlaceholder')"></el-input>
            </el-form-item>
            <el-form-item :label="$t('dictDataDialog.dictValue')" prop="dictValue">
                <el-input v-model="form.dictValue" maxlength="128" class="dd-code" :placeholder="$t('dictDataDialog.dictValuePlaceholder')"></el-input>
            </el-form-item>
            <el-form-item :label="$t('dictDataDialog.sort')" prop="sort">
                <el-input-number v-model="form.sort" :min="0" :max="999" controls-position="right" style="width: 160px;"></el-input-number>
                <p class="dd-hint">{{ $t('xn.admin.dict.sortHint') }}</p>
            </el-form-item>
        </el-form>
        <span slot="footer" class="dd-footer">
            <el-button @click="resetToInitial">{{ $t('xn.common.reset') }}</el-button>
            <span class="dd-grow"></span>
            <el-button @click="handleClose">{{ $t('button.cancel') }}</el-button>
            <el-button type="primary" @click="handleSave">{{ $t('button.save') }}</el-button>
        </span>
    </el-dialog>
</template>

<script>
export default {
    name: 'DictDataDialog',
    props: {
        visible: {
            type: Boolean,
            default: false
        },
        title: {
            type: String,
            default() { return this.$t('dictDataDialog.addDictData') }
        },
        dictData: {
            type: Object,
            default: () => ({})
        },
        dictTypeId: {
            type: [Number, String],
            default: null
        }
    },
    data() {
        return {
            dialogVisible: this.visible,
            form: {
                id: null,
                dictTypeId: null,
                dictLabel: '',
                dictValue: '',
                sort: 0
            },
            rules: {
                dictLabel: [{ required: true, message: this.$t('dictDataDialog.requiredDictLabel'), trigger: 'blur' }],
                dictValue: [{ required: true, message: this.$t('dictDataDialog.requiredDictValue'), trigger: 'blur' }]
            }
        }
    },
    watch: {
        dictData: {
            handler(val) {
                if (val) {
                    this.form = { ...val }
                }
            },
            immediate: true
        },
        dictTypeId: {
            handler(val) {
                if (val) {
                    this.form.dictTypeId = val
                }
            },
            immediate: true
        },
        visible(val) {
          this.dialogVisible = val;
          if (val) this.resetToInitial();
        },
        dialogVisible(val) {
          this.$emit('update:visible', val);
        }
    },
    methods: {
        handleClose() {
          this.dialogVisible = false;
          this.resetForm();
        },
        resetForm() {
            this.form = {
                id: null,
                dictTypeId: this.dictTypeId,
                dictLabel: '',
                dictValue: '',
                sort: 0
            }
            this.$refs.form?.resetFields()
        },
        // 恢复到打开弹窗时的内容
        resetToInitial() {
            this.form = { ...(this.dictData || {}) }
            if (!this.form.dictTypeId && this.dictTypeId) this.form.dictTypeId = this.dictTypeId
            this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate())
        },
        handleSave() {
            this.$refs.form.validate(valid => {
                if (valid) {
                    this.$emit('save', this.form)
                }
            })
        }
    }
}
</script>

<style scoped>
.dd-footer { display: flex; align-items: center; }
.dd-grow { flex: 1; }
.dd-code ::v-deep .el-input__inner { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.dd-hint { margin: 6px 0 0; font-size: 13px; line-height: 1.5; color: var(--xn-ink-3); }
</style>
