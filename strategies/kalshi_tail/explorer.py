from datetime import datetime
from zoneinfo import ZoneInfo
import math
from fastapi import APIRouter,HTTPException
from shared import kalshi
from strategies.kalshi_tail.observations import load,multi_tail,tail_strategy
import multi_pull
import btc_pm_data_pull as bp
router=APIRouter(prefix='/kalshi',tags=['Kalshi explorer'])
@router.get('/ladder')
def ladder(market:str='BTC',day:str|None=None,estimator:str='S'):
    config=multi_pull.load_markets()
    if market not in config or estimator not in ('S','P'):raise HTTPException(422,'Unknown market or estimator')
    dt=datetime.fromisoformat(day).date() if day else datetime.now(ZoneInfo('America/New_York')).date()
    cfg=config[market];items=[];event=None
    for series in cfg['series']:
        event=multi_pull.event_ticker(series,dt,cfg['event_suffix']);items=kalshi.markets_for_event(event)
        if items:break
    # Never train on the displayed expiry day or later outcomes.
    obs=load(['BTC','SPX'] if market in ('BTC','SPX') else None);obs=obs[obs.day<dt]
    history_by_market=obs.groupby('market').day.nunique().to_dict()
    est=multi_tail.make_estimator(estimator,multi_tail.MultiConfig(estimator=estimator))
    for _,g in obs.groupby('day',sort=True):est.update(tail_strategy.tail_candidates(g))
    history=int(obs[obs.market==market].day.nunique())
    rows=[];now=datetime.now(ZoneInfo('UTC'))
    for m in items:
        bid=bp.price(m,'yes_bid');ask=bp.price(m,'yes_ask');mid=(bid+ask)/2 if bid is not None and ask is not None else None
        close=datetime.fromisoformat(m['close_time'].replace('Z','+00:00'));h=(close-now).total_seconds()/3600
        H=min((6,3),key=lambda v:abs(h-v));f,n=est.estimate(market,H,mid) if mid is not None else (float('nan'),0)
        side,price,edge=tail_strategy.best_side(bid,ask,f,multi_tail.MultiConfig()) if mid is not None and math.isfinite(f) else (0,0,0)
        tail=mid is not None and (mid<.1 or mid>.9)
        reason='Eligible signal'
        if market not in ('BTC','SPX'):reason='Exploratory market; outside frozen market set'
        elif history<150:reason='Fewer than 150 observed expiry days'
        elif estimator=='P' and any(history_by_market.get(k,0)<150 for k in ('BTC','SPX')):reason='Frozen pooled history incomplete: BTC and SPX each need 150 days'
        elif not 0<=H-h<1:reason='Outside the 6h / 3h decision hour'
        elif not tail:reason='Outside longshot price range'
        elif bid<.01 or ask>.99 or ask-bid>.06+1e-12:reason='Quote fails spread / boundary filter'
        elif n<100 or not math.isfinite(f):reason='Fewer than 100 prior cell observations'
        elif edge<.005:reason='Net edge below 0.5%'
        if m.get('result') or m.get('status') not in ('active','open'):reason='Market closed or settled'
        rows.append(dict(ticker=m['ticker'],floor=m.get('floor_strike'),bid=bid,ask=ask,mid=mid,longshot=tail,
                         side='Buy YES' if side==1 else 'Sell YES' if side==-1 else None,edge=float(edge) if math.isfinite(edge) else None,
                         estimate=float(f) if math.isfinite(f) else None,cell_n=int(n),eligible=reason=='Eligible signal',reason=reason,close_time=m['close_time']))
    return dict(market=market,event=event,day=str(dt),history_days=history,estimator=estimator,items=rows,
                note='Signals use current quotes and frozen filters. Final quantities require portfolio LP sizing and next-hour fills; this is not an order.')
