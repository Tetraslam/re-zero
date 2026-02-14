"""Scan orchestration — start scans, receive agent callbacks."""

import logging

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

import modal

from ..config import settings
from ..convex_client import convex_mutation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scans", tags=["scans"])


class StartScanRequest(BaseModel):
    scan_id: str
    project_id: str
    target_type: str
    target_config: dict
    agent: str


class AgentActionRequest(BaseModel):
    scan_id: str
    type: str  # tool_call | tool_result | reasoning | observation | report
    payload: dict | str


class SubmitReportRequest(BaseModel):
    scan_id: str
    project_id: str
    findings: list[dict]
    summary: str | None = None


async def _launch_scan(req: StartScanRequest):
    """Background task that launches the Modal sandbox."""
    try:
        await convex_mutation("scans:updateStatus", {
            "scanId": req.scan_id,
            "status": "running",
        })

        if req.target_type == "oss":
            repo_url = req.target_config.get("repoUrl", "")
            if not repo_url:
                raise ValueError("Missing repoUrl in target config")

            # Look up the deployed Modal function and spawn it
            run_oss_scan = modal.Function.from_name("re-zero-sandbox", "run_oss_scan")
            await run_oss_scan.remote.aio(
                scan_id=req.scan_id,
                project_id=req.project_id,
                repo_url=repo_url,
                agent=req.agent,
                convex_url=settings.convex_url,
                convex_deploy_key=settings.convex_deploy_key,
            )

        elif req.target_type == "web":
            # TODO: Web pentesting sandbox
            await convex_mutation("actions:push", {
                "scanId": req.scan_id,
                "type": "observation",
                "payload": "Web pentesting agent not yet implemented.",
            })

        elif req.target_type in ("hardware", "fpga"):
            # TODO: Hardware/FPGA gateway integration
            await convex_mutation("actions:push", {
                "scanId": req.scan_id,
                "type": "observation",
                "payload": f"{req.target_type} target not yet implemented.",
            })

    except Exception as e:
        logger.exception(f"Scan {req.scan_id} failed")
        await convex_mutation("scans:updateStatus", {
            "scanId": req.scan_id,
            "status": "failed",
            "error": str(e),
        })


@router.post("/start")
async def start_scan(req: StartScanRequest, background_tasks: BackgroundTasks):
    """Called when a scan is created. Spins up the Modal sandbox."""
    background_tasks.add_task(_launch_scan, req)
    return {"status": "started", "scan_id": req.scan_id}


@router.post("/action")
async def report_action(req: AgentActionRequest):
    """Called by agents in sandboxes to report actions."""
    await convex_mutation("actions:push", {
        "scanId": req.scan_id,
        "type": req.type,
        "payload": req.payload,
    })
    return {"status": "ok"}


@router.post("/report")
async def submit_report(req: SubmitReportRequest):
    """Called by agents to submit final report."""
    await convex_mutation("reports:submit", {
        "scanId": req.scan_id,
        "projectId": req.project_id,
        "findings": req.findings,
        "summary": req.summary,
    })

    # Mark scan as completed
    await convex_mutation("scans:updateStatus", {
        "scanId": req.scan_id,
        "status": "completed",
    })

    return {"status": "submitted"}
