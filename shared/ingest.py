import io,uuid
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import pandas as pd
from pydantic import BaseModel,ConfigDict,Field
from fastapi import APIRouter,Depends,HTTPException
from shared import storage,kalshi
from shared.auth import require_write,require_cron
from strategies.kalshi_tail.observations import multi_obs
from strategies.kalshi_tail.results import ROOT
import multi_pull
import btc_pm_data_pull as bp
router=APIRouter(prefix='/ingest',tags=['Ingestion'])
class IngestRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    day:date|None=None
    markets:list[str]=Field(default_factory=lambda:['BTC','SPX','GOLD','WTI','NATGAS'],min_length=1,max_length=7)

def ingest(body):
    day=body.day or (datetime.now(ZoneInfo('America/New_York')).date()-timedelta(days=1))
    if day>=datetime.now(ZoneInfo('America/New_York')).date():raise HTTPException(422,'Ingest only completed expiry days')
    config=multi_pull.load_markets()
    if set(body.markets)-set(config):raise HTTPException(422,'Unknown market key')
    ident=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    log=dict(id=ident,day=str(day),started=datetime.now(timezone.utc).isoformat(),status='running',markets=[],rows=0)
    storage.save(f'ingest/logs/{ident}.json',log)
    for key in dict.fromkeys(body.markets):
        cfg=config[key];entry=dict(market=key,status='ok',rows=0)
        try:
            if cfg['weekdays_only'] and day.weekday()>4:
                entry['status']='non_trading_day';log['markets'].append(entry);continue
            ms=[];series=None
            for s in cfg['series']:
                ms=kalshi.markets_for_event(multi_pull.event_ticker(s,day,cfg['event_suffix']))
                if ms:series=s;break
            settled=[m for m in ms if m.get('result') in ('yes','no')]
            if ms and not settled:raise ValueError('Event is not settled yet; retry later')
            if not ms:
                entry['status']='no_event';log['markets'].append(entry);continue
            prev=day-timedelta(days=1)
            if cfg['weekdays_only']:
                while prev.weekday()>4:prev-=timedelta(days=1)
            prev_ms=kalshi.markets_for_event(multi_pull.event_ticker(series,prev,cfg['event_suffix']))
            vals=[bp.fnum(m.get('expiration_value')) for m in prev_ms if bp.fnum(m.get('expiration_value'))]
            ref=vals[0] if vals else None
            chosen=multi_pull.select_strikes(settled,ref,cfg['band'],200)
            market_rows=[];hourly=[];missing=[]
            end_max=int(max(pd.Timestamp(m['close_time']).timestamp() for _,m,_ in chosen)) if chosen else 0
            batch=kalshi.batch_candles([m['ticker'] for _,m,_ in chosen],end_max-8*3600,end_max+3600)
            for _,m,fl in chosen:
                expiry=pd.Timestamp(m['close_time']);end=int(expiry.timestamp())
                d=batch.get(m['ticker']);hist=False
                if d is None:d,hist=kalshi.candle_data(series,m['ticker'],end-8*3600,end+3600)
                candles=d.get('candlesticks',[])
                if not candles:missing.append(m['ticker']);continue
                market_rows.append(dict(ticker=m['ticker'],expiry=expiry.isoformat(),result=m['result'],floor=fl,strike_rule=cfg['strike_rule']))
                for c in candles:
                    hourly.append(dict(ticker=m['ticker'],ts=pd.to_datetime(c['end_period_ts'],unit='s',utc=True),bid=bp.price(c.get('yes_bid',{}),'close',hist),ask=bp.price(c.get('yes_ask',{}),'close',hist)))
            if not market_rows:raise ValueError('No usable hourly candles returned')
            obs=multi_obs.build_market_obs(pd.DataFrame(market_rows),pd.DataFrame(hourly),key,cfg['group'])
            if obs.empty:raise ValueError('No complete decision/fill observation pairs returned')
            storage.put(f'observations/{key}/{day}.csv',obs.to_csv(index=False).encode(),'text/csv')
            entry.update(rows=len(obs),contracts=len(chosen),missing_candles=missing)
            if missing:entry['status']='partial'
            log['rows']+=len(obs)
        except Exception as e:
            entry.update(status='failed',error=(str(e.detail) if isinstance(e,HTTPException) else str(e))[:400])
        log['markets'].append(entry)
        storage.save(f'ingest/logs/{ident}.json',log)
    log['status']='ok' if all(x['status'] in ('ok','no_event','non_trading_day') for x in log['markets']) else 'partial'
    log['finished']=datetime.now(timezone.utc).isoformat()
    # Forward recomputation is registered by the strategy run module.
    try:
        from strategies.kalshi_tail.runs import update_forward
        log['forward']=update_forward()
    except ImportError:pass
    except Exception as e:log['forward_error']=str(e)[:300]
    storage.save(f'ingest/logs/{ident}.json',log)
    return log
@router.post('/trigger',dependencies=[Depends(require_write)])
def trigger(body:IngestRequest):return ingest(body)
@router.get('/cron',dependencies=[Depends(require_cron)])
def cron():return ingest(IngestRequest())
@router.get('/logs')
def logs():return sorted([storage.load(p) for p in storage.listing('ingest/logs/')],key=lambda r:r['started'],reverse=True)
