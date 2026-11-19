import hashlib,io,json,re,uuid
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from fastapi import APIRouter,Depends,File,Form,HTTPException,UploadFile,Query
from shared import storage
from shared.auth import require_write
from strategies.kalshi_tail.results import records
router=APIRouter(prefix='/uploads',tags=['Uploads'])
MAX_BYTES=4_000_000
OBS_COLS=['ticker','expiry','day','H','y','bid','ask','bid_f','ask_f','floor','strike_type']

def parse(raw,filename,mapping,kind):
    if not raw or len(raw)>MAX_BYTES:raise HTTPException(422,'File must contain 1 byte to 4 MB')
    try:
        if filename.lower().endswith('.json'):
            value=json.loads(raw)
            if not isinstance(value,list) or not all(isinstance(r,dict) for r in value):raise ValueError('JSON must be an array of row objects')
            df=pd.DataFrame(value)
        elif filename.lower().endswith('.csv'):df=pd.read_csv(io.BytesIO(raw))
        else:raise ValueError('Use a CSV or JSON file')
        rename=json.loads(mapping)
        if not isinstance(rename,dict) or any(k not in df.columns for k in rename):raise ValueError('Mapping must map existing source columns to destination columns')
        df=df.rename(columns=rename)
        if df.columns.duplicated().any():raise ValueError('Mapped column names must be unique')
        if df.empty or len(df)>100000 or len(df.columns)>200:raise ValueError('Dataset must have 1 to 100,000 rows and at most 200 columns')
        if kind=='observations':
            missing=set(OBS_COLS)-set(df.columns)
            if missing:raise ValueError('Missing observation columns: '+', '.join(sorted(missing)))
            for c in ['H','y','bid','ask','bid_f','ask_f','floor']:df[c]=pd.to_numeric(df[c],errors='raise')
            if not np.isfinite(df[['H','y','bid','ask','bid_f','ask_f','floor']].to_numpy()).all():raise ValueError('Observation numbers must be finite')
            for c in ['bid','ask','bid_f','ask_f']:
                if not df[c].between(0,1).all():raise ValueError(c+' must be a probability between 0 and 1')
            if not df.H.isin([12,6,3]).all() or not df.y.isin([0,1]).all():raise ValueError('H must be 12, 6 or 3; settled y must be 0 or 1')
            if (df.bid>df.ask).any() or (df.bid_f>df.ask_f).any():raise ValueError('Bid must not exceed ask')
            for c in ['expiry','day']:pd.to_datetime(df[c],utc=True,errors='raise')
            expiry_day=pd.to_datetime(df.expiry,utc=True,format='mixed').dt.tz_convert('America/New_York').dt.date
            if not (pd.to_datetime(df.day).dt.date==expiry_day).all():raise ValueError('day must equal the expiry date in New York')
            if not (df.floor>0).all():raise ValueError('floor must be positive')
            if df.duplicated((['market'] if 'market' in df else [])+['ticker','H']).any():raise ValueError('Duplicate market/ticker/horizon observation rows')
            if df[OBS_COLS].isna().any().any():raise ValueError('Required observation fields cannot be empty')
            if not df.strike_type.isin(['greater']).all():raise ValueError('The engine accepts normalized greater ladders only')
            if 'market' not in df:df['market']='BTC'
            if not df.market.isin(['BTC','SPX','GOLD','WTI','NATGAS','NDX','SILVER']).all():raise ValueError('Unknown market key')
        elif kind=='trades':
            if not {'day','ticker','pnl'}.issubset(df.columns):raise ValueError('Trade files require day, ticker and pnl')
            pd.to_datetime(df.day,errors='raise');pd.to_numeric(df.pnl,errors='raise')
        elif kind=='candles':
            if not {'ticker','ts','bid','ask'}.issubset(df.columns):raise ValueError('Candle files require ticker, ts, bid and ask')
        elif kind!='custom':raise ValueError('kind must be observations, trades, candles or custom')
        return df
    except HTTPException:raise
    except Exception as e:raise HTTPException(422,str(e))

def preview(df):return dict(rows=len(df),columns=[dict(name=c,dtype=str(df[c].dtype),missing=int(df[c].isna().sum())) for c in df],sample=records(df.head(8)))

@router.post('/preview',dependencies=[Depends(require_write)])
def preview_upload(file:UploadFile=File(...),mapping:str=Form('{}'),kind:str=Form('custom')):
    return preview(parse(file.file.read(MAX_BYTES+1),file.filename or '',mapping,kind))

@router.post('',dependencies=[Depends(require_write)],status_code=201)
def upload(file:UploadFile=File(...),mapping:str=Form('{}'),kind:str=Form('custom'),name:str=Form('')):
    raw=file.file.read(MAX_BYTES+1);df=parse(raw,file.filename or '',mapping,kind)
    ident=uuid.uuid4().hex
    metadata=dict(id=ident,name=(name or file.filename or 'Dataset')[:160],filename=re.sub(r'[^\w. -]','_',file.filename or 'upload')[:160],
                  kind=kind,version=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest(),mapping=json.loads(mapping),**preview(df))
    storage.put(f'uploads/{ident}/data.csv',df.to_csv(index=False).encode(),'text/csv')
    storage.save(f'uploads/{ident}/metadata.json',metadata)
    return metadata

@router.get('')
def list_uploads():return sorted([storage.load(p) for p in storage.listing('uploads/') if p.endswith('/metadata.json')],key=lambda r:r['version'],reverse=True)

def get_metadata(ident):
    if not re.fullmatch(r'[a-f0-9]{32}',ident):raise HTTPException(404,'Dataset not found')
    value=storage.load(f'uploads/{ident}/metadata.json')
    if value is None:raise HTTPException(404,'Dataset not found')
    return value

@router.get('/{ident}')
def detail(ident:str):return get_metadata(ident)
@router.get('/{ident}/rows')
def rows(ident:str,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=5000)):
    get_metadata(ident)
    df=pd.read_csv(io.BytesIO(storage.read(f'uploads/{ident}/data.csv')))
    return dict(total=len(df),items=records(df.iloc[offset:offset+limit]))
@router.delete('/{ident}',dependencies=[Depends(require_write)])
def remove(ident:str):
    metadata=get_metadata(ident)
    if metadata.get('active'):storage.delete(f'observations/imports/{ident}.csv')
    storage.delete(f'uploads/{ident}/metadata.json');storage.delete(f'uploads/{ident}/data.csv')
    if metadata.get('active'):
        from strategies.kalshi_tail.runs import update_forward
        update_forward()
    return {'deleted':ident}

@router.post('/{ident}/activate',dependencies=[Depends(require_write)])
def activate(ident:str):
    metadata=get_metadata(ident)
    if metadata['kind']!='observations':raise HTTPException(422,'Only validated observation datasets can be activated as shared history')
    storage.put(f'observations/imports/{ident}.csv',storage.read(f'uploads/{ident}/data.csv'),'text/csv')
    metadata['active']=True;storage.save(f'uploads/{ident}/metadata.json',metadata)
    from strategies.kalshi_tail.runs import update_forward
    return dict(dataset=metadata,forward=update_forward())

@router.post('/{ident}/deactivate',dependencies=[Depends(require_write)])
def deactivate(ident:str):
    metadata=get_metadata(ident)
    if metadata.get('active'):storage.delete(f'observations/imports/{ident}.csv')
    metadata['active']=False;storage.save(f'uploads/{ident}/metadata.json',metadata)
    from strategies.kalshi_tail.runs import update_forward
    return dict(dataset=metadata,forward=update_forward())
