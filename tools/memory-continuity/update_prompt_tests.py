from pathlib import Path
import json
root=Path(__file__).resolve().parents[2]/'tmp/bailian-memory-product/server';n='main/xiaozhi-server/test/test_prompt_pipeline_v2.py';p=root/n;t=p.read_text(encoding='utf-8')
s=t.index('    def test_is_pipeline_v2_fail_closed');e=t.index('    def test_is_pipeline_v2_rollout_match',s)
t=t[:s]+'''    def test_is_pipeline_v2_config_missing_fails_closed_and_v2_is_global(self):
        self.assertFalse(prompt_pipeline.is_pipeline_v2(_conn()))
        self.assertFalse(prompt_pipeline.is_pipeline_v2(_conn(config={"prompt_pipeline":{"version":"v1"}})))
        for rollout in (None,[],["dev-other"]):
            self.assertTrue(prompt_pipeline.is_pipeline_v2(_conn(config={"prompt_pipeline":{"version":"v2","rollout_device_ids":rollout}})))

'''+t[e:]
t=t.replace('with patch.object(PromptManager, "_load_base_template", lambda self: None), patch.object(\n            PromptManager, "_load_v2_template", lambda self: None\n        ):','with patch.object(PromptManager, "_load_v2_template", lambda self: None):')
t=t.replace('pm.base_prompt_template_v2 = ""','pm.base_prompt_template_v2 = "synthetic platform rules"')
s=t.index('    def test_render_includes_emotion_and_speaker');e=t.index('    def test_emotion_unknown_when_missing',s);part=t[s:e]
part=part.replace('        ):\n            ctx = turn_context.build_turn_context(', '        ), patch("core.utils.person_identity.current_turn", return_value=SimpleNamespace(eligible=True,display_name="小明",status="matched",person_id="usr_test")):\n            ctx = turn_context.build_turn_context(')
t=t[:s]+part+t[e:];p.write_text(t,encoding='utf-8')
mf=Path(__file__).with_name('changed.json');names=json.loads(mf.read_text());names.append(n);mf.write_text(json.dumps(sorted(set(names)),indent=2))
