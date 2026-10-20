<template>
    <el-dialog :title="title" :visible.sync="dialogVisible" width="480px" append-to-body :close-on-click-modal="false" @close="handleClose">
        <el-form :model="form" :rules="rules" ref="form" label-position="top" @submit.native.prevent>
            <el-form-item :label="$t('dictTypeDialog.dictName')" prop="dictName">
                <el-input v-model="form.dictName" maxlength="64" :placeholder="$t('dictTypeDialog.dictNamePlaceholder')"></el-input>
            </el-form-item>
            <el-form-item :label="$t('dictTypeDialog.dictType')" prop="dictType">
                <el-input v-model="form.dictType" maxlength="64" class="dt-code" :placeholder="$t('dictTypeDialog.dictTypePlaceholder')"></el-input>
                <p v-if="form.id" class="dt-hint">{{ $t('xn.admin.dict.typeCodeHint') }}</p>
            </el-form-item>
        </el-form>
        <span slot="footer" class="dt-footer">
            <el-button @click="resetToInitial">{{ $t('xn.common.reset') }}</el-button>
            <span class="dt-grow"></span>
            <el-button @click="handleClose">{{ $t('button.cancel') }}</el-button>
            <el-button type="primary" @click="handleSave">{{ $t('button.save') }}</el-button>
        </span>
    </el-dialog>
</template>

<script>
export default {
    name: 'DictTypeDialog',
    props: {
        visible: {
            type: Boolean,
            default: false
        },
        title: {
            type: String,
            default() { return this.$t('dictTypeDialog.addDictType') }
        },
        dictTypeData: {
            type: Object,
            default: () => ({})
        }
    },
    data() {
        return {
            dialogVisible: this.visible,
            form: {
                id: null,
                dictName: '',
                dictType: ''
            },
            rules: {
                dictName: [{ required: true, message: this.$t('dictTypeDialog.requiredDictName'), trigger: 'blur' }],
                dictType: [{ required: true, message: this.$t('dictTypeDialog.requiredDictType'), trigger: 'blur' }]
            }
        }
    },
    watch: {
        visible(val) {
          this.dialogVisible = val;
          if (val) this.form = { ...(this.dictTypeData || {}) };
        },
        dialogVisible(val) {
          this.$emit('update:visible', val);
        },
        dictTypeData: {
            handler(val) {
                if (val) {
                    this.form = { ...val }
                }
            },
            immediate: true
        }
    },
    methods: {
        handleClose() {
            this.dialogVisible = false;
            this.resetForm()
        },
        resetForm() {
            this.form = {
                id: null,
                dictName: '',
                dictType: ''
            }
            this.$refs.form?.resetFields()
        },
        // 恢复到打开弹窗时的内容
        resetToInitial() {
            this.form = { ...(this.dictTypeData || {}) }
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
.dt-footer { display: flex; align-items: center; }
.dt-grow { flex: 1; }
.dt-code ::v-deep .el-input__inner { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.dt-hint { margin: 6px 0 0; font-size: 13px; line-height: 1.5; color: var(--xn-ink-3); }
</style>
