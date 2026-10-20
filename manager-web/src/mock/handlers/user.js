/**
 * 账号与登录（/user/*）。
 * - 图形验证码只存在内存里；登录密文用本次页面加载时生成的 SM2 临时密钥解密，用来核对图形验证码。
 * - 不保存任何密码：演示账号输入任意非空密码即可登录；注册、改密、找回密码只校验格式，不落库。
 * - 演示短信验证码固定为 000000，不会真实发送短信。
 */
import { sm2 } from 'sm-crypto';
import { route, ok, fail, blob, requireAdmin } from '../core';
import { captchaBlob } from '../media';

const keys = sm2.generateKeyPairHex();       // 仅内存，刷新即换，不写入任何存储
const captchas = new Map();                    // captchaId → code
export const DEMO_SMS_CODE = '000000';

function decrypt(cipher) {
  if (!cipher) return '';
  try {
    const hex = String(cipher).replace(/^04/, '');
    return sm2.doDecrypt(hex, keys.privateKey, 1) || '';
  } catch (e) {
    return '';
  }
}

/** 校验“图形验证码 + 密码”密文；返回去掉验证码后的密码，校验失败返回 null 与错误信息 */
function checkCaptchaCipher(captchaId, cipher) {
  const code = captchas.get(captchaId);
  if (!code) return { error: '图形验证码已过期，请刷新后重试' };
  captchas.delete(captchaId);
  const plain = decrypt(cipher);
  if (!plain || plain.slice(0, code.length).toLowerCase() !== code.toLowerCase()) {
    return { error: '图形验证码错误' };
  }
  return { password: plain.slice(code.length) };
}

function publicUser(u) {
  return { id: u.id, username: u.username, superAdmin: u.superAdmin, status: u.status, mobile: u.mobile || '' };
}

route('GET', '/user/captcha', ({ query }) => {
  const alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  let code = '';
  for (let i = 0; i < 4; i++) code += alphabet[Math.floor(Math.random() * alphabet.length)];
  captchas.set(query.uuid, code);
  // 仅 mock 构建：供自动化检查读取最近一次演示验证码（real 构建不包含 src/mock）
  if (typeof window !== 'undefined') (window.__xnMock = window.__xnMock || {}).lastCaptcha = code;
  return blob(captchaBlob(code));
});

route('GET', '/user/pub-config', ({ db }) => ok({
  name: '小念',
  version: '演示版（Mock）',
  year: String(new Date().getFullYear()),
  beianIcpNum: 'null',   // 与原 store 默认值一致：字符串 'null' 表示没有备案号，页脚不显示
  beianGaNum: 'null',
  allowUserRegister: true,
  enableMobileRegister: true,
  mobileAreaList: db.dictByType.MOBILE_AREA,
  sm2PublicKey: keys.publicKey,
}));

route('POST', '/user/login', ({ body, db }) => {
  const check = checkCaptchaCipher(body.captchaId, body.password);
  if (check.error) return fail(check.error);
  const user = db.users.find((u) => u.username === body.username);
  if (!user || !check.password) return fail('用户名或密码错误（演示环境请使用登录页提示的演示账号）');
  if (user.status !== 1) return fail('该账号已被禁用（演示）');
  const token = `mock-${user.username}-${Math.random().toString(36).slice(2, 10)}`;
  db.sessions[token] = { userId: user.id, createdAt: Date.now() };
  return ok({ token, expire: 43200, clientHash: '' });
});

route('POST', '/user/smsVerification', ({ body }) => {
  if (!/^\+?\d{6,15}$/.test(String(body.phone || ''))) return fail('请输入正确的手机号码');
  return ok(null, `演示环境未发送短信，验证码为 ${DEMO_SMS_CODE}`);
});

route('POST', '/user/register', ({ body, db }) => {
  const check = checkCaptchaCipher(body.captchaId, body.password);
  if (check.error) return fail(check.error);
  if (!body.username) return fail('请输入用户名');
  if (db.users.some((u) => u.username === body.username)) return fail('用户名已存在');
  if (body.mobileCaptcha && body.mobileCaptcha !== DEMO_SMS_CODE) return fail('手机验证码错误（演示验证码为 000000）');
  const isMobile = /^\+\d+/.test(body.username);
  db.users.push({
    id: `demo-u-${Date.now()}`, username: body.username, superAdmin: 0, status: 1,
    mobile: isMobile ? body.username : '', createDate: new Date().toISOString().slice(0, 19).replace('T', ' '), deviceCount: 0,
  });
  return ok(null, '注册成功（演示账号，仅保存在本机浏览器）');
});

route('PUT', '/user/retrieve-password', ({ body, db }) => {
  const check = checkCaptchaCipher(body.captchaId, body.password);
  if (check.error) return fail(check.error);
  if (!db.users.some((u) => u.mobile && u.mobile === body.phone)) return fail('该手机号未注册（演示）');
  if (body.code !== DEMO_SMS_CODE) return fail('短信验证码错误（演示验证码为 000000）');
  return ok(null, '密码已重置（演示：未保存任何密码）');
});

route('GET', '/user/info', ({ user }) => ok(publicUser(user)));

route('PUT', '/user/change-password', ({ body }) => {
  if (!body.password || !body.newPassword) return fail('请填写原密码和新密码');
  return ok(null, '密码已修改（演示：未保存任何密码）');
});

route('PUT', '/user/configDevice/:deviceId', () => ok(null));

/** 管理员批量修改账号状态：body 为用户 id 数组 */
route('PUT', '/admin/users/changeStatus/:status', ({ params, body, db, user }) => {
  const denied = requireAdmin(user); if (denied) return denied;
  const ids = Array.isArray(body) ? body.map(String) : [];
  db.users.forEach((u) => { if (ids.includes(String(u.id)) && u.id !== user.id) u.status = Number(params.status); });
  return ok(null);
});
