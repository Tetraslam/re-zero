"""Gateway management for hardware/FPGA targets."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/gateways", tags=["gateways"])


class GatewayHeartbeat(BaseModel):
    gateway_id: str
    status: str


@router.post("/heartbeat")
async def heartbeat(req: GatewayHeartbeat):
    """Called by local gateway processes to report status."""
    # TODO: Update gateway status in Convex
    return {"status": "ok"}
