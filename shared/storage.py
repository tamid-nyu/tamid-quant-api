"""Private Blob persistence shared by all quant projects."""
import json
from vercel.blob.sync import put_blob, get_blob, query_blobs, delete_blob
from vercel.blob import BlobNotFoundError

def put(path, body, content_type='application/json'):
    return put_blob(path, body, access='private', content_type=content_type, allow_overwrite=True, cache_control_max_age=0)

def save(path, value):
    put(path, json.dumps(value, default=str, allow_nan=False).encode())

def read(path):
    return get_blob(path, access='private').body

def load(path, default=None):
    try: return json.loads(read(path))
    except BlobNotFoundError: return default

def listing(prefix):
    return [b.pathname for b in query_blobs(prefix=prefix)]

def delete(path):
    delete_blob(path)
