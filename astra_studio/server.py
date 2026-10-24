from __future__ import annotations
import base64,io,json,os,re,zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .models import Project
from .storage import Store,Conflict,within,identifier
from .jobs import Jobs
from .adapters import capabilities,part_prompt
from .art import composite

class Create(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    width:int=Field(default=1254,ge=256,le=4096)
    height:int=Field(default=1254,ge=256,le=4096)
class Save(BaseModel):
    project:Project
    expected_revision:int=Field(ge=0)
class Upload(BaseModel):
    data:str=Field(max_length=44_000_000)
    expected_revision:int=Field(ge=0)
    layer_id:str|None=None
    reference:bool=False
class Archive(BaseModel):
    data:str=Field(max_length=44_000_000)

class Build(BaseModel):
    target:str='package'
    layer_id:str|None=None
    prompt:str=Field(default='',max_length=4000)
class Restore(BaseModel):
    revision:int=Field(ge=0)
    expected_revision:int=Field(ge=0)


def create_app(data:Path,repo:Path):
    store=Store(data);jobs=Jobs(store,repo)
    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()
    app=FastAPI(title='Astra Studio',version='0.1.0',lifespan=lifespan);app.state.store=store;app.state.jobs=jobs
    @app.middleware('http')
    async def local_only(request:Request,call_next):
        host=request.url.hostname or ''
        allowed={'127.0.0.1','localhost','::1','testserver'}|set(filter(None,os.getenv('ASTRA_ALLOWED_HOSTS','').split(',')))
        if host not in allowed:return JSONResponse({'detail':'허용되지 않은 호스트'},status_code=403)
        if not request.headers.get('content-length','0').isdigit():return JSONResponse({'detail':'잘못된 Content-Length'},status_code=400)
        if int(request.headers.get('content-length','0'))>45_000_000:return JSONResponse({'detail':'요청이 너무 큽니다.'},status_code=413)
        if request.method not in ['GET','HEAD','OPTIONS']:
            origin=request.headers.get('origin')
            if origin and urlparse(origin).netloc!=request.headers.get('host'):return JSONResponse({'detail':'다른 사이트의 변경 요청은 허용하지 않습니다.'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    @app.exception_handler(Conflict)
    async def conflict(request,error):return JSONResponse({'detail':str(error)},status_code=409)
    @app.exception_handler(ValueError)
    async def invalid(request,error):return JSONResponse({'detail':str(error)},status_code=400)
    @app.exception_handler(FileNotFoundError)
    async def missing(request,error):return JSONResponse({'detail':'프로젝트 또는 파일을 찾을 수 없습니다.'},status_code=404)
    @app.get('/api/capabilities')
    def doctor():return capabilities()
    @app.get('/api/projects')
    def projects():return store.list()
    @app.post('/api/projects')
    def create(body:Create):return store.create(body.name,(body.width,body.height))
    @app.post('/api/import-project')
    def import_project(body:Archive):
        try:return store.import_archive(body.data)
        except (zipfile.BadZipFile,KeyError) as e:raise ValueError('유효한 Studio 프로젝트 ZIP이 아닙니다.') from e
    @app.post('/api/examples/astra')
    def example():return store.import_astra(repo)
    @app.get('/api/projects/{pid}')
    def project(pid:str):return store.load(pid)
    @app.put('/api/projects/{pid}')
    def save(pid:str,body:Save):
        if body.project.id!=pid:raise ValueError('프로젝트 ID가 다릅니다.')
        return store.save(body.project,body.expected_revision)
    @app.post('/api/projects/{pid}/upload')
    def upload(pid:str,body:Upload):return store.upload(pid,body.data,body.expected_revision,body.layer_id,body.reference)
    @app.get('/api/projects/{pid}/assets/{name}')
    def asset(pid:str,name:str):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+\.png',name):raise ValueError('잘못된 이미지 이름')
        return FileResponse(within(store.directory(pid),'assets/'+name),media_type='image/png')
    @app.get('/api/projects/{pid}/preview')
    def preview(pid:str):
        p=store.load(pid);im=composite(p,store.directory(pid));buf=io.BytesIO();im.save(buf,format='PNG');return Response(buf.getvalue(),media_type='image/png')
    @app.get('/api/projects/{pid}/history')
    def history(pid:str):
        store.load(pid);return [json.loads(f.read_text()) for f in sorted((store.directory(pid)/'history').glob('*.json'),reverse=True)[:100]]
    @app.post('/api/projects/{pid}/restore')
    def restore(pid:str,body:Restore):return store.restore(pid,body.revision,body.expected_revision)
    @app.get('/api/projects/{pid}/archive')
    def archive(pid:str):
        p=store.load(pid);buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('project.json',p.model_dump_json(indent=2))
            for name in set([p.reference,*[l.image for l in p.layers]])-{None}:z.write(within(store.directory(pid),name),name)
        return Response(buf.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="astra-project.zip"'})
    @app.get('/api/projects/{pid}/prompts')
    def prompts(pid:str):
        p=store.load(pid);return {'project':p.name,'reference':p.reference,'parts':[{'id':l.id,'prompt':part_prompt(p,l),'suggested_rect':l.rect} for l in p.layers]}
    @app.post('/api/projects/{pid}/jobs')
    def build(pid:str,body:Build):return jobs.submit(pid,body.target,body.layer_id,body.prompt)
    @app.get('/api/jobs')
    def listing(project_id:str|None=None):return jobs.list(project_id)
    @app.get('/api/jobs/{jid}')
    def job(jid:str):
        data=jobs.get(jid);root=store.jobs/jid/'output'
        report=root/'validate/report.json'
        data['validation']=json.loads(report.read_text()) if report.is_file() else None
        data['artifacts']=[str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and not p.name.startswith('_') and p.suffix in ['.png','.gif','.mp4','.psd','.zip','.json','.moc3','.cmo3']]
        log=store.jobs/jid/'run.log';data['log']=log.read_text(errors='replace')[-16000:] if log.exists() else ''
        return data
    @app.post('/api/jobs/{jid}/cancel')
    def cancel(jid:str):return jobs.cancel(jid)
    @app.get('/api/jobs/{jid}/artifacts/{name:path}')
    def artifact(jid:str,name:str):
        jobs.get(jid);root=store.jobs/identifier(jid)/'output';p=within(root,name)
        if not p.is_file():raise FileNotFoundError()
        return FileResponse(p,filename=p.name if p.suffix in ['.zip','.psd','.moc3','.cmo3'] else None)
    @app.post('/api/projects/{pid}/apply-generation/{jid}')
    def apply(pid:str,jid:str,body:Restore):
        state=jobs.get(jid)
        if state['project_id']!=pid or state['target']!='generate' or state['status']!='completed':raise ValueError('적용할 수 없는 생성 결과')
        d=store.jobs/jid;spec=json.loads((d/'request.json').read_text());raw=(d/'output/generation/generated.png').read_bytes()
        return store.upload(pid,base64.b64encode(raw).decode(),body.expected_revision,spec['layer_id'])
    web=Path(__file__).parent/'web';app.mount('/',StaticFiles(directory=web,html=True),name='web')
    return app
