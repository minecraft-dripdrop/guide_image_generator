# -*- coding: utf-8 -*-
"""Local-only MILP backend for v15 browser UI. Python >= 3.9; numpy/scipy installed."""
import json, os, sys, webbrowser, threading, time, traceback
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit
from solver_engine import run_model

ROOT=Path(__file__).resolve().parent
PORT=18771

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT),**kwargs)
    def end_headers(self):
        origin=self.headers.get('Origin','')
        if origin in ('http://127.0.0.1:18771','null'):
            self.send_header('Access-Control-Allow-Origin',origin)
        self.send_header('Access-Control-Allow-Methods','POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        super().end_headers()
    def do_OPTIONS(self):
        self.send_response(204);self.end_headers()
    def do_POST(self):
        if urlsplit(self.path).path!='/api/solve':
            self.send_error(404);return
        # Refuse remote browsers, strictly bind loopback and do not expose internet API
        if self.client_address[0] not in ('127.0.0.1','::1') or self.headers.get('Origin','') not in ('','http://127.0.0.1:18771','null'):
            self.send_error(403);return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>2_000_000:raise ValueError('数据为空或过大')
            params=json.loads(self.rfile.read(n).decode('utf-8'))
            cfg=params['config'];scope=params.get('scope','C')
            limit=min(max(float(params.get('seconds',30)),5),600)
            routes=['A','B','C'] if scope=='ABC' else ['C']
            results=[]
            for sc in cfg['scenarios']:
                trials=[]
                for route in routes:
                    first=run_model(cfg,route,sc['coins'],'jade',time_limit=limit)
                    chosen=first;second=None
                    if first.get('solution') and first.get('status')==0:
                        second=run_model(cfg,route,sc['coins'],'yuan',jade_cap=first['solution']['jade'],time_limit=limit)
                        if second.get('solution'):chosen=second
                    trials.append(dict(route=route,first=first,second=second,chosen=chosen,
                        certifiedJade=(first.get('status')==0 and bool(first.get('solution'))),
                        certifiedYuan=(first.get('status')==0 and bool(first.get('solution')) and second is not None and second.get('status')==0)))
                feasible=[t for t in trials if t['chosen'].get('solution')]
                feasible.sort(key=lambda t:(t['chosen']['solution']['jade'],t['chosen']['solution']['yuan']))
                results.append(dict(name=sc['name'],trials=trials,best=feasible[0]['route'] if feasible else None))
            ret={'type':'complete','config':{k:cfg.get(k) for k in ('game','target','names','assumptions','tiers')},'scenarios':results}
            body=json.dumps(ret,ensure_ascii=False,default=lambda x: x.item() if hasattr(x,'item') else str(x)).encode('utf8')
            self.send_response(200);self.send_header('Content-Type','application/json;charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        except Exception as ex:
            traceback.print_exc()
            body=json.dumps({'type':'error','message':str(ex)},ensure_ascii=False).encode('utf8')
            self.send_response(500);self.send_header('Content-Type','application/json;charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

if __name__=='__main__':
    try:
        import numpy,scipy
        print('NumPy',numpy.__version__,'SciPy',scipy.__version__)
    except ImportError:
        raise SystemExit('缺少依赖。先运行 python -m pip install numpy scipy')
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    print(f'本地求解器已启动：http://127.0.0.1:{PORT}/')
    print('已绑定本机 127.0.0.1，不对外提供服务。按 Ctrl+C 退出。')
    threading.Timer(1.0,lambda:webbrowser.open(f'http://127.0.0.1:{PORT}/index.html')).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    server.server_close()
