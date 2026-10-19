#!/usr/bin/env node
/**
 * Lightweight OTA i18n integrity check (no browser).
 * Verifies $t() references exist in zh_CN.js and en.js for OTA namespaces.
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const LOCALES = {
  zh_CN: path.join(SRC, 'i18n', 'zh_CN.js'),
  en: path.join(SRC, 'i18n', 'en.js'),
}

const OTA_PREFIXES = ['rolePack.', 'wallpaperPack.', 'visualOta.', 'deviceAssets.', 'header.rolePack', 'header.wallpaperPack']
const KNOWN_SCREENSHOT_KEYS = [
  'wallpaperPack.coverImage',
  'wallpaperPack.imageHint',
  'wallpaperPack.demoVideo',
  'wallpaperPack.videoHint',
]

function readKeys(filePath) {
  const content = fs.readFileSync(filePath, 'utf8')
  const keys = new Set()
  const re = /'([^']+)'\s*:/g
  let m
  while ((m = re.exec(content)) !== null) {
    keys.add(m[1])
  }
  return keys
}

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name)
    const stat = fs.statSync(full)
    if (stat.isDirectory()) {
      if (name !== 'node_modules') walk(full, out)
    } else if (/\.(vue|js)$/.test(name)) {
      out.push(full)
    }
  }
  return out
}

function collectTKeys(filePath) {
  const content = fs.readFileSync(filePath, 'utf8')
  const keys = new Set()
  const patterns = [
    /\$t\(\s*['"]([^'"]+)['"]/g,
    /i18n\.t\(\s*['"]([^'"]+)['"]/g,
  ]
  for (const re of patterns) {
    let m
    while ((m = re.exec(content)) !== null) {
      keys.add(m[1])
    }
  }
  return keys
}

function isOtaKey(key) {
  return OTA_PREFIXES.some((p) => key === p || key.startsWith(p))
}

function main() {
  const zhKeys = readKeys(LOCALES.zh_CN)
  const enKeys = readKeys(LOCALES.en)
  const files = walk(SRC)
  const used = new Map()

  for (const file of files) {
    if (file.includes(`${path.sep}i18n${path.sep}`)) continue
    for (const key of collectTKeys(file)) {
      if (!isOtaKey(key)) continue
      if (!used.has(key)) used.set(key, [])
      used.get(key).push(path.relative(ROOT, file))
    }
  }

  let failed = false
  const report = []

  for (const [key, refs] of [...used.entries()].sort()) {
    const missingZh = !zhKeys.has(key)
    const missingEn = !enKeys.has(key)
    if (missingZh || missingEn) {
      failed = true
      report.push({ key, refs, missingZh, missingEn })
    }
  }

  for (const prefix of ['rolePack.', 'wallpaperPack.', 'visualOta.']) {
    const zhNs = [...zhKeys].filter((k) => k.startsWith(prefix))
    const enNs = [...enKeys].filter((k) => k.startsWith(prefix))
    const zhSet = new Set(zhNs)
    const enSet = new Set(enNs)
    for (const k of zhNs) {
      if (!enSet.has(k)) {
        failed = true
        report.push({ key: k, refs: ['namespace symmetry'], missingZh: false, missingEn: true, symmetry: true })
      }
    }
    for (const k of enNs) {
      if (!zhSet.has(k)) {
        failed = true
        report.push({ key: k, refs: ['namespace symmetry'], missingZh: true, missingEn: false, symmetry: true })
      }
    }
  }

  for (const key of KNOWN_SCREENSHOT_KEYS) {
    if (!zhKeys.has(key) || !enKeys.has(key)) {
      failed = true
      report.push({ key, refs: ['screenshot regression'], missingZh: !zhKeys.has(key), missingEn: !enKeys.has(key) })
    }
  }

  if (report.length) {
    console.error('OTA i18n check FAILED:\n')
    for (const row of report) {
      const loc = row.missingZh ? 'zh_CN' : row.missingEn ? 'en' : '?'
      console.error(`  - ${row.key} (missing in ${loc})`)
      if (row.refs && !row.symmetry) console.error(`      used in: ${row.refs.join(', ')}`)
    }
    process.exit(1)
  }

  console.log(`OTA i18n check OK (${used.size} OTA $t keys, namespaces symmetric)`)
  process.exit(0)
}

main()
