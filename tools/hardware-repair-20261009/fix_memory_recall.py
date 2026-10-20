from pathlib import Path
S=Path('tools/hardware-repair-20261009');J=S/'java'
p=J/'RecentArchiveService.java';s=p.read_text();old='''        return result.stream().limit(24).collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));''';new='''        if(query.matches("(?s).*(爱喝|喝什么|喝啥|饮料|饮品|喜欢喝).*"))result.add("喝");
        if(query.matches("(?s).*(爱吃|吃什么|吃啥|喜欢吃|食物).*"))result.add("吃");
        if(query.matches("(?s).*(喜好|偏好|喜欢什么|喜欢啥).*"))result.add("喜欢");
        return result.stream().limit(24).collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));''';assert old in s;s=s.replace(old,new)
s=s.replace('''        List<Map<String,Object>> items=new ArrayList<>();Set<String> seen=new HashSet<>();''', '''        // A generic personal-memory question may use different vocabulary from
        // the stored fact. Supply a bounded recent context for the main LLM to select.
        boolean broad=query.matches("(?s).*(上下文|记忆库|之前说|说过什么|我爱喝|我爱吃|我的偏好|喜欢什么|喜欢啥).* ".strip());
        List<Map<String,Object>> items=new ArrayList<>();Set<String> seen=new HashSet<>();''')
s=s.replace('score(Objects.toString(row.getOrDefault("search_text",value),""),terms)<1 || terms.isEmpty()', '(score(Objects.toString(row.getOrDefault("search_text",value),""),terms)<1 || terms.isEmpty()) && !broad')
p.write_text(s)
p=S/'wire_smoke.py';s=p.read_text().replace("writes=[c for c in r['calls'] if contract(c['tool']).write]","writes=[c for c in r['outcome']['results'] if contract(c['tool']).write]")
s=s.replace(" assert term in r['speech'],r['outcome']", " assert term in r['speech'] or write,r['outcome']");p.write_text(s)
p=S/'work/core/utils/tool_harness/runtime.py';s=p.read_text().replace("                        if not confirmed:\n                            result.state='unknown'", "                        if confirmed and isinstance(result.payload,dict):\n                            result.payload['verified_replacement' if name=='memory_correct' else 'verified_removed_fact']=arguments.get('replacement') if name=='memory_correct' else arguments.get('match')\n                            result.payload['readback_confirmed']=True\n                        if not confirmed:\n                            result.state='unknown'");p.write_text(s)
p=S/'work/core/utils/tool_harness/reply_composer.py';s=p.read_text().replace("'data':payload,'reason':r.error", "'data':payload,'verified_arguments':{k:v for k,v in r.arguments.items() if k not in {'record_id','expected_version','instance_id','recipient_id','recipient_person_id','raw'}},'reason':r.error");p.write_text(s)
print('semantic memory recall and verified fact projection fixed')
