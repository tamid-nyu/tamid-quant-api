import io,sys
from pathlib import Path
import pandas as pd
from shared import storage
from strategies.kalshi_tail.results import ROOT,frame,BTC
sys.path.insert(0,str(ROOT/'engine/kalshi-multi-tail'))
sys.path.insert(0,str(ROOT/'engine/btc-kalshi-digital'))
import multi_obs,multi_tail,tail_strategy

def normalize(df,key=None):
    o=df.copy()
    if 'market' not in o:o['market']=key or 'BTC'
    groups={'BTC':'crypto','SPX':'equity','GOLD':'metals','WTI':'crude','NATGAS':'gas','NDX':'equity','SILVER':'metals'}
    o['group']=o['market'].map(groups)
    o['strike_rule']='gt'
    o=o[o.H.isin([6,3]) & (o.strike_type=='greater') & o.y.notna()].copy()
    o['expiry']=pd.to_datetime(o.expiry,utc=True,format='mixed')
    o['day']=pd.to_datetime(o.day).dt.date
    if 'decision_ts' in o:o['decision_ts']=pd.to_datetime(o.decision_ts,utc=True,format='mixed')
    else:o['decision_ts']=o.expiry-pd.to_timedelta(o.H,unit='h')
    o['mid']=(o.bid+o.ask)/2
    return o

def load(markets=None,upload_id=None):
    parts=[normalize(frame(BTC/'btc_pm_results_long/btc_observations.csv'))]
    for p in storage.listing('observations/'):
        if p.endswith('.csv'):parts.append(normalize(pd.read_csv(io.BytesIO(storage.read(p)))))
    if upload_id:
        from shared.uploads import get_metadata
        from fastapi import HTTPException
        m=get_metadata(upload_id)
        if m['kind']!='observations':raise HTTPException(422,'Backtest inputs must be validated observations. Map the columns and upload as observations.')
        parts.append(normalize(pd.read_csv(io.BytesIO(storage.read(f'uploads/{upload_id}/data.csv')))))
    o=pd.concat(parts,ignore_index=True).drop_duplicates(['market','ticker','H'],keep='last')
    if markets:o=o[o.market.isin(markets)]
    return o.sort_values(['day','decision_ts','market','ticker']).reset_index(drop=True)
