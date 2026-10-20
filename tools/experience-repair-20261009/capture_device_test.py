"""Dual capture; selftest opens neither UART nor SSH. Start only after user consent."""
import argparse,base64,codecs,json,os,shutil,subprocess,threading,time
from pathlib import Path
FILES=['/root/.pm2/logs/xiaozhi-server-out.log','/root/.pm2/logs/xiaozhi-server-error.log']
READER='''
import os,json,base64,time
out=[]
for path in request['files']:
 try:
  with open(path,'rb') as f:
   st=os.fstat(f.fileno());identity=str(st.st_dev)+':'+str(st.st_ino);old=request['cursors'].get(path);offset=old['offset'] if old and old['identity']==identity else max(0,st.st_size-262144);reason=''
   if old and old['identity']!=identity:offset=0;reason='rotation_gap_risk'
   if offset>st.st_size:offset=0;reason='truncation_gap_risk'
   f.seek(offset);data=f.read(1048576);out.append(dict(path=path,identity=identity,start=offset,end=offset+len(data),size=st.st_size,data=base64.b64encode(data).decode(),reason=reason))
 except OSError as e:out.append(dict(path=path,error=type(e).__name__))
print(json.dumps(dict(server_ns=time.time_ns(),files=out)))
'''
def atomic(p,value):
 tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,p)
class Sink:
 def __init__(self,root,name,limit=33554432):
  self.root=root;self.name=name;self.limit=limit;self.part=0;self.size=0;self.total=0;self.file=None;self.index=(root/(name+'-index.jsonl')).open('a',encoding='utf-8',buffering=1)
 def write(self,data,**meta):
  if not data:return
  if self.file is None or self.size+len(data)>self.limit:
   if self.file:self.file.close()
   self.part+=1;self.size=0;self.path=self.root/(self.name+'-%04d.raw'%self.part);self.file=self.path.open('xb',buffering=0)
  start=self.size;self.file.write(data);self.size+=len(data);self.total+=len(data);self.index.write(json.dumps(dict(local_ns=time.time_ns(),monotonic_ns=time.monotonic_ns(),file=self.path.name,start=start,end=self.size,stream_end=self.total,**meta))+'\n')
 def sync(self):
  if self.file:os.fsync(self.file.fileno())
 def close(self):
  if self.file:self.file.close()
  self.index.close()
def selftest():
 import tempfile
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);sink=Sink(root,'test',limit=5);chunks=[b'abc',b'def',b'ghi']
  for c in chunks:sink.write(c)
  sink.close();assert b''.join(p.read_bytes() for p in sorted(root.glob('test-*.raw')))==b''.join(chunks);assert len((root/'test-index.jsonl').read_text().splitlines())==3
  atomic(root/'state.json',{'offset':9});assert json.loads((root/'state.json').read_text())['offset']==9
  decoder=codecs.getincrementaldecoder('utf-8')('replace');data='固件日志'.encode();assert decoder.decode(data[:4])+decoder.decode(data[4:],final=True)=='固件日志'
 print('PASS: raw preservation, rotation/index, atomic checkpoint, split UTF-8. No SSH/UART opened.')
def capture(a):
 import serial
 root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=False);stop=threading.Event();lock=threading.Lock();counts={};started=time.monotonic();ef=(root/'events.jsonl').open('a',encoding='utf-8',buffering=1)
 def event(kind,**kw):
  with lock:ef.write(json.dumps(dict(local_ns=time.time_ns(),event=kind,**kw),ensure_ascii=False)+'\n')
 port=serial.Serial(port=None,baudrate=115200,timeout=.1);port.port=a.port;port.dtr=False;port.rts=False
 try:port.open()
 except Exception:ef.close();raise
 atomic(root/'manifest.json',dict(port=a.port,baud=115200,server=a.server,files=FILES,started_ns=time.time_ns(),duration_seconds=a.seconds,stop_file=str(root/'STOP')))
 def uart():
  sink=Sink(root,'firmware');text=(root/'firmware.log').open('a',encoding='utf-8',buffering=1);decode=codecs.getincrementaldecoder('utf-8')('replace')
  try:
   while not stop.is_set():
    try:
     if not port.is_open:port.open();event('serial_reconnected',port=a.port)
     data=port.read(min(65536,max(1,port.in_waiting)))
     if data:sink.write(data);text.write(decode.decode(data));counts['firmware_bytes']=sink.total
    except serial.SerialException as exc:
     event('serial_gap',error=type(exc).__name__);port.close();stop.wait(1)
  except Exception as exc:event('serial_capture_failed',error=type(exc).__name__);stop.set()
  finally:text.write(decode.decode(b'',final=True));text.close();sink.close();port.close()
 def server():
  cursors={};sinks={p:Sink(root,'server-'+str(i)) for i,p in enumerate(FILES)};texts={p:(root/('server-'+str(i)+'.log')).open('a',encoding='utf-8',buffering=1) for i,p in enumerate(FILES)};decoders={p:codecs.getincrementaldecoder('utf-8')('replace') for p in FILES}
  try:
   while not stop.is_set():
    before=time.time_ns();request=base64.b64encode(json.dumps(dict(files=FILES,cursors=cursors)).encode()).decode();code="import json,base64;request=json.loads(base64.b64decode('"+request+"'));"+READER;encoded=base64.b64encode(code.encode()).decode()
    try:
     result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8',a.server,'python3 -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"'],capture_output=True,timeout=20)
     if result.returncode:raise RuntimeError('SSH_exit_'+str(result.returncode))
     obj=json.loads(result.stdout);after=time.time_ns();event('server_clock',offset_ns=obj['server_ns']-(before+after)//2,uncertainty_ns=(after-before)//2)
     for row in obj['files']:
      path=row['path']
      if row.get('error'):event('server_file_error',path=path,error=row['error']);continue
      if row['reason']:event('server_log_gap_risk',path=path,reason=row['reason'])
      data=base64.b64decode(row['data'],validate=True);assert len(data)==row['end']-row['start'];sinks[path].write(data,server_path=path,server_identity=row['identity'],server_start=row['start'],server_end=row['end']);sinks[path].sync();texts[path].write(decoders[path].decode(data));cursors[path]=dict(identity=row['identity'],offset=row['end']);counts['server_'+str(FILES.index(path))+'_bytes']=sinks[path].total
     atomic(root/'server-cursors.json',cursors)
    except Exception as exc:event('server_reconnect_pending',error=str(exc)[:100])
    stop.wait(2)
  except Exception as exc:event('server_capture_failed',error=type(exc).__name__);stop.set()
  finally:
   for p in FILES:texts[p].write(decoders[p].decode(b'',final=True));texts[p].close();sinks[p].close()
 threads=[threading.Thread(target=uart),threading.Thread(target=server)]
 for t in threads:t.start()
 try:
  while (a.seconds<=0 or time.monotonic()-started<a.seconds) and not stop.wait(1):
   atomic(root/'status.json',dict(at_ns=time.time_ns(),elapsed_seconds=round(time.monotonic()-started),counts=counts,active=True))
   if (root/'STOP').exists():break
   if shutil.disk_usage(root).free<536870912:event('disk_space_low');break
 except KeyboardInterrupt:pass
 finally:
  stop.set()
  for t in threads:t.join()
  event('capture_stopped',counts=counts);ef.close();atomic(root/'status.json',dict(at_ns=time.time_ns(),counts=counts,active=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--selftest',action='store_true');p.add_argument('--approved',action='store_true');p.add_argument('--port',default='COM7');p.add_argument('--server',default='root@121.40.239.140');p.add_argument('--seconds',type=int,default=14400);p.add_argument('--output');a=p.parse_args()
 if a.selftest:selftest()
 elif not a.approved or not a.output:p.error('Explicit human approval and a new output directory are required.')
 else:capture(a)

