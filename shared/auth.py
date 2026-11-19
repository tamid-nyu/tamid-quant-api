import os
import secrets
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
bearer=HTTPBearer(auto_error=False)
def require_write(credentials:HTTPAuthorizationCredentials|None=Depends(bearer)):
    expected=os.getenv('LAB_API_TOKEN')
    if not expected:raise HTTPException(503,'Write authentication is not configured')
    if not credentials or not secrets.compare_digest(credentials.credentials,expected):raise HTTPException(401,'A valid bearer token is required',headers={'WWW-Authenticate':'Bearer'})
def require_cron(credentials:HTTPAuthorizationCredentials|None=Depends(bearer)):
    expected=os.getenv('CRON_SECRET')
    if not expected or not credentials or not secrets.compare_digest(credentials.credentials,expected):raise HTTPException(401,'Cron authorization required')
