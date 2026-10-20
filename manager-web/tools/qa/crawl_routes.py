"""改版 QA：以演示账号登录后逐个访问全部路由，检查控制台错误、外部网络请求、横向溢出与权限状态，并截图。

用法（先 npm run serve，或用任意静态服务器打开 mock 构建的 dist/）：
  pip install playwright==1.55.0 && python -m playwright install chromium   # 已装有 Chromium 时可用 CHROMIUM 指定路径
  python3 tools/qa/crawl_routes.py --base http://localhost:8001 --out qa-out
输出：qa-out/<身份>/<路由>.png 与 qa-out/report.json。只适用于 mock 构建（依赖演示账号与 window.__xnMock）。
"""
import argparse, json, os, re, sys
from playwright.sync_api import sync_playwright

USER_ROUTES = ['/home', '/role-config?agentId=demo-a-1', '/device-management', '/unified-user-management?agentId=demo-a-1',
               '/role-pack-catalog', '/wallpaper-pack-catalog', '/official-tts/voices', '/official-tts/dubbing',
               '/knowledge-base-management', '/billing/packages', '/billing/orders', '/billing/result']
ADMIN_ROUTES = ['/user-management', '/model-config', '/params-management', '/dict-management', '/provider-management',
                '/server-side-management', '/agent-template-management', '/template-quick-config', '/admin/official-tts',
                '/memory-management', '/memory-extract-config', '/habit-management', '/habit-analyze-config']
GUARDED = ['/habit-management', '/memory-management', '/memory-extract-config']   # 原路由守卫：非管理员跳回首页

def login(pg, base, username):
    pg.goto(base + '/#/login')
    pg.wait_for_selector('.auth-form', timeout=30000)
    pg.wait_for_timeout(700)
    if pg.locator('.auth-tab').count() and not pg.is_visible('#username'):
        pg.locator('.auth-tab').first.click()
        pg.wait_for_timeout(900)
    pg.wait_for_function('window.__xnMock && window.__xnMock.lastCaptcha', timeout=20000)
    pg.fill('#username', username)
    pg.fill('#password', 'demo-only')
    pg.fill('.auth-captcha input', pg.evaluate('window.__xnMock.lastCaptcha'))
    pg.click('.auth-submit')
    pg.wait_for_function("location.hash.indexOf('#/home') === 0", timeout=20000)
    pg.wait_for_timeout(1000)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://localhost:8001')
    ap.add_argument('--out', default='qa-out')
    ap.add_argument('--width', type=int, default=1440)
    ap.add_argument('--height', type=int, default=900)
    a = ap.parse_args()
    exe = os.environ.get('CHROMIUM')
    origin = re.match(r'https?://[^/]+', a.base).group(0)
    report = {'base': a.base, 'results': []}
    with sync_playwright() as p:
        b = p.chromium.launch(**({'executable_path': exe} if exe else {}), args=['--disable-background-networking', '--disable-component-update'])
        for who, routes in [('demo_user', USER_ROUTES + ADMIN_ROUTES), ('demo_admin', USER_ROUTES + ADMIN_ROUTES)]:
            ctx = b.new_context(viewport={'width': a.width, 'height': a.height}, locale='zh-CN')
            pg = ctx.new_page()
            events = []
            pg.on('console', lambda m: events.append(f'{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
            pg.on('pageerror', lambda e: events.append(f'pageerror: {e}'))
            pg.on('request', lambda r: events.append(f'external-request: {r.method} {r.url}') if not r.url.startswith((origin, 'data:', 'blob:')) else None)
            login(pg, a.base, who)
            os.makedirs(os.path.join(a.out, who), exist_ok=True)
            for route in routes:
                del events[:]
                pg.goto(a.base + '/#' + route)
                pg.wait_for_timeout(1800)
                state = pg.evaluate("""() => ({
                  hash: location.hash,
                  overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                  denied: !!Array.from(document.querySelectorAll('.xn-empty__title')).find(e => e.textContent.includes('没有访问权限')),
                  title: (document.querySelector('.xn-page-header__title') || {}).textContent || '',
                  oldHeader: !!document.querySelector('.header-container, .el-header .header'),
                })""")
                is_admin_route = route in ADMIN_ROUTES
                expect = 'page'
                if who == 'demo_user' and is_admin_route:
                    expect = 'redirect-home' if route in GUARDED else 'denied'
                ok_perm = (expect == 'page' and not state['denied']) or (expect == 'denied' and state['denied']) or (expect == 'redirect-home' and state['hash'].startswith('#/home'))
                shot = os.path.join(a.out, who, re.sub(r'[^a-zA-Z0-9]+', '_', route).strip('_') + '.png')
                pg.screenshot(path=shot)
                report['results'].append({'who': who, 'route': route, 'expect': expect, 'permission_ok': ok_perm,
                                          'overflow': state['overflow'], 'title': state['title'].strip(), 'old_header': state['oldHeader'],
                                          'events': list(events), 'screenshot': shot})
            ctx.close()
        b.close()
    bad = [r for r in report['results'] if r['events'] or r['overflow'] or not r['permission_ok'] or r['old_header']]
    report['summary'] = {'checked': len(report['results']), 'problems': len(bad)}
    with open(os.path.join(a.out, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report['summary'], ensure_ascii=False))
    for r in bad:
        print('-', r['who'], r['route'], 'perm_ok' if r['permission_ok'] else 'PERMISSION', 'OVERFLOW' if r['overflow'] else '', 'OLD_HEADER' if r['old_header'] else '', r['events'][:3])
    sys.exit(1 if bad else 0)

if __name__ == '__main__':
    main()
