/**
 * Shared i18n helpers for Spine / Wallpaper visual OTA pages.
 * Maps backend error codes and task states to user-readable messages.
 */

const ERROR_CODE_RE = /^E_[A-Z0-9_]+$/

/** @param {import('vue').default} vm */
export function resolveOtaApiMessage(vm, res, fallbackKey) {
  if (!res || res.code === 0) return ''
  const code = normalizeErrorCode(res)
  if (code && vm.$te(`visualOta.error.${code}`)) {
    return vm.$t(`visualOta.error.${code}`)
  }
  return vm.$t(fallbackKey)
}

function normalizeErrorCode(res) {
  const direct = (res.errorCode || res.error_code || '').trim()
  if (direct && ERROR_CODE_RE.test(direct)) return direct
  const msg = typeof res.msg === 'string' ? res.msg.trim() : ''
  if (ERROR_CODE_RE.test(msg)) return msg
  return ''
}

/** @param {import('vue').default} vm */
export function translateOtaState(vm, state) {
  if (!state) return '-'
  const key = `visualOta.state.${state}`
  return vm.$te(key) ? vm.$t(key) : state
}

/** @param {import('vue').default} vm */
export function formatOtaFileSize(vm, n) {
  if (!n && n !== 0) return '-'
  if (n < 1024) return `${n}${vm.$t('visualOta.sizeUnitB')}`
  if (n < 1024 * 1024) {
    return `${(n / 1024).toFixed(1)}${vm.$t('visualOta.sizeUnitKiB')}`
  }
  return `${(n / 1024 / 1024).toFixed(2)}${vm.$t('visualOta.sizeUnitMiB')}`
}

/** @param {import('vue').default} vm */
export function formatOtaFieldLine(vm, labelKey, value) {
  const label = vm.$t(labelKey)
  const sep = vm.$t('visualOta.valueSeparator')
  const display = value === null || value === undefined || value === '' ? '-' : value
  return `${label}${sep} ${display}`
}
