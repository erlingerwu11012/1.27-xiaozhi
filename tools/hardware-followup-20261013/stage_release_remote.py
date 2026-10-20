from pathlib import Path
import os,sys,json,hashlib,shutil,time,subprocess
s=Path('/root/prjs/tmp/hardware-followup-20261013');old=Path('/root/prjs/releases/harness-stream-20261012');new=Path('/root/prjs/releases/harness-followup-20261013');root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
sys.path.insert(0,str(s));from budget import Budget
b=Budget();charge=b.reserve('case','stage-independent-release-hardlinked-immutable-baseline')
assert not new.exists();assert shutil.disk_usage('/').free>150*1024**2
apps=json.loads(subprocess.check_output(['pm2','jlist']));assert next(a for a in apps if a['pm_id']==10)['pm2_env']['pm_exec_path']==str(old/'serve.py')
new.mkdir(mode=0o700)
ignore={'__pycache__','logs','tmp','data','.git','test'}
shutil.copytree(old/'runtime',new/'runtime',copy_function=os.link,symlinks=True,ignore=lambda directory,names:[n for n in names if n in ignore or n.endswith('.pyc')])
(new/'runtime/data').mkdir();(new/'runtime/data/.config.yaml').symlink_to(root/'data/.config.yaml')
changed=[];frozen={}
for source in (s/'work').rglob('*'):
 rel=source.relative_to(s/'work')
 if not source.is_file() or source.is_symlink() or any(x in ignore|{'models','build','target'} for x in rel.parts) or source.suffix not in {'.py','.txt','.yaml','.yml','.json'} or str(rel)=='config.yaml':continue
 frozen[str(rel)]=hashlib.sha256(source.read_bytes()).hexdigest();target=new/'runtime'/rel
 if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==frozen[str(rel)]:continue
 target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name(target.name+'.followup-new');shutil.copy2(source,temp);os.replace(temp,target);changed.append(str(rel))
jar=s/'candidate-api-05.jar';e=json.loads((s/'api-package-evidence-05.json').read_text());assert e['all_other_entries_identical_to_production']
os.link(jar,new/'xiaozhi-esp32-api.jar')
start=(old/'start-manager-api.sh').read_text();assert start.count(str(old/'xiaozhi-esp32-api.jar'))==1
(new/'start-manager-api.sh').write_text(start.replace(str(old/'xiaozhi-esp32-api.jar'),str(new/'xiaozhi-esp32-api.jar')));(new/'start-manager-api.sh').chmod(0o700)
wrapper=(old/'serve.py').read_text().replace(str(old),str(new)).replace('/root/prjs/tmp/harness-stream-20261011','/root/prjs/tmp/hardware-followup-20261013').replace('18002/xiaozhi','18006/xiaozhi').replace('8170 if alternate else 8070','8270').replace('8173 if alternate else 8073','8273').replace('8176 if alternate else 8076','8276')
wrapper=wrapper.replace(' r=original(c);',' r=original(c);')
(new/'serve.py').write_text(wrapper)
manifest={'release':str(new),'rollback_release':str(old),'created':time.time(),'changed_source':changed,'candidate_work_hashes':frozen,'api_sha256':hashlib.sha256(jar.read_bytes()).hexdigest(),'rollback_api_sha256':hashlib.sha256((old/'xiaozhi-esp32-api.jar').read_bytes()).hexdigest(),'new_ports':[8270,8273,8276],'production_processes_changed':False,'immutable_baseline_hardlinked':True,'changed_files_replaced_atomically':True,'free_bytes':shutil.disk_usage('/').free}
(new/'release-manifest.json').write_text(json.dumps(manifest,indent=2));(s/'staged-release-manifest.json').write_text(json.dumps(manifest,indent=2));b.finish(charge,{'passed':True,'changed_sources':len(changed),'free_bytes':manifest['free_bytes']});print(json.dumps({'staged':str(new),'changed_sources':len(changed),'free_bytes':manifest['free_bytes']}))
