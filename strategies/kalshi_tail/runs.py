"""Run the unchanged source engine, preserving input row order for LP reproducibility."""
import hashlib,json,uuid
from datetime import date,datetime,timezone
from typing import Literal
import numpy as np
import pandas as pd
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field,model_validator
from shared import storage
from shared.auth import require_write
from strategies.kalshi_tail.observations import load,multi_tail,tail_strategy
from strategies.kalshi_tail.results import metrics,records
router=APIRouter(prefix='/strategies/kalshi-tail',tags=['Backtests'])
class RunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    markets:list[Literal['BTC','SPX','GOLD','WTI','NATGAS','NDX','SILVER']]=Field(default_factory=lambda:['BTC'],min_length=1,max_length=7)
    cap:float=Field(.03,gt=0,le=.2,description='Per-market cap c as a bankroll fraction')
    k:int=Field(1,ge=1,le=7)
    C:float=Field(.03,gt=0,le=.5,description='k-worst cap as a bankroll fraction')
    slip:float=Field(.02,ge=0,le=.2)
    q_max:int=Field(50,ge=1,le=1000)
    estimator:Literal['S','P']='S'
    start:date|None=None
    end:date|None=None
    variant:Literal['base','#5','#7']='base'
    upload_id:str|None=Field(None,pattern=r'^[a-f0-9]{32}$')
    min_history_days:int=Field(150,ge=30,le=1000,description='150 is frozen; lower settings are exploratory')
    @model_validator(mode='after')
    def valid(self):
        if self.start and self.end and self.start>self.end:raise ValueError('start must not be after end')
        if self.variant!='base' and (set(self.markets)!={'BTC'} or self.estimator!='S'):raise ValueError('#5 and #7 are BTC-only variants with estimator S')
        if self.variant!='base' and (self.k!=1 or abs(self.C-self.cap)>1e-12):raise ValueError('#5 and #7 use BTC portfolio sizing: set k=1 and C=cap')
        if len(self.markets)!=len(set(self.markets)):raise ValueError('Market list must be unique')
        return self

def execute(body,obs=None):
    obs=load(body.markets,body.upload_id) if obs is None else obs
    if body.end:obs=obs[obs.day<=body.end]
    counts={str(k):int(v) for k,v in obs.groupby('market').day.nunique().items()}
    missing=[k for k in body.markets if counts.get(k,0)<body.min_history_days]
    if missing:raise HTTPException(422,dict(message='Insufficient stored observation history. Upload observations or ingest more expiry days.',required_days=body.min_history_days,available=counts,markets=missing))
    # Hash the exact ordered input including model-prior columns, so every run identifies its evidence.
    input_hash=hashlib.sha256(obs.to_csv(index=False).encode()).hexdigest()
    if body.variant=='base':
        cfg=multi_tail.MultiConfig(cap_m=body.cap,k=body.k,cap_k=body.C,slip=body.slip,q_max=body.q_max,estimator=body.estimator)
        tr,dy,md=multi_tail.run(obs,cfg)
        engine='multi_tail.run'
    else:
        if obs[['p_ewma_fhs']].isna().any().any():raise HTTPException(422,'Numbered variants need model probability p_ewma_fhs for every observation')
        cfg=tail_strategy.Config(cap_frac=body.cap,slip=body.slip,q_max=body.q_max,**({'prior':'model'} if body.variant=='#5' else {'estimator':'logit'}))
        tr,dy=tail_strategy.run(obs,cfg);tr['market']='BTC'
        md=tr.groupby(['day','market'],as_index=False).agg(pnl=('pnl','sum'),n_trades=('pnl','size'))
        engine='tail_strategy.run'
    # Preserve all earlier observations for training; date range only selects reported results.
    if body.start:
        tr=tr[tr.day>=body.start];dy=dy[dy.day>=body.start];md=md[md.day>=body.start]
    if dy.empty:raise HTTPException(422,'No observed expiry days in the selected result window')
    dy=dy.copy();dy['equity']=1000+dy.pnl.cumsum();dy['drawdown']=(dy.equity-1000-(dy.equity-1000).clip(lower=0).cummax())/10
    return dict(summary=metrics(dy),trades=records(tr),daily=records(dy),market_daily=records(md),engine=engine,
                input_sha256=input_hash,history_days=counts,observations=len(obs),
                source_commit=(__import__('pathlib').Path(__file__).resolve().parents[2]/'engine/SOURCE_COMMIT').read_text().strip(),
                warning='Exploratory configuration' if body.min_history_days<150 or body.variant!='base' or set(body.markets)-{'BTC','SPX'} else None)

@router.post('/runs',dependencies=[Depends(require_write)],status_code=201)
def create_run(body:RunRequest):
    ident=uuid.uuid4().hex
    item=dict(id=ident,created=datetime.now(timezone.utc).isoformat(),status='running',parameters=body.model_dump(mode='json'))
    storage.save(f'runs/{ident}/metadata.json',item)
    try:
        result=execute(body)
        storage.save(f'runs/{ident}/result.json',result)
        item.update(status='completed',summary=result['summary'],engine=result['engine'],input_sha256=result['input_sha256'],warning=result['warning'])
    except Exception as e:
        item.update(status='failed',error=e.detail if isinstance(e,HTTPException) else str(e)[:500])
        storage.save(f'runs/{ident}/metadata.json',item)
        if isinstance(e,HTTPException):raise
        raise HTTPException(422,{'run_id':ident,'message':str(e)[:500]})
    item['finished']=datetime.now(timezone.utc).isoformat();storage.save(f'runs/{ident}/metadata.json',item)
    return dict(item,result=result)

@router.get('/runs')
def list_runs():return sorted([storage.load(p) for p in storage.listing('runs/') if p.endswith('/metadata.json')],key=lambda r:r['created'],reverse=True)

def run_meta(ident):
    import re
    if not re.fullmatch(r'[a-f0-9]{32}',ident):raise HTTPException(404,'Run not found')
    item=storage.load(f'runs/{ident}/metadata.json')
    if not item:raise HTTPException(404,'Run not found')
    return item
@router.get('/runs/{ident}')
def get_run(ident:str):return dict(run_meta(ident),result=storage.load(f'runs/{ident}/result.json'))
@router.get('/runs/{ident}/trades')
def run_trades(ident:str,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=5000)):
    run_meta(ident);result=storage.load(f'runs/{ident}/result.json',{});rows=result.get('trades',[])
    return dict(total=len(rows),items=rows[offset:offset+limit])
@router.get('/compare')
def compare(left:str,right:str):
    a=get_run(left);b=get_run(right)
    return dict(left=a,right=b,pnl_difference=(b.get('summary',{}).get('pnl',0)-a.get('summary',{}).get('pnl',0)))
@router.get('/observations')
def observations(market:str|None=None,start:date|None=None,end:date|None=None,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=5000)):
    o=load([market] if market else None)
    if start:o=o[o.day>=start]
    if end:o=o[o.day<=end]
    return dict(total=len(o),items=records(o.iloc[offset:offset+limit]))
@router.get('/markets')
def markets():
    import multi_pull
    obs=load();counts=obs.groupby('market').day.agg(['nunique','min','max'])
    return [dict(v,expiry_days=int(counts.loc[k,'nunique']) if k in counts.index else 0,
                 first=str(counts.loc[k,'min']) if k in counts.index else None,last=str(counts.loc[k,'max']) if k in counts.index else None,
                 frozen=k in ('BTC','SPX'),history_gate=bool(k in counts.index and counts.loc[k,'nunique']>=150)) for k,v in multi_pull.load_markets().items()]

def update_forward():
    obs=load();counts=obs.groupby('market').day.nunique().to_dict()
    eligible=[k for k in ('BTC','SPX') if counts.get(k,0)>=150]
    after=obs[obs.day>=date(2026,11,12)]
    result=dict(start='2026-11-12',updated=datetime.now(timezone.utc).isoformat(),status='current' if set(eligible)=={'BTC','SPX'} else 'incomplete_history',
                available_history={k:int(v) for k,v in counts.items()},eligible_markets=eligible,missing_frozen_markets=[k for k in ('BTC','SPX') if k not in eligible],
                observed_days=sorted(str(x) for x in after.day.unique()),note='Training uses earlier expiry days only. Missing expiry days are not counted as zero-return days.')
    if eligible and len(after):
        by_est={}
        for est in ('S','P'):
            body=RunRequest(markets=eligible,k=2,C=.04,estimator=est,start=date(2026,11,12))
            by_est[est]=execute(body,obs[obs.market.isin(eligible)])
        result['summary']=by_est['S']['summary'];result['estimators']={k:v['summary'] for k,v in by_est.items()}
        storage.save('forward/results.json',by_est)
    storage.save('forward/latest.json',result)
    return {k:v for k,v in result.items() if k!='estimators'}
