from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]/'tmp/hardware-billing70/server/main/manager-web/src'

def patch(path,old,new):
    p=ROOT/path;s=p.read_text(encoding='utf-8')
    if new in s:return
    if s.count(old)!=1:raise RuntimeError('source mismatch: '+path)
    p.write_text(s.replace(old,new),encoding='utf-8',newline='\n')

patch('apis/module/pay.js','export default {', '''export default {
    hardwareCalls(page, limit, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/pay/billing/calls?page=${encodeURIComponent(page || 1)}&limit=${encodeURIComponent(limit || 20)}`)
            .method('GET').success(res => { RequestService.clearRequestTime(); callback(res.data); })
            .networkFail(() => callback({ code: 500, msg: '调用账单读取失败' })).send();
    },''')
patch('views/BillingPackages.vue', "import HeaderBar from '@/components/HeaderBar.vue';", "import HeaderBar from '@/components/HeaderBar.vue';\nimport HardwareCallBills from '@/components/HardwareCallBills.vue';")
patch('views/BillingPackages.vue', 'components: { HeaderBar },', 'components: { HeaderBar, HardwareCallBills },')
patch('views/BillingPackages.vue', '<!-- 充值套餐 / 充值入口', '<HardwareCallBills />\n\n        <!-- 充值套餐 / 充值入口')
print('candidate call-bill UI patched')
