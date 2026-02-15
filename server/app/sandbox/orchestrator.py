"""Sandbox orchestrator — spins up Modal sandboxes for scan jobs.

Sandboxes write directly to Convex (not back to the server) since
Modal containers can't reach localhost.
"""

import modal

MINUTES = 60

# MCP servers available to the agent
MCP_SERVERS = [
    {
        "type": "url",
        "url": "https://mcp.firecrawl.dev/fc-a82ab47650734b138291950300675c4a/v2/mcp",
        "name": "firecrawl",
    },
]

sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "jq")
    .pip_install(
        "httpx",
        "anthropic",
        "pydantic",
    )
)

web_sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl")
    .pip_install(
        "httpx",
        "anthropic",
        "pydantic",
        "playwright",
    )
    .run_commands("playwright install --with-deps chromium")
)

app = modal.App("re-zero-sandbox")


@app.function(
    image=sandbox_image,
    timeout=60 * MINUTES,
    secrets=[modal.Secret.from_name("re-zero-keys")],
)
async def run_oss_scan(
    scan_id: str,
    project_id: str,
    repo_url: str,
    agent: str,
    convex_url: str,
    convex_deploy_key: str,
):
    """Run an OSS security scan in a Modal sandbox."""
    import subprocess

    work_dir = "/root/target"

    await _push_action(convex_url, convex_deploy_key, scan_id, "observation", "Rem is cloning the repository...")
    subprocess.run(
        ["git", "clone", "--depth=1", repo_url, work_dir],
        check=True,
        capture_output=True,
    )

    result = subprocess.run(
        ["find", work_dir, "-type", "f", "-not", "-path", "*/.git/*"],
        capture_output=True,
        text=True,
    )
    file_list = result.stdout.strip().split("\n")[:200]

    await _push_action(
        convex_url, convex_deploy_key, scan_id, "observation",
        f"Rem cloned {repo_url} — {len(file_list)} files indexed"
    )

    if agent == "opus":
        await _run_claude_agent(
            scan_id, project_id, repo_url, work_dir, file_list,
            convex_url, convex_deploy_key,
        )
    else:
        await _run_opencode_agent(
            scan_id, agent, convex_url, convex_deploy_key,
        )


async def _convex_mutation(convex_url: str, deploy_key: str, path: str, args: dict):
    """Call a Convex mutation directly from the sandbox."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{convex_url}/api/mutation",
            json={"path": path, "args": args},
            headers={"Authorization": f"Convex {deploy_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def _push_action(convex_url: str, deploy_key: str, scan_id: str, action_type: str, payload):
    """Push an action directly to Convex."""
    await _convex_mutation(convex_url, deploy_key, "actions:push", {
        "scanId": scan_id,
        "type": action_type,
        "payload": payload,
    })


async def _convex_query(convex_url: str, deploy_key: str, path: str, args: dict):
    """Call a Convex query directly from the sandbox."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{convex_url}/api/query",
            json={"path": path, "args": args},
            headers={"Authorization": f"Convex {deploy_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def _ask_human(
    convex_url: str, deploy_key: str,
    scan_id: str, question: str,
) -> str:
    """Ask the human operator a question and wait for their response.

    Creates a prompt in Convex, pushes a human_input_request action to the
    trace, then polls until the user responds (or 10 minutes elapse).
    """
    import asyncio

    # Create the prompt record
    result = await _convex_mutation(convex_url, deploy_key, "prompts:create", {
        "scanId": scan_id,
        "question": question,
    })
    prompt_id = result["value"]

    # Push a trace action so the frontend shows the input UI
    await _push_action(convex_url, deploy_key, scan_id, "human_input_request", {
        "promptId": prompt_id,
        "question": question,
    })

    # Poll until answered (10 min timeout, 3s interval)
    for _ in range(200):
        await asyncio.sleep(3)
        resp = await _convex_query(convex_url, deploy_key, "prompts:get", {
            "promptId": prompt_id,
        })
        prompt = resp.get("value") or resp
        if isinstance(prompt, dict) and prompt.get("status") == "answered":
            return prompt.get("response", "")

    return "(no response — operator timed out)"


async def _upload_screenshot(convex_url: str, deploy_key: str, screenshot_bytes: bytes) -> str:
    """Upload screenshot to Convex file storage, return storageId."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{convex_url}/api/mutation",
            json={"path": "storage:generateUploadUrl", "args": {}},
            headers={"Authorization": f"Convex {deploy_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        upload_url = resp.json()["value"]

        resp = await client.post(
            upload_url,
            content=screenshot_bytes,
            headers={"Content-Type": "image/png"},
            timeout=30,
        )
        resp.raise_for_status()
        # Upload returns either {"storageId":"..."} or a bare "..." string
        import json
        try:
            data = json.loads(resp.text)
            if isinstance(data, dict) and "storageId" in data:
                return data["storageId"]
            return str(data)
        except (json.JSONDecodeError, TypeError):
            return resp.text.strip().strip('"')


def _extract_snippet(work_dir: str, location: str) -> str | None:
    """Parse a location like 'src/auth.py:31-36' and read those lines from the repo."""
    import os
    import re

    m = re.match(r"^(.+?):(\d+)(?:-(\d+))?", location)
    if not m:
        return None
    file_path, start_str, end_str = m.group(1), m.group(2), m.group(3)
    start = int(start_str)
    end = int(end_str) if end_str else start

    abs_path = os.path.join(work_dir, file_path)
    try:
        with open(abs_path) as f:
            lines = f.readlines()
        snippet_lines = lines[start - 1 : end]
        if not snippet_lines:
            return None
        return "".join(snippet_lines)
    except Exception:
        return None


async def _compile_report(
    convex_url: str, deploy_key: str,
    scan_id: str, project_id: str,
    work_dir: str = "",
):
    """Second-pass agent that reads the scan trace and produces a structured report.

    Called when the scanning agent finishes without a proper report. A fresh
    context means it can focus entirely on structuring findings.
    """
    import anthropic
    import json

    # Fetch all actions from the trace
    resp = await _convex_query(convex_url, deploy_key, "actions:listByScan", {
        "scanId": scan_id,
    })
    actions = resp.get("value", resp) if isinstance(resp, dict) else resp

    # Build a condensed trace for the report agent — reasoning + observations + tool summaries
    trace_lines = []
    for action in (actions if isinstance(actions, list) else []):
        a_type = action.get("type", "")
        payload = action.get("payload", "")
        if a_type == "reasoning":
            trace_lines.append(f"[reasoning] {payload}")
        elif a_type == "observation":
            trace_lines.append(f"[observation] {payload}")
        elif a_type == "tool_call" and isinstance(payload, dict):
            trace_lines.append(f"[tool_call] {payload.get('summary', '')}")
        elif a_type == "tool_result" and isinstance(payload, dict):
            summary = payload.get("summary", "")
            content = payload.get("content", "")
            # Include content for results that have security-relevant data
            if content and len(str(content)) < 2000:
                trace_lines.append(f"[tool_result] {summary}\n  {str(content)[:1500]}")
            else:
                trace_lines.append(f"[tool_result] {summary}")

    trace_text = "\n".join(trace_lines)
    # Cap at ~80k chars to stay within context
    if len(trace_text) > 80000:
        trace_text = trace_text[:80000] + "\n... (trace truncated)"

    client = anthropic.Anthropic()

    system = """You are a security report writer. You're given the full trace from an automated penetration test / security scan. Your job is to read through the trace and produce a structured vulnerability report.

Extract every distinct vulnerability or security issue mentioned in the trace. For each one, create a separate finding with:
- title: specific name of the vulnerability
- severity: critical/high/medium/low/info
- description: what the vulnerability is and why it matters
- location: URL, file path, or page where it was found
- recommendation: how to fix it
- code_snippet: the actual evidence — HTTP headers, HTML, JS code, response content, etc. that demonstrates the issue

Be thorough — if the scanning agent mentioned it, include it. Don't combine multiple issues into one finding. The summary should be 2-3 sentences covering the overall security posture."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8192,
        system=system,
        tools=[{
            "name": "submit_findings",
            "description": "Submit the structured security report",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                                "description": {"type": "string"},
                                "location": {"type": "string"},
                                "recommendation": {"type": "string"},
                                "code_snippet": {"type": "string"},
                            },
                            "required": ["title", "severity", "description"],
                        },
                    },
                },
                "required": ["summary", "findings"],
            },
        }],
        messages=[{"role": "user", "content": f"Here is the full trace from a security scan. Read through it and produce a structured vulnerability report using the submit_findings tool.\n\n{trace_text}"}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_findings":
            findings = block.input.get("findings", [])
            summary = block.input.get("summary", "Report compiled from scan trace.")
            await _push_action(convex_url, deploy_key, scan_id, "observation",
                f"Report writer compiled {len(findings)} findings from trace")
            await _submit_report(
                convex_url, deploy_key,
                scan_id, project_id,
                findings, summary,
                work_dir=work_dir,
            )
            return

    # Report agent also failed — mark scan failed
    await _convex_mutation(convex_url, deploy_key, "scans:updateStatus", {
        "scanId": scan_id,
        "status": "failed",
        "error": "Could not compile a structured report from the scan trace.",
    })


async def _submit_report(
    convex_url: str, deploy_key: str,
    scan_id: str, project_id: str, findings: list, summary: str,
    work_dir: str = "",
):
    """Submit report and mark scan completed directly in Convex.

    Assigns each finding a sequential ID (VN-001, VN-002, ...) before saving.
    Extracts code snippets from the repo when the LLM didn't include them.
    """
    for i, finding in enumerate(findings):
        finding["id"] = f"VN-{i + 1:03d}"
        # Map snake_case from LLM to camelCase for Convex
        if "code_snippet" in finding:
            finding["codeSnippet"] = finding.pop("code_snippet")
        # Fallback: extract from repo if LLM didn't include a snippet
        if not finding.get("codeSnippet") and finding.get("location") and work_dir:
            snippet = _extract_snippet(work_dir, finding["location"])
            if snippet:
                finding["codeSnippet"] = snippet

    await _convex_mutation(convex_url, deploy_key, "reports:submit", {
        "scanId": scan_id,
        "projectId": project_id,
        "findings": findings,
        "summary": summary,
    })
    await _convex_mutation(convex_url, deploy_key, "scans:updateStatus", {
        "scanId": scan_id,
        "status": "completed",
    })


async def _run_claude_agent(
    scan_id: str,
    project_id: str,
    repo_url: str,
    work_dir: str,
    file_list: list[str],
    convex_url: str,
    deploy_key: str,
):
    """Run security scan using Claude API (Opus 4.6)."""
    import anthropic
    import os
    import subprocess

    client = anthropic.Anthropic()

    system_prompt = f"""You are Rem, a security researcher performing a vulnerability audit on a codebase.

Repository: {repo_url}
Working directory: {work_dir}

Your task:
1. Analyze the codebase for security vulnerabilities
2. Focus on: injection flaws, authentication issues, data exposure, misconfigurations, dependency vulnerabilities
3. For each finding, provide: title, severity (critical/high/medium/low/info), description, file location, remediation
4. IMPORTANT: For each finding, include a code_snippet field with the exact vulnerable code lines you found. Copy the relevant lines verbatim from the files you read. Include just the vulnerable section (typically 3-15 lines), not entire files.

You have Firecrawl tools for web scraping and search. Use firecrawl_search to look up known CVEs for dependencies you find, or firecrawl_scrape to check project documentation and websites for security-relevant info.

Be thorough but precise. Only report real vulnerabilities, not style issues.

Files in repository:
{chr(10).join(file_list[:100])}
"""

    await _push_action(convex_url, deploy_key, scan_id, "reasoning", "Rem starting security analysis...")

    messages = [{"role": "user", "content": "Analyze this codebase for security vulnerabilities. Read key files, identify attack surfaces, and produce a structured security report."}]

    tools = [
        {
            "name": "read_file",
            "description": "Read a file from the repository",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to repo root"}
                },
                "required": ["path"],
            },
        },
        {
            "name": "search_code",
            "description": "Search for a pattern in the codebase",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Grep pattern to search for"}
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "submit_findings",
            "description": "Submit the final security report",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                                "description": {"type": "string"},
                                "location": {"type": "string", "description": "File path and line numbers, e.g. src/auth.py:31-36"},
                                "recommendation": {"type": "string"},
                                "code_snippet": {"type": "string", "description": "The exact vulnerable code lines copied from the file"},
                            },
                            "required": ["title", "severity", "description"],
                        },
                    },
                },
                "required": ["summary", "findings"],
            },
        },
        {
            "name": "ask_human",
            "description": "Ask the human operator a question and wait for their response. Use this when you need information only a human can provide: 2FA codes, CAPTCHAs, login instructions, clarification about the target, or any situation where you're stuck and need human guidance.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the operator. Be specific about what you need and why."},
                },
                "required": ["question"],
            },
        },
    ]

    mcp_tools = [{"type": "mcp_toolset", "mcp_server_name": s["name"]} for s in MCP_SERVERS]

    turn = 0
    while True:
        turn += 1

        # MCP servers can have transient failures — retry, then fall back without them
        response = None
        for attempt in range(3):
            try:
                response = client.beta.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=[*tools, *mcp_tools] if attempt < 2 else tools,
                    mcp_servers=MCP_SERVERS if attempt < 2 else [],
                    messages=messages,
                    betas=["mcp-client-2025-11-20"],
                )
                break
            except Exception as e:
                if attempt < 2 and "MCP" in str(e):
                    import asyncio
                    await asyncio.sleep(2)
                    continue
                raise

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Push text/reasoning blocks
        text_blocks = [b.text for b in assistant_content if hasattr(b, "text") and b.type == "text"]
        for text in text_blocks:
            if text.strip():
                await _push_action(convex_url, deploy_key, scan_id, "reasoning", text.strip())

        # Push MCP tool calls/results to trace (already executed server-side)
        # Build tool_use_id -> tool name map for pairing results with calls
        mcp_tool_names = {}
        for block in assistant_content:
            if block.type == "mcp_tool_use":
                mcp_tool_names[block.id] = block.name

        for block in assistant_content:
            if block.type == "mcp_tool_use":
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": block.name,
                    "summary": f"{block.name}({', '.join(f'{k}={repr(v)[:60]}' for k, v in (block.input or {}).items())})"[:120],
                    "input": block.input,
                })
            elif block.type == "mcp_tool_result":
                tool_name = mcp_tool_names.get(block.tool_use_id, "mcp")
                # Extract text from MCP content blocks
                content_text = ""
                if hasattr(block, "content") and block.content:
                    if isinstance(block.content, str):
                        content_text = block.content
                    elif isinstance(block.content, list):
                        parts = []
                        for item in block.content:
                            if hasattr(item, "text"):
                                parts.append(item.text)
                            else:
                                parts.append(str(item))
                        content_text = "\n".join(parts)
                    else:
                        content_text = str(block.content)
                # Cap at 50KB for Convex doc size limits
                content_text = content_text[:50000]
                char_count = f"{len(content_text):,}" if content_text else "0"
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": tool_name,
                    "summary": f"{tool_name} returned {char_count} chars",
                    "content": content_text,
                })

        # Only process LOCAL tool_use blocks (MCP tools are handled server-side)
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_uses and response.stop_reason == "end_turn":
            break

        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "ask_human":
                question = tool_use.input["question"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "ask_human",
                    "summary": f"Asking operator: {question[:80]}",
                    "input": {"question": question},
                })
                human_response = await _ask_human(
                    convex_url, deploy_key, scan_id, question,
                )
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "ask_human",
                    "summary": f"Operator responded",
                    "content": human_response,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"Operator response: {human_response}",
                })

            elif tool_use.name == "read_file":
                file_path = tool_use.input["path"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "read_file",
                    "summary": f"Reading {file_path}",
                    "input": {"path": file_path},
                })

                abs_path = os.path.join(work_dir, file_path)
                try:
                    with open(abs_path) as f:
                        content = f.read(50000)
                    result_text = content
                except Exception as e:
                    result_text = f"Error reading file: {e}"

                lines = result_text.count("\n") + 1
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "read_file",
                    "summary": f"Read {file_path} ({len(result_text):,} chars, {lines} lines)",
                    "path": file_path,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "search_code":
                pattern = tool_use.input["pattern"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "search_code",
                    "summary": f"Searching for `{pattern}`",
                    "input": {"pattern": pattern},
                })

                try:
                    grep_result = subprocess.run(
                        ["grep", "-rn", pattern, work_dir,
                         "--include=*.py", "--include=*.js", "--include=*.ts",
                         "--include=*.go", "--include=*.c", "--include=*.cpp",
                         "--include=*.java", "--include=*.rs", "--include=*.rb",
                         "--include=*.php", "--include=*.sol", "--include=*.yaml",
                         "--include=*.yml", "--include=*.json", "--include=*.toml",
                         "--include=*.cfg", "--include=*.ini", "--include=*.env",
                         "--include=*.sh", "--include=*.bash", "--include=*.dockerfile",
                         "--include=Makefile", "--include=*.html", "--include=*.xml"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    output = grep_result.stdout[:10000]
                except Exception as e:
                    output = f"Error: {e}"

                match_count = output.count("\n") if output.strip() else 0
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "search_code",
                    "summary": f"Found {match_count} matches for `{pattern}`",
                    "pattern": pattern,
                    "matches": match_count,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": output if output else "No matches found.",
                })

            elif tool_use.name == "submit_findings":
                findings = tool_use.input.get("findings", [])
                summary = tool_use.input.get("summary", "")
                n = len(findings)

                # If the agent crammed everything into the summary with few/no
                # structured findings, hand off to the report writer instead.
                if n <= 1 and len(summary) > 300:
                    await _push_action(convex_url, deploy_key, scan_id, "observation",
                        "Findings are under-structured — handing off to report writer for proper breakdown...")
                    await _compile_report(convex_url, deploy_key, scan_id, project_id, work_dir=work_dir)
                    return

                await _push_action(convex_url, deploy_key, scan_id, "observation", f"Rem is compiling report — {n} findings identified")
                await _submit_report(
                    convex_url, deploy_key,
                    scan_id, project_id,
                    findings,
                    summary,
                    work_dir=work_dir,
                )
                return

        messages.append({"role": "user", "content": tool_results})

    # Agent stopped without calling submit_findings — hand off to report writer
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        "Scanning complete. Handing off to report writer...")
    await _compile_report(convex_url, deploy_key, scan_id, project_id, work_dir=work_dir)


async def _run_opencode_agent(
    scan_id: str,
    agent: str,
    convex_url: str,
    deploy_key: str,
):
    """Run security scan using OpenCode SDK with RL-trained models."""
    await _push_action(
        convex_url, deploy_key, scan_id, "observation",
        f"Rem ({agent}) not yet deployed. Models need RL training first."
    )


# ---------------------------------------------------------------------------
# Web pentesting scan (Playwright + headless Chromium)
# ---------------------------------------------------------------------------

@app.function(
    image=web_sandbox_image,
    timeout=60 * MINUTES,
    secrets=[modal.Secret.from_name("re-zero-keys")],
)
async def run_web_scan(
    scan_id: str,
    project_id: str,
    target_url: str,
    test_account: dict | None,
    user_context: str | None,
    agent: str,
    convex_url: str,
    convex_deploy_key: str,
):
    """Run a web application pentesting scan with headless Chromium via Playwright."""
    from playwright.async_api import async_playwright

    try:
        await _push_action(
            convex_url, convex_deploy_key, scan_id, "observation",
            f"Rem is launching a headless browser targeting {target_url}...",
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(target_url, timeout=20000)

            await _push_action(
                convex_url, convex_deploy_key, scan_id, "observation",
                f"Browser active — loaded {page.url}",
            )

            if agent == "opus":
                await _run_web_claude_agent(
                    scan_id, project_id, target_url, test_account,
                    user_context, page, convex_url, convex_deploy_key,
                )
            else:
                await _push_action(
                    convex_url, convex_deploy_key, scan_id, "observation",
                    f"Rem ({agent}) not yet deployed for web scanning.",
                )

            await browser.close()

    except Exception as e:
        # Surface error to the frontend
        try:
            await _push_action(
                convex_url, convex_deploy_key, scan_id, "observation",
                f"Rem encountered an error: {e}",
            )
            await _convex_mutation(convex_url, convex_deploy_key, "scans:updateStatus", {
                "scanId": scan_id,
                "status": "failed",
                "error": str(e)[:500],
            })
        except Exception:
            pass  # best-effort error reporting
        raise


async def _run_web_claude_agent(
    scan_id: str,
    project_id: str,
    target_url: str,
    test_account: dict | None,
    user_context: str | None,
    page,
    convex_url: str,
    deploy_key: str,
):
    """Run web pentesting using Claude Opus 4.6 with Playwright browser tools."""
    import anthropic
    import json

    client = anthropic.Anthropic()

    auth_info = ""
    if test_account:
        username = test_account.get("username", "")
        password = test_account.get("password", "")
        auth_info = f"""Test account provided:
  Username: {username}
  Password: {password}

Scan BOTH unauthenticated and authenticated surfaces:
1. First pass: unauthenticated — check public attack surface, headers, exposed endpoints
2. Then login with the test account
3. Second pass: authenticated — explore protected areas, test privilege escalation, session management"""
    else:
        auth_info = "No test credentials provided. Scan unauthenticated attack surface only."

    context_info = ""
    if user_context:
        context_info = f"""
Operator notes (from the person who set up this scan):
{user_context}

Pay close attention to these notes — they contain insider knowledge about the target."""

    system_prompt = f"""You are Rem, a security researcher performing a web application penetration test.

Target: {target_url}
{auth_info}
{context_info}

Human-in-the-loop:
You have an ask_human tool. The operator is watching the scan live and can help you. When you hit something you can't get past alone — 2FA codes, email verification, CAPTCHAs, bot detection, or any authentication challenge — use ask_human to request what you need. Don't skip these and move on to unauthenticated testing; the whole point of having test credentials is to test the authenticated surface. Ask, wait for the response, then continue.

Methodology:
1. Use get_page_content to understand the page structure — forms, links, inputs
2. Check security headers and cookies via execute_js
3. Crawl key pages — forms, login, search, API endpoints, admin paths
4. Actively test for vulnerabilities:
   - XSS: inject payloads via fill_field and navigate to URL params
   - SQL injection: test inputs with ' OR 1=1 --, UNION SELECT, etc.
   - Auth bypass: navigate to /admin, /api/users, modify IDs in URLs
   - CSRF: check if forms have anti-CSRF tokens (get_page_content)
   - Security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options
   - Cookie flags: HttpOnly, Secure, SameSite
   - Info disclosure: error messages, stack traces, .env, .git, robots.txt
   - CORS: check Access-Control-Allow-Origin via execute_js
   - Directory traversal: try ../../etc/passwd in file parameters
5. Take screenshots of important findings as visual evidence
6. Submit your report with all findings

For click and fill_field, use CSS selectors. Use get_page_content first to find the right selectors.

You have Firecrawl tools for supplementary web research (CVE lookups, documentation).

Be thorough and aggressive in testing. Only report confirmed or highly probable vulnerabilities.

Report format:
When you call submit_findings, each vulnerability should be its own entry in the findings array — don't consolidate them into the summary. The summary is just a brief overview (2-3 sentences). Each finding should include title, severity, description, location (URL/page), recommendation, and code_snippet (the actual headers, HTML, JS, or response content that demonstrates the issue). The richer each finding is, the more useful the report."""

    await _push_action(convex_url, deploy_key, scan_id, "reasoning",
        "Rem starting web penetration test...")

    messages = [{"role": "user", "content": f"Perform a comprehensive penetration test on {target_url}. Actively probe for vulnerabilities, take screenshots of findings, and produce a structured security report."}]

    tools = [
        {
            "name": "navigate",
            "description": "Navigate the browser to a URL. Returns the page title and first 2000 chars of visible text.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"},
                },
                "required": ["url"],
            },
        },
        {
            "name": "get_page_content",
            "description": "Get the current page's HTML, links, forms, and interactive elements. Use this to understand page structure before interacting.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "click",
            "description": "Click an element by CSS selector or text. Use get_page_content first to find selectors.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector (e.g. 'button.login', '#submit', 'a[href=\"/admin\"]') or text: prefix for text content (e.g. 'text:Sign In')"},
                },
                "required": ["selector"],
            },
        },
        {
            "name": "fill_field",
            "description": "Fill a form field with a value. Triggers proper input events.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector for the input field"},
                    "value": {"type": "string", "description": "Value to fill in"},
                },
                "required": ["selector", "value"],
            },
        },
        {
            "name": "execute_js",
            "description": "Execute JavaScript in the browser. Use for checking cookies, response headers, testing XSS, DOM inspection. Return values to see results.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "JavaScript to execute. Use 'return' to get values back."},
                },
                "required": ["script"],
            },
        },
        {
            "name": "screenshot",
            "description": "Capture a screenshot of the current page as visual evidence",
            "input_schema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Brief label for what this screenshot captures"},
                },
                "required": ["label"],
            },
        },
        {
            "name": "submit_findings",
            "description": "Submit the final security report",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                                "description": {"type": "string"},
                                "location": {"type": "string", "description": "URL path or page where the vulnerability was found"},
                                "recommendation": {"type": "string"},
                                "code_snippet": {"type": "string", "description": "Relevant HTML, JS, or HTTP headers showing the vulnerability"},
                            },
                            "required": ["title", "severity", "description"],
                        },
                    },
                },
                "required": ["summary", "findings"],
            },
        },
        {
            "name": "ask_human",
            "description": "Ask the human operator a question and wait for their response. Use this when you need information only a human can provide: 2FA codes, CAPTCHAs, login instructions, clarification about the target, or any situation where you're stuck and need human guidance.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the operator. Be specific about what you need and why."},
                },
                "required": ["question"],
            },
        },
    ]

    mcp_tools = [{"type": "mcp_toolset", "mcp_server_name": s["name"]} for s in MCP_SERVERS]

    turn = 0
    while True:
        turn += 1

        # MCP servers can have transient failures — retry, then fall back without them
        response = None
        for attempt in range(3):
            try:
                response = client.beta.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=[*tools, *mcp_tools] if attempt < 2 else tools,
                    mcp_servers=MCP_SERVERS if attempt < 2 else [],
                    messages=messages,
                    betas=["mcp-client-2025-11-20"],
                )
                break
            except Exception as e:
                if attempt < 2 and "MCP" in str(e):
                    import asyncio
                    await asyncio.sleep(2)
                    continue
                raise

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Push text/reasoning blocks
        text_blocks = [b.text for b in assistant_content if hasattr(b, "text") and b.type == "text"]
        for text in text_blocks:
            if text.strip():
                await _push_action(convex_url, deploy_key, scan_id, "reasoning", text.strip())

        # Push MCP tool calls/results to trace
        mcp_tool_names = {}
        for block in assistant_content:
            if block.type == "mcp_tool_use":
                mcp_tool_names[block.id] = block.name

        for block in assistant_content:
            if block.type == "mcp_tool_use":
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": block.name,
                    "summary": f"{block.name}({', '.join(f'{k}={repr(v)[:60]}' for k, v in (block.input or {}).items())})"[:120],
                    "input": block.input,
                })
            elif block.type == "mcp_tool_result":
                tool_name = mcp_tool_names.get(block.tool_use_id, "mcp")
                content_text = ""
                if hasattr(block, "content") and block.content:
                    if isinstance(block.content, str):
                        content_text = block.content
                    elif isinstance(block.content, list):
                        parts = []
                        for item in block.content:
                            if hasattr(item, "text"):
                                parts.append(item.text)
                            else:
                                parts.append(str(item))
                        content_text = "\n".join(parts)
                    else:
                        content_text = str(block.content)
                content_text = content_text[:50000]
                char_count = f"{len(content_text):,}" if content_text else "0"
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": tool_name,
                    "summary": f"{tool_name} returned {char_count} chars",
                    "content": content_text,
                })

        # Process local tool_use blocks
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_uses and response.stop_reason == "end_turn":
            break

        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "ask_human":
                question = tool_use.input["question"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "ask_human",
                    "summary": f"Asking operator: {question[:80]}",
                    "input": {"question": question},
                })
                human_response = await _ask_human(
                    convex_url, deploy_key, scan_id, question,
                )
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "ask_human",
                    "summary": f"Operator responded",
                    "content": human_response,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"Operator response: {human_response}",
                })

            elif tool_use.name == "navigate":
                url = tool_use.input["url"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "navigate",
                    "summary": f"Navigating to {url}",
                    "input": {"url": url},
                })

                try:
                    resp = await page.goto(url, timeout=15000)
                    status = resp.status if resp else "?"
                    title = await page.title()
                    text = await page.inner_text("body")
                    result_text = f"Navigated to {page.url} (HTTP {status})\nTitle: {title}\n\n{text[:2000]}"
                except Exception as e:
                    result_text = f"Navigation failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "navigate",
                    "summary": f"Loaded {page.url}"[:120],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:5000],
                })

            elif tool_use.name == "get_page_content":
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "get_page_content",
                    "summary": f"Reading page content at {page.url}",
                })

                try:
                    # Get a structured view of the page
                    content = await page.evaluate("""() => {
                        const result = {
                            url: location.href,
                            title: document.title,
                            forms: [],
                            links: [],
                            inputs: [],
                            meta: [],
                        };
                        // Forms
                        document.querySelectorAll('form').forEach((f, i) => {
                            result.forms.push({
                                action: f.action, method: f.method, id: f.id,
                                fields: Array.from(f.querySelectorAll('input,select,textarea')).map(el => ({
                                    tag: el.tagName, type: el.type, name: el.name, id: el.id, placeholder: el.placeholder
                                }))
                            });
                        });
                        // Links (first 50)
                        Array.from(document.querySelectorAll('a[href]')).slice(0, 50).forEach(a => {
                            result.links.push({href: a.href, text: a.textContent?.trim().slice(0, 60)});
                        });
                        // Standalone inputs
                        document.querySelectorAll('input:not(form input), textarea:not(form textarea)').forEach(el => {
                            result.inputs.push({tag: el.tagName, type: el.type, name: el.name, id: el.id});
                        });
                        // Meta tags
                        document.querySelectorAll('meta').forEach(m => {
                            if (m.name || m.httpEquiv) result.meta.push({name: m.name, httpEquiv: m.httpEquiv, content: m.content});
                        });
                        return result;
                    }""")
                    # Also get truncated HTML
                    html = await page.content()
                    content["html_preview"] = html[:8000]
                    result_text = json.dumps(content, indent=2, default=str)
                except Exception as e:
                    result_text = f"Failed to read page: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "get_page_content",
                    "summary": f"Page content: {len(result_text):,} chars",
                    "content": result_text[:15000],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:15000],
                })

            elif tool_use.name == "click":
                selector = tool_use.input["selector"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "click",
                    "summary": f"Clicking: {selector[:80]}",
                    "input": {"selector": selector},
                })

                try:
                    if selector.startswith("text:"):
                        await page.get_by_text(selector[5:]).first.click(timeout=5000)
                    else:
                        await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    result_text = f"Clicked {selector}. Now at {page.url}"
                except Exception as e:
                    result_text = f"Click failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "click",
                    "summary": result_text[:120],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "fill_field":
                selector = tool_use.input["selector"]
                value = tool_use.input["value"]
                display_val = value if len(value) < 40 else value[:37] + "..."
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "fill_field",
                    "summary": f"Filling {selector[:40]} with '{display_val}'",
                    "input": {"selector": selector, "value": value},
                })

                try:
                    await page.fill(selector, value, timeout=5000)
                    result_text = f"Filled {selector} with value"
                except Exception as e:
                    result_text = f"Fill failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "fill_field",
                    "summary": result_text[:120],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "execute_js":
                script = tool_use.input["script"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "execute_js",
                    "summary": f"JS: {script[:80]}",
                    "input": {"script": script},
                })

                try:
                    result = await page.evaluate(script)
                    result_text = json.dumps(result, indent=2, default=str) if result is not None else "undefined"
                except Exception as e:
                    result_text = f"JS execution failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "execute_js",
                    "summary": f"JS returned {len(str(result_text)):,} chars",
                    "content": result_text[:10000],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:10000],
                })

            elif tool_use.name == "screenshot":
                label = tool_use.input.get("label", "screenshot")
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "screenshot",
                    "summary": f"Capturing: {label}",
                })

                try:
                    screenshot_bytes = await page.screenshot(type="png")
                    storage_id = await _upload_screenshot(
                        convex_url, deploy_key, screenshot_bytes,
                    )
                    await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                        "tool": "screenshot",
                        "summary": f"Captured: {label}",
                        "storageId": storage_id,
                    })
                    result_text = f"Screenshot captured: {label}"
                except Exception as e:
                    await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                        "tool": "screenshot",
                        "summary": f"Screenshot failed: {e}",
                    })
                    result_text = f"Screenshot failed: {e}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "submit_findings":
                findings = tool_use.input.get("findings", [])
                summary = tool_use.input.get("summary", "")
                n = len(findings)

                if n <= 1 and len(summary) > 300:
                    await _push_action(convex_url, deploy_key, scan_id, "observation",
                        "Findings are under-structured — handing off to report writer for proper breakdown...")
                    await _compile_report(convex_url, deploy_key, scan_id, project_id)
                    return

                await _push_action(convex_url, deploy_key, scan_id, "observation",
                    f"Rem is compiling report — {n} findings identified")
                await _submit_report(
                    convex_url, deploy_key,
                    scan_id, project_id,
                    findings,
                    summary,
                )
                return

        messages.append({"role": "user", "content": tool_results})

    # Agent stopped without calling submit_findings — hand off to report writer
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        "Scanning complete. Handing off to report writer...")
    await _compile_report(convex_url, deploy_key, scan_id, project_id)
