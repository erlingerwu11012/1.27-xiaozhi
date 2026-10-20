#!/usr/bin/env node
/**
 * 检查 Mock 覆盖率：解析 src/apis/module/*.js 与组件里直接调用 RequestService 的 URL + 方法，
 * 再与 src/mock/handlers/*.js 里 route() 注册的接口比对，列出没有 mock 的接口。
 * 用法：npm run check:mock   （不联网，只读源码）
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SRC = path.join(ROOT, 'src');

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) { if (name !== 'node_modules' && name !== 'mock') walk(full, out); }
    else if (/\.(js|vue)$/.test(name)) out.push(full);
  }
  return out;
}

/** 把 URL 模板规整成路径模式：去掉 base 前缀与 query，${...} 变成 :p */
function normalize(url) {
  let u = url.replace(/\$\{\s*(getServiceUrl\(\)|PYTHON_API|Api\.getServiceUrl\(\)|api\.getServiceUrl\(\))\s*\}/g, '')
    .replace(/^getServiceUrl\(\)\s*\+\s*/, '');
  u = u.replace(/\$\{[^}]*\?[^}]*\}/g, ''); // ${query ? '?' + query : ''} 这类拼接查询串的写法
  u = u.split('?')[0];
  u = u.replace(/\$\{[^}]*\}/g, ':p').replace(/'\s*\+\s*[^+]+\+\s*'/g, ':p').replace(/'\s*\+\s*[A-Za-z_.()]+$/g, ':p');
  return u.replace(/\/+$/, '') || '/';
}

const calls = [];
for (const file of walk(SRC)) {
  const src = fs.readFileSync(file, 'utf8');
  // 1) RequestService 链式：.url(`...`) ... .method('X')
  const re = /\.url\(\s*([`'"])(.*?)\1\s*\)([\s\S]{0,400}?)\.method\(\s*['"](\w+)['"]/g;
  let m;
  while ((m = re.exec(src))) calls.push({ method: m[4].toUpperCase(), path: normalize(m[2]), file });
  // 2) knowledgeBase：makeApiRequest({ url: `...`, method: 'X' })
  const re2 = /url:\s*`([^`]*)`,\s*\n?\s*method:\s*'(\w+)'/g;
  while ((m = re2.exec(src))) calls.push({ method: m[2].toUpperCase(), path: normalize(m[1]), file });
  // 3) userIdentity：request('METHOD', '/path' + ...)
  const re3 = /request\(\s*'(GET|POST|PUT|DELETE)'\s*,\s*('[^']*'(?:\s*\+\s*[^,]+?)*)\s*,/g;
  while ((m = re3.exec(src))) {
    const p = m[2].replace(/'\s*\+\s*[^']+?\s*\+\s*'/g, ':p').replace(/'\s*\+\s*[^']+$/g, ':p').replace(/'/g, '');
    calls.push({ method: m[1], path: normalize(p), file });
  }
}

const routes = [];
const HANDLERS = path.join(SRC, 'mock', 'handlers');
const handlerSources = fs.readdirSync(HANDLERS).map((name) => fs.readFileSync(path.join(HANDLERS, name), 'utf8'));
// 同一组路由用 `${cfg.base}/...` 注册时（角色包 / 壁纸包共用 registerPackRoutes），按各文件声明的 base: '...' 展开
const bases = handlerSources.flatMap((src) => [...src.matchAll(/base:\s*'([^']+)'/g)].map((b) => b[1]));
for (const src of handlerSources) {
  const add = (method, p) => routes.push({ method: method.toUpperCase(), re: new RegExp('^' + p.replace(/:[A-Za-z_]\w*/g, '[^/]+') + '$') });
  const re = /route\(\s*'(\w+)'\s*,\s*(['`])([^'`]+)\2/g;
  let m;
  while ((m = re.exec(src))) {
    if (m[3].includes('${')) bases.forEach((b) => add(m[1], m[3].replace(/\$\{[^}]*\}/, b)));
    else add(m[1], m[3]);
  }
}

const seen = new Set();
const missing = [];
for (const c of calls) {
  const key = c.method + ' ' + c.path;
  if (seen.has(key)) continue;
  seen.add(key);
  const probe = c.path.replace(/:p/g, 'x');
  if (!routes.some((r) => r.method === c.method && r.re.test(probe))) missing.push(`${key}   (${path.relative(ROOT, c.file)})`);
}

console.log(`接口调用 ${seen.size} 个，mock 路由 ${routes.length} 条`);
if (missing.length) {
  console.log(`未覆盖 ${missing.length} 个：`);
  missing.forEach((x) => console.log('  - ' + x));
  process.exit(1);
}
console.log('Mock 覆盖检查通过：所有接口都有演示实现');
