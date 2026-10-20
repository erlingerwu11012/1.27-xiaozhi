"""Free, local checks. These are NOT substitutes for Go/Java/Vue builds or API tests."""
from pathlib import Path
from fractions import Fraction as F
import json
import re
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
CAND=ROOT/'tmp/hardware-billing70'

class LocalChecks(unittest.TestCase):
    def test_financial_reference_vectors(self):
        # Independent oracle for the assertions in billing_test.go, not execution
        # of the Go production code. The Go suite must still pass before release.
        cost=F('0.018');sale=cost/F('0.3')
        self.assertEqual(sale,F('0.06'))
        self.assertEqual(sale/F('0.01'),6)
        self.assertEqual(sale/(F(29)/50000),F(3000,29))
        self.assertEqual(sale/(F(99)/200000),F(4000,33))
        self.assertEqual(F('0.00002')/F('0.3')/F('0.01'),F(1,150))
        self.assertEqual(((sale-cost)/sale),F('0.7'))

    def test_fifo_vector(self):
        # Half covered by legacy, 1 point taken from experience lot, remainder
        # from standard package. No averaged conversion or minimum-one charge.
        sale=F('0.06')*F(1,2)
        self.assertEqual((sale-F('0.01'))/(F(29)/50000),F(1000,29))

    def test_actual_meter_survives_legacy_fallback(self):
        p=(CAND/'gateway/relay/adaptor/openai/main.go').read_text(encoding='utf-8')
        self.assertLess(p.index('hardwarebilling.ParseUsage(responseBody'),p.index('if textResponse.Usage.TotalTokens == 0'))
        self.assertGreater(p.rindex('textResponse.Usage.ActualEvidence = &evidence'),p.index('if textResponse.Usage.TotalTokens == 0'))
        self.assertIn('usage.ActualEvidence = &evidence',p)
        ali=(CAND/'gateway/relay/adaptor/ali/main.go').read_text(encoding='utf-8')
        self.assertIn('hardwarebilling.ParseUsage([]byte(data)',ali)
        self.assertIn('fullTextResponse.Usage.ActualEvidence = &evidence',ali)

    def test_customer_ownership_and_internal_cost_hidden(self):
        controller=(CAND/'server/main/manager-api/src/main/java/xiaozhi/modules/pay/controller/HardwareBillingController.java').read_text(encoding='utf-8')
        service=(CAND/'server/main/manager-api/src/main/java/xiaozhi/modules/pay/service/HardwareBillingReadService.java').read_text(encoding='utf-8')
        self.assertIn('SecurityUser.getUser().getId()',controller)
        self.assertNotIn('accountId',controller)
        self.assertIn('user_id=? AND product_account=?',service)
        self.assertNotIn('cost_cny',service)
        self.assertNotIn('oneapi_token_key',service)
        self.assertIn('${hardware.billing.enabled:false}',service)

    def test_request_and_refund_idempotency_guards_present(self):
        source=(CAND/'gateway/hardwarebilling/ledger.go').read_text(encoding='utf-8')
        for needle in ['clause.Locking{Strength:"UPDATE"}','request_idempotency_conflict','usage_idempotency_conflict','recharge_idempotency_conflict','refund_idempotency_conflict','already_compensated','ReservationJSON']:
            self.assertIn(needle,source)
        self.assertNotIn('float64',source)

    def test_price_snapshot_coverage(self):
        source=(CAND/'gateway/hardwarebilling/pricing.go').read_text(encoding='utf-8')
        for model in ['qwen-plus','qwen3-vl-flash','qwen3-asr-flash-realtime','qwen-audio-3.0-tts-plus','bailian-memory-lite']:
            self.assertIn(model,source)
        self.assertNotIn('aimi-chat',source)
        self.assertNotIn('siliconflow',source)
        self.assertIn('usage_pending',source)
        self.assertIn('Reasoning is already included',source)

    def test_migration_preserves_existing_data_and_packages(self):
        migration=(ROOT/'tools/hardware-billing70/migration.sql').read_text(encoding='utf-8')
        self.assertNotRegex(migration,re.compile(r'\b(DROP|DELETE|UPDATE)\b',re.I))
        self.assertNotIn('api_key',migration)
        self.assertIn('reservation_json TEXT NOT NULL',migration)

    def test_frontend_candidate_js_syntax(self):
        node=Path('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
        if not node.exists():self.skipTest('bundled node unavailable')
        base=CAND/'server/main/manager-web/src'
        for name in ['components/HardwareCallBills.vue','views/BillingPackages.vue','apis/module/pay.js']:
            content=(base/name).read_text(encoding='utf-8')
            if name.endswith('.vue'):content=content.split('<script>',1)[1].split('</script>',1)[0]
            temp=ROOT/'tmp/hardware-billing70/syntax-check.mjs';temp.write_text(content,encoding='utf-8')
            p=subprocess.run([str(node),'--check',str(temp)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
        temp.unlink(missing_ok=True)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(LocalChecks)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'scope':'local static checks and independent financial oracle','passed':result.wasSuccessful(),'tests':result.testsRun,'production_go_java_vue_builds':'not run','upstream_calls':0,'api_cost_cny':'0','production_changed':False}
    (ROOT/'tools/hardware-billing70/local-check-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
