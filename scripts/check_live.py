"""Production acceptance checks. Never emits tokens. Writes small verification artifacts."""
import argparse,json,os
from pathlib import Path
from datetime import datetime,timezone
import requests
p=argparse.ArgumentParser();p.add_argument('--url',default='https://tamid-quant-api.vercel.app');p.add_argument('--token-file',default=str(Path.home()/'mcp/vercel/secrets/tamid-quant-api.token'));p.add_argument('--output',default='/tmp/tamid-live-checks.json');args=p.parse_args()
base=args.url.rstrip('/');token=os.getenv('LAB_API_TOKEN') or Path(args.token_file).read_text().strip();headers={'Authorization':'Bearer '+token}
report={'at':datetime.now(timezone.utc).isoformat(),'api':base,'checks':{}}
def req(method,path,**kwargs):
    r=requests.request(method,base+path,timeout=300,**kwargs);r.raise_for_status();return r
r=req('GET','/strategies/kalshi-tail/results');s=r.json()['summary'];assert abs(s['return_pct']-5.261)<.001 and abs(s['max_drawdown_pct']+5.454)<.001
report['checks']['dashboard']=s
r=req('GET','/api/openapi.json');assert '/strategies/kalshi-tail/runs' in r.json()['paths'];report['checks']['openapi']={'status':r.status_code,'paths':len(r.json()['paths'])}
r=requests.post(base+'/strategies/kalshi-tail/runs',json={},timeout=30);assert r.status_code==401;report['checks']['write_auth']={'without_token':r.status_code}
r=req('POST','/uploads',headers=headers,files={'file':('acceptance.csv',b'day,value\n2026-11-17,1\n','text/csv')},data={'kind':'custom','name':'Production acceptance check'});report['checks']['upload']={'status':r.status_code,'id':r.json()['id'],'rows':r.json()['rows']}
r=req('POST','/api/strategies/kalshi-tail/runs',headers=headers,json={'markets':['BTC'],'k':1,'C':.03,'end':'2026-11-11'});run=r.json();assert run['summary']['trades']==402 and abs(run['summary']['pnl']-52.61)<.005;report['checks']['backtest']={'status':r.status_code,'id':run['id'],'engine':run['engine'],'summary':run['summary'],'input_sha256':run['input_sha256']}
r=req('GET','/api/ingest/cron',headers=headers);log=r.json();assert log['status']=='ok';report['checks']['cron']={'status':r.status_code,**log}
Path(args.output).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
