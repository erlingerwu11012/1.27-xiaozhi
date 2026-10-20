"""核心交互检查：首页、添加设备、删除确认、设备管理、账户菜单、演示模式、英文界面。"""
import sys, json
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from xnqa import launch, new_page, login, BASE
from playwright.sync_api import sync_playwright
OUT = __file__.rsplit('/', 1)[0] + '/core/'
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond), detail)); print(('PASS ' if cond else 'FAIL ') + name, detail)

with sync_playwright() as p:
    b = launch(p); logs = []
    pg = new_page(b, logs=logs)
    # 先清空演示数据（含会话），保证从种子开始，再登录
    pg.goto(BASE + '/login'); pg.wait_for_timeout(500); pg.evaluate("localStorage.clear()")
    login(pg, 'demo_user'); pg.wait_for_selector('.ac', timeout=15000); pg.wait_for_timeout(800)
    n_all = pg.locator('.ac').count(); check('home cards render', n_all >= 3, f'{n_all} cards')
    stats = pg.inner_text('.home-stats'); check('stats show bound and online separately', '已绑定' in stats and '暂不可查' in stats, stats.replace('\n', ' '))
    check('no balance card on home', pg.locator('.home .xn-balance, .home [class*=balance]').count() == 0)
    check('no bind card on home', pg.locator('text=绑定新设备').count() == 0)
    # 搜索
    pg.fill('.home-search input', '晚安'); pg.wait_for_timeout(400)
    check('search by name', pg.locator('.ac').count() == 1)
    pg.fill('.home-search input', '02:00:5E'); pg.wait_for_timeout(400)
    check('search by MAC', pg.locator('.ac').count() >= 1, str(pg.locator('.ac').count()))
    pg.fill('.home-search input', 'zzz-no-such'); pg.wait_for_timeout(400)
    check('no-match state', pg.locator('text=没有符合条件的智能体').count() == 1)
    pg.click('button:has-text("清除筛选")'); pg.wait_for_timeout(400)
    check('clear filters restores', pg.locator('.ac').count() == n_all)
    # 筛选
    pg.click('.home-filter >> text=未绑定'); pg.wait_for_timeout(400)
    unb = pg.locator('.ac').count(); check('filter unbound', unb >= 1 and unb < n_all, str(unb))
    pg.click('.home-filter >> text=全部'); pg.wait_for_timeout(300)
    # 视图切换并记忆
    pg.click('.home-view__btn[aria-label="列表视图"]'); pg.wait_for_timeout(400)
    check('list view table', pg.locator('.home-table .el-table__row').count() == n_all)
    pg.reload(); pg.wait_for_timeout(2500)
    check('view preference persists', pg.locator('.home-table').count() == 1)
    pg.click('.home-view__btn[aria-label="卡片视图"]'); pg.wait_for_timeout(400)
    pg.screenshot(path=OUT + 'home.png')
    # 顶栏添加设备：验证码绑定
    before = pg.inner_text('.home-stats__bound')
    pg.click('.xn-top__add'); pg.wait_for_selector('.bd-cell', timeout=5000); pg.wait_for_timeout(500)
    tabs = pg.inner_text('.el-dialog__wrapper:visible')
    check('bind dialog has 3 modes', all(t in tabs for t in ['验证码', '恢复', '手动']), '')
    pg.screenshot(path=OUT + 'bind-dialog.png')
    pg.locator('.bd-cell').first.click(); pg.keyboard.type('000001')
    pg.locator('.el-dialog__wrapper:visible .el-dialog__footer .el-button--primary').click(); pg.wait_for_timeout(900)
    check('wrong code shows error', pg.locator('.el-message--error, .el-message--warning').count() >= 1)
    for i in range(6): pg.locator('.bd-cell').nth(i).fill('')
    pg.locator('.bd-cell').first.click(); pg.keyboard.type('246810')
    pg.locator('.el-dialog__wrapper:visible .el-dialog__footer .el-button--primary').click(); pg.wait_for_timeout(1500)
    after = pg.inner_text('.home-stats__bound')
    check('bind updates bound count', before != after, f'{before} -> {after}')
    # 手动添加：校验
    pg.click('.xn-top__add'); pg.wait_for_timeout(600)
    pg.locator('.el-dialog__wrapper:visible >> text=手动添加').first.click(); pg.wait_for_timeout(400)
    pg.locator('.el-dialog__wrapper:visible .el-dialog__footer .el-button--primary').click(); pg.wait_for_timeout(500)
    check('manual add validation', pg.locator('.el-dialog__wrapper:visible .el-form-item__error').count() >= 1)
    pg.keyboard.press('Escape'); pg.wait_for_timeout(600)
    # 删除智能体：取消、确认
    n0 = pg.locator('.ac').count()
    pg.locator('.ac').last.locator('.ac__del').click(); pg.wait_for_selector('.el-message-box', timeout=5000)
    pg.click('.el-message-box__btns button:first-child'); pg.wait_for_timeout(600)
    check('delete cancel keeps agent', pg.locator('.ac').count() == n0)
    pg.locator('.ac').last.locator('.ac__del').click(); pg.wait_for_selector('.el-message-box', timeout=5000)
    pg.click('.el-message-box__btns .el-button--primary'); pg.wait_for_timeout(1500)
    check('delete confirm removes agent', pg.locator('.ac').count() == n0 - 1)
    # 余额 → 充值页
    pg.click('.xn-balance'); pg.wait_for_timeout(1500)
    check('balance chip opens top-up', '/billing/packages' in pg.url)
    # 设备管理：解绑确认
    pg.goto(BASE + '/device-management?agentId=demo-a-1'); pg.wait_for_timeout(2000)
    rows = pg.locator('.el-table__body-wrapper .el-table__row').count()
    pg.locator('.el-table__row').first.locator('text=解绑').click(); pg.wait_for_selector('.el-message-box', timeout=5000)
    pg.click('.el-message-box__btns .el-button--primary'); pg.wait_for_timeout(1500)
    check('unbind removes row', pg.locator('.el-table__body-wrapper .el-table__row').count() == rows - 1, f'{rows} -> {pg.locator(".el-table__body-wrapper .el-table__row").count()}')
    pg.screenshot(path=OUT + 'devices.png')
    # 账户菜单：修改密码弹窗校验
    pg.click('.xn-account, .xn-top__account, .el-dropdown >> nth=-1'); pg.wait_for_timeout(500)
    pg.locator('.el-dropdown-menu:visible >> text=修改密码').click(); pg.wait_for_timeout(600)
    pg.locator('.el-dialog__wrapper:visible .el-dialog__footer .el-button--primary').click(); pg.wait_for_timeout(500)
    check('change password validation', pg.locator('.el-dialog__wrapper:visible .el-form-item__error').count() >= 1 or pg.locator('.el-message', has_text='请填写所有字段').count() >= 1)
    pg.keyboard.press('Escape'); pg.wait_for_timeout(500)
    # 演示模式：重置数据恢复智能体
    pg.goto(BASE + '/home'); pg.wait_for_timeout(1500)
    pg.click('.xn-mockbtn'); pg.wait_for_timeout(600)
    pg.screenshot(path=OUT + 'mock-panel.png')
    pg.locator('text=重置演示数据').last.click(); pg.wait_for_timeout(500)
    if pg.locator('.el-message-box').count(): pg.click('.el-message-box__btns .el-button--primary')
    pg.wait_for_timeout(3000)
    if '/login' in pg.url: login(pg, 'demo_user')
    pg.goto(BASE + '/home'); pg.wait_for_selector('.ac', timeout=15000); pg.wait_for_timeout(1000)
    check('reset restores seed data', pg.locator('.ac').count() == n_all, str(pg.locator('.ac').count()))
    # 英文界面
    pg.evaluate("localStorage.setItem('userLanguage','en')"); pg.reload(); pg.wait_for_timeout(2500)
    raw = pg.evaluate("() => (document.body.innerText.match(/\\bxn\\.[a-zA-Z.]+/g) || []).slice(0,5)")
    check('english home has no raw keys', not raw and 'My agents' in pg.inner_text('body'), str(raw))
    pg.screenshot(path=OUT + 'home-en.png')
    pg.evaluate("localStorage.setItem('userLanguage','zh_CN')")
    # 退出
    pg.reload(); pg.wait_for_timeout(1500)
    pg.click('.xn-account, .xn-top__account, .el-dropdown >> nth=-1'); pg.wait_for_timeout(500)
    pg.locator('.el-dropdown-menu:visible >> text=退出登录').click(); pg.wait_for_timeout(1500)
    if pg.locator('.el-message-box').count(): pg.click('.el-message-box__btns .el-button--primary'); pg.wait_for_timeout(1500)
    check('logout returns to login', '/login' in pg.url, pg.url)
    real = [l for l in logs if 'async-validator' not in l]   # Element 表单校验失败时的开发版提示，生产构建不输出
    check('no console errors / external requests', not real, str(real[:5]))
    b.close()
fails = [r for r in results if not r[1]]
print(json.dumps({'checks': len(results), 'failed': len(fails)}))
