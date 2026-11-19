"""Run with BLOB_READ_WRITE_TOKEN set. Never prints credentials."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.storage import put
root=Path(__file__).resolve().parents[1]/'engine'
for f in root.rglob('*'):
    if f.is_file() and f.suffix in ('.csv','.txt','.md') and '/output/' in str(f):
        put('seed/'+str(f.relative_to(root)), f.read_bytes(), 'text/csv' if f.suffix=='.csv' else 'text/plain')
        print('Seeded',f.relative_to(root))
