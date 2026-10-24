from __future__ import annotations
import argparse,json,os,time
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description='Astra Studio · local 2D → Live2D workbench')
    parser.add_argument('--data',type=Path,default=Path(os.getenv('ASTRA_STUDIO_DATA','studio_data')))
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--psd2live',help='PSD2Live executable (or PSD2LIVE_BIN)')
    parser.add_argument('--psd2live-source',help='Directory containing mcp_proxy.py')
    parser.add_argument('--bridge',help='Cubism native renderer bridge library')
    sub=parser.add_subparsers(dest='command',required=True)
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=7860)
    sub.add_parser('doctor');sub.add_parser('import-astra');sub.add_parser('list')
    create=sub.add_parser('create');create.add_argument('name')
    build=sub.add_parser('build');build.add_argument('project');build.add_argument('--target',choices=['assemble','rig','validate','package'],default='package')
    args=parser.parse_args()
    for attr,key in [('psd2live','PSD2LIVE_BIN'),('psd2live_source','PSD2LIVE_SOURCE'),('bridge','LIVE2D_BRIDGE')]:
        if getattr(args,attr):os.environ[key]=str(Path(getattr(args,attr)).resolve())
    from .storage import Store
    from .adapters import capabilities
    if args.command=='doctor':print(json.dumps(capabilities(),ensure_ascii=False,indent=2));return
    store=Store(args.data)
    if args.command=='import-astra':print(store.import_astra(args.repo.resolve()).id);return
    if args.command=='create':print(store.create(args.name).id);return
    if args.command=='list':print(json.dumps(store.list(),ensure_ascii=False,indent=2));return
    if args.command=='serve':
        import uvicorn
        from .server import create_app
        print(f'Astra Studio: http://127.0.0.1:{args.port}',flush=True)
        uvicorn.run(create_app(args.data,args.repo.resolve()),host='127.0.0.1',port=args.port);return
    from .jobs import Jobs
    jobs=Jobs(store,args.repo.resolve());job=jobs.submit(args.project,args.target)
    try:
        while True:
            state=jobs.get(job['id'])
            if state['status'] not in ['queued','running']:break
            time.sleep(.25)
        print(json.dumps(state,ensure_ascii=False,indent=2));print('Artifacts:',store.jobs/job['id']/'output')
        if state['status']!='completed':raise SystemExit(1)
    finally:jobs.close()
