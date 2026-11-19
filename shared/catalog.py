from datetime import date
from fastapi import APIRouter,HTTPException,Query
from shared import storage
from strategies.kalshi_tail.results import dataset,metrics,records,ROOT
router=APIRouter(tags=['API catalog'])
@router.get('/')
def catalog():
    return dict(service='TAMID Quant API',version='1.0.0',docs='/docs',openapi='/api/openapi.json',
                strategies=[dict(id='kalshi-tail',name='Kalshi tail strategy',base='/strategies/kalshi-tail',frozen_on='2026-11-12')],
                resources=dict(kalshi='/kalshi',uploads='/uploads',ingest='/ingest',runs='/strategies/kalshi-tail/runs'),
                storage='Private Vercel Blob; reads are exposed through this public research API',write_auth='Bearer token',source_commit=(ROOT/'engine/SOURCE_COMMIT').read_text().strip())
@router.get('/strategies')
def strategies():return catalog()['strategies']
@router.get('/strategies/kalshi-tail/summary')
def summary(dataset_name:str='btc',start:date|None=None,end:date|None=None):
    try:dy,_,_=dataset(dataset_name)
    except ValueError:raise HTTPException(422,'Unknown dataset; use btc, gate150:S, gate150:P, gate100_posthoc:S or gate100_posthoc:P')
    if start and end and start>end:raise HTTPException(422,'start must not be after end')
    if start:dy=dy[dy.day>=str(start)]
    if end:dy=dy[dy.day<=str(end)]
    if dy.empty:raise HTTPException(404,'No result days in this window')
    return metrics(dy)
@router.get('/strategies/kalshi-tail/forward-test/results')
def forward_results():return storage.load('forward/results.json',{})
