from __future__ import annotations
import base64,json,os,re,shutil,socket,subprocess,sys,time,urllib.request,uuid
from pathlib import Path
from .storage import atomic_json

class Blocked(RuntimeError): pass

def capabilities():
    binary=os.getenv('PSD2LIVE_BIN') or shutil.which('PSD2Live')
    source=os.getenv('PSD2LIVE_SOURCE','')
    bridge=os.getenv('LIVE2D_BRIDGE','')
    return {'exporter':bool(binary and Path(binary).is_file()),'exporter_path':binary,
            'mcp':bool(source and (Path(source)/'mcp_proxy.py').is_file()),
            'native_validation':bool(bridge and Path(bridge).is_file()),
            'render_display':bool(os.getenv('DISPLAY')),'image_generation':bool(os.getenv('OPENAI_API_KEY')),
            'image_model':os.getenv('ASTRA_IMAGE_MODEL','gpt-image-1'),
            'notes':['MOC3 내보내기에는 별도 PSD2Live 설치가 필요합니다.','이미지 생성은 API 설정 후 요청한 파츠에만 실행합니다.']}

def part_prompt(project,layer,request=''):
    return (f'Create exactly ONE complete isolated Live2D character part: {layer.name} ({layer.alias}). '
            'Use the attached character reference as the sole visual design reference. Preserve character identity, palette, costume and anime rendering style. '
            'Transparent background. Fully paint hidden attachment roots and occluded surfaces. No assembled character, labels, duplicate features, or other parts. '
            'For a face base omit eyes/brows/mouth; for hair include full roots; for clothing include hidden fabric tabs. '
            f'Part attachment requirements: {layer.attachment}. User direction: {request}')

def generate_part(project,root,layer,request,dest):
    key=os.getenv('OPENAI_API_KEY')
    if not key:raise Blocked('OPENAI_API_KEY가 없습니다. 프롬프트를 다운로드하거나 생성한 파츠를 직접 업로드하세요.')
    if not project.reference:raise Blocked('기준 이미지를 먼저 등록하세요.')
    boundary='astra-'+uuid.uuid4().hex;body=[]
    def field(name,value):body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for n,v in {'model':os.getenv('ASTRA_IMAGE_MODEL','gpt-image-1'),'prompt':part_prompt(project,layer,request),'size':'1024x1024','background':'transparent','output_format':'png','n':'1'}.items():field(n,v)
    body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="reference.png"\r\nContent-Type: image/png\r\n\r\n'.encode())
    body.append((root/project.reference).read_bytes());body.append(f'\r\n--{boundary}--\r\n'.encode())
    endpoint=os.getenv('ASTRA_IMAGE_BASE_URL','https://api.openai.com/v1').rstrip('/')+'/images/edits'
    req=urllib.request.Request(endpoint,data=b''.join(body),headers={'Authorization':'Bearer '+key,'Content-Type':'multipart/form-data; boundary='+boundary})
    # Do not propagate provider response bodies or credentials into public job logs.
    try:
        with urllib.request.urlopen(req,timeout=300) as res:data=json.load(res)
        raw=base64.b64decode(data['data'][0]['b64_json'],validate=True)
    except Exception as e:raise RuntimeError(f'이미지 제공자 요청 실패 ({type(e).__name__}). API 설정과 모델 접근 권한을 확인하세요.') from None
    from PIL import Image
    import io
    im=Image.open(io.BytesIO(raw));im.load()
    if im.width*im.height>20_000_000:raise ValueError('생성 이미지가 너무 큽니다.')
    im=im.convert('RGBA');box=im.getbbox()
    if not box:raise ValueError('빈 이미지가 반환되었습니다.')
    dest.mkdir(parents=True,exist_ok=True);im.crop(box).save(dest/'generated.png')
    atomic_json(dest/'provenance.json',{'provider':'OpenAI-compatible image edits','model':os.getenv('ASTRA_IMAGE_MODEL','gpt-image-1'),'layer_id':layer.id,'prompt':part_prompt(project,layer,request),'source_revision':project.revision})

class MCPSession:
    def __enter__(self):
        from tempfile import TemporaryDirectory
        self.tmp=TemporaryDirectory(prefix='astra-mcp-');self.log=Path(self.tmp.name)/'service.log'
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        self.stream=self.log.open('w');binary=capabilities()['exporter_path']
        self.proc=subprocess.Popen([binary,'mcp','--port',str(port),'--store',self.tmp.name+'/store'],stdout=self.stream,stderr=subprocess.STDOUT)
        try:
            for _ in range(600):
                text=self.log.read_text(errors='replace');m=re.search(r'^token\s+(\S+)',text,re.M)
                if m:break
                if self.proc.poll() is not None:raise RuntimeError('전용 MCP 서비스를 시작하지 못했습니다.')
                time.sleep(.1)
            else:raise RuntimeError('MCP 시작 시간이 초과되었습니다.')
            os.environ['PSD2LIVE_MCP_ENDPOINT']=f'http://127.0.0.1:{port}/mcp';os.environ['PSD2LIVE_MCP_TOKEN']=m.group(1)
            sys.path.insert(0,os.environ['PSD2LIVE_SOURCE'])
            from mcp_proxy import Client
            self.client=Client(timeout=240);self.client.__enter__();return self.client
        except BaseException:self.close();raise
    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
        self.stream.close();self.tmp.cleanup()
    def __exit__(self,*args):
        try:self.client.__exit__(*args)
        finally:self.close()

def rig(project,art,dest,work,repo):
    caps=capabilities()
    if not caps['exporter']:raise Blocked('PSD2LIVE_BIN을 설정하세요. PSD와 조립 이미지는 제작되었습니다.')
    if project.rig.profile=='astra' and not all((repo/'scripts'/n).is_file() for n in ['refine_rig.py','body_rig.py','finalize_bundle.py']):
        raise Blocked('Astra 전용 스크립트가 없습니다. --repo에 astra-witch-vtuber 저장소 경로를 지정하세요. 다른 캐릭터는 범용 프리셋을 사용하세요.')
    profile=project.rig.profile;name='witch' if profile=='astra' else 'model'
    inp=work/(name+'.psd');work.mkdir(parents=True,exist_ok=True);shutil.copy2(art/'model.psd',inp)
    native=work/'output/live2d';native.mkdir(parents=True,exist_ok=True)
    cfg=project.rig
    subprocess.run([caps['exporter_path'],'--input',str(inp),'--output',str(native),'--mesh-spacing',str(cfg.mesh_spacing),
                    '--head-strength',str(cfg.head_strength),'--body-strength',str(cfg.body_strength),'--lang','en'],check=True,timeout=600)
    if profile=='astra':
        if not caps['mcp']:raise Blocked('Astra 고급 프리셋은 PSD2LIVE_SOURCE의 mcp_proxy.py가 필요합니다.')
        scripts=work/'scripts';scripts.mkdir(exist_ok=True);(work/'output/reports').mkdir(exist_ok=True)
        for fn in ['refine_rig.py','body_rig.py','finalize_bundle.py']:
            shutil.copy2(repo/'scripts'/fn,scripts/fn)
        with MCPSession() as c:
            c.edit('project_import_cmo3',path=str(native/'witch.cmo3'),mode='new',discard_unsaved=True)
            subprocess.run([sys.executable,str(scripts/'refine_rig.py')],env=os.environ.copy(),check=True,timeout=600)
            subprocess.run([sys.executable,str(scripts/'finalize_bundle.py')],check=True,timeout=60)
    elif caps['mcp']:
        meta=json.loads((native/'model.psd2live.json').read_text());aliases={l['source']:l['drawable'] for l in meta['layers']}
        with MCPSession() as c:
            c.edit('project_import_cmo3',path=str(native/'model.cmo3'),mode='new',discard_unsaved=True)
            for side in ['L','R']:
                if 'brow '+side in aliases:
                    c.edit('author_axis',parameter={'id':f'ParamBrow{side}Angle','min':-1,'max':1,'default':0},shapes=[{'target':'mesh:'+aliases['brow '+side],'value':v,'operations':[{'type':'rotate','degrees':v*10}]} for v in [-1,1]])
            c.edit('project_export_model',output_directory=str(native))
    manifest=native/(name+'.model3.json')
    if not manifest.is_file() or not (native/(name+'.moc3')).is_file():raise RuntimeError('내보내기가 실행 가능한 모델을 생성하지 않았습니다.')
    if profile=='standard':
        data=json.loads(manifest.read_text());cdi=json.loads((native/(name+'.cdi3.json')).read_text());ids={p['Id'] for p in cdi.get('Parameters',[])}
        expressions={'neutral':{},'smile':{'ParamMouthForm':.8},'angry':{'ParamBrowLAngle':-.7,'ParamBrowRAngle':.7,'ParamMouthForm':-.5},'sad':{'ParamMouthForm':-.6,'ParamBrowLY':-.3,'ParamBrowRY':-.3},'surprised':{'ParamMouthOpenY':.5,'ParamBrowLY':.6,'ParamBrowRY':.6},'eye_smile':{'ParamEyeLOpen':0,'ParamEyeROpen':0,'ParamMouthForm':.8}}
        data['FileReferences']['Expressions']=[]
        for n,vals in expressions.items():
            rel=f'expressions/{n}.exp3.json';atomic_json(native/rel,{'Type':'Live2D Expression','FadeInTime':.2,'FadeOutTime':.2,'Parameters':[{'Id':k,'Value':v,'Blend':'Multiply' if 'Open' in k and v==0 else 'Add'} for k,v in vals.items() if k in ids]})
            data['FileReferences']['Expressions'].append({'Name':n,'File':rel})
        atomic_json(manifest,data)
    shutil.copytree(native,dest,dirs_exist_ok=True)
    atomic_json(dest/'studio.json',{'manifest':manifest.name,'profile':profile,'grade':'specialized-template' if profile=='astra' else 'automatic-draft','note':'자동 리깅은 원본 외형 및 추적 품질에 대한 수동 검토를 대신하지 않습니다.'})
    return {'manifest':manifest.name,'profile':profile}
