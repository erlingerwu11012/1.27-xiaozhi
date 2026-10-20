import 'normalize.css/normalize.css'; // A modern alternative to CSS resets
import Vue from 'vue';
import ElementUI from 'element-ui';
import App from './App.vue';
import router from './router';
import store from './store';
import i18n from './i18n';
// Element UI 主题按设计规范从源码编译，必须在全局样式之前引入
import './styles/element-variables.scss';
import './styles/global.scss';
import { register as registerServiceWorker } from './registerServiceWorker';

// 创建事件总线，用于组件间通信
Vue.prototype.$eventBus = new Vue();

Vue.use(ElementUI);

// 改版共用组件：图标、页面标题区、空状态 / 失败状态、演示数据标记
import XnIcon from './components/common/XnIcon.vue';
import PageHeader from './components/common/PageHeader.vue';
import XnEmpty from './components/common/XnEmpty.vue';
import DemoTag from './components/common/DemoTag.vue';
Vue.component('XnIcon', XnIcon);
Vue.component('PageHeader', PageHeader);
Vue.component('XnEmpty', XnEmpty);
Vue.component('DemoTag', DemoTag);

// 所有 MessageBox 默认带圆角；删除类确认自动套用阿里云删除样式
const rawConfirm = Vue.prototype.$confirm.bind(Vue.prototype);
Vue.prototype.$confirm = function confirmRounded(message, title, options) {
  let opts = options;
  let msg = message;
  let ttl = title;
  if (typeof title === "object" && title !== null && options === undefined) {
    opts = title;
    ttl = "";
  }
  opts = Object.assign({}, opts || {});
  const blob = `${msg || ""} ${ttl || ""} ${opts.confirmButtonText || ""}`;
  const isDelete = /删除|delete/i.test(blob);
  const classes = ["ot-msg-box"];
  if (opts.customClass) classes.push(opts.customClass);
  if (isDelete) {
    classes.push("ot-delete-confirm");
    if (!opts.confirmButtonText) opts.confirmButtonText = "删除";
    if (!opts.cancelButtonText) opts.cancelButtonText = "取消";
    if (!opts.confirmButtonClass) opts.confirmButtonClass = "ot-delete-confirm__danger";
    if (!opts.cancelButtonClass) opts.cancelButtonClass = "ot-delete-confirm__cancel";
  }
  opts.customClass = classes.filter(Boolean).join(" ");
  return rawConfirm(msg, ttl, opts);
};

Vue.config.productionTip = false

// 注册Service Worker
registerServiceWorker();

// 创建Vue实例
new Vue({
  router,
  store,
  i18n,
  render: function (h) { return h(App) }
}).$mount('#app')
