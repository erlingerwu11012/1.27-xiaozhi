// Test only the built candidate with synthetic HTTP responses and a new browser.
const fs = require('fs');
const path = require('path');
const http = require('http');
const assert = require('assert');
const playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
fs.mkdirSync(output, { recursive: true });
const types = { '.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.png':'image/png', '.svg':'image/svg+xml', '.woff':'font/woff', '.ttf':'font/ttf' };
const server = http.createServer((req,res) => {
  const file = path.resolve(root, '.' + decodeURIComponent(new URL(req.url,'http://localhost').pathname));
  if (!file.startsWith(root+path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const browser=await playwright.chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE});
  try {
    const context=await browser.newContext({serviceWorkers:'block',viewport:{width:1440,height:1000}});
    await context.addInitScript(()=>{localStorage.setItem('token',JSON.stringify({token:'synthetic-test-only'}));localStorage.setItem('isSuperAdmin','false');});
    const users=[{userId:'usr_test_a',displayName:'爸爸',faceProfileIds:[],voiceprintIds:[]},{userId:'usr_test_b',displayName:'孩子',faceProfileIds:[],voiceprintIds:[]}];
    await context.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url()),pathname=url.pathname;
      if(pathname.includes('/xiaozhi/')) {
        let data={},code=0,msg='success';
        if(pathname.endsWith('/user-identities/users')) {
          if(request.method()==='POST') {const body=request.postDataJSON();assert.deepStrictEqual(Object.keys(body),['displayName']);if(users.some(user=>user.displayName===body.displayName)){code=400;msg='昵称已重复';}else users.push({userId:'usr_test_new',displayName:body.displayName,faceProfileIds:[],voiceprintIds:[]});}
          data=users;
        } else if(pathname.endsWith('/user-identities/voiceprints'))data=[];
        else if(pathname.endsWith('/agent/list'))data=[{id:'agent_test',agentName:'测试智能体'}];
        else if(pathname.includes('/agent/') && pathname.endsWith('/chat-history/user'))data=[];
        else if(pathname.includes('/face/profiles'))data={profiles:[]};
        else if(pathname.endsWith('/face/enrollment/sessions'))data={sessions:[]};
        else if(pathname.endsWith('/user/info'))data={username:'测试账号',superAdmin:0};
        else if(pathname.endsWith('/user/pub-config'))data={version:'测试候选',allowUserRegister:false};
        else if(pathname.endsWith('/pay/memory-bills'))data={available:true,total:1,list:[{createdAt:1790640000000,operation:'search',strategy:'lite',units:1,state:'settled',amountCny:'0.0000286',chargedPoints:'0.004'}]};
        else if(pathname.endsWith('/pay/orders'))data={list:[],total:0};
        else if(pathname.endsWith('/pay/quota') || pathname.endsWith('/pay/quota/me'))data={balance:123,balanceSource:'oneapi',balanceRealtime:true};
        else if(pathname.endsWith('/display-name')) {const id=decodeURIComponent(pathname.split('/').slice(-2)[0]);const user=users.find(user=>user.userId===id);user.displayName=request.postDataJSON().displayName;}
        else if(request.method()==='DELETE' && pathname.includes('/user-identities/users/')) {const id=pathname.split('/').pop();const index=users.findIndex(user=>user.userId===id);if(index>=0)users.splice(index,1);}
        return route.fulfill({contentType:'application/json',body:JSON.stringify({code,msg,data})});
      }
      if(url.origin===origin)return route.continue();
      return route.abort();
    });
    const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(origin+'/index.html#/unified-user-management');
    await page.getByRole('heading',{name:'爸爸',exact:true}).waitFor();
    assert.equal(await page.getByText('usr_test_a',{exact:true}).count(),0);
    assert.equal(await page.getByText('习惯管理',{exact:true}).count(),0);
    await page.screenshot({path:path.join(output,'members-desktop.png'),fullPage:true});
    await page.getByRole('button',{name:'添加成员',exact:true}).click();
    await page.getByPlaceholder('例如：爸爸').fill('妈妈');
    await page.getByRole('button',{name:'添加',exact:true}).click();
    await page.getByRole('heading',{name:'妈妈',exact:true}).waitFor();
    const card=page.locator('.member-card').filter({has:page.getByRole('heading',{name:'爸爸',exact:true})});
    await card.getByRole('button',{name:'录入声纹',exact:true}).click();
    await page.locator('.dialog-title').filter({hasText:'录入声纹'}).waitFor();
    await page.screenshot({path:path.join(output,'voice-dialog-desktop.png'),fullPage:true});
    await page.locator('.el-dialog:visible .custom-close-btn').click();
    await page.locator('.el-dialog:visible').waitFor({state:'hidden'});
    await card.getByRole('button',{name:'采集 / 绑定',exact:true}).click();
    await page.getByRole('tab',{name:'绑定已有资料'}).waitFor();
    await page.screenshot({path:path.join(output,'face-dialog-desktop.png'),fullPage:true});
    await page.locator('.el-dialog:visible .el-dialog__headerbtn').click();
    await page.locator('.el-dialog:visible').waitFor({state:'hidden'});
    await page.setViewportSize({width:390,height:844});
    await page.waitForFunction(()=>document.documentElement.scrollWidth<=window.innerWidth);
    await page.screenshot({path:path.join(output,'members-narrow.png'),fullPage:true});
    await page.getByRole('button',{name:'添加成员',exact:true}).click();
    await page.screenshot({path:path.join(output,'create-dialog-narrow.png'),fullPage:true});
    await page.getByPlaceholder('例如：爸爸').fill('爸爸');
    await page.getByRole('button',{name:'添加',exact:true}).click();
    await page.getByText('昵称已重复',{exact:true}).waitFor();
    await page.locator('.el-dialog:visible .el-dialog__headerbtn').click();
    await page.locator('.el-dialog:visible').waitFor({state:'hidden'});
    await page.locator('.el-message:visible').waitFor({state:'hidden'});
    await page.goto(origin+'/index.html#/billing/orders');
    await page.getByText('¥0.0000286',{exact:true}).waitFor();
    await page.waitForFunction(()=>document.documentElement.scrollWidth<=window.innerWidth);
    await page.screenshot({path:path.join(output,'memory-bills-narrow.png'),fullPage:true});
    await page.setViewportSize({width:1440,height:1000});
    await page.screenshot({path:path.join(output,'memory-bills-desktop.png'),fullPage:true});
    assert.equal(errors.length,0,errors.join('\n'));
    const result={passed:true,synthetic:true,cases:['nickname-only-create','duplicate-feedback','normal-entry-voice-dialog','face-binding-dialog','no-technical-ids','admin-only-analysis-navigation','desktop-and-narrow-layout','exact-low-price-bill-display'],pageErrors:errors};
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
    await context.close();
  }finally {await browser.close();server.close();}
})().catch(error=>{console.error(error.stack);server.close();process.exitCode=1;});
