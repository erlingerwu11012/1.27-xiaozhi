const fs = require('fs'), path = require('path'), http = require('http'), assert = require('assert'), vm = require('vm');
const { chromium } = require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root = path.join(__dirname, 'dist');
const server = http.createServer((req, res) => {
  const file = path.resolve(root, '.' + decodeURIComponent(req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  const type = { '.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.png':'image/png', '.svg':'image/svg+xml' }[path.extname(file)];
  fs.readFile(file, (err, data) => { if (err) res.writeHead(404).end(); else { res.setHeader('Content-Type', type || 'application/octet-stream'); res.end(data); } });
});
function checkWallpaper() {
  let calls = 0, timer = null, next = null;
  const source = fs.readFileSync(path.join(__dirname, 'WallpaperPackCatalog.vue'), 'utf8').split('<script>')[1].split('</script>')[0].replace(/^import .*$/mg, '').replace('export default', 'component =');
  const box = { component:null, HeaderBar:{}, Api:{wallpaperPack:{getTask(id, cb){ calls++; cb(next); }}}, userApi:{}, wallpaperPackApi:{}, translateOtaState:(_,s)=>s, resolveOtaApiMessage:(_,r)=>r.errorCode, formatOtaFileSize(){}, formatOtaFieldLine(){}, setTimeout:f=>{timer=f;return 1;}, clearTimeout:()=>{timer=null;} };
  vm.runInNewContext(source, box);
  const component = box.component, state = {...component.data(), $t:k=>k};
  Object.entries(component.methods).forEach(([k,v])=>state[k]=v.bind(state));
  state.readyVisible=true; state.deployTask={taskId:'test', state:'pending', progress:0};
  next={code:0,data:{taskId:'test',state:'downloading',progress:47}};
  state.pollDeployTask('test'); assert.equal(component.computed.taskProgress.call(state),47); assert(timer);
  state.stopTaskPolling(); next={code:0,data:{taskId:'test',state:'failed',progress:0,errorCode:'E_BUSY'}};
  state.pollDeployTask('test'); assert(component.computed.taskError.call(state).includes('E_BUSY')); assert.equal(component.computed.taskProgressStatus.call(state),'exception'); assert.equal(timer,null);
  state.deployTask={taskId:'test',state:'downloading'}; next={code:0,data:{taskId:'test',state:'completed',progress:100}};
  state.pollDeployTask('test'); assert.equal(component.computed.taskProgressStatus.call(state),'success'); assert.equal(timer,null);
  state.readyVisible=false; state.pollDeployTask('test'); assert.equal(calls,3);
  return 'downloading progress, busy failure, completion, closed-dialog stop passed';
}
(async()=>{
  console.log('Wallpaper:',checkWallpaper());
  await new Promise(r=>server.listen(18111,'127.0.0.1',r));
  const browser=await chromium.launch({headless:true, executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const context=await browser.newContext({serviceWorkers:'block'}), page=await context.newPage();
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    let submissions=0;
    await page.route('**/user/login', async route=>{
      submissions++;
      const body=route.request().postDataJSON();
      assert.equal(body.username,'autofill@example.invalid'); assert.equal(typeof body.password,'string'); assert(body.password.length>64); assert.notEqual(body.password,'SyntheticAutofill456');
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({code:1,msg:'Synthetic validation only'})});
    });
    await page.goto((process.env.TEST_BASE_URL || 'http://127.0.0.1:18111')+'/#/login');
    await page.locator('button.btn-login').click();
    const username=page.locator('#username'), password=page.locator('#password');
    assert.equal(await username.getAttribute('autocomplete'),'username'); assert.equal(await password.getAttribute('autocomplete'),'current-password');
    await username.fill('synthetic@example.invalid'); await password.fill('SyntheticOnly123');
    await page.getByPlaceholder('请输入验证码').fill('0000'); await page.waitForTimeout(600);
    assert.equal(await username.inputValue(),'synthetic@example.invalid'); assert.equal(await password.inputValue(),'SyntheticOnly123');
    const eye=page.locator('.el-input__icon.el-icon-view');
    await eye.click(); assert.equal(await password.getAttribute('type'),'text'); assert.equal(await password.inputValue(),'SyntheticOnly123');
    await eye.click(); assert.equal(await password.getAttribute('type'),'password');
    await page.evaluate(()=>{ document.querySelector('#username').value='autofill@example.invalid'; document.querySelector('#password').value='SyntheticAutofill456'; });
    await eye.click(); assert.equal(await password.getAttribute('type'),'text');
    assert.equal(await password.evaluate(el=>el.closest('.el-input').__vue__.value),'SyntheticAutofill456');
    await page.locator('form').getByRole('button',{name:'登录',exact:true}).click(); await page.waitForTimeout(700);
    assert.equal(submissions,1); assert.deepEqual(errors,[]);
    console.log('Login: autocomplete attributes, blur persistence, eye toggle, silent DOM autofill submission, single request passed');
  } finally { await browser.close(); server.close(); }
})().catch(e=>{ console.error(e); server.close(); process.exitCode=1; });
