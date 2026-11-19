"""Compute missing numbered comparisons from the original committed BTC observations."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strategies.kalshi_tail.observations import normalize,tail_strategy
from strategies.kalshi_tail.results import BTC,frame,metrics
from shared import storage
import variants
obs=normalize(frame(BTC/'btc_pm_results_long/btc_observations.csv'))
rows=[]
for model in [0,5,7]:
    cfg=variants.configs(model)[0][1];tr,dy=tail_strategy.run(obs,cfg)
    if model==0:assert len(tr)==402 and abs(tr.pnl.sum()-52.61)<.005
    for period,start,end in [('check','2026-01-01','2026-06-30'),('holdout','2026-07-01','2026-11-11')]:
        part=dy[(dy.day.astype(str)>=start)&(dy.day.astype(str)<=end)]
        rows.append(dict(model=model,name=variants.MODELS[model]['name'],period=period,**metrics(part)))
    print(model,len(tr),round(float(tr.pnl.sum()),2))
storage.save('results/numbered-variants.json',rows)
