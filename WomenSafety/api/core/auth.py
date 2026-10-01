"""Fix pass item 8: shared-secret guard for state-changing / demo routes."""
import hmac

from fastapi import Header, HTTPException

from api.core.config import settings


def require_demo_token(x_demo_token: str = Header(default="")):
    if not settings.DEMO_TOKEN:
        raise HTTPException(status_code=403, detail="DEMO_TOKEN is not configured on the server; this route is disabled")
    if not hmac.compare_digest(x_demo_token.encode(), settings.DEMO_TOKEN.encode()):
        raise HTTPException(status_code=403, detail="missing or invalid X-Demo-Token")
