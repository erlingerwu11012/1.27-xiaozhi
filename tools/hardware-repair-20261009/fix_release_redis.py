from pathlib import Path
p=Path('tools/hardware-repair-20261009/release.py');s=p.read_text(encoding='utf-8').replace(' import redis,yaml',' import yaml')
s=s.replace(" return redis.Redis(host=v('host','127.0.0.1'),port=int(v('port',6379)),password=v('password',None),db=int(v('database',0)),socket_timeout=4)",''' class Redis:
  def execute(self,*args):
   with socket.create_connection((v('host','127.0.0.1'),int(v('port',6379))),timeout=4) as sock:
    stream=sock.makefile('rb')
    def call(*parts):
     values=[str(x).encode() for x in parts];sock.sendall(b'*'+str(len(values)).encode()+b'\\r\\n'+b''.join(b'$'+str(len(x)).encode()+b'\\r\\n'+x+b'\\r\\n' for x in values));line=stream.readline();kind=line[:1];body=line[1:-2]
     if kind==b'-':raise RuntimeError('redis_command_failed')
     if kind==b'$':
      size=int(body)
      if size<0:return None
      value=stream.read(size);assert stream.read(2)==b'\\r\\n';return value
     if kind==b':':return int(body)
     return body
    password=v('password',None)
    if password:
     username=v('username',None);call('AUTH',username,password) if username else call('AUTH',password)
    database=int(v('database',0))
    if database:call('SELECT',database)
    return call(*args)
  def ping(self):return self.execute('PING')==b'PONG'
  def hget(self,*a):return self.execute('HGET',*a)
  def hdel(self,*a):return self.execute('HDEL',*a)
  def delete(self,*a):return self.execute('DEL',*a)
 return Redis()''')
p.write_text(s,encoding='utf-8')
