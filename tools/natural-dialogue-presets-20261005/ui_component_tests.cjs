const fs = require('fs');
const path = require('path');
const assert = require('assert');
const OUT = '/root/prjs/tmp/natural-dialogue-presets-20261005';
const ROOT = OUT + '/worktree/main/manager-web';
const testRequire = require('module').createRequire(OUT + '/ui-tests/package.json');
const sourceRequire = require('module').createRequire(ROOT + '/package.json');
const { JSDOM } = testRequire('jsdom');
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
global.window = dom.window; global.document = dom.window.document; global.navigator = dom.window.navigator;
for (const key of ['HTMLElement', 'HTMLBodyElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MutationObserver']) global[key] = dom.window[key];
global.getComputedStyle = dom.window.getComputedStyle;
global.requestAnimationFrame = fn => setTimeout(fn, 0);
global.cancelAnimationFrame = clearTimeout;
const Vue = testRequire('vue');
Vue.config.productionTip = false;
const { mount, createLocalVue } = testRequire('@vue/test-utils');
const compiler = sourceRequire('vue-template-compiler');
const babel = sourceRequire('@babel/core');
const storage = new Map();
global.sessionStorage = { setItem: (k,v) => storage.set(k,v), getItem: k => storage.get(k) };
let existingPrompt = '这是用户此前自己写的人格，喜欢严谨讨论。';
let updates = [], messages = [];
const config = () => ({ id: 'synthetic-agent', agentName: '测试', deviceName: '测试', userNickname: '小林', systemPrompt: existingPrompt,
 asrModelId: 'ASR_Qwen3ASRRealtime', llmModelId: 'LLM_QwenPlusOfficial', ttsModelId: 'TTS_QwenAudioTTSPlus', ttsVoiceId: 'voice-test',
 memModelId: 'Memory_mem_local_short', chatHistoryConf: 2, functions: [] });
const Api = {
 agent: {
  getDeviceConfig: (id, cb) => cb({data:{code:0,data:config()}}),
  addAgent: (name, cb) => cb({data:{code:0,data:'synthetic-agent'}}),
  updateAgentConfig: (id, payload, cb) => { updates.push({id,payload}); existingPrompt = payload.systemPrompt; cb({data:{code:0,data:{}}}); },
 },
 model: {
  getModelNames: (category, query, cb) => cb({data:{code:0,data: category === 'Memory' ? [{id:'Memory_mem_local_short'}] : []}}),
  getModelVoices: (id, query, cb) => cb({data:{code:0,data:[]}}),
  getLlmModelCodeList: (query, cb) => cb({data:{code:0,data:[]}}),
  getPluginFunctionList: (query, cb) => cb({data:{code:0,data:[]}}),
 },
};
const cache = new Map();
function load(file) {
 if (cache.has(file)) return cache.get(file);
 const isVue = file.endsWith('.vue'); const source = fs.readFileSync(file, 'utf8');
 const parsed = isVue ? compiler.parseComponent(source) : null;
 const code = babel.transformSync(isVue ? parsed.script.content : source, { babelrc:false, configFile:false,
  plugins: [sourceRequire.resolve('@babel/plugin-transform-modules-commonjs')] }).code;
 const module = {exports:{}};
 const mockRequire = name => {
  if (name === '@/apis/api') return {__esModule:true,default:Api,getServiceUrl:()=> 'http://localhost/mock'};
  if (name === '@/apis/httpRequest') return {__esModule:true,default:{}};
  if (name === '@/i18n') return {__esModule:true,default:{t:k=>k}};
  if (name.endsWith('/HeaderBar.vue') || name.endsWith('/FunctionDialog.vue')) return {__esModule:true,default:{render:h=>h('span')}};
  if (name.startsWith('@/')) { let p = ROOT+'/src/'+name.slice(2); if (!path.extname(p)) p += '.js'; return load(p); }
  return sourceRequire(name);
 };
 new Function('require','module','exports',code)(mockRequire,module,module.exports);
 if (isVue) {
  const compiled = compiler.compile(parsed.template.content);
  assert(!compiled.errors.length, compiled.errors.join('\n'));
  module.exports.default.render = new Function(compiled.render);
  module.exports.default.staticRenderFns = compiled.staticRenderFns.map(code=>new Function(code));
 }
 cache.set(file,module.exports); return module.exports;
}
const localVue = createLocalVue();
localVue.use(sourceRequire('element-ui'));
localVue.prototype.$t = key=>key;
localVue.prototype.$message = Object.assign(()=>{}, {warning:x=>messages.push(x),error:x=>messages.push(x),success:x=>messages.push(x)});
const mocks = { $route:{query:{agentId:'synthetic-agent'}},$router:{push:()=>{}} };
const tick = async()=> { await Vue.nextTick(); await Promise.resolve(); await Vue.nextTick(); };
const results = [];
async function test(name, fn) { await fn(); results.push({name,pass:true}); console.log('PASS '+name); }
(async()=> {
 const {PERSONA_PRESETS,DEFAULT_PERSONA_PROMPT} = load(ROOT+'/src/constants/personaPresets.js');
 const Picker = load(ROOT+'/src/components/PersonaPresetPicker.vue').default;
 const Wizard = load(ROOT+'/src/components/AwakeningWizard.vue').default;
 const Role = load(ROOT+'/src/views/roleConfig.vue').default;
 let picker = mount(Picker,{localVue,propsData:{value:DEFAULT_PERSONA_PROMPT}});
 await test('six selectable accessible preset cards', async()=> {assert.equal(picker.findAll('button.persona-presets__card').length,6);assert.equal(picker.find('[aria-pressed="true"]').text().includes('自然朋友'),true);});
 await test('preset switch emits exact editable text', async()=> {await picker.findAll('button.persona-presets__card').at(2).trigger('click');await tick();assert.equal(picker.emitted('input')[0][0],PERSONA_PRESETS[2].prompt);});
 await picker.setProps({value:'我自己写的草稿'});
 await test('cancel replacing custom draft keeps original', async()=> {picker.vm.$confirm=()=>Promise.reject('cancel');const before=(picker.emitted('input')||[]).length;await picker.vm.selectPreset(PERSONA_PRESETS[0]);assert.equal((picker.emitted('input')||[]).length,before);assert.equal(picker.props('value'),'我自己写的草稿');});
 await test('confirmed replacement emits selected preset', async()=> {picker.vm.$confirm=()=>Promise.resolve();await picker.vm.selectPreset(PERSONA_PRESETS[4]);assert.equal(picker.emitted('input').slice(-1)[0][0],PERSONA_PRESETS[4].prompt);});
 picker.destroy();
 let wizard = mount(Wizard,{localVue,mocks,propsData:{visible:true,mode:'create'},attachTo:document.body});await tick();
 await test('new agent starts with natural personality',async()=>assert.equal(wizard.vm.form.systemPrompt,DEFAULT_PERSONA_PROMPT));
 wizard.vm.form.deviceName='新朋友';wizard.vm.form.userNickname='小林';wizard.vm.nextStep();wizard.vm.nextStep();await tick();
 await test('third step shows presets and hides optional generators',async()=> {assert(wizard.text().includes('人格设定'));assert.equal(wizard.findAll('button.persona-presets__card').length,6);assert(!wizard.find('.soul-entry-cards').exists());});
 await test('custom editing does not reset draft when navigating back',async()=> {wizard.vm.onPromptInput('我的自定义人格');wizard.vm.prevStep();wizard.vm.nextStep();assert.equal(wizard.vm.form.systemPrompt,'我的自定义人格');});
 await test('unfinished generated text cannot be saved',async()=> {wizard.vm.typewriterGenerating=true;const before=updates.length;wizard.vm.handleFinish();assert.equal(updates.length,before);wizard.vm.typewriterGenerating=false;});
 await test('create sends custom personality through existing API',async()=> {wizard.vm.handleFinish();assert.equal(updates.slice(-1)[0].payload.systemPrompt,'我的自定义人格');});
 wizard.destroy();
 existingPrompt='这是此前用户的原始人格';
 let role=mount(Role,{localVue,mocks,attachTo:document.body});await tick();
 await test('opening role configuration preserves saved personality',async()=> {assert.equal(role.vm.form.systemPrompt,existingPrompt);assert.equal(role.vm.initializationReady,true);assert.equal(role.vm.hasUnsavedChanges,false);});
 await test('personality textarea is enabled',async()=>assert.equal(role.find('textarea').attributes('disabled'),undefined));
 await test('personality-only edit enables save',async()=> {await role.find('textarea').setValue('保存后的自定义人格');await tick();assert.equal(role.vm.hasUnsavedChanges,true);});
 await test('save persists exact draft and resets dirty state',async()=> {role.vm.saveConfig();await tick();assert.equal(updates.slice(-1)[0].payload.systemPrompt,'保存后的自定义人格');assert.equal(role.vm.hasUnsavedChanges,false);});
 role.destroy();role=mount(Role,{localVue,mocks});await tick();
 await test('reopening reads back the saved custom personality',async()=>assert.equal(role.vm.form.systemPrompt,'保存后的自定义人格'));
 role.destroy();
 fs.writeFileSync(OUT+'/ui-component-tests.json',JSON.stringify({synthetic_api:true,real_business_writes:0,passed:results.length,results},null,2));
 console.log(JSON.stringify({passed:results.length,failed:0}));
 process.exit(0);
})().catch(error=>{console.error(error.stack);process.exit(1);});
