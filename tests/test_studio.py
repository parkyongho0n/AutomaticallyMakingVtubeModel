import base64,io,tempfile,time,unittest,zipfile
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from astra_studio.storage import Store,Conflict,within
from astra_studio.models import Layer,Project
from astra_studio.art import composite,assemble
from astra_studio.worker import fingerprints
from astra_studio.server import create_app
from astra_studio.jobs import Jobs
REPO=Path(__file__).resolve().parents[1]
class StudioTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=Store(self.root)
 def tearDown(self):self.temp.cleanup()
 def part(self):
  p=self.store.create('Test',(256,256));image=Image.new('RGBA',(30,30),'red');asset=self.store.asset(p.id,image);p.layers=[Layer(id='base',name='Base',alias='face',image=asset,rect=(10,10,30,30))];return self.store.save(p,0)
 def test_revision_restore_and_snapshot(self):
  p=self.part();self.store.snapshot(p.id,self.root/'snapshot');p.name='Changed';p=self.store.save(p,1)
  with self.assertRaises(Conflict):self.store.save(p,1)
  restored=self.store.restore(p.id,1,2);self.assertEqual(restored.revision,3);self.assertEqual(restored.name,'Test');self.assertEqual(Project.model_validate_json((self.root/'snapshot/project.json').read_text()).revision,1)
 def test_paths(self):
  for s in ['../secret','/etc/passwd']:
   with self.assertRaises(ValueError):within(self.root,s)
  with self.assertRaises(ValueError):Layer(id='x',name='x',alias='x',image='../x.png',rect=(0,0,2,2))
 def test_clipping_and_psd(self):
  p=self.part();blue=self.store.asset(p.id,Image.new('RGBA',(50,50),'blue'));p.layers.append(Layer(id='iris',name='Iris',alias='iris L',image=blue,rect=(0,0,50,50),clip_to='base'))
  im=composite(p,self.store.directory(p.id));self.assertEqual(im.getpixel((1,1))[3],0);self.assertEqual(im.getpixel((15,15)),(0,0,255,255));report=assemble(p,self.store.directory(p.id),self.root/'art');self.assertLess(report['psd_mae'],3)
 def test_cache_dependencies(self):
  p=self.part();a=fingerprints(p,self.store.directory(p.id),REPO);p.rig.head_strength=.7;b=fingerprints(p,self.store.directory(p.id),REPO);self.assertEqual(a['assemble'],b['assemble']);self.assertNotEqual(a['rig'],b['rig']);p.layers[0].rect=(20,10,30,30);c=fingerprints(p,self.store.directory(p.id),REPO);self.assertNotEqual(b['assemble'],c['assemble'])
 def test_zip_roundtrip_and_traversal(self):
  p=self.part()
  with TestClient(create_app(self.root,REPO)) as c:
   raw=c.get(f'/api/projects/{p.id}/archive').content
   r=c.post('/api/import-project',json={'data':base64.b64encode(raw).decode()});self.assertEqual(r.status_code,200);self.assertNotEqual(r.json()['id'],p.id);self.assertEqual(r.json()['layers'],p.model_dump(mode='json')['layers'])
   buf=io.BytesIO()
   with zipfile.ZipFile(buf,'w') as z:z.writestr('../evil','oops')
   self.assertEqual(c.post('/api/import-project',json={'data':base64.b64encode(buf.getvalue()).decode()}).status_code,400)
 def test_cancel_queued(self):
  from threading import Event
  p=self.part();j=Jobs(self.store,REPO);gate=Event();j.pool.submit(gate.wait)
  try:
   state=j.submit(p.id,'assemble');j.cancel(state['id']);gate.set();j.pool.shutdown(wait=True);self.assertEqual(j.get(state['id'])['status'],'cancelled');self.assertFalse((self.store.jobs/state['id']/'output').exists())
  finally:gate.set();j.close()
 def test_worker_lock(self):
  j=Jobs(self.store,REPO)
  try:
   with self.assertRaises(RuntimeError):Jobs(self.store,REPO)
  finally:j.close()
 def test_api_and_real_assembly_cache(self):
  p=self.part()
  with TestClient(create_app(self.root,REPO)) as c:
   self.assertEqual(c.get('/').status_code,200)
   self.assertEqual(c.post('/api/projects',json={'name':'x'},headers={'Origin':'https://evil.example'}).status_code,403)
   self.assertEqual(c.put('/api/projects/'+p.id,json={'project':p.model_dump(),'expected_revision':0}).status_code,409)
   for cached in [False,True]:
    j=c.post(f'/api/projects/{p.id}/jobs',json={'target':'assemble'}).json()
    for _ in range(150):
     state=c.get('/api/jobs/'+j['id']).json()
     if state['status'] not in ['queued','running']:break
     time.sleep(.1)
    self.assertEqual(state['status'],'completed',state);self.assertEqual(state['steps'][0]['cached'],cached)
   self.assertEqual(c.get(f"/api/jobs/{j['id']}/artifacts/assemble/layers.psd").status_code,200)
if __name__=='__main__':unittest.main()
