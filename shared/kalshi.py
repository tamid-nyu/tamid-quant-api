"""Read-only Kalshi v2 client. No account credentials or order execution."""
import hashlib,json,threading,time
from datetime import datetime,timezone
import requests
from fastapi import APIRouter,HTTPException,Query,Request
from shared import storage
BASE='https://api.elections.kalshi.com/trade-api/v2'
lock=threading.Lock();last_request=0.0
MEMORY={}

def get(path,params=None,ttl=60):
    global last_request
    params={k:v for k,v in (params or {}).items() if v is not None}
    key=hashlib.sha256(json.dumps([path,params],sort_keys=True).encode()).hexdigest()
    cached=MEMORY.get(key)
    if cached and time.time()-cached['at']<ttl:return cached['data']
    cached=storage.load('kalshi/cache/'+key+'.json')
    if cached and time.time()-cached['at']<ttl:
        MEMORY[key]=cached;return cached['data']
    for attempt in range(4):
        with lock:
            time.sleep(max(0,.18-(time.monotonic()-last_request)))
            last_request=time.monotonic()
            try:r=requests.get(BASE+path,params=params,timeout=20)
            except requests.RequestException:
                if attempt==3:raise HTTPException(502,'Kalshi request failed; retry later')
                continue
        if r.status_code==404:return None
        if r.status_code==429 or r.status_code>=500:
            time.sleep(min(2**attempt,8));continue
        if not r.ok:raise HTTPException(502,f'Kalshi returned {r.status_code}')
        data=r.json();entry={'at':time.time(),'data':data}
        storage.save('kalshi/cache/'+key+'.json',entry);MEMORY[key]=entry
        if len(MEMORY)>500:MEMORY.pop(next(iter(MEMORY)))
        return data
    raise HTTPException(502,'Kalshi unavailable after retries')

def markets_for_event(ticker):
    for path in ['/markets','/historical/markets']:
        items=[];cursor=None
        for _ in range(10):
            d=get(path,dict(event_ticker=ticker,limit=1000,cursor=cursor),3600) or {}
            items.extend(d.get('markets',[]));cursor=d.get('cursor')
            if not cursor:break
        if items:return items
    return []

def candle_data(series,ticker,start_ts,end_ts):
    params=dict(start_ts=start_ts,end_ts=end_ts,period_interval=60)
    for path in [f'/series/{series}/markets/{ticker}/candlesticks',f'/historical/markets/{ticker}/candlesticks']:
        d=get(path,params,86400)
        if d and d.get('candlesticks'):return d,path.startswith('/historical')
    return {'candlesticks':[]},False

router=APIRouter(prefix='/kalshi',tags=['Kalshi public market data'])
def query(request,allowed):
    extra=set(request.query_params)-set(allowed)
    if extra:raise HTTPException(422,'Unsupported query parameters: '+', '.join(sorted(extra)))
    return dict(request.query_params)
def missing(value):
    if value is None:raise HTTPException(404,'Kalshi resource not found')
    return value
@router.get('/series')
def series(request:Request):return get('/series',query(request,['category','tags','include_product_metadata']),3600)
@router.get('/series/{ticker}')
def series_detail(ticker:str):return missing(get('/series/'+ticker,ttl=3600))
@router.get('/events')
def events(request:Request):return get('/events',query(request,['series_ticker','status','cursor','limit','with_nested_markets','min_close_ts']))
@router.get('/events/{ticker}')
def event(ticker:str):return missing(get('/events/'+ticker,{'with_nested_markets':'true'}))
@router.get('/markets')
def markets(request:Request):return get('/markets',query(request,['series_ticker','event_ticker','status','limit','cursor','min_close_ts','max_close_ts','tickers']))
@router.get('/trades')
def trades(request:Request):return get('/markets/trades',query(request,['ticker','limit','cursor','min_ts','max_ts']))
@router.get('/settlements')
def settlements(series_ticker:str|None=None,cursor:str|None=None,limit:int=Query(100,ge=1,le=1000)):
    # Public settlement outcomes, not the authenticated portfolio settlements resource.
    return get('/markets',dict(status='settled',series_ticker=series_ticker,cursor=cursor,limit=limit),3600)
@router.get('/markets/{ticker}')
def market(ticker:str):return missing(get('/markets/'+ticker))
@router.get('/markets/{ticker}/orderbook')
def orderbook(ticker:str,depth:int=Query(10,ge=0,le=100)):return missing(get(f'/markets/{ticker}/orderbook',{'depth':depth},5))
@router.get('/markets/{ticker}/candlesticks')
def candles(ticker:str,series_ticker:str,start_ts:int,end_ts:int,period_interval:int=60):
    if period_interval not in (1,60,1440) or start_ts>=end_ts:raise HTTPException(422,'Use interval 1, 60 or 1440 and start_ts < end_ts')
    params=dict(start_ts=start_ts,end_ts=end_ts,period_interval=period_interval)
    d=get(f'/series/{series_ticker}/markets/{ticker}/candlesticks',params,3600)
    if not d or not d.get('candlesticks'):d=get(f'/historical/markets/{ticker}/candlesticks',params,3600)
    return missing(d)

def batch_candles(tickers,start_ts,end_ts):
    """Up to 100 contracts per documented request; archived data falls back per contract."""
    out={}
    for offset in range(0,len(tickers),100):
        group=tickers[offset:offset+100]
        try:
            d=get('/markets/candlesticks',dict(market_tickers=','.join(group),start_ts=start_ts,end_ts=end_ts,period_interval=60),86400) or {}
            for m in d.get('markets',[]):
                if m.get('candlesticks'):out[m['market_ticker']]={'candlesticks':m['candlesticks']}
        except HTTPException:
            # The single-contract historical endpoint remains the authority for archives.
            continue
    return out
