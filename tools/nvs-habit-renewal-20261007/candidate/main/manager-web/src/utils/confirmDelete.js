/**
 * 阿里云风格删除确认框。
 * @param {Vue} vm
 * @param {{ title?: string, message?: string }} [opts]
 * @returns {Promise}
 */
export function confirmDelete(vm, opts = {}) {
  const title = opts.title || "你确认删除该资产吗？";
  const message = opts.message || "资产删除后无法找回，请谨慎操作。";
  return vm.$confirm(message, title, {
    confirmButtonText: "删除",
    cancelButtonText: "取消",
    customClass: "ot-msg-box ot-delete-confirm",
    confirmButtonClass: "ot-delete-confirm__danger",
    cancelButtonClass: "ot-delete-confirm__cancel",
    showClose: true,
    closeOnClickModal: false,
    type: "",
  });
}

export default confirmDelete;
