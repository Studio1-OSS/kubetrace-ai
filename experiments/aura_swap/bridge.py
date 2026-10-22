"""KubeTrace's tools as an MCP server, so another agent runtime (Aura) can drive an experiment.

Every call goes through the same `dispatch` the KubeTrace loop uses: the same policy engine,
dry runs, workspace, sandboxed tests and image builds. The bridge emits the same `tool_call` and
`tool_result` events, so a run driven by Aura shows up in the KubeTrace timeline like any other.

What the bridge does not copy from the KubeTrace loop is the loop itself: no repeat notices,
no budget notices, no verification retries. Those belong to the agent runtime under test.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import anyio
import httpx
import mcp.types as types
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

from kubetrace_agent.redact import Redactor, truncate
from kubetrace_agent.tools import ToolContext, dispatch, tool_schemas


@dataclass
class BridgeSession:
    """The experiment the bridge is serving right now."""
    ctx: ToolContext
    redactor: Redactor
    emit: Callable[[str, dict], None]
    max_output_chars: int
    tools: set[str]
    calls: list[dict] = field(default_factory=list)
    model_calls: list[dict] = field(default_factory=list)  # one per request Aura sent to the model provider
    tool_time_s: float = 0.0
    tool_errors: int = 0
    rejected_actions: int = 0


class Bridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host, self.port = host, port
        self.session: BridgeSession | None = None
        self.lock = threading.Lock()
        self._server: uvicorn.Server | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp/"

    # MCP ------------------------------------------------------------------------------------
    def _mcp(self) -> Server:
        server = Server("kubetrace-tools")

        @server.list_tools()
        async def list_tools() -> list[types.Tool]:
            allowed = self.session.tools if self.session else set()
            out = []
            for s in tool_schemas():
                fn = s["function"]
                if fn["name"] in allowed:
                    out.append(types.Tool(name=fn["name"], description=fn["description"], inputSchema=fn["parameters"]))
            return out

        @server.call_tool(validate_input=False)
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
            text = await anyio.to_thread.run_sync(self._call, name, arguments or {})
            return [types.TextContent(type="text", text=text)]

        return server

    def _call(self, name: str, arguments: dict) -> str:
        s = self.session
        if s is None or name not in s.tools:
            return json.dumps({"error": f"tool {name} is not available"})
        call_id = f"aura-{len(s.calls) + 1}"
        s.emit("tool_call", {"id": call_id, "tool": name, "arguments": s.redactor.value(arguments)})
        started = time.monotonic()
        ok, result = dispatch(s.ctx, name, json.dumps(arguments))
        duration = time.monotonic() - started
        s.tool_time_s += duration
        if not ok:
            s.tool_errors += 1
        if isinstance(result, dict) and result.get("status") in ("denied", "rejected", "stale"):
            s.rejected_actions += 1
        text = truncate(json.dumps(s.redactor.value(result), default=str), s.max_output_chars)
        s.calls.append({"id": call_id, "tool": name, "ok": ok, "duration_s": round(duration, 3)})
        s.emit("tool_result", {"id": call_id, "tool": name, "ok": ok, "duration_ms": round(duration * 1000), "output": text})
        return text

    # Model proxy ---------------------------------------------------------------------------
    # Aura reaches the model through this pass-through, which records each call's token usage,
    # latency and status. Aura's own aura.usage event is skipped when a run ends on an error
    # (for example its turn limit), so it cannot be the only record.
    @property
    def model_base_url(self) -> str:
        return f"http://{self.host}:{self.port}/model/v1"

    async def _proxy(self, scope, receive, send) -> None:
        from starlette.requests import Request
        from starlette.responses import Response, StreamingResponse
        request = Request(scope, receive)
        body = await request.body()
        url = self.upstream.rstrip("/") + "/" + scope["path"].split("/v1/", 1)[-1]
        headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "content-type", "accept")}
        started = time.monotonic()
        record: dict = {"path": scope["path"], "status": None, "usage": None, "latency_s": None}
        client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15))
        upstream = await client.send(client.build_request(request.method, url, content=body, headers=headers), stream=True)
        record["status"] = upstream.status_code

        def finish_record() -> None:
            record["latency_s"] = round(time.monotonic() - started, 3)
            if self.session is not None and scope["path"].endswith("/chat/completions"):
                self.session.model_calls.append(record)

        if "text/event-stream" not in upstream.headers.get("content-type", ""):
            data = await upstream.aread()
            await upstream.aclose()
            await client.aclose()
            try:
                record["usage"] = json.loads(data).get("usage")
            except ValueError:
                record["error"] = data[:500].decode(errors="replace")
            finish_record()
            await Response(data, status_code=upstream.status_code,
                           media_type=upstream.headers.get("content-type"))(scope, receive, send)
            return

        async def relay():
            buf = b""
            try:
                async for chunk in upstream.aiter_bytes():  # decoded: the response is relayed uncompressed
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        if line.startswith(b"data:") and b'"usage"' in line:
                            try:
                                usage = json.loads(line[5:]).get("usage")
                                if usage:
                                    record["usage"] = usage
                            except ValueError:
                                pass
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()
                finish_record()

        await StreamingResponse(relay(), status_code=upstream.status_code,
                                media_type="text/event-stream")(scope, receive, send)

    # HTTP server ---------------------------------------------------------------------------
    def start(self, upstream: str = "https://api.tokenfactory.nebius.com/v1") -> None:
        self.upstream = upstream
        manager = StreamableHTTPSessionManager(app=self._mcp(), stateless=True, json_response=True)

        async def handle(scope, receive, send):
            await manager.handle_request(scope, receive, send)

        @contextlib.asynccontextmanager
        async def lifespan(_app):
            async with manager.run():
                yield

        app = Starlette(routes=[Mount("/mcp", app=handle), Mount("/model", app=self._proxy)], lifespan=lifespan)
        self._server = uvicorn.Server(uvicorn.Config(app, host=self.host, port=self.port, log_level="warning"))
        threading.Thread(target=self._server.run, name="kubetrace-mcp", daemon=True).start()
        for _ in range(100):
            if self._server.started:
                return
            time.sleep(0.1)
        raise RuntimeError("MCP bridge did not start")

    def serve(self, session: BridgeSession) -> None:
        with self.lock:
            self.session = session

    def release(self) -> BridgeSession | None:
        with self.lock:
            s, self.session = self.session, None
            return s
