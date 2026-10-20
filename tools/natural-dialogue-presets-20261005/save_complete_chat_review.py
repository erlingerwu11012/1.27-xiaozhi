"""Save only candidate sources and synthetic evidence; never deploy."""
import hashlib,json,os,re,shutil,subprocess,tarfile
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD=Path('/root/prjs/xiaozhi-esp32-server')
CAND=OUT/'worktree'
REVIEW=Path('/root/prjs/tmp/complete-chat-review-20261006')
BRANCH='codex/conversation-validation-review-20261006'
def git(root,*args):
    p=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,check=True)
    return p.stdout.strip()
baseline=git(PROD,'rev-parse','HEAD')
assert baseline.startswith('35236f03') and not git(PROD,'status','--porcelain','--untracked-files=no')
sources=['main/xiaozhi-server/core/connection.py',
         'main/xiaozhi-server/core/utils/conversation_turn.py',
         'main/xiaozhi-server/core/utils/conversation_guidance.py',
         'main/xiaozhi-server/config/config_loader.py',
         'main/xiaozhi-server/test/test_conversation_turn.py',
         'main/xiaozhi-server/test/test_semantic_conversation_guard.py',
         'main/xiaozhi-server/test/test_conversation_config.py']
formal_hashes={p:hashlib.sha256((PROD/p).read_bytes()).hexdigest()
               for p in sources if (PROD/p).exists()}
if REVIEW.exists():
    assert git(REVIEW,'branch','--show-current')==BRANCH
    assert git(REVIEW,'rev-parse','HEAD')==baseline, 'review_has_another_commit'
else:
    git(PROD,'worktree','add','-b',BRANCH,str(REVIEW),baseline)
for name in sources:
    target=REVIEW/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(CAND/name,target)
evidence=['complete-chat-final-candidate','complete-chat-simple-pilot',
          'complete-chat-direct-simple','complete-chat-simple-flash',
          'complete-chat-deepseek-nonthinking','complete-chat-deepseek-simple',
          'complete-chat-think-simple','complete-chat-kimi-simple',
          'complete-chat-plus-control','complete-chat-semantic-full',
          'complete-chat-heldout','complete-chat-voice20','complete-chat-mcp-scoped',
          'complete-chat-regression','complete-chat-judge-long-context',
          'complete-chat-judge-sentences']
def public_data(value):
    if isinstance(value,dict):
        assert not {'api_key','password','secret','Authorization','HW_BILLING_SERVICE_KEY'} & value.keys()
        for v in value.values():public_data(v)
    elif isinstance(value,list):
        for v in value:public_data(v)
    elif isinstance(value,str):
        assert not re.search(r'sk-[A-Za-z0-9_-]{20,}',value),'credential_like_content'
paths=list(sources)
docs=REVIEW/'docs/natural-dialogue-presets-20261005';docs.mkdir(parents=True,exist_ok=True)
for name in evidence:
    p=OUT/(name+'.json');data=json.loads(p.read_text());public_data(data)
    for suffix in ('.json','-conversations.md'):
        src=OUT/(name+suffix)
        if not src.exists():continue
        dest=docs/src.name;shutil.copyfile(src,dest);paths.append(str(dest.relative_to(REVIEW)))
report=Path('docs/COMPLETE_DIALOGUE_ACCEPTANCE_20261006.md')
shutil.copyfile(OUT/report.name,REVIEW/report);paths.append(str(report))
scripts=['complete_chat_acceptance.py','complete_chat_mcp_acceptance.py',
         'complete_chat_regression.py','run_dialogue_fix_regression.py',
         'runtime_production_acceptance.py','export_complete_chat_records.py',
         'semantic_checker_acceptance.py','semantic_long_context_acceptance.py',
         'complete_chat_voice20_acceptance.py','dialogue_fix_voice_chain.py',
         'save_complete_chat_review.py']
for name in scripts:
    dest=REVIEW/'tools/natural-dialogue-presets-20261005'/name
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(OUT/name,dest);paths.append(str(dest.relative_to(REVIEW)))
# Explicit, reviewed paths only. No environment files, database or audio backup.
assert set(git(REVIEW,'diff','--cached','--name-only').splitlines())<=set(paths)
assert set(git(REVIEW,'diff','--name-only').splitlines())<=set(paths)
git(REVIEW,'add','-f','--',*paths)
changed=set(git(REVIEW,'diff','--cached','--name-only').splitlines())
assert changed<=set(paths) and str(report) in changed
git(REVIEW,'-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol',
    'diff','--cached','--check')
git(REVIEW,'commit','-m','Add opt-in conversation checks and record failed natural chat acceptance')
assert not git(REVIEW,'status','--porcelain','--untracked-files=no')
assert git(PROD,'rev-parse','HEAD')==baseline
assert not git(PROD,'status','--porcelain','--untracked-files=no')
assert all(hashlib.sha256((PROD/p).read_bytes()).hexdigest()==h for p,h in formal_hashes.items())
receipt={'production_commit':baseline,'review_branch':BRANCH,
         'review_commit':git(REVIEW,'rev-parse','HEAD'),'review_root':str(REVIEW),
         'deployed':False,'sensitive_files_committed':False,
         'source_sha256':{p:hashlib.sha256((REVIEW/p).read_bytes()).hexdigest() for p in sources}}
(OUT/'complete-chat-review-receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt,ensure_ascii=False))
