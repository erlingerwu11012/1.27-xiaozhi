<template>
  <el-dialog :visible="visible" :title="title" :close-on-click-modal="false" @update:visible="handleVisibleChange"
    width="820px" append-to-body custom-class="xn-provider-dialog" @close="handleClose">
    <el-form :model="form" :rules="rules" ref="form" label-position="top" @submit.native.prevent>
      <div class="pv-grid">
        <el-form-item :label="$t('providerDialog.category')" prop="modelType">
          <el-select v-model="form.modelType" :placeholder="$t('providerDialog.selectCategory')" style="width: 100%;">
            <el-option v-for="item in modelTypes" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('providerDialog.code')" prop="providerCode">
          <el-input v-model="form.providerCode" class="pv-code" :placeholder="$t('providerDialog.inputCode')" />
        </el-form-item>
        <el-form-item :label="$t('providerDialog.name')" prop="name">
          <el-input v-model="form.name" :placeholder="$t('providerDialog.inputName')" />
        </el-form-item>
        <el-form-item :label="$t('providerDialog.sort')" prop="sort">
          <el-input-number v-model="form.sort" :min="0" controls-position="right" style="width: 100%;" />
        </el-form-item>
      </div>

      <div class="pv-fields-head">
        <div>
          <h3 class="pv-fields-title">{{ $t('providerDialog.fieldConfig') }}</h3>
          <p class="pv-fields-help">{{ $t('xn.admin.provider.fieldsHelp') }}</p>
        </div>
        <div class="pv-fields-actions">
          <el-button v-if="selectedFieldCount" type="danger" plain size="small" @click="batchRemoveFields">
            <xn-icon name="trash" /> {{ $t('xn.admin.provider.deleteFields', { n: selectedFieldCount }) }}
          </el-button>
          <el-button size="small" @click="addField" :disabled="hasIncompleteFields"><xn-icon name="plus" /> {{ $t('xn.admin.provider.addField') }}</el-button>
        </div>
      </div>

      <div class="pv-fields">
        <el-table :data="form.fields" size="small" :key="tableKey">
          <el-table-column width="44" align="center">
            <template slot="header" slot-scope="{}">
              <el-checkbox :value="isAllFieldsSelected" :disabled="!(form.fields && form.fields.length)"
                :aria-label="$t('providerDialog.selectAll')" @change="toggleSelectAllFields" />
            </template>
            <template slot-scope="scope">
              <el-checkbox v-model="scope.row.selected" @change="handleFieldSelectChange"></el-checkbox>
            </template>
          </el-table-column>
          <el-table-column :label="$t('providerDialog.fieldKey')" min-width="140">
            <template slot-scope="scope">
              <el-input v-if="scope.row.editing" v-model="scope.row.key" size="small" class="pv-code" :placeholder="$t('providerDialog.fieldKey')" />
              <span v-else class="pv-mono">{{ scope.row.key }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('providerDialog.fieldLabel')" min-width="140">
            <template slot-scope="scope">
              <el-input v-if="scope.row.editing" v-model="scope.row.label" size="small" :placeholder="$t('providerDialog.fieldLabel')" />
              <span v-else>{{ scope.row.label }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('providerDialog.fieldType')" width="130">
            <template slot-scope="scope">
              <el-select v-if="scope.row.editing" v-model="scope.row.type" size="small" :placeholder="$t('providerDialog.type')">
                <el-option :label="$t('providerDialog.stringType')" value="string"></el-option>
                <el-option :label="$t('providerDialog.numberType')" value="number"></el-option>
                <el-option :label="$t('providerDialog.booleanType')" value="boolean"></el-option>
                <el-option :label="$t('providerDialog.dictType')" value="dict"></el-option>
                <el-option :label="$t('providerDialog.arrayType')" value="array"></el-option>
                <el-option :label="$t('providerDialog.ragType')" value="RAG"></el-option>
              </el-select>
              <span v-else>{{ getTypeLabel(scope.row.type) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('providerDialog.defaultValue')" min-width="140">
            <template slot-scope="scope">
              <el-input v-if="scope.row.editing" v-model="scope.row.default" size="small" :placeholder="$t('providerDialog.inputDefaultValue')" />
              <span v-else class="pv-mono xn-muted">{{ scope.row.default }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('providerDialog.operation')" width="110" align="right">
            <template slot-scope="scope">
              <el-button v-if="!scope.row.editing" type="text" @click="startEditing(scope.row)">{{ $t('providerDialog.edit') }}</el-button>
              <el-button v-else type="text" @click="stopEditing(scope.row)">{{ $t('providerDialog.complete') }}</el-button>
              <el-button type="text" class="pv-danger" @click="removeField(scope.$index)">{{ $t('providerDialog.delete') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <p class="pv-empty">{{ $t('xn.admin.provider.noFields') }}</p>
          </template>
        </el-table>
      </div>
    </el-form>

    <span slot="footer">
      <el-button @click="handleClose">{{ $t('xn.common.cancel') }}</el-button>
      <el-button type="primary" @click="submit" :loading="saving">{{ $t('providerDialog.save') }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
export default {
  props: {
    title: String,
    visible: Boolean,
    form: Object,
    modelTypes: Array
  },
  data() {
    return {
      saving: false,
      isAllFieldsSelected: false,
      tableKey: 0 // 用于强制表格重新渲染
    };
  },
  computed: {
    selectedFieldCount() {
      return (this.form.fields || []).filter((f) => f.selected).length;
    },
    rules() {
      return {
        modelType: [{ required: true, message: this.$t('providerDialog.requiredCategory'), trigger: 'change' }],
        providerCode: [{ required: true, message: this.$t('providerDialog.requiredCode'), trigger: 'blur' }],
        name: [{ required: true, message: this.$t('providerDialog.requiredName'), trigger: 'blur' }]
      };
    },
    hasIncompleteFields() {
      return this.form.fields && this.form.fields.some(field =>
        !field.key || !field.label || !field.type
      );
    }
  },
  methods: {
    getTypeLabel(type) {
      const typeMap = {
        'string': this.$t('providerDialog.stringType'),
        'number': this.$t('providerDialog.numberType'),
        'boolean': this.$t('providerDialog.booleanType'),
        'dict': this.$t('providerDialog.dictType'),
        'array': this.$t('providerDialog.arrayType'),
        'RAG': this.$t('providerDialog.ragType')
      };
      return typeMap[type];
    },

    startEditing(row) {
      this.$set(row, 'editing', true);
    },

    stopEditing(row) {
      this.$set(row, 'editing', false);

      const index = this.form.fields.indexOf(row);
      if (index > -1) {
        this.form.fields.splice(index, 1);
        this.form.fields.push(row);
        this.forceTableRerender();
      }
    },

    handleFieldSelectChange() {
      this.isAllFieldsSelected = this.form.fields.length > 0 &&
        this.form.fields.every(field => field.selected);
    },

    toggleSelectAllFields() {
      this.isAllFieldsSelected = !this.isAllFieldsSelected;
      this.form.fields = this.form.fields.map(field => ({
        ...field,
        selected: this.isAllFieldsSelected
      }));
    },

    handleVisibleChange(val) {
      this.$emit('update:visible', val);
      if (!val) {
        this.resetForm();
      }
    },

    handleClose() {
      this.resetForm();
      this.$emit('update:visible', false);
      this.$emit('cancel');
    },

    addField() {
      if (this.hasIncompleteFields) {
        this.$message.warning({
          message: this.$t('providerDialog.completeFieldEdit'),
          showClose: true
        });
        return;
      }

      this.form.fields.unshift({
        key: '',
        label: '',
        type: 'string',
        default: '',
        selected: false,
        editing: true
      });
      this.forceTableRerender();
    },

    removeField(index) {
      this.$confirm(this.$t('providerDialog.confirmDeleteField'), this.$t('common.warning'), {
        confirmButtonText: this.$t('common.confirm'),
        cancelButtonText: this.$t('common.cancel'),
        type: 'warning'
      }).then(() => {
        this.form.fields = this.form.fields.filter((_, i) => i !== index);
        this.updateSelectAllStatus();
        this.forceTableRerender();
        this.$message.success({
            message: this.$t('common.deleteSuccess'),
            showClose: true
          });
      }).catch(() => {
          this.$message.info({
            message: this.$t('common.deleteCancelled'),
            showClose: true
          });
        });
    },

    batchRemoveFields() {
      const selectedFields = this.form.fields.filter(field => field.selected);
      if (selectedFields.length === 0) {
        this.$message.warning({
          message: this.$t('providerDialog.selectFieldsToDelete'),
          showClose: true
        });
        return;
      }
      this.$confirm(this.$t('providerDialog.confirmBatchDeleteFields', { count: selectedFields.length }), this.$t('common.warning'), {
        confirmButtonText: this.$t('common.confirm'),
        cancelButtonText: this.$t('common.cancel'),
        type: 'warning'
      }).then(() => {
        this.form.fields = this.form.fields.filter(field => !field.selected);
        this.isAllFieldsSelected = false;
        this.forceTableRerender();
        this.$message.success({
            message: this.$t('providerDialog.batchDeleteFieldsSuccess', { count: selectedFields.length }),
            showClose: true
          });
      }).catch(() => {
        this.$message.info({
          message: this.$t('common.deleteCancelled'),
          showClose: true
        });
      });
    },

    updateSelectAllStatus() {
      this.isAllFieldsSelected = this.form.fields.length > 0 &&
        this.form.fields.every(field => field.selected);
    },

    forceTableRerender() {
      this.tableKey += 1; // 改变key值强制表格重新渲染
    },

    submit() {
      this.$refs.form.validate(valid => {
        if (valid) {
          const editingField = this.form.fields.find(field => field.editing);
          if (editingField) {
          this.$message.warning({
            message: this.$t('providerDialog.completeFieldEdit'),
            showClose: true
          });
          return;
        }

          this.form.fields = this.form.fields.map(field => ({
            ...field,
            selected: false
          }));
          this.isAllFieldsSelected = false;

          this.saving = true;
          this.$emit('submit', {
            form: this.form,
            done: () => {
              this.saving = false;
              this.resetForm();
            }
          });
        }
      });
    },

    resetForm() {
      this.$refs.form.resetFields();
      if (this.form.fields) {
        this.form.fields.forEach(field => {
          field.selected = false;
          field.editing = false;
        });
      }
      this.isAllFieldsSelected = false;
      this.forceTableRerender();
    },

  },
  watch: {
    visible(val) {
      if (!val) {
        this.resetForm();
      }
    }
  }
};
</script>

<style scoped>
.el-form--label-top ::v-deep .el-form-item__label { padding: 0 0 6px; line-height: 1.5; }
.pv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.pv-code ::v-deep .el-input__inner, .pv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
.pv-fields-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin: 4px 0 10px; padding-top: 14px; border-top: 1px solid var(--xn-line-2); }
.pv-fields-title { margin: 0; font-size: 16px; font-weight: 600; color: var(--xn-ink); }
.pv-fields-help { margin: 4px 0 0; font-size: 13px; color: var(--xn-ink-3); }
.pv-fields-actions { display: flex; gap: 8px; }
.pv-fields-actions .el-button + .el-button { margin-left: 0; }
.pv-fields { border: 1px solid var(--xn-line); border-radius: var(--xn-r); overflow: hidden; }
.pv-fields ::v-deep .el-table::before { display: none; }
.pv-danger { color: var(--xn-danger); }
.pv-danger:hover, .pv-danger:focus { color: #8D3523; }
.pv-empty { margin: 0; padding: 20px 0; font-size: 13px; color: var(--xn-ink-3); }
@media (max-width: 640px) { .pv-grid { grid-template-columns: 1fr; } }
</style>
