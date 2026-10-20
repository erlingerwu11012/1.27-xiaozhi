from pathlib import Path
S=Path('tools/experience-repair-20261009')
p=S/'bootstrap.py';s=p.read_text(encoding='utf-8-sig').replace("{'HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN'}","{'HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN'}");p.write_text(s,encoding='utf-8')
p=S/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');s=s.replace("write_scope=None\n        constraints=", "write_scope=None;satisfied_noops=set()\n        constraints=",1);s=s.replace("set(r.tool for r in outcome.results if r.state=='completed'):","set(r.tool for r in outcome.results if r.state=='completed')-satisfied_noops:",1)
needle="                    fp=Ledger.fingerprint(name,arguments)"
s=s.replace(needle,"""                    if step.relative is not None and status.state=='completed' and arguments[key]==value:
                        status.intermediate=False
                        status.reply=f'当前{"音量" if key=="volume" else "亮度"}已经是{value}{"档" if key=="brightness" and high==5 else ""}，已到可调边界，无需重复设置。'
                        step_results[step.id]=status;satisfied_noops.add(name)
                        self.observe('no_change',request_id=turn,tool=name,source_call_id=status.call_id)
                        continue
"""+needle,1)
s=s.replace("if write_scope and write_scope<=confirmed_writes:","if write_scope and write_scope<=confirmed_writes|satisfied_noops:",1);p.write_text(s,encoding='utf-8')
p=S/'run_final.py';s=p.read_text(encoding='utf-8');s=s.replace("'source':hashes,'cases_sha256'", "'source':hashes,'java_source':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (stage/'manager-api/src/main/java/xiaozhi/modules/personmemory').glob('*.java')},'jar_sha256':hashlib.sha256((stage/'manager-api/target/xiaozhi-esp32-api.jar').read_bytes()).hexdigest(),'cases_sha256'")
p.write_text(s,encoding='utf-8')
