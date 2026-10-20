/**
 * 数据模式开关（构建期读取环境变量）。
 *
 *   VUE_APP_DATA_MODE=mock   默认。所有业务请求由 src/mock 在浏览器内应答，不发出任何网络请求。
 *   VUE_APP_DATA_MODE=real   走原有 RequestService → flyio → VUE_APP_API_BASE_URL。
 *
 * 只有明确写成小写 real 才会访问真实服务；拼写错误、留空都按 mock 处理，避免误连线上。
 */
export const DATA_MODE = process.env.VUE_APP_DATA_MODE === 'real' ? 'real' : 'mock';

export function isMockMode() {
  return DATA_MODE === 'mock';
}

/** 演示数据统一的标记文字，界面与数据里都用它，避免与真实账号数据混淆 */
export const MOCK_LABEL = '演示数据';

/** localStorage 键：只保存演示数据与演示场景，不保存密码、密钥或真实账号信息 */
export const MOCK_STORAGE_KEYS = {
  db: 'xn-mock-db-v1',
  scenario: 'xn-mock-scenario-v1',
};
