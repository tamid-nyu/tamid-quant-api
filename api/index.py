import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from strategies.kalshi_tail.results import dashboard,dataset,records
app=FastAPI(title='TAMID Quant API',version='1.0.0',description='Shared research API. Public reads; authenticated writes. Research simulations, no order execution.')
app.add_middleware(CORSMiddleware,allow_origins=['https://kalshi-tail-web.vercel.app','http://localhost:3000'],allow_methods=['GET','POST','DELETE'],allow_headers=['Authorization','Content-Type'])
@app.get('/health')
def health(): return {'status':'ok','service':'tamid-quant-api'}
@app.get('/strategies/kalshi-tail/results')
def results(dataset: str='btc'): 
    try:return dashboard(dataset)
    except ValueError as e:raise HTTPException(422,str(e))
@app.get('/strategies/kalshi-tail/daily')
def daily(dataset_name: str='btc'):return records(dataset(dataset_name)[0])
@app.get('/strategies/kalshi-tail/trades')
def trades(dataset_name: str='btc',market: str|None=None,side: int|None=None,start: str|None=None,end: str|None=None,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=5000)):
    tr=dataset(dataset_name)[1]
    for col,val in [('market',market),('side',side)]:
        if val is not None:tr=tr[tr[col]==val]
    if start:tr=tr[tr.day>=start]
    if end:tr=tr[tr.day<=end]
    return {'total':len(tr),'items':records(tr.iloc[offset:offset+limit])}
@app.get('/strategies/kalshi-tail/forward-test')
def forward():return dashboard()['forward']
# Both URL styles are supported for direct clients and Vercel routing.
@app.middleware('http')
async def api_prefix(request,call_next):
    p=request.scope['path']
    if p.startswith('/api/'):request.scope['path']=p[4:]
    return await call_next(request)
