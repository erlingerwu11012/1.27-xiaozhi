<script>
/* 线性图标：24 网格，1.7 描边，圆头。用法：<xn-icon name="device" />，尺寸随字号（1em）或 size 属性。 */
const P = {
  agent: '<circle cx="12" cy="8.5" r="3.6"/><path d="M4.5 20c1.3-3.7 4.1-5.6 7.5-5.6s6.2 1.9 7.5 5.6"/>',
  device: '<rect x="4.5" y="3.5" width="15" height="12.5" rx="2.5"/><path d="M9 20h6M12 16v4"/>',
  people: '<circle cx="9" cy="9" r="3.2"/><path d="M3.5 19c1-3 3-4.5 5.5-4.5s4.5 1.5 5.5 4.5"/><path d="M15.5 6.2a3 3 0 0 1 0 5.6M17 14.6c1.8.6 3 2 3.5 4.4"/>',
  role: '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="12" cy="10.5" r="3"/><path d="M7.5 17.5c1-2 2.6-3 4.5-3s3.5 1 4.5 3"/>',
  image: '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M3.5 15l4.5-4 4 3.5 3-2.5 5.5 4.5"/><circle cx="15.5" cy="9" r="1.4"/>',
  voice: '<path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 11v2"/>',
  mic: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  book: '<path d="M5 4.5h9.5a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h9.5"/>',
  wallet: '<rect x="3.5" y="6" width="17" height="13" rx="2.5"/><path d="M3.5 10h17M16 14.5h1.5"/>',
  receipt: '<path d="M6 3.5h12v17l-3-2-3 2-3-2-3 2z"/><path d="M9 8.5h6M9 12h6"/>',
  users: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/>',
  chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 9.5h5v5h-5zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
  plug: '<path d="M9 3v5M15 3v5M6.5 8h11v3a5.5 5.5 0 0 1-11 0zM12 16.5V21"/>',
  template: '<rect x="4" y="4" width="16" height="16" rx="2.5"/><path d="M4 9h16M9 9v11"/>',
  memory: '<path d="M12 4a6 6 0 0 0-6 6c0 2.4 1.3 3.8 2.5 4.8V18h7v-3.2c1.2-1 2.5-2.4 2.5-4.8a6 6 0 0 0-6-6z"/><path d="M10 21h4"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4L18 18M6 18l1.6-1.6M16.4 7.6L18 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  list: '<path d="M8.5 6.5H20M8.5 12H20M8.5 17.5H20M4 6.5h.01M4 12h.01M4 17.5h.01"/>',
  trash: '<path d="M5 7h14M10 7V4.8h4V7M7 7l.8 12.2h8.4L17 7"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
  chevronDown: '<path d="M6 9l6 6 6-6"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  logout: '<path d="M14 4.5h4a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5h-4M10 16l-4-4 4-4M6 12h10"/>',
  lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.5 3.5 5.3 3.5 8.5s-1.1 6-3.5 8.5c-2.4-2.5-3.5-5.3-3.5-8.5S9.6 6 12 3.5z"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.2"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4.5M12 17.2v.2"/>',
  edit: '<path d="M14.5 5.5l4 4L9 19H5v-4z"/><path d="M12.5 7.5l4 4"/>',
  chat: '<path d="M5 5.5h14A1.5 1.5 0 0 1 20.5 7v8.5A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5V7A1.5 1.5 0 0 1 5 5.5z"/>',
  tune: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/>',
  download: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
  upload: '<path d="M12 15V4M7.5 8.5L12 4l4.5 4.5M5 19.5h14"/>',
  link: '<path d="M10 14l4-4M8.5 16.5l-1 1a3.5 3.5 0 0 1-5-5l3-3a3.5 3.5 0 0 1 5 0M15.5 7.5l1-1a3.5 3.5 0 0 1 5 5l-3 3a3.5 3.5 0 0 1-5 0"/>',
  dots: '<circle cx="6" cy="12" r="1.1"/><circle cx="12" cy="12" r="1.1"/><circle cx="18" cy="12" r="1.1"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l2.5 2.5"/>',
  wifi: '<path d="M4 9.5a12 12 0 0 1 16 0M7 12.8a7.5 7.5 0 0 1 10 0M10 16a3 3 0 0 1 4 0M12 19.2v.1"/>',
  flask: '<path d="M9.5 3.5h5M10.5 3.5v5.5l-5 9a1.5 1.5 0 0 0 1.3 2.2h10.4a1.5 1.5 0 0 0 1.3-2.2l-5-9V3.5"/><path d="M7.5 15h9"/>',
};

export default {
  name: 'XnIcon',
  functional: true,
  props: { name: { type: String, required: true }, size: { type: [Number, String], default: null } },
  render(h, { props, data }) {
    const s = props.size ? (typeof props.size === 'number' ? props.size + 'px' : props.size) : '1em';
    return h('svg', {
      ...data,
      class: ['xn-icon', data.staticClass, data.class],
      attrs: { viewBox: '0 0 24 24', width: s, height: s, 'aria-hidden': 'true', focusable: 'false', ...(data.attrs || {}) },
      domProps: { innerHTML: P[props.name] || '' },
    });
  },
};
</script>

<style>
.xn-icon { flex: none; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; vertical-align: -0.15em; }
</style>
