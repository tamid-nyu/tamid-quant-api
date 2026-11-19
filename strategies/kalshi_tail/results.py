from pathlib import Path
import io
import json
import pandas as pd
from shared import storage
ROOT = Path(__file__).resolve().parents[2]
BTC = ROOT/'engine/btc-kalshi-digital/output'
MULTI = ROOT/'engine/kalshi-multi-tail/output'

def frame(path):
    key = 'seed/' + str(path.relative_to(ROOT/'engine'))
    try: return pd.read_csv(io.BytesIO(storage.read(key)))
    except Exception:
        # Source artifacts remain a read-only recovery copy, never a write destination.
        return pd.read_csv(path)

def records(df):
    return json.loads(df.to_json(orient='records',date_format='iso'))

def metrics(daily, trades=None, bankroll=1000):
    cum = daily.pnl.cumsum()
    dd = cum - cum.clip(lower=0).cummax()
    return dict(pnl=float(daily.pnl.sum()),return_pct=float(daily.pnl.sum()/bankroll*100),
                max_drawdown_pct=float(dd.min()/bankroll*100) if len(dd) else 0,
                trades=int(daily.n_trades.sum()),days=len(daily),
                traded_days=int((daily.n_trades>0).sum()),bankroll=bankroll,
                start=str(daily.day.min()) if len(daily) else None,end=str(daily.day.max()) if len(daily) else None)

def dataset(name='btc'):
    if name=='btc':
        dy=frame(BTC/'btc_tail_results_long/tail_daily.csv')
        tr=frame(BTC/'btc_tail_results_long/tail_trades.csv');tr['market']='BTC'
        return dy,tr,None
    gate,est = name.split(':')
    if gate not in ('gate150','gate100_posthoc') or est not in ('S','P'): raise ValueError('Unknown dataset')
    return (frame(MULTI/gate/f'daily_{est}.csv'),frame(MULTI/gate/f'trades_{est}.csv'),frame(MULTI/gate/f'market_daily_{est}.csv'))

def dashboard(name='btc'):
    dy,tr,md=dataset(name)
    dy['equity']=1000+dy.pnl.cumsum()
    dy['drawdown']=((dy.equity-1000)-(dy.equity-1000).clip(lower=0).cummax())/10
    variants=[]
    for gate in ('gate150','gate100_posthoc'):
        for period in ('check','holdout'):
            for r in records(frame(MULTI/gate/f'summary_{period}.csv')): variants.append(dict(r,gate=gate,period=period))
    market=[];corr=[]
    if md is not None:
        market=records(md.groupby('market',as_index=False).agg(pnl=('pnl','sum'),trades=('n_trades','sum')))
        c=md.pivot_table(index='day',columns='market',values='pnl',aggfunc='sum').corr(min_periods=2)
        corr=[dict(market=i,**r) for i,r in c.to_dict(orient='index').items()]
    else:market=[dict(market='BTC',pnl=float(tr.pnl.sum()),trades=len(tr))]
    fwd=storage.load('forward/latest.json',{}) if __import__('os').getenv('BLOB_READ_WRITE_TOKEN') else {}
    return dict(summary=metrics(dy),daily=records(dy),trades=records(tr),markets=market,correlation=corr,variants=variants,
                numbered_variants=storage.load('results/numbered-variants.json',[]) if __import__('os').getenv('BLOB_READ_WRITE_TOKEN') else [],
                calibration=records(frame(BTC/'btc_pm_results_long/btc_reliability_table.csv')),
                forward={'start':'2026-11-12','status':'awaiting_ingestion',**fwd},
                source_commit=(ROOT/'engine/SOURCE_COMMIT').read_text().strip(),
                caveats=['Mean daily return is not significantly above zero.', 'One-hour fill slippage can breach the sizing cap.', 'Five-market results use a post-hoc 100-day history gate.'])
