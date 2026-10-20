"""小念控制台改版：Playwright 公共助手（登录、收集控制台错误）。"""
from playwright.sync_api import sync_playwright
BASE = 'http://localhost:8001/#'
CHROMIUM = '/opt/pw-browsers/chromium'
ARGS = ['--disable-background-networking', '--disable-component-update', '--no-default-browser-check', '--disable-sync']

def launch(p):
    return p.chromium.launch(executable_path=CHROMIUM, args=ARGS)

def new_page(browser, w=1440, h=900, scale=1, logs=None):
    ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=scale, locale='zh-CN')
    pg = ctx.new_page()
    if logs is not None:
        pg.on('console', lambda m: logs.append(f'{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        pg.on('pageerror', lambda e: logs.append(f'pageerror: {e}'))
        pg.on('request', lambda r: logs.append(f'NETWORK: {r.method} {r.url}') if not r.url.startswith(('http://localhost:8001', 'data:', 'blob:')) else None)
    return pg

def login(pg, username='demo_user'):
    pg.goto(BASE + '/login')
    pg.wait_for_selector('.auth-form', timeout=20000)
    pg.wait_for_timeout(600)
    if pg.locator('.auth-tab', has_text='用户名').count() and not pg.is_visible('#username'):
        pg.click('.auth-tab >> text=用户名')
        pg.wait_for_timeout(900)   # 切换方式会重新获取验证码
    pg.wait_for_selector('#username', timeout=10000)
    pg.wait_for_function('window.__xnMock && window.__xnMock.lastCaptcha', timeout=20000)
    pg.fill('#username', username)
    pg.fill('#password', 'any-demo-password')
    code = pg.evaluate('window.__xnMock.lastCaptcha')
    pg.fill('.auth-captcha input', code)
    pg.click('.auth-submit')
    pg.wait_for_function("location.hash.indexOf('#/home') === 0", timeout=20000)
    pg.wait_for_timeout(1200)
