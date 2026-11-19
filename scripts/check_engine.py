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
