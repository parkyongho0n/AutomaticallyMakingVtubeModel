from __future__ import annotations
import json,os,signal,subprocess,sys,threading,time,uuid,fcntl
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .storage import atomic_json,identifier

class Jobs:
    def __init__(self,store,repo):
        self.owner=(store.root/'worker.lock').open('a')
        try:fcntl.flock(self.owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner.close();raise RuntimeError('이 데이터 폴더에서 이미 Studio가 실행 중입니다. 실행 중인 웹 화면을 사용하세요.')
        self.cancelled=set()
        self.store=store;self.repo=repo;self.pool=ThreadPoolExecutor(max_workers=1);self.lock=threading.RLock();self.procs={}
        for f in store.jobs.glob('*/job.json'):
            state=json.loads(f.read_text())
            if state['status'] in ['queued','running']:
                state.update(status='interrupted',error='프로그램이 재시작되었습니다. 같은 단계를 다시 실행하면 완료된 단계의 캐시를 재사용합니다.');atomic_json(f,state)
    def submit(self,pid,target,layer_id=None,prompt=''):
        if target not in ['assemble','rig','validate','package','generate']:raise ValueError('지원하지 않는 작업')
        project=self.store.load(pid)
        if target=='generate' and layer_id not in {l.id for l in project.layers}:raise ValueError('파츠를 찾을 수 없습니다.')
        jid=uuid.uuid4().hex[:16];d=self.store.jobs/jid;d.mkdir()
        project=self.store.snapshot(pid,d/'input')
        atomic_json(d/'request.json',{'target':target,'layer_id':layer_id,'prompt':prompt[:4000]})
        state={'id':jid,'project_id':pid,'revision':project.revision,'target':target,'status':'queued','created':time.time(),'progress':0,'steps':[]}
        atomic_json(d/'job.json',state);self.pool.submit(self._execute,jid);return state
    def _execute(self,jid):
        d=self.store.jobs/jid
        with self.lock:
            if self.get(jid)['status']=='cancelled':return
            log=(d/'run.log').open('w');env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+env.get('PYTHONPATH','');env['PYTHONUNBUFFERED']='1'
            proc=subprocess.Popen([sys.executable,'-m','astra_studio.worker',str(d),'--repo',str(self.repo)],stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            self.procs[jid]=proc
        code=proc.wait();log.close()
        with self.lock:
            self.procs.pop(jid,None);state=self.get(jid)
            if jid in self.cancelled:
                state.update(status='cancelled',finished=time.time());atomic_json(d/'job.json',state)
            elif state['status'] in ['queued','running']:
                state.update(status='failed',error=f'작업 프로세스가 종료되었습니다 (code {code}). 로그를 확인하세요.',finished=time.time());atomic_json(d/'job.json',state)
    def get(self,jid):return json.loads((self.store.jobs/identifier(jid)/'job.json').read_text())
    def list(self,pid=None):
        rows=[json.loads(f.read_text()) for f in self.store.jobs.glob('*/job.json')]
        return sorted([r for r in rows if pid is None or r['project_id']==pid],key=lambda r:r['created'],reverse=True)[:100]
    def cancel(self,jid):
        with self.lock:
            state=self.get(jid)
            if state['status'] not in ['running','queued']:return state
            self.cancelled.add(jid)
            proc=self.procs.get(jid)
            if proc and proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError:pass
            state.update(status='cancelled',finished=time.time());atomic_json(self.store.jobs/jid/'job.json',state);return state
    def close(self):
        for jid in list(self.procs):self.cancel(jid)
        for state in self.list():
            if state['status']=='queued':self.cancel(state['id'])
        self.pool.shutdown(wait=True,cancel_futures=True)
        self.owner.close()
