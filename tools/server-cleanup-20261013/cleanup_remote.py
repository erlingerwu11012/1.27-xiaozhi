"""Space recovery without deleting Git objects, business data or releases."""
from pathlib import Path
import subprocess,hashlib,json,os,shutil,gzip,time
repo=Path('/root/prjs/xiaozhi-esp32-server');audit=Path('/root/prjs/tmp')/('server-cleanup-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime()));audit.mkdir(mode=0o700)
def run(args):return subprocess.check_output(args,stderr=subprocess.STDOUT)
def git(*args):return run(['git','-C',str(repo),*args])
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while chunk:=f.read(1024*1024):h.update(chunk)
 return h.hexdigest()
def objects():return hashlib.sha256(b'\n'.join(sorted(git('cat-file','--batch-all-objects','--batch-check=%(objectname)').splitlines()))).hexdigest()
def pm2():return [{'id':a['pm_id'],'pid':a['pid'],'name':a['name'],'path':a['pm2_env']['pm_exec_path']} for a in json.loads(run(['pm2','jlist'])) if a['pm2_env']['status']=='online']
state={'started_at':time.time(),'before_free_bytes':shutil.disk_usage('/').free,'services_before':pm2(),'actions':[]};(audit/'cleanup.json').write_text(json.dumps(state,indent=2))
os.environ['GIT_OPTIONAL_LOCKS']='0'
assert not list((repo/'.git').rglob('*.lock')) and not (repo/'.git/gc.pid').exists()
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:argv=(p/'cmdline').read_bytes().split(b'\0')
 except (FileNotFoundError,PermissionError,ProcessLookupError):continue
 assert not argv or Path(argv[0].decode(errors='replace')).name!='git','another Git operation is active'
refs=git('show-ref');head=git('rev-parse','HEAD');status=git('status','--porcelain=v1','--untracked-files=no');before_objects=objects();before_git=int(run(['du','-s','-B1',str(repo/'.git')]).split()[0])
(audit/'git-refs.before').write_bytes(refs);(audit/'git-status.before').write_bytes(status)
print('Compressing Git, preserving reflogs and all objects',flush=True)
cmd=['nice','-n','19','ionice','-c','3','git','-C',str(repo),'-c','pack.threads=1','-c','pack.windowMemory=512m','-c','pack.deltaCacheSize=64m','-c','core.bigFileThreshold=256m','-c','gc.autoDetach=false','-c','gc.reflogExpire=never','-c','gc.reflogExpireUnreachable=never','-c','gc.worktreePruneExpire=never','gc','--prune=never']
with (audit/'git-gc.log').open('wb') as log:p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
assert p.returncode==0,'Git compression failed; see audit log'
assert git('show-ref')==refs and git('rev-parse','HEAD')==head and objects()==before_objects,'Git refs or complete object set changed'
assert git('status','--porcelain=v1','--untracked-files=no')==status,'tracked working state changed during cleanup'
after_git=int(run(['du','-s','-B1',str(repo/'.git')]).split()[0]);state['actions'].append({'action':'git_gc_no_pruning','before_bytes':before_git,'after_bytes':after_git,'all_objects_preserved':True,'refs_head_and_tracked_working_state_preserved':True});print('Git bytes',before_git,'->',after_git,flush=True)
backup_root=repo/'docs/deployments/artifacts/official-tts-fullcap-20260918-prod/backup/db'
for name in ['xiaozhi_esp32_server.sql','one_api.sql']:
 p=backup_root/name
 if not p.exists():continue
 assert p.resolve().parent==backup_root.resolve() and not p.is_symlink();assert not git('ls-files','--',str(p.relative_to(repo))).strip(),'do not change tracked backup files'
 target=p.with_name(p.name+'.gz');tmp=target.with_name(target.name+'.cleanup-part');assert not target.exists() and not tmp.exists()
 original=digest(p);before=p.stat().st_size
 with p.open('rb') as source,gzip.open(tmp,'wb',compresslevel=6) as out:shutil.copyfileobj(source,out,1024*1024)
 h=hashlib.sha256()
 with gzip.open(tmp,'rb') as source:
  while chunk:=source.read(1024*1024):h.update(chunk)
 assert h.hexdigest()==original and digest(p)==original
 os.replace(tmp,target);target.chmod(0o600);p.unlink()
 state['actions'].append({'action':'compress_old_sql_backup_losslessly','original':str(p),'compressed':str(target),'before_bytes':before,'after_bytes':target.stat().st_size,'uncompressed_sha256':original,'restore':'gunzip -c compressed_path > restored_sql_path'})
 print('Compressed old SQL backup',name,before,'->',target.stat().st_size,flush=True)
cache=repo/'main/manager-web/.webpack_cache/default-production'
if cache.exists():
 assert cache.resolve()==Path('/root/prjs/xiaozhi-esp32-server/main/manager-web/.webpack_cache/default-production') and not cache.is_symlink()
 assert not git('ls-files','--',str(cache.relative_to(repo))).strip(),'tracked cache must be retained'
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:argv=(p/'cmdline').read_bytes()
  except (FileNotFoundError,PermissionError,ProcessLookupError):continue
  assert not (b'webpack' in argv and (b'--mode production' in argv or b'vue-cli-service build' in argv)),'production build currently active'
 size=int(run(['du','-s','-B1',str(cache)]).split()[0]);shutil.rmtree(cache);state['actions'].append({'action':'remove_untracked_rebuildable_production_webpack_cache','path':str(cache),'bytes':size})
state.update(after_free_bytes=shutil.disk_usage('/').free,services_after=pm2(),completed_at=time.time());state['freed_bytes']=state['after_free_bytes']-state['before_free_bytes'];state['service_pids_unchanged']=state['services_before']==state['services_after'];assert state['service_pids_unchanged']
(audit/'cleanup.json').write_text(json.dumps(state,indent=2));(audit/'cleanup.json').chmod(0o600)
print(json.dumps({'audit':str(audit),'before_free_bytes':state['before_free_bytes'],'after_free_bytes':state['after_free_bytes'],'freed_bytes':state['freed_bytes'],'git_before_bytes':before_git,'git_after_bytes':after_git,'all_git_objects_preserved':True,'service_pids_unchanged':True},indent=2),flush=True)
