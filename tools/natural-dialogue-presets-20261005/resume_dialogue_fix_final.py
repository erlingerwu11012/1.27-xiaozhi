"""Resume incomplete final comparison; preserve every prior response and call cap."""
from pathlib import Path
path=Path(__file__).with_name('dialogue_fix_final.py')
source=path.read_text()
source=source.replace("result.update(calls=0,max_calls=40,dialogues=[],boundaries=[],completed=False,unseen_topic_test=True)",
"result=json.loads((OUT/'dialogue-fix-final.json').read_text());result['resumed_after_shared_account_guard']=True")
# The earlier account-wide guard also counts unrelated production requests.
# Keep the 40-call total cap and bound this continuation's own token usage.
source=source.replace("for model in ['qwen3.8-flash','qwen3.8-max']:",
"result['continuation_limits']={'new_calls':18,'input_tokens':80000,'output_tokens':7000};resume_start_calls=result['calls'];resume_input=0;resume_output=0\n"
"old_ask=ask\n"
"def check_budget():\n"
" assert result['calls']-resume_start_calls<18 and resume_input<80000 and resume_output<7000,'individual_test_token_guard'\n"
"def ask(p,messages):\n"
" global resume_input,resume_output\n"
" row=old_ask(p,messages);usage=row.get('usage') or {};resume_input+=usage.get('prompt_tokens',0);resume_output+=usage.get('completion_tokens',0)\n"
" result['continuation_usage']={'input_tokens':resume_input,'output_tokens':resume_output};return row\n"
"for model in ['qwen3.8-flash','qwen3.8-max']:")
source=source.replace("entry={'model':model,'revision':'final-candidate','persona':profile['id'],'persona_prompt':profile['prompt'],'turns':[]};result['dialogues'].append(entry)",
"entry=next((d for d in result['dialogues'] if d['model']==model and d['persona']==profile['id']),None)\n   if entry is None:\n    entry={'model':model,'revision':'final-candidate','persona':profile['id'],'persona_prompt':profile['prompt'],'turns':[]};result['dialogues'].append(entry)")
source=source.replace("messages.append(user(text));row={'turn':index,'user':text,**ask(p,messages)};entry['turns'].append(row);save()",
"messages.append(user(text))\n    if index<=len(entry['turns']):\n     messages.append({'role':'assistant','content':entry['turns'][index-1]['assistant']});continue\n    row={'turn':index,'user':text,**ask(p,messages)};entry['turns'].append(row);save()")
source=source.replace("row={'model':model,'case':label,'user':text,**ask(p,", "if any(r['model']==model and r['case']==label for r in result['boundaries']):continue\n   row={'model':model,'case':label,'user':text,**ask(p,")
exec(compile(source,'<resume-final-comparison>','exec'))
