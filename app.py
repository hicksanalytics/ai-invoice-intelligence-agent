"""CLI and localhost dashboard. Run `python app.py --help`."""
import argparse
import base64
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from src.pipeline import ingest, approved_export
from src.database import rows, review, audit
BASE=Path(__file__).resolve().parent
DEFAULT_DB=BASE/'data'/'invoices.sqlite3'

def handler_for(db_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,status,payload,kind='application/json'):
            blob=json.dumps(payload).encode() if kind=='application/json' else payload
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(blob)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(blob)
        def do_GET(self):
            if self.headers.get('Host','') not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:
                return self.send(403,{'error':'Use this app through its local address.'})
            route=urlparse(self.path).path
            if route=='/api/documents': return self.send(200,rows(db_path))
            if route=='/api/export': return self.send(200,approved_export(db_path))
            if route.startswith('/api/audit/'):
                try: return self.send(200,audit(db_path,int(route.split('/')[-1])))
                except ValueError:return self.send(400,{'error':'Invalid document ID.'})
            files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
            if route in files:
                mime={'/':'text/html; charset=utf-8','/app.js':'application/javascript','/style.css':'text/css'}[route]
                return self.send(200,(BASE/'web'/files[route]).read_bytes(),mime)
            self.send(404,{'error':'Not found.'})
        def do_POST(self):
            # JSON-only same-origin mutations. Loopback binding is not authentication.
            origin=self.headers.get('Origin')
            host=self.headers.get('Host','')
            allowed_hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            if host not in allowed_hosts or (origin and origin not in {'http://'+h for h in allowed_hosts}):
                return self.send(403,{'error':'Requests must originate from this local app.'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.send(415,{'error':'Use application/json.'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>14*1024*1024: raise ValueError('Request exceeds upload limit or has no body.')
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict): raise ValueError('Request body must be an object.')
                if self.path=='/api/ingest':
                    data=base64.b64decode(body['data'],validate=True)
                    filename=Path(str(body['filename']).replace('\\','/')).name
                    result=ingest(data,filename,db_path,body.get('mode','demo'),body.get('model'),int(body.get('threshold_cents',1_000_000)))
                    return self.send(200,result)
                if self.path=='/api/review':
                    review(db_path,int(body['id']),body['action'],body['actor'],body['note'])
                    return self.send(200,{'ok':True})
                self.send(404,{'error':'Not found.'})
            except (ValueError,KeyError,TypeError) as e: self.send(400,{'error':str(e)})
    return Handler

def main():
    parser=argparse.ArgumentParser(description='Hicks Analytics Invoice Intelligence')
    parser.add_argument('--db',type=Path,default=DEFAULT_DB)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('demo',help='Load six synthetic invoices using the deterministic demo parser')
    load=sub.add_parser('ingest');load.add_argument('file',type=Path);load.add_argument('--mode',choices=['demo','ollama'],default='demo');load.add_argument('--model');load.add_argument('--threshold',type=int,default=1_000_000,help='USD cents; default $10,000')
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=8766)
    sub.add_parser('list')
    export=sub.add_parser('export');export.add_argument('--out',type=Path,default=BASE/'data'/'approved_invoices.json')
    args=parser.parse_args()
    if args.command=='demo':
        for file in sorted((BASE/'data'/'sample_invoices').glob('*.txt')):
            print(file.name,ingest(file.read_bytes(),file.name,args.db))
        print('Loaded synthetic samples. Next: python app.py serve')
    elif args.command=='ingest':print(json.dumps(ingest(args.file.read_bytes(),args.file.name,args.db,args.mode,args.model,args.threshold),indent=2))
    elif args.command=='list':
        for r in rows(args.db):print(r['id'],r['filename'],r['validation_status'],r['review_status'],', '.join(f['code'] for f in r['findings']) or r['error'] or 'No rule findings')
    elif args.command=='export':
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(approved_export(args.db),indent=2),encoding='utf-8');print(args.out)
    elif args.command=='serve':
        server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(args.db))
        print(f'Local review dashboard: http://127.0.0.1:{args.port}',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:server.server_close()
if __name__=='__main__':main()
