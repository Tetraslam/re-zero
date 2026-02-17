"""CI gate — fast, synchronous Haiku scan on git diffs."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, require_api_key
from ..config import settings
from ..convex_client import convex_query
from ..lib.anthropic_client import get_anthropic_client, get_model_id
from ..lib.autumn import autumn_check, autumn_track

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gate", tags=["gate"])

MAX_DIFF_CHARS = 150_000  # Safe limit for Haiku's 200K context

GATE_SYSTEM_PROMPT = """You are Rem, a security engineer reviewing a code diff for vulnerabilities.

Analyze the diff for:
- Injection flaws (SQL, command, template, XSS, path traversal)
- Authentication/authorization issues (missing auth, hardcoded secrets, weak checks)
- Sensitive data exposure (API keys, passwords, tokens in code or logs)
- Insecure cryptography (weak algorithms, hardcoded keys, missing TLS)
- Security misconfigurations (debug mode, permissive CORS, missing headers)
- Dependency issues (known vulnerable versions, suspicious packages)
- Logic flaws that could lead to privilege escalation or data access

Rules:
- Only report issues visible in the diff. Don't speculate about code you can't see.
- Each finding must reference a specific file and line from the diff.
- Severity guide:
  - critical: Directly exploitable, leads to RCE/data breach/auth bypass
  - high: Exploitable with moderate effort, significant impact
  - medium: Requires specific conditions, moderate impact
  - low: Minor issues, defense-in-depth improvements
  - info: Observations, not vulnerabilities
- If no issues are found, return an empty findings array.
- Be precise, not exhaustive. False positives erode trust.

Use the submit_gate_findings tool to return your analysis."""

SUBMIT_GATE_FINDINGS_TOOL = {
    "name": "submit_gate_findings",
    "description": "Submit the security analysis of the diff",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One-sentence summary of the diff's security posture",
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "high", "medium", "low", "info"],
                        },
                        "description": {"type": "string"},
                        "location": {
                            "type": "string",
                            "description": "file:line from the diff",
                        },
                        "recommendation": {"type": "string"},
                    },
                    "required": ["title", "severity", "description"],
                },
            },
        },
        "required": ["summary", "findings"],
    },
}


class GateScanRequest(BaseModel):
    diff: str
    repo_name: str | None = None
    repo_url: str | None = None
    commit_sha: str | None = None
    pr_number: int | None = None
    event_type: str | None = None


@router.post("/scan")
async def gate_scan(
    req: GateScanRequest,
    auth: AuthContext = Depends(require_api_key),
):
    """Synchronous gate scan — calls Haiku directly, returns findings."""
    start = time.time()

    # 1. Billing check
    if settings.autumn_secret_key and auth.clerk_id:
        try:
            check = await autumn_check(
                settings.autumn_secret_key, auth.clerk_id, "gate_scan"
            )
            if not check.get("allowed"):
                raise HTTPException(
                    402,
                    "Payment required. Set up billing at https://rezero.sh/billing",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Autumn gate check failed (allowing scan): {e}")

    # 2. Empty diff — skip Haiku entirely
    diff_text = (req.diff or "").strip()
    if not diff_text:
        return {
            "findings": [],
            "summary": "Empty diff — nothing to analyze.",
            "blocked": False,
            "drift": None,
            "scan_duration_ms": int((time.time() - start) * 1000),
        }

    # 3. Truncate if needed
    truncated = False
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS]
        truncated = True

    # 4. Call Haiku
    try:
        client = get_anthropic_client()
        model = get_model_id("claude-haiku-4-5")

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=[{"type": "text", "text": GATE_SYSTEM_PROMPT}],
            tools=[SUBMIT_GATE_FINDINGS_TOOL],
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this diff for security vulnerabilities:\n\n```diff\n{diff_text}\n```"
                    + (
                        "\n\nNote: diff was truncated (too large for gate scan). Focus on what's visible."
                        if truncated
                        else ""
                    ),
                }
            ],
        )
    except Exception as e:
        logger.exception("Haiku gate call failed")
        raise HTTPException(502, f"Gate scan failed: {e}")

    # 5. Parse findings from tool_use response
    findings = []
    summary = "No issues found."
    for block in response.content:
        if hasattr(block, "type") and block.type == "tool_use":
            if block.name == "submit_gate_findings":
                findings = block.input.get("findings", [])
                summary = block.input.get("summary", summary)

    # 6. Track billing
    if settings.autumn_secret_key and auth.clerk_id:
        try:
            await autumn_track(
                settings.autumn_secret_key, auth.clerk_id, "gate_scan", 1
            )
        except Exception as e:
            logger.warning(f"Autumn gate track failed: {e}")

    # 7. Drift detection (non-blocking)
    drift = None
    if req.repo_url and auth.user_id:
        try:
            drift = await _get_drift_info(auth.user_id, req.repo_url)
        except Exception:
            pass

    elapsed_ms = int((time.time() - start) * 1000)
    return {
        "findings": findings,
        "summary": summary
        + (f" (diff truncated to {MAX_DIFF_CHARS // 1000}K chars)" if truncated else ""),
        "blocked": False,  # Server doesn't know the threshold; action decides
        "drift": drift,
        "scan_duration_ms": elapsed_ms,
    }


async def _get_drift_info(user_id: str, repo_url: str) -> dict | None:
    """Query Convex for last deep scan date on this repo."""
    result = await convex_query(
        "projects:getLastScanDate",
        {"userId": user_id, "repoUrl": repo_url},
    )
    value = (
        result.get("value", result) if isinstance(result, dict) else result
    )

    if not value:
        return {
            "last_deep_scan_days_ago": None,
            "message": "Last deep scan: never. Run: rem scan --deep",
        }

    last_scan_at = value.get("lastScanAt")
    if not last_scan_at:
        return {
            "last_deep_scan_days_ago": None,
            "message": "Last deep scan: never. Run: rem scan --deep",
        }

    days_ago = int((time.time() * 1000 - last_scan_at) / (1000 * 60 * 60 * 24))

    if days_ago > 14:
        return {
            "last_deep_scan_days_ago": days_ago,
            "message": f"Last deep scan: {days_ago} days ago. Run: rem scan --deep",
        }

    return None  # Recent scan, no nudge
