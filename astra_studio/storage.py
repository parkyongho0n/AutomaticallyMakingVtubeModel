from __future__ import annotations
import base64, hashlib, io, json, re, shutil, threading, uuid
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from .models import Project, Layer, template_layers

class Conflict(Exception): pass

def identifier(value):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',value): raise ValueError('잘못된 ID')
    return value

def within(root: Path, relative: str):
    p=(root/relative).resolve()
    if not p.is_relative_to(root.resolve()) or p==root.resolve(): raise ValueError('잘못된 파일 경로')
    return p

def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)

def decode_image(data: str):
    if len(data)>44_000_000: raise ValueError('이미지는 32MB 이하여야 합니다.')
    try:
        raw=base64.b64decode(data,validate=True)
        im=Image.open(io.BytesIO(raw))
        if im.width*im.height>20_000_000: raise ValueError('이미지는 2천만 픽셀 이하여야 합니다.')
        im.load();return im.convert('RGBA')
    except (UnidentifiedImageError, OSError, ValueError) as e: raise ValueError('유효한 PNG/JPEG/WebP 이미지가 필요합니다.') from e

class Store:
    def __init__(self, root: Path):
        self.root=root.resolve();self.projects=self.root/'projects';self.jobs=self.root/'jobs'
        self.projects.mkdir(parents=True,exist_ok=True);self.jobs.mkdir(exist_ok=True)
        self.lock=threading.RLock()
    def directory(self,pid): return self.projects/identifier(pid)
    def load(self,pid): return Project.model_validate_json((self.directory(pid)/'project.json').read_text())
    def list(self):
        result=[]
        for f in self.projects.glob('*/project.json'):
            p=Project.model_validate_json(f.read_text());result.append({'id':p.id,'name':p.name,'revision':p.revision,'parts':sum(bool(l.image) for l in p.layers),'slots':len(p.layers),'profile':p.rig.profile})
        return result
    def create(self,name,canvas=(1254,1254)):
        pid=uuid.uuid4().hex[:16];p=Project(id=pid,name=name,canvas=canvas,layers=template_layers(canvas))
        (self.directory(pid)/'assets').mkdir(parents=True)
        self._write(p);return p
    def _write(self,p):
        atomic_json(self.directory(p.id)/'history'/f'{p.revision:06}.json',p.model_dump())
        atomic_json(self.directory(p.id)/'project.json',p.model_dump())
    def save(self,p,expected):
        with self.lock:
            current=self.load(p.id)
            if current.revision!=expected: raise Conflict('다른 변경 사항이 있습니다. 새로고침 후 다시 저장하세요.')
            for asset in [p.reference,*[l.image for l in p.layers]]:
                if asset and not within(self.directory(p.id),asset).is_file(): raise ValueError('존재하지 않는 자산')
            p=p.model_copy(update={'revision':current.revision+1});self._write(p);return p
    def asset(self,pid,image):
        buf=io.BytesIO();image.save(buf,format='PNG');raw=buf.getvalue()
        name='assets/'+hashlib.sha256(raw).hexdigest()+'.png';path=within(self.directory(pid),name)
        if not path.exists():path.write_bytes(raw)
        return name
    def upload(self,pid,data,expected,layer_id=None,reference=False):
        with self.lock:
            p=self.load(pid)
            if p.revision!=expected:raise Conflict('저장된 프로젝트가 변경되었습니다.')
            im=decode_image(data)
            if not reference:
                box=im.getbbox()
                if box is None:raise ValueError('완전히 투명한 파츠입니다.')
                im=im.crop(box)
            name=self.asset(pid,im)
            if reference:p.reference=name
            else:
                layer=next((l for l in p.layers if l.id==layer_id),None)
                if not layer:raise ValueError('파츠를 찾을 수 없습니다.')
                layer.image=name
            return self.save(p,expected)
    def restore(self,pid,revision,expected):
        if revision<0:raise ValueError('잘못된 버전')
        p=Project.model_validate_json((self.directory(pid)/'history'/f'{revision:06}.json').read_text())
        return self.save(p,expected)
    def snapshot(self,pid,dest):
        with self.lock:
            p=self.load(pid);dest.mkdir(parents=True,exist_ok=True)
            atomic_json(dest/'project.json',p.model_dump());(dest/'assets').mkdir(exist_ok=True)
            for name in set([p.reference,*[l.image for l in p.layers]])-{None}:
                shutil.copy2(within(self.directory(pid),name),within(dest,name))
            return p
    def import_astra(self,repo: Path):
        if not (repo/'output/parts/manifest.json').is_file():
            raise ValueError('마녀 예제 자산이 없습니다. astra-witch-vtuber 저장소를 별도로 받고 --repo 경로로 지정하세요. 새 프로젝트는 예제 없이 사용할 수 있습니다.')
        manifest=json.loads((repo/'output/parts/manifest.json').read_text())
        p=self.create('Astra Witch · 예제',tuple(manifest['canvas']));p.layers=[];p.rig.profile='astra'
        for item in manifest['parts']:
            im=Image.open(within(repo,item['file'])).convert('RGBA');name=self.asset(p.id,im);x,y,r,b=item['bbox'];n=item['name']
            clip=n.rsplit('_',1)[0]+'_White' if n.startswith('EYE_') and n.endswith(('_Iris','_Pupil','_Highlight')) else None
            p.layers.append(Layer(id=n,name=n,alias=item['alias'],image=name,rect=(x,y,r-x,b-y),visible=item['visible'],clip_to=clip,
                                  rig_include=not(n.startswith('BROW_') and not item['visible']),attachment='원본 파츠의 숨은 면과 연결부를 유지하세요.'))
        p.reference=self.asset(p.id,Image.open(repo/'assets/reference/main_reference.png').convert('RGBA'))
        p.notes='기존 최종 파츠를 복사한 독립 프로젝트입니다. astra 프리셋은 예제의 파츠 ID/별칭을 필요로 합니다.'
        return self.save(p,0)

    def import_archive(self, data):
        import zipfile
        raw=base64.b64decode(data,validate=True)
        if len(raw)>32_000_000:raise ValueError('프로젝트 ZIP은 32MB 이하여야 합니다.')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            entries=z.infolist()
            if len(entries)>202 or sum(e.file_size for e in entries)>160_000_000:raise ValueError('ZIP 확장 크기가 너무 큽니다.')
            if len({e.filename for e in entries})!=len(entries):raise ValueError('ZIP에 중복 경로가 있습니다.')
            for e in entries:
                if e.filename!='project.json' and not re.fullmatch(r'assets/[a-zA-Z0-9_-]+\.png',e.filename):raise ValueError('허용되지 않은 ZIP 경로')
            p=Project.model_validate_json(z.read('project.json'))
            refs=set([p.reference,*[l.image for l in p.layers]])-{None}
            # Validate all bytes before creating a project; never extract user paths.
            assets={n:decode_image(base64.b64encode(z.read(n)).decode()) for n in refs}
        p.id=uuid.uuid4().hex[:16];p.revision=0;(self.directory(p.id)/'assets').mkdir(parents=True)
        renamed={n:self.asset(p.id,im) for n,im in assets.items()}
        p.reference=renamed.get(p.reference)
        for l in p.layers:l.image=renamed.get(l.image)
        self._write(p);return p
