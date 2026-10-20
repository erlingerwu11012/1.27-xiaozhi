// Candidate static bundle only. All API routes are synthetic; external requests blocked.
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const {chromium}=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core');
const root=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
const server=http.createServer((req,res)=>{const file=path.resolve(root,'.'+new URL(req.url,'http://localhost').pathname);if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.woff':'font/woff','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
  await context.addInitScript(()=>{localStorage.setItem('token',JSON.stringify({token:'synthetic-only'}));localStorage.setItem('isSuperAdmin','false');});
  let failed=false,available=true;
  const bills=[{id:'synthetic-search',state:'settled',operation:'search',model:'bailian-memory-lite',unit:'official_units',units:'1',points:'0.006666666666666667',paidAmountCny:'0.000066666666666667',legacyPoints:'0',createdAt:1790827200},{id:'synthetic-pending',state:'pending',operation:'llm',model:'qwen-plus',inputTokens:null,outputTokens:null,cachedTokens:null,points:null,paidAmountCny:null,reservedPoints:'1',createdAt:1790827201}];
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url()),p=url.pathname;
   if(p.includes('/xiaozhi/') || p.includes('/pay/') || p.includes('/user/')){
    let data={},code=0,msg='success';
    if(p.endsWith('/pay/billing/calls')){if(failed){code=500;msg='合成账单读取失败';}else data={available,list:available?bills:[],total:available?21:0};}
    else if(p.endsWith('/pay/billing/summary'))data={balancePoints:99.9933333333,balanceSource:'hardware_ledger',balanceRealtime:true,consumptionAvailable:true,daily:[{date:'2026-10-01',rechargeAmountCny:1,rechargePoints:100,usedPoints:.0066666667,netPoints:99.9933333333}]};
    else if(p.endsWith('/pay/packages'))data=[{id:1,name:'体验包',amountCents:100,quotaPoints:100,description:'1元100点'},{id:2,name:'标准包',amountCents:2900,quotaPoints:50000},{id:3,name:'专业包',amountCents:9900,quotaPoints:200000}];
    else if(p.endsWith('/user/info'))data={username:'合成测试',superAdmin:0};
    else if(p.endsWith('/user/pub-config'))data={version:'测试',allowUserRegister:false};
    return route.fulfill({contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'GET,POST,OPTIONS'},body:JSON.stringify({code,msg,data})});
   }
   if(url.origin===origin)return route.continue();return route.abort();
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/index.html#/billing/packages');
  try {await page.getByText('¥0.000067',{exact:true}).waitFor({timeout:10000});}
  catch(e){fs.writeFileSync(path.join(out,'failure-page.txt'),await page.locator('body').innerText());await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw e;}
  await page.getByText('实时账本',{exact:true}).waitFor();
  assert.equal(await page.getByText('0.006667',{exact:true}).count(),1);
  assert.equal(await page.getByText('待核对',{exact:true}).count(),1);
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.screenshot({path:path.join(out,'billing-'+width+'.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));}
  failed=true;await page.locator('.hardware-bills').getByRole('button',{name:'刷新'}).click();await page.getByText('合成账单读取失败',{exact:true}).waitFor();assert.equal(await page.getByText('¥0.000067',{exact:true}).count(),0);
  failed=false;available=false;await page.locator('.hardware-bills').getByRole('button',{name:'刷新'}).click();await page.locator('.hardware-bills').waitFor({state:'hidden'});
  assert.equal(errors.length,0,errors.join('\n'));const result={passed:true,synthetic_only:true,cases:['low-price-six-decimal-display','pending-is-not-zero-charge','failed-read-clears-old-bills','disabled-wallet-hides-component','desktop-and-narrow-layout','no-page-errors','exact-ledger-balance-source'],does_not_validate_live_payment_or_aggregate:true};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
