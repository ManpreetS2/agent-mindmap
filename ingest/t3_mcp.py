"""Official MCP SDK transport and explicit OAuth login; credentials never enter web/dist."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import threading
import webbrowser
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def validate_url(url: str) -> str:
    p = urlparse(url)
    if p.username or p.password or p.query or p.fragment or p.path != "/mcp":
        raise ValueError("Use the credential-free T3 /mcp URL")
    if p.scheme != "https" and not (
        p.scheme == "http" and p.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("T3 requires HTTPS or loopback HTTP")
    if not p.hostname:
        raise ValueError("Missing T3 host")
    return url


def credential_path(url: str) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()
    return Path.home() / ".config" / "agent-mindmap" / (key + ".json")


class TokenStore:
    def __init__(self, url: str):
        self.path = credential_path(url)

    def read(self):
        if not self.path.exists():
            return {}
        if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
            raise ValueError("T3 credential file must be private (0600)")
        return json.loads(self.path.read_text())

    def save(self, key, value):
        data = self.read()
        data[key] = value.model_dump(mode="json")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            tmp.replace(self.path)
        finally:
            tmp.unlink(missing_ok=True)

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken

        data = self.read().get("tokens")
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens):
        self.save("tokens", tokens)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull

        data = self.read().get("client")
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info):
        self.save("client", client_info)


async def connect(url: str, *, login: bool = False, cache: dict | None = None):
    import httpx
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.auth import OAuthClientMetadata

    from .t3 import collect

    validate_url(url)
    store = TokenStore(url)
    server = None
    result = {}
    ready = threading.Event()
    redirect_uri = "http://127.0.0.1:18789/callback"
    if login:

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                parsed = urlparse(self.path)
                q = parse_qs(parsed.query)
                if (
                    parsed.path != "/callback"
                    or not q.get("code")
                    or not q.get("state")
                ):
                    self.send_error(400)
                    return
                result.update(code=q["code"][0], state=q["state"][0])
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    b"Return to the mindmap terminal. Authorization is being verified."
                )
                ready.set()

        server = HTTPServer(("127.0.0.1", 18789), Callback)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    async def redirect(auth_url):
        if not login:
            raise RuntimeError("Run python -m ingest.t3_mcp login first")
        print("Approve Agent Mindmap in T3 with Read only access in the browser.")
        webbrowser.open(auth_url)

    async def callback():
        if not login or not await asyncio.to_thread(ready.wait, 180):
            raise RuntimeError("T3 login required")
        return result["code"], result["state"]

    auth = OAuthClientProvider(
        server_url=url,
        client_metadata=OAuthClientMetadata(
            client_name="Agent Mindmap (read only)",
            redirect_uris=[redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        ),
        storage=store,
        redirect_handler=redirect,
        callback_handler=callback,
    )
    try:
        async with (
            httpx.AsyncClient(auth=auth, timeout=20, follow_redirects=False) as client,
            streamable_http_client(url, http_client=client) as (read, write, _),
            ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=20)
            ) as session,
        ):
            await session.initialize()
            return await collect(session, cache)
    finally:
        if server:
            server.shutdown()
            server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Authorize read-only T3 monitoring")
    parser.add_argument("action", choices=["login"])
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(connect(args.url, login=True))
    except Exception:  # noqa: BLE001 — redact upstream error payloads
        # SDK errors may include server text or headers. Do not print them.
        print(
            "T3 authorization/read check failed. Verify URL, running server and Read only approval."
        )
        return 1
    print("T3 read interface verified. Credentials saved privately on this host.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
