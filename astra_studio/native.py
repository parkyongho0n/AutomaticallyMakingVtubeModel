"""Generic Cubism inspection and rendering. No SDK binary is redistributed."""
from __future__ import annotations
import ctypes as C,hashlib,json,os
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from .storage import within,atomic_json

REQUIRED='ParamAngleX ParamAngleY ParamAngleZ ParamEyeLOpen ParamEyeROpen ParamEyeBallX ParamEyeBallY ParamBrowLY ParamBrowRY ParamBrowLAngle ParamBrowRAngle ParamMouthOpenY ParamMouthForm ParamBodyAngleX ParamBreath'.split()

def references(root):
    meta=json.loads((root/'studio.json').read_text());manifest=root/meta['manifest'];model=json.loads(manifest.read_text());refs=model['FileReferences']
    names=[manifest.name,refs['Moc'],*refs.get('Textures',[])]
    names += [refs[k] for k in ['Physics','DisplayInfo','Pose','UserData'] if refs.get(k)]
    names += [e['File'] for e in refs.get('Expressions',[])]
    names += [e['File'] for es in refs.get('Motions',{}).values() for e in es]
    for name in names:
        if not within(root,name).is_file():raise ValueError(f'런타임 참조 파일이 없습니다: {name}')
    return manifest,refs,sorted(set(names))

def validate(root:Path,dest:Path):
    dest.mkdir(parents=True,exist_ok=True);manifest,refs,names=references(root)
    raw=within(root,refs['Moc']).read_bytes()
    report={'moc3_sha256':hashlib.sha256(raw).hexdigest(),'references_valid':True,'native_validated':False,'rendered':False,'webcam_tested':False,'vtube_studio_tested':False,'missing_parameters':[],'warnings':[]}
    bridge=os.getenv('LIVE2D_BRIDGE')
    if not bridge or not Path(bridge).is_file():
        report['warnings'].append('네이티브 브리지가 없어 MOC 일관성·파라미터·렌더 검사를 생략했습니다.');atomic_json(dest/'report.json',report);return report
    lib=C.CDLL(bridge);ptr=C.c_void_p;fp=C.POINTER(C.c_float);ip=C.POINTER(C.c_int)
    def fn(n,r,a):f=getattr(lib,n);f.restype=r;f.argtypes=a;return f
    def align(n,a):buf=C.create_string_buffer(n+a);return buf,(C.addressof(buf)+a-1)&~(a-1)
    buf,mp=align(len(raw),64);C.memmove(mp,raw,len(raw))
    if fn('csmHasMocConsistency',C.c_int,[ptr,C.c_uint])(mp,len(raw))!=1:raise ValueError('MOC3 일관성 검사 실패')
    moc=fn('csmReviveMocInPlace',ptr,[ptr,C.c_uint])(mp,len(raw));size=fn('csmGetSizeofModel',C.c_uint,[ptr])(moc)
    storage,sp=align(size,16);model=fn('csmInitializeModelInPlace',ptr,[ptr,ptr,C.c_uint])(moc,sp,size)
    if not model:raise ValueError('Cubism 모델 초기화 실패')
    n=fn('csmGetParameterCount',C.c_int,[ptr])(model);ids=fn('csmGetParameterIds',C.POINTER(C.c_char_p),[ptr])(model)
    values=fn('csmGetParameterValues',fp,[ptr])(model);defaults=fn('csmGetParameterDefaultValues',fp,[ptr])(model);low=fn('csmGetParameterMinimumValues',fp,[ptr])(model);high=fn('csmGetParameterMaximumValues',fp,[ptr])(model)
    params=[{'id':ids[k].decode(),'default':defaults[k],'min':low[k],'max':high[k]} for k in range(n)]
    count=fn('csmGetDrawableCount',C.c_int,[ptr])(model);counts=fn('csmGetDrawableVertexCounts',ip,[ptr])(model);verts=fn('csmGetDrawableVertexPositions',C.POINTER(fp),[ptr])(model);opacity=fn('csmGetDrawableOpacities',fp,[ptr])(model)
    update=fn('csmUpdateModel',None,[ptr])
    ic=fn('csmGetDrawableIndexCounts',ip,[ptr])(model);indices=fn('csmGetDrawableIndices',C.POINTER(C.POINTER(C.c_ushort)),[ptr])(model)
    triangles=[np.ctypeslib.as_array(indices[k],shape=(ic[k],)).copy().reshape(-1,3) for k in range(count)]
    def capture():
        update(model);vs=[np.ctypeslib.as_array(verts[k],shape=(counts[k]*2,)).copy().reshape(-1,2) for k in range(count)]
        return vs,np.ctypeslib.as_array(opacity,shape=(count,)).copy()
    def areas(vs):
        result=[]
        for v,t in zip(vs,triangles):
            q=v[t];a=q[:,1]-q[:,0];b=q[:,2]-q[:,0];result.append(a[:,0]*b[:,1]-a[:,1]*b[:,0])
        return result
    for k in range(n):values[k]=defaults[k]
    base,base_o=capture();base_area=areas(base);responses={};foldovers=[]
    for k,q in enumerate(params):
        peak=op_peak=0.
        for value in [low[k],high[k]]:
            values[k]=value;vs,op=capture()
            if any(not np.isfinite(v).all() for v in vs) or not np.isfinite(op).all():raise ValueError('비정상 메쉬 좌표')
            peak=max(peak,max((float(np.max(abs(v-b))) for v,b in zip(vs,base) if len(v)),default=0));op_peak=max(op_peak,float(np.max(abs(op-base_o))))
            for d,(a,b) in enumerate(zip(areas(vs),base_area)):
                if op[d]>.05 and ((a*b<0)&(abs(a)>1e-8)&(abs(b)>1e-8)).any():foldovers.append({'parameter':q['id'],'value':float(value),'drawable':d})
        values[k]=defaults[k];capture();responses[q['id']]={'geometry_delta':peak,'opacity_delta':op_peak,'responsive':peak>1e-7 or op_peak>1e-7}
    missing=[p for p in REQUIRED if p not in responses];unresponsive=[p for p in REQUIRED if p in responses and not responses[p]['responsive']]
    report.update(native_validated=True,parameters=params,parameter_count=n,drawable_count=count,missing_parameters=missing,unresponsive_parameters=unresponsive,responses=responses,visible_foldovers=foldovers,geometry_samples=n*2+1)
    if missing:report['warnings'].append('필수 추적 파라미터 누락: '+', '.join(missing))
    if unresponsive:report['warnings'].append('반응하지 않는 추적 파라미터: '+', '.join(unresponsive))
    if foldovers:report['warnings'].append('일부 파라미터 극값에서 메쉬 뒤집힘이 관찰됐습니다. 범위를 줄이거나 리깅을 수정하세요.')
    if os.getenv('DISPLAY'):
        init=fn('Live2D_InitOffscreen',C.c_int,[])
        if init():
            h=fn('Live2D_CreateModel',ptr,[C.c_char_p])(str(manifest).encode())
            if not h:raise RuntimeError('네이티브 렌더 모델 생성 실패')
            setp=fn('Live2D_SetParameterValue',None,[ptr,C.c_char_p,C.c_float]);refresh=fn('Live2D_RefreshModel',None,[ptr]);render=fn('Live2D_RenderToRgba',C.c_int,[ptr,C.c_int,C.c_int,C.c_float,C.c_float,C.c_float,ptr])
            poses={'neutral':{},'left':{'ParamAngleX':-20},'right':{'ParamAngleX':20},'up':{'ParamAngleY':15},'down':{'ParamAngleY':-15},'blink':{'ParamEyeLOpen':0,'ParamEyeROpen':0},'mouth':{'ParamMouthOpenY':1},'smile':{'ParamMouthForm':1},'body_left':{'ParamBodyAngleX':-8},'body_right':{'ParamBodyAngleX':8},'breath':{'ParamBreath':1},'combined':{'ParamAngleX':20,'ParamAngleY':10,'ParamBodyAngleX':8,'ParamMouthOpenY':.6}}
            sheet=Image.new('RGB',(4*256,3*280),'#211e2b');draw=ImageDraw.Draw(sheet)
            for idx,(name,pose) in enumerate(poses.items()):
                for q in params:setp(h,q['id'].encode(),pose.get(q['id'],q['default']))
                refresh(h);pixels=(C.c_ubyte*(768*768*4))()
                if not render(h,768,768,1,0,0,pixels):raise RuntimeError('렌더 실패')
                im=Image.frombytes('RGBA',(768,768),bytes(pixels));im.save(dest/(name+'.png'));small=im.resize((256,256));x=idx%4*256;y=idx//4*280;sheet.paste(small,(x,y+24),small);draw.text((x+8,y+6),name,fill='white')
            sheet.save(dest/'contact_sheet.png');report['rendered']=True
            atomic_json(dest/'poses.json',poses)
        else:report['warnings'].append('그래픽 컨텍스트 초기화 실패: 정지 렌더 생략')
    else:report['warnings'].append('DISPLAY가 없어 정지 렌더를 생략했습니다.')
    report['scope']='일반 자동 검사: 파일 참조, Core 일관성, 단일 축 반응/뒤집힘, 12개 렌더. 미적 품질·눈 가림·실제 물리 감쇠·장시간 추적은 별도 검토가 필요합니다.'
    atomic_json(dest/'report.json',report);return report
