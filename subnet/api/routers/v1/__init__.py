"""API v1.0 routers."""

from fastapi import APIRouter

from subnet.api.routers.v1 import health, keys, nmaps, peers, security_events

# Create v1 router
router = APIRouter(prefix="/v1.0", tags=["v1.0"])

# Include all v1 sub-routers
router.include_router(health.router)
router.include_router(peers.router)
router.include_router(nmaps.router)
router.include_router(keys.router)
router.include_router(security_events.router)
