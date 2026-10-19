"""Automated QA for the static prototype: JS errors, horizontal overflow, and every interaction.
usage: python3 tools/check.py [outdir]   (run from the prototype folder; needs playwright + Chromium)"""
import os, sys, json
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'screenshots')
os.makedirs(OUT, exist_ok=True)
URL = 'file://' + os.path.join(ROOT, 'index.html')
results, errors = [], []

def check(name, cond, detail=''):
    results.append((name, bool(cond), detail)); print(('PASS ' if cond else 'FAIL ') + name + (f' — {detail}' if detail and not cond else ''))

def overflow(pg):
    return pg.evaluate("""() => {
      const w = document.documentElement.clientWidth, bad = [];
      if (document.documentElement.scrollWidth > w + 1) bad.push('page scrollWidth ' + document.documentElement.scrollWidth + ' > ' + w);
      for (const el of document.querySelectorAll('body *')) {
        const r = el.getBoundingClientRect(); if (!r.width || getComputedStyle(el).position === 'fixed') continue;
        if (el.closest('.table-wrap, .side:not(.is-open), .drawer, .modal-wrap, .toasts')) continue;
        if (r.right > w + 1) bad.push((el.className || el.tagName) + ' right=' + Math.round(r.right));
      }
      // text that is clipped without an intentional ellipsis
      for (const el of document.querySelectorAll('button, .btn, .nav__item, .seg, label, h1, h2, h3, .page-sub')) {
        const cs = getComputedStyle(el);
        if (el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== 'ellipsis' && cs.overflow !== 'visible') bad.push('clipped: ' + el.textContent.trim().slice(0, 24));
      }
      return bad.slice(0, 10);
    }""")

with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    for vw, vh, tag in [(1440, 900, 'desktop'), (1280, 800, 'laptop'), (390, 844, 'mobile')]:
        pg = b.new_page(viewport={'width': vw, 'height': vh}, device_scale_factor=2 if tag == 'desktop' else 1)
        pg.on('console', lambda m: errors.append(f'{tag} console.{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        pg.on('pageerror', lambda e: errors.append(f'{tag} pageerror: {e}'))
        pg.goto(URL); pg.evaluate('document.fonts.ready'); pg.wait_for_timeout(300)
        check(f'[{tag}] fonts loaded', pg.evaluate("document.fonts.check('600 18px \"XN Serif\"') && document.fonts.check('14px \"XN Sans\"')"))
        o = overflow(pg); check(f'[{tag}] no overflow on home (card view)', not o, '; '.join(o))
        pg.screenshot(path=f'{OUT}/{tag}-home.png', full_page=(tag != 'desktop'))
        if tag != 'desktop':
            if tag == 'mobile':
                pg.click('#menuBtn'); pg.wait_for_timeout(250)
                check('[mobile] nav drawer opens', pg.evaluate("document.querySelector('#side').classList.contains('is-open')"))
                pg.screenshot(path=f'{OUT}/mobile-nav.png'); pg.keyboard.press('Escape'); pg.wait_for_timeout(250)
            pg.close(); continue

        # ---- desktop interaction tests ----
        n = lambda: pg.locator('.agent').count()
        check('4 demo agents rendered', n() == 4, str(n()))
        pg.fill('#q', 'A4:CF:12:3B:91'); check('search by device MAC finds owning agent', n() == 1 and '小念' in pg.inner_text('.agent'))
        check('matched MAC highlighted', pg.locator('.agent mark').count() >= 1)
        pg.fill('#q', '不存在的名字'); check('no-result empty state', pg.locator('.empty').count() == 1)
        pg.click('[data-action=resetFilter]'); check('reset filter restores list', n() == 4)
        pg.click('[data-filter=bound]'); check('filter bound → 2 agents', n() == 2)
        pg.click('[data-filter=unbound]'); check('filter unbound → 2 agents', n() == 2)
        pg.click('[data-filter=all]')
        pg.click('[data-view=list]'); check('list view renders table rows', pg.locator('table.list tbody tr').count() == 4)
        o = overflow(pg); check('no overflow in list view', not o, '; '.join(o))
        pg.screenshot(path=f'{OUT}/desktop-home-list.png')
        pg.click('[data-view=card]')
        # chat history disabled when memory off
        pg.click('.agent:has-text("学习搭子") [data-action=chat]', force=True); pg.wait_for_timeout(100)
        check('chat history disabled for Memory_nomem (toast, no modal)', pg.locator('#modalWrap').is_hidden() and '开启记忆' in pg.inner_text('#toasts'))
        # persona config drawer
        pg.click('.agent:has-text("小念") [data-action=config]'); pg.wait_for_timeout(300)
        check('config drawer opens', pg.locator('#drawer').is_visible())
        o = overflow(pg); check('no overflow with drawer open', not o, '; '.join(o))
        pg.screenshot(path=f'{OUT}/desktop-config-panel.png')
        pg.click('[data-preset=listener]'); check('preset fills role intro', '温和体贴' in pg.input_value('#f-prompt'))
        pg.fill('#f-name', ''); pg.click('[data-action=saveConfig]'); check('empty name blocked with error', pg.locator('#e-name').is_visible())
        pg.fill('#f-name', '小念 Pro'); pg.select_option('#f-mem', 'Memory_nomem'); pg.click('[data-action=saveConfig]'); pg.wait_for_timeout(150)
        check('save updates card + closes drawer', pg.locator('#drawer').is_hidden() and pg.locator('.agent:has-text("小念 Pro")').count() == 1)
        check('memory off now disables chat on that card', pg.get_attribute('.agent:has-text("小念 Pro") [data-action=chat]', 'aria-disabled') == 'true')
        pg.click('.agent:has-text("小念 Pro") [data-action=config]'); pg.keyboard.press('Escape'); pg.wait_for_timeout(100)
        check('Escape closes drawer', pg.locator('#drawer').is_hidden())
        # add device: validation + success
        pg.click('.page-head [data-action=addDevice]'); check('add-device modal opens', pg.locator('#modalWrap').is_visible())
        pg.fill('#m-code', '12ab'); check('code input keeps digits only', pg.input_value('#m-code') == '12')
        pg.click('[data-action=confirmBind]'); check('short code rejected', pg.locator('#m-err').is_visible())
        pg.screenshot(path=f'{OUT}/desktop-add-device.png')
        pg.select_option('#m-agent', 'demo-a3'); pg.fill('#m-code', '123456'); pg.click('[data-action=confirmBind]'); pg.wait_for_timeout(100)
        check('bind adds device to chosen agent', '已绑定' in pg.inner_text('.agent:has-text("学习搭子")'))
        pg.click('.page-head [data-action=addDevice]'); pg.click('[data-tab=manual]')
        pg.select_option('#m-board', index=1); pg.fill('#m-fw', '1.6.2'); pg.fill('#m-mac', 'zz'); pg.click('[data-action=confirmManual]')
        check('manual add rejects bad MAC', 'Mac 地址格式不正确' in pg.inner_text('#m-err'))
        pg.fill('#m-mac', 'a4-cf-00-11-22-33'); pg.click('[data-action=confirmManual]'); pg.wait_for_timeout(100)
        check('manual add succeeds', pg.locator('#modalWrap').is_hidden())
        # add agent
        pg.click('.page-head [data-action=addAgent]'); pg.click('[data-action=confirmAgent]'); check('add agent requires name', pg.locator('#m-err').is_visible())
        pg.fill('#m-name', '新伙伴'); pg.click('[data-action=confirmAgent]'); pg.wait_for_timeout(100)
        check('new agent appears first', '新伙伴' in pg.locator('.agent').first.inner_text())
        # delete agent
        pg.click('.agent:has-text("新伙伴") [data-action=deleteAgent]'); pg.click('[data-action=doDeleteAgent]'); pg.wait_for_timeout(100)
        check('delete agent removes card', pg.locator('.agent:has-text("新伙伴")').count() == 0)
        # devices page
        pg.click('.agent:has-text("小念 Pro") [data-action=agentDevices]'); pg.wait_for_timeout(100)
        exp = pg.evaluate("__proto.S.agents.find(a => a.agentName === '小念 Pro').devices.length")
        check('device page filtered to agent', pg.locator('table.list tbody tr').count() == exp, f'expected {exp}')
        o = overflow(pg); check('no overflow on device page', not o, '; '.join(o))
        pg.screenshot(path=f'{OUT}/desktop-devices.png')
        pg.fill('.remark-input >> nth=0', '新的备注'); pg.keyboard.press('Tab'); check('remark change acknowledged', '备注已保存' in pg.inner_text('#toasts'))
        pg.click('[data-action=unbind] >> nth=0'); pg.click('[data-action=doUnbind]'); pg.wait_for_timeout(100)
        check('unbind removes row', pg.locator('table.list tbody tr').count() == exp - 1)
        pg.click('[data-action=assets] >> nth=0'); check('visual-assets placeholder opens', pg.locator('#modalWrap').is_visible()); pg.keyboard.press('Escape')
        # roles
        check('user: no admin group in nav', pg.locator('.nav__group--admin').count() == 0)
        check('user: no memory/user-admin entries', pg.locator('#nav >> text=记忆管理').count() == 0 and pg.locator('#nav >> text=用户管理').count() == 0)
        pg.click('[data-role=admin]'); check('admin: admin group shown', pg.locator('.nav__group--admin').count() == 1)
        pg.click('[data-sub=mem]'); pg.click('#nav >> text=记忆管理'); check('admin opens memory placeholder', '记忆管理' in pg.inner_text('.page-title'))
        pg.screenshot(path=f'{OUT}/desktop-admin-nav.png')
        pg.click('[data-role=user]'); check('switching to user leaves admin page', pg.inner_text('.page-title') == '我的智能体')
        # placeholder pages + user menu
        for key in ['people', 'rolePack', 'wallpaper', 'tts', 'knowledge', 'billing', 'orders']:
            pg.click(f'#nav [data-go={key}]'); ok = pg.locator('.placeholder').count() == 1
            o = overflow(pg); check(f'placeholder page {key}', ok and not o, '; '.join(o))
        pg.click('#userChip'); check('user menu opens', pg.locator('#userMenu').is_visible())
        pg.click('#userMenu [data-placeholder=logout]'); check('logout is placeholder (no real logout)', pg.locator('#modalWrap').is_visible()); pg.keyboard.press('Escape')
        # keyboard focus visible
        pg.click('#nav [data-go=home]'); pg.keyboard.press('Tab')
        check('keyboard focus ring present', pg.evaluate("getComputedStyle(document.activeElement).boxShadow !== 'none'"))
        pg.close()
    b.close()

check('no JS errors / warnings', not errors, ' | '.join(errors))
passed = sum(1 for r in results if r[1])
json.dump({'passed': passed, 'total': len(results), 'results': [{'check': n, 'pass': ok, 'detail': d} for n, ok, d in results], 'console': errors},
          open(os.path.join(OUT, 'qc-report.json'), 'w'), ensure_ascii=False, indent=1)
print(f'\n{passed}/{len(results)} checks passed')
