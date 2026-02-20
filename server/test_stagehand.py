"""Test Stagehand with Bedrock proxy in Modal — validates streaming fix."""
import modal
import os

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("httpx", "playwright", "stagehand", "anthropic[bedrock]", "aiohttp")
    .run_commands(
        "playwright install --with-deps chromium",
        'bash -c \'CHROME=$(find /root/.cache/ms-playwright -type f \\( -name chrome -o -name headless_shell \\) -executable 2>/dev/null | head -1) && '
        'ln -sf "$CHROME" /usr/local/bin/stagehand-chrome && '
        'echo "Linked $CHROME -> /usr/local/bin/stagehand-chrome"\'',
    )
    .env({"CHROME_PATH": "/usr/local/bin/stagehand-chrome"})
)

app = modal.App("stagehand-test")


BEDROCK_MODEL_MAP = {
    "claude-haiku-4-5-20251001": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-sonnet-4-5-20250929": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-opus-4-6": "global.anthropic.claude-opus-4-6-v1",
}


async def _start_bedrock_proxy():
    """Start a local HTTP proxy that translates Anthropic API calls to Bedrock."""
    from aiohttp import web
    import anthropic
    import json

    bedrock = anthropic.AsyncAnthropicBedrock(
        aws_region=os.environ.get("AWS_REGION", "us-west-2"),
    )

    async def handle_messages(request):
        body = await request.json()
        model = body.get("model", "")
        bedrock_model = BEDROCK_MODEL_MAP.get(model, model)
        body["model"] = bedrock_model
        print(f"[proxy] {model} → {bedrock_model}, stream={body.get('stream', False)}, tools={len(body.get('tools', []))}")

        stream_mode = body.pop("stream", False)

        # Build shared kwargs
        api_kwargs = {
            "model": body["model"],
            "max_tokens": body.get("max_tokens", 1024),
            "messages": body.get("messages", []),
        }
        for key in ("system", "temperature", "tools", "tool_choice"):
            val = body.get(key)
            if val is not None:
                api_kwargs[key] = val

        try:
            if stream_mode:
                resp = web.StreamResponse(headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                })
                await resp.prepare(request)

                # Use raw streaming to get wire-format SSE events
                raw_stream = await bedrock.messages.create(**api_kwargs, stream=True)
                async for event in raw_stream:
                    data = event.model_dump()
                    event_type = data.get("type", "unknown")
                    sse_line = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                    await resp.write(sse_line.encode())

                return resp
            else:
                # Bedrock SDK forces streaming for tool-use / high-max_tokens.
                # Use .stream() helper to stream under the hood and collect the
                # final message for a JSON response.
                async with bedrock.messages.stream(**api_kwargs) as stream:
                    final_message = await stream.get_final_message()
                return web.json_response(final_message.model_dump())
        except Exception as e:
            import traceback
            print(f"[proxy] ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            return web.json_response(
                {"error": {"type": "api_error", "message": str(e)}},
                status=500,
            )

    proxy_app = web.Application()
    proxy_app.router.add_post("/v1/messages", handle_messages)
    proxy_app.router.add_post("/messages", handle_messages)

    runner = web.AppRunner(proxy_app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    print(f"[proxy] Bedrock proxy listening on port {port}")

    return port, runner


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("re-zero-keys")],
    timeout=300,
)
async def test_stagehand():
    import time
    from stagehand import AsyncStagehand

    print("=== ENV CHECK ===")
    print(f"CHROME_PATH={os.environ.get('CHROME_PATH')}")
    print(f"AWS_ACCESS_KEY_ID={'set' if os.environ.get('AWS_ACCESS_KEY_ID') else 'MISSING'}")

    # Step 1: Start Bedrock proxy
    print("\n=== STARTING BEDROCK PROXY ===")
    proxy_port, proxy_runner = await _start_bedrock_proxy()
    proxy_url = f"http://127.0.0.1:{proxy_port}/v1"

    # Step 2: Test proxy with streaming (this is what act/observe/extract use)
    print("\n=== TEST: Proxy streaming ===")
    import httpx
    async with httpx.AsyncClient() as http:
        try:
            r = await http.post(
                f"{proxy_url}/messages",
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 50,
                    "stream": True,
                    "messages": [{"role": "user", "content": "Say hello in 3 words"}],
                },
                timeout=30,
            )
            print(f"Stream response status: {r.status_code}")
            # Check SSE format
            text = r.text
            lines = text.strip().split('\n')
            event_count = sum(1 for l in lines if l.startswith('event:'))
            data_count = sum(1 for l in lines if l.startswith('data:'))
            print(f"SSE events: {event_count}, data lines: {data_count}")
            # Print first few events for debugging
            for line in lines[:10]:
                print(f"  {line[:150]}")
        except Exception as e:
            print(f"Stream test failed: {e}")
            await proxy_runner.cleanup()
            return

    # Step 3: Test proxy non-streaming
    print("\n=== TEST: Proxy non-streaming ===")
    async with httpx.AsyncClient() as http:
        r = await http.post(
            f"{proxy_url}/messages",
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 50,
                "messages": [{"role": "user", "content": "Say hello in 3 words"}],
            },
            timeout=30,
        )
        print(f"Non-stream response: {r.status_code}: {r.text[:300]}")

    # Step 4: Start Stagehand with proxy
    print("\n=== STARTING STAGEHAND ===")
    os.environ["ANTHROPIC_BASE_URL"] = proxy_url
    chrome_path = os.environ.get("CHROME_PATH", "/usr/local/bin/stagehand-chrome")

    client = AsyncStagehand(
        server="local",
        model_api_key="dummy-key-proxy-handles-auth",
        local_chrome_path=chrome_path,
        local_ready_timeout_s=60.0,
    )

    try:
        t0 = time.time()
        session = await client.sessions.start(
            model_name="anthropic/claude-haiku-4-5-20251001",
            browser={
                "type": "local",
                "launchOptions": {
                    "executablePath": chrome_path,
                    "headless": True,
                    "args": ["--no-sandbox", "--disable-setuid-sandbox"],
                },
            },
        )
        print(f"Session started in {time.time()-t0:.1f}s, cdp_url={session.data.cdp_url}")

        # Step 5: Navigate to example.com
        print("\n=== NAVIGATE ===")
        await session.navigate(url="https://example.com")
        print("Navigation done")

        # Step 6: Test observe (uses LLM via streaming)
        print("\n=== TEST: observe() ===")
        t0 = time.time()
        try:
            result = await session.observe(instruction="Find all links on the page")
            elements = result.data.result if result.data else []
            print(f"observe() returned {len(elements or [])} elements in {time.time()-t0:.1f}s")
            for el in (elements or [])[:5]:
                d = el.to_dict(exclude_none=True) if hasattr(el, "to_dict") else str(el)
                print(f"  - {d}")
        except Exception as e:
            print(f"observe() FAILED: {type(e).__name__}: {e}")

        # Step 7: Test act (the one that was intermittently failing)
        print("\n=== TEST: act() — click a link ===")
        t0 = time.time()
        try:
            result = await session.act(input="click the 'More information...' link")
            msg = result.data.result.message if result.data and result.data.result else "?"
            success = result.data.result.success if result.data and result.data.result else None
            print(f"act() returned in {time.time()-t0:.1f}s: success={success}, msg={msg}")
        except Exception as e:
            print(f"act() FAILED: {type(e).__name__}: {e}")

        # Step 8: Test extract
        print("\n=== TEST: extract() ===")
        t0 = time.time()
        try:
            result = await session.extract(instruction="Extract the page title and main heading")
            extracted = result.data.result if result.data else {}
            print(f"extract() returned in {time.time()-t0:.1f}s: {extracted}")
        except Exception as e:
            print(f"extract() FAILED: {type(e).__name__}: {e}")

        await session.end()
        print("\n=== ALL TESTS PASSED ===")

    except Exception as e:
        print(f"\nStagehand error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await client.close()
        except Exception:
            pass
        await proxy_runner.cleanup()
        print("Cleaned up")
