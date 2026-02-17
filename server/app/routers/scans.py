"""Scan orchestration — start scans, receive agent callbacks."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

import modal

from ..auth import AuthContext, require_api_key
from ..config import settings
from ..convex_client import convex_mutation, convex_query
from ..lib.autumn import autumn_check, autumn_track

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scans", tags=["scans"])


class StartScanRequest(BaseModel):
    scan_id: str
    project_id: str
    target_type: str
    target_config: dict
    agent: str


class LaunchScanRequest(BaseModel):
    repo_url: str | None = None
    storage_id: str | None = None
    repo_name: str | None = None
    target_type: str = "oss"
    agent: str = "opus"


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
            storage_id = req.target_config.get("storageId", "")
            if not repo_url and not storage_id:
                raise ValueError("Missing repoUrl or storageId in target config")

            # Route to correct Modal function based on agent
            if req.agent == "opus":
                fn = modal.Function.from_name("re-zero-sandbox", "run_oss_scan")
            else:
                fn = modal.Function.from_name("re-zero-sandbox", "run_oss_scan_opencode")

            await fn.remote.aio(
                scan_id=req.scan_id,
                project_id=req.project_id,
                repo_url=repo_url or "",
                storage_id=storage_id or "",
                agent=req.agent,
                convex_url=settings.convex_url,
                convex_deploy_key=settings.convex_deploy_key,
            )

        elif req.target_type == "web":
            target_url = req.target_config.get("url", "")
            if not target_url:
                raise ValueError("Missing url in target config")

            test_account = req.target_config.get("testAccount")
            user_context = req.target_config.get("context")

            # Route to correct Modal function based on agent
            if req.agent == "opus":
                fn = modal.Function.from_name("re-zero-sandbox", "run_web_scan")
            else:
                fn = modal.Function.from_name("re-zero-sandbox", "run_web_scan_opencode")

            await fn.remote.aio(
                scan_id=req.scan_id,
                project_id=req.project_id,
                target_url=target_url,
                test_account=test_account,
                user_context=user_context,
                agent=req.agent,
                convex_url=settings.convex_url,
                convex_deploy_key=settings.convex_deploy_key,
            )

    except Exception as e:
        logger.exception(f"Scan {req.scan_id} failed")
        await convex_mutation("scans:updateStatus", {
            "scanId": req.scan_id,
            "status": "failed",
            "error": str(e),
        })


@router.post("/start")
async def start_scan(
    req: StartScanRequest,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(require_api_key),
):
    """Called when a scan is created. Spins up the Modal sandbox."""
    # Verify the user owns this project
    project_result = await convex_query("projects:get", {"projectId": req.project_id})
    project = project_result.get("value", project_result) if isinstance(project_result, dict) else project_result
    if not project or project.get("userId") != auth.user_id:
        raise HTTPException(status_code=403, detail="Not your project")

    background_tasks.add_task(_launch_scan, req)
    return {"status": "started", "scan_id": req.scan_id}


@router.post("/launch")
async def launch_scan(
    req: LaunchScanRequest,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(require_api_key),
):
    """All-in-one: find/create project, create scan, start Modal."""
    # Check billing — requires payment method on file
    if settings.autumn_secret_key and auth.clerk_id:
        try:
            check = await autumn_check(settings.autumn_secret_key, auth.clerk_id, "scan")
            if not check.get("allowed"):
                raise HTTPException(402, "Payment required. Set up billing at https://rezero.sh/billing")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Autumn check failed (allowing scan): {e}")

    # Validate: exactly one of repo_url or storage_id
    if not req.repo_url and not req.storage_id:
        raise HTTPException(400, "Either repo_url or storage_id is required")
    if req.repo_url and req.storage_id:
        raise HTTPException(400, "Provide repo_url or storage_id, not both")

    # Determine display name and repo URL for project lookup
    display_name = req.repo_name or req.repo_url or "local-upload"
    project_repo_url = req.repo_url or f"local://{display_name}"

    # 1. Find or create project
    project_result = await convex_mutation("projects:findOrCreate", {
        "userId": auth.user_id,
        "repoUrl": project_repo_url,
        "targetType": req.target_type,
    })
    project_id = project_result.get("value", project_result) if isinstance(project_result, dict) else project_result

    # 2. Create scan
    scan_result = await convex_mutation("scans:create", {
        "projectId": project_id,
        "agent": req.agent,
    })
    scan_id = scan_result.get("value", scan_result) if isinstance(scan_result, dict) else scan_result

    # 3. Build target config and launch
    if req.target_type == "oss":
        target_config = {}
        if req.repo_url:
            target_config["repoUrl"] = req.repo_url
        if req.storage_id:
            target_config["storageId"] = req.storage_id
    else:
        raise HTTPException(400, "Only 'oss' target type supported via CLI for now")

    internal_req = StartScanRequest(
        scan_id=scan_id,
        project_id=project_id,
        target_type=req.target_type,
        target_config=target_config,
        agent=req.agent,
    )
    background_tasks.add_task(_launch_scan, internal_req)

    return {"scan_id": scan_id, "project_id": project_id}


@router.get("/{scan_id}/poll")
async def poll_scan(
    scan_id: str,
    after: float = 0,
    auth: AuthContext = Depends(require_api_key),
):
    """Poll scan status, new actions, and report."""
    scan_result = await convex_query("scans:get", {"scanId": scan_id})
    scan = scan_result.get("value", scan_result) if isinstance(scan_result, dict) else scan_result
    if not scan:
        raise HTTPException(404, "Scan not found")

    # Verify ownership through project
    project_result = await convex_query("projects:get", {"projectId": scan["projectId"]})
    project = project_result.get("value", project_result) if isinstance(project_result, dict) else project_result
    if not project or project.get("userId") != auth.user_id:
        raise HTTPException(403, "Not your scan")

    # Get actions after timestamp
    actions_result = await convex_query("actions:listByScanAfter", {
        "scanId": scan_id,
        "after": after,
    })
    actions = actions_result.get("value", actions_result) if isinstance(actions_result, dict) else actions_result

    # Get report if completed
    report = None
    if scan.get("status") == "completed":
        report_result = await convex_query("reports:getByScan", {"scanId": scan_id})
        report = report_result.get("value", report_result) if isinstance(report_result, dict) else report_result

    return {
        "status": scan.get("status"),
        "error": scan.get("error"),
        "actions": actions or [],
        "report": report,
    }


@router.post("/upload-url")
async def get_upload_url(auth: AuthContext = Depends(require_api_key)):
    """Get a presigned URL for uploading a tarball to Convex storage."""
    result = await convex_mutation("storage:generateUploadUrl", {})
    url = result.get("value", result) if isinstance(result, dict) else result
    return {"upload_url": url}


@router.post("/verify")
async def verify_key(auth: AuthContext = Depends(require_api_key)):
    """Verify an API key is valid."""
    return {"valid": True, "user_id": auth.user_id}


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

    # Track usage in Autumn for billing
    if settings.autumn_secret_key:
        try:
            project_result = await convex_query("projects:get", {"projectId": req.project_id})
            project = project_result.get("value", project_result) if isinstance(project_result, dict) else project_result
            if project:
                user_result = await convex_query("users:get", {"userId": project["userId"]})
                user = user_result.get("value", user_result) if isinstance(user_result, dict) else user_result
                if user and user.get("clerkId"):
                    await autumn_track(settings.autumn_secret_key, user["clerkId"], "scan", 1)
        except Exception as e:
            logger.warning(f"Autumn track failed: {e}")

    return {"status": "submitted"}
