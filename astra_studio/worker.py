from __future__ import annotations
import argparse,hashlib,json,os,shutil,sys,time,traceback,zipfile,uuid
from pathlib import Path
from .models import Project
from .storage import atomic_json
from .adapters import Blocked,capabilities,generate_part,rig
from .art import assemble
from .native import validate,references

STAGES=['assemble','rig','validate','package']

def digest(*values):return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def tool_signature(name):
    p=Path(os.getenv(name,'/nonexistent'))
    if not p.is_file():return None
    st=p.stat();return [str(p.resolve()),st.st_size,st.st_mtime_ns]

def fingerprints(project,root,repo):
    engine={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    images={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in set([project.reference,*[l.image for l in project.layers]])-{None}}
    art=digest(project.canvas,[l.model_dump() for l in project.layers],images,engine['art.py'])
    recipes={n:hashlib.sha256((repo/'scripts'/n).read_bytes()).hexdigest() for n in ['refine_rig.py','body_rig.py','finalize_bundle.py'] if (repo/'scripts'/n).is_file()}
    r=digest(art,project.rig.model_dump(),recipes,engine['adapters.py'],tool_signature('PSD2LIVE_BIN'),os.getenv('PSD2LIVE_SOURCE'),tool_signature('LIVE2D_BRIDGE'))
    v=digest(r,engine['native.py'],tool_signature('LIVE2D_BRIDGE'),os.getenv('DISPLAY'))
    return {'assemble':art,'rig':r,'validate':v,'package':digest(v,project.name,engine['worker.py'])}

def package(project,rigdir,validation,dest):
    dest.mkdir(parents=True,exist_ok=True);manifest,refs,names=references(rigdir);report=json.loads((validation/'report.json').read_text())
    readme=f'# {project.name}\n\nAstra Studio build.\n\nNative validation: {report["native_validated"]}\nRendered: {report["rendered"]}\n\n'
    readme+='\n'.join('- '+w for w in report.get('warnings',[]))+'\n\nWebcam/VTube Studio application testing was not performed. Review appearance and tracking before streaming.\n'
    hashes={n:hashlib.sha256((rigdir/n).read_bytes()).hexdigest() for n in names}
    with zipfile.ZipFile(dest/'model.zip','w',zipfile.ZIP_DEFLATED) as z:
        for n in names:z.write(rigdir/n,'Avatar/'+n)
        z.writestr('Avatar/READINESS.md',readme)
    with zipfile.ZipFile(dest/'model.zip') as z:
        if z.testzip():raise ValueError('ZIP 무결성 검사 실패')
        for n,h in hashes.items():
            if hashlib.sha256(z.read('Avatar/'+n)).hexdigest()!=h:raise ValueError('ZIP 해시 불일치')
    atomic_json(dest/'hashes.json',hashes);return {'files':len(names),'native_validated':report['native_validated'],'warnings':report['warnings']}

def run(jobdir:Path,repo:Path):
    spec=json.loads((jobdir/'request.json').read_text());project=Project.model_validate_json((jobdir/'input/project.json').read_text());output=jobdir/'output';output.mkdir(exist_ok=True)
    state=json.loads((jobdir/'job.json').read_text());state.update(status='running',started=time.time(),steps=[])
    def write(**changes):state.update(changes);atomic_json(jobdir/'job.json',state)
    write()
    try:
        if spec['target']=='generate':
            layer=next(l for l in project.layers if l.id==spec['layer_id'])
            write(stage='generate',progress=.2);generate_part(project,jobdir/'input',layer,spec.get('prompt',''),output/'generation');write(status='completed',progress=1,finished=time.time());return
        keys=fingerprints(project,jobdir/'input',repo);cache=jobdir.parent.parent/'cache';cache.mkdir(exist_ok=True)
        last=STAGES.index(spec['target'])
        for index,stage in enumerate(STAGES[:last+1]):
            write(stage=stage,progress=index/(last+1));print(f'[{stage}] starting',flush=True)
            dest=output/stage;entry=cache/stage/keys[stage];cached=(entry/'_success.json').is_file()
            if cached:
                shutil.copytree(entry,dest);info=json.loads((dest/'_success.json').read_text());print(f'[{stage}] cache hit',flush=True)
            else:
                if stage=='assemble':info=assemble(project,jobdir/'input',dest)
                elif stage=='rig':info=rig(project,output/'assemble',dest,jobdir/'work',repo)
                elif stage=='validate':info=validate(output/'rig',dest)
                else:info=package(project,output/'rig',output/'validate',dest)
                atomic_json(dest/'_success.json',info);entry.parent.mkdir(parents=True,exist_ok=True)
                if not entry.exists():
                    staging=entry.with_name(entry.name+'.tmp-'+uuid.uuid4().hex)
                    shutil.copytree(dest,staging);staging.rename(entry)
            state['steps'].append({'stage':stage,'cached':cached,'fingerprint':keys[stage]});write()
        write(status='completed',progress=1,finished=time.time())
    except Blocked as e:write(status='blocked',error=str(e),finished=time.time());print(str(e),flush=True)
    except Exception as e:
        write(status='failed',error=str(e)[:1200],finished=time.time());traceback.print_exc();sys.exit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job');p.add_argument('--repo',required=True);a=p.parse_args();run(Path(a.job).resolve(),Path(a.repo).resolve())
