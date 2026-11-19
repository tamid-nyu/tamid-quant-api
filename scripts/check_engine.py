"""The source BTC-only acceptance fixture, with no network or credentials."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'engine/btc-kalshi-digital'))
sys.path.insert(0,str(root/'engine/kalshi-multi-tail'))
from multi_obs import load_btc_obs
from multi_tail import run,MultiConfig
obs=load_btc_obs();tr,dy,_=run(obs,MultiConfig(k=1,cap_k=.03))
assert len(tr)==402,(len(tr),'expected 402')
assert abs(float(tr.pnl.sum())-52.61)<.005,float(tr.pnl.sum())
print(f'Real multi engine: {len(tr)} trades, ${tr.pnl.sum():.2f} P&L')

# Predictor v2 (F1) and v3 (frozen blend) on the same BTC-only input; numbers match tamid-quant-nyu's own
# features.csv path at engine/SOURCE_COMMIT (F1 needs only mid, H and market, so API observations suffice).
for est,n,pnl in (('V2',250,172.24),('V3',358,106.41)):
    tr,_,_=run(obs,MultiConfig(k=1,cap_k=.03,estimator=est))
    assert len(tr)==n and abs(float(tr.pnl.sum())-pnl)<.005,(est,len(tr),float(tr.pnl.sum()))
    print(f'Real multi engine {est}: {len(tr)} trades, ${tr.pnl.sum():.2f} P&L')

# Forward guard: before the pre-registered look date, V2/V3 runs never see expiry days after the holdout.
import datetime as dt
sys.path.insert(0,str(root))
from fastapi import HTTPException
from strategies.kalshi_tail.observations import normalize
from strategies.kalshi_tail.results import frame,BTC
from strategies.kalshi_tail import runs
api_obs=normalize(frame(BTC/'btc_pm_results_long/btc_observations.csv'))
fwd=api_obs[api_obs.day==api_obs.day.max()].copy();fwd['day']=dt.date(2026,11,20);fwd['ticker']=fwd.ticker+'-FWD'
with_fwd=__import__('pandas').concat([api_obs,fwd],ignore_index=True)
if not runs.forward_open():
    res=runs.execute(runs.RunRequest(estimator='V2'),with_fwd)
    assert res['forward_rows_held_back']==len(fwd) and res['summary']['end']<='2026-11-11',res['summary']
    try:runs.execute(runs.RunRequest(estimator='V3',start=dt.date(2026,11,12)),with_fwd);raise AssertionError('V3 forward window not blinded')
    except HTTPException as e:assert e.status_code==422
    assert runs.execute(runs.RunRequest(estimator='S'),with_fwd)['forward_rows_held_back']==0
    print(f'Forward guard: V2/V3 hold back {len(fwd)} forward rows until {runs.multi_tail.FORWARD_OPEN}')
