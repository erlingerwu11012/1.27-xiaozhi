// Chromium regression: synthetic credentials only; login requests are intercepted.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const args=process.argv.slice(2),offline=args.includes('--candidate');
const root=path.resolve('build/login_account_guard_20261002/dist');
const output=path.resolve('build/login_account_guard_20261002',offline?'candidate-check.json':'published-check.json');
const mime={'.html':'text/html','.js':'application/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml','.jpg':'image/jpeg','.woff2':'font/woff2','.ico':'image/x-icon'};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const b=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const result={passed:false,mode:offline?'candidate':'public',real_login_attempts:0,domains:[]};
 try {
 for(const host of ['https://realecho.cn','https://www.realecho.cn']) {
  const c=await b.newContext({serviceWorkers:'block'}),p=await c.newPage(),errors=[],submitted=[];
  p.on('pageerror',e=>errors.push(e.message));
  if(offline) await p.route(host+'/**',async r=>{
   const u=new URL(r.request().url()),rel=u.pathname==='/'?'index.html':decodeURIComponent(u.pathname.slice(1));
   const file=path.resolve(root,rel);
   if(!file.startsWith(root+path.sep)&&file!==path.join(root,'index.html'))return r.abort();
   if(!fs.existsSync(file))return r.fulfill({status:404,body:'missing fixture'});
   return r.fulfill({status:200,contentType:mime[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)});
  });
  const configReply=await c.request.get('https://api.realecho.cn/xiaozhi/user/pub-config');
  assert(configReply.ok());const publicConfig=await configReply.json();assert.equal(publicConfig.code,0);
  publicConfig.data.allowUserRegister=true;publicConfig.data.enableMobileRegister=true;
  let release;const delay=new Promise(r=>release=r);
  await p.route('**/user/pub-config',async r=>{await delay;await r.fulfill({json:publicConfig});});
  await p.route('**/user/login',async r=>{
   assert.equal(new URL(r.request().url()).origin,'https://api.realecho.cn');
   const payload=r.request().postDataJSON();submitted.push({username:payload.username,hasPassword:!!payload.password});
   await r.fulfill({json:{code:10067,msg:'Synthetic regression: login intercepted'}});
  });
  await p.goto(host+'/#/login',{waitUntil:'domcontentloaded'});
  await p.locator('button.btn-login').waitFor();assert.equal(await p.locator('#username').count(),0);
  await p.locator('button.btn-login').click();
  const user=p.locator('#username'),pass=p.locator('#password'),captcha=p.getByPlaceholder('请输入验证码');
  await user.waitFor();assert(await user.evaluate(e=>e.readOnly));assert(await pass.evaluate(e=>e.readOnly));
  await user.click();await user.fill('zcs478455026');await pass.click();await pass.fill('SyntheticOnly123');
  await captcha.fill('ABCDE');assert.equal(await user.inputValue(),'zcs478455026');
  release();await sleep(350);assert.equal(await user.inputValue(),'zcs478455026');
  assert.equal(await p.getByPlaceholder('请输入用户名').count(),1);
  const checks=['hidden_login_fields_absent','focus_allows_typing','delayed_config_keeps_login_mode'];
  // Model an external delayed fill, with input/change events, after captcha gained focus.
  await p.evaluate(()=>{
   for(const [id,value] of [['username','478455026@qq.com'],['password','WrongPairSynthetic']]) {
    const e=document.getElementById(id);e.value=value;
    e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));
   }
  });
  await sleep(300);assert.equal(await user.inputValue(),'zcs478455026');assert.equal(await pass.inputValue(),'SyntheticOnly123');
  checks.push('inactive_delayed_autofill_pair_rejected');
  await user.click();await user.evaluate(e=>{e.value='478455026@qq.com'});
  await sleep(300);assert.equal(await user.inputValue(),'zcs478455026');checks.push('focused_silent_fill_restored');
  await user.fill('different-account');assert.equal(await user.inputValue(),'different-account');
  await user.fill('zcs478455026');checks.push('intentional_account_edit_allowed');
  await user.dispatchEvent('compositionstart');
  await user.evaluate(e=>{e.value='输入中';e.dispatchEvent(new Event('input',{bubbles:true}))});
  await sleep(300);assert.equal(await user.inputValue(),'输入中');
  await user.dispatchEvent('compositionend');await user.dispatchEvent('input');
  await user.fill('zcs478455026');checks.push('ime_composition_preserved');
  await captcha.click();await p.locator('.captcha-img-box').click();
  await sleep(500);assert.equal(await user.inputValue(),'zcs478455026');checks.push('captcha_refresh_preserves_account');
  await p.locator('form a').filter({hasText:'新用户注册'}).click();
  await p.locator('#register-username').waitFor();assert.equal(await p.locator('#username').count(),0);
  await p.locator('form a').filter({hasText:'已有账号'}).click();
  await user.waitFor();assert.equal(await user.inputValue(),'zcs478455026');checks.push('register_login_components_isolated');
  await pass.click();await pass.fill('SyntheticOnly123');await captcha.fill('ABCDE');
  await p.locator('form').getByRole('button',{name:'登录',exact:true}).click();
  await p.waitForFunction(()=>!!document.querySelector('.el-message'));
  assert(submitted.length>=1&&submitted.every(x=>x.username==='zcs478455026'&&x.hasPassword));
  checks.push('submitted_account_matches_selection');
  assert.equal(errors.length,0,errors.join('\n'));
  const keys=await p.evaluate(()=>Object.keys(localStorage));assert(!keys.some(k=>/password|credential/i.test(k)));
  checks.push('credentials_not_persisted','no_page_errors');
  await p.locator('.close-btn').click();assert.equal(await p.locator('#username').count(),0);
  checks.push('close_removes_fields_and_stops_guard');
  result.domains.push({host,checks,submitted,errors});await c.close();
 }
 result.passed=true;fs.writeFileSync(output,JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }catch(e){result.error=e.stack;fs.writeFileSync(output,JSON.stringify(result,null,2));throw e;}
 finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
