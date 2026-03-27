# -*- coding: utf-8 -*-
"""N.E.K.O channel.

Receives messages over local HTTP and returns the final assistant reply
in the same request.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import deque
from typing import Any, Optional

from aiohttp import web
from agentscope_runtime.engine.schemas.agent_schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    MessageType,
    RunStatus,
    TextContent,
    VideoContent,
)

from ....config.config import NekoConfig
from ..base import BaseChannel
from ..schema import ChannelType

logger = logging.getLogger(__name__)

_TOOL_MESSAGE_TYPES = {
    MessageType.FUNCTION_CALL,
    MessageType.PLUGIN_CALL,
    MessageType.MCP_TOOL_CALL,
    MessageType.FUNCTION_CALL_OUTPUT,
    MessageType.PLUGIN_CALL_OUTPUT,
    MessageType.MCP_TOOL_CALL_OUTPUT,
}


class NekoChannel(BaseChannel):
    """N.E.K.O channel served via HTTP."""

    channel: ChannelType = "neko"
    display_name = "Neko"

    @staticmethod
    def parse_reply_timeout(
        value: object,
        default: float | None = 300.0,
    ) -> float | None:
        """Parse timeout seconds; non-positive means no timeout."""
        if value in (None, ""):
            return None
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else None

    @staticmethod
    def _normalize_sender_id(value: object) -> str:
        if value in (None, ""):
            return "unknown"
        return str(value)

    def _normalize_session_id(
        self,
        value: object,
        sender_id: str,
        meta: dict[str, object],
    ) -> str:
        if value in (None, ""):
            return str(self.resolve_session_id(sender_id, meta))
        return str(value)

    def __init__(
        self,
        process,
        enabled: bool = True,
        bot_prefix: str = "",
        host: str = "127.0.0.1",
        port: int = 8089,
        reply_timeout: float | None = 300.0,
        on_reply_sent=None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        **kwargs,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=kwargs.get("dm_policy", "open"),
            group_policy=kwargs.get("group_policy", "open"),
            allow_from=kwargs.get("allow_from"),
            deny_message=kwargs.get("deny_message", ""),
            require_mention=kwargs.get("require_mention", False),
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        self.host = host
        self.port = port
        self.reply_timeout = reply_timeout
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._pending_replies: dict[str, asyncio.Future[str]] = {}
        self._pending_sender_replies: dict[
            str,
            deque[asyncio.Future[str]],
        ] = {}
        self._pending_reply_texts: dict[
            str,
            list[tuple[str, str | None]],
        ] = {}

    @classmethod
    def from_config(
        cls,
        process,
        config: NekoConfig,
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
        **_,
    ) -> "NekoChannel":
        return cls(
            process=process,
            enabled=getattr(config, "enabled", True),
            bot_prefix=getattr(config, "bot_prefix", ""),
            host=getattr(config, "host", "127.0.0.1"),
            port=getattr(config, "port", 8089),
            reply_timeout=cls.parse_reply_timeout(
                getattr(config, "reply_timeout", 300.0),
            ),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=getattr(config, "dm_policy", "open"),
            group_policy=getattr(config, "group_policy", "open"),
            allow_from=getattr(config, "allow_from", []),
            deny_message=getattr(config, "deny_message", ""),
            require_mention=getattr(config, "require_mention", False),
        )

    @classmethod
    def from_env(cls, process, on_reply_sent=None, **kwargs) -> "NekoChannel":
        return cls(
            process=process,
            enabled=os.getenv("NEKO_CHANNEL_ENABLED", "true").lower()
            == "true",
            bot_prefix=os.getenv("NEKO_CHANNEL_BOT_PREFIX", ""),
            host=os.getenv("NEKO_CHANNEL_HOST", "127.0.0.1"),
            port=int(os.getenv("NEKO_CHANNEL_PORT", "8089")),
            reply_timeout=cls.parse_reply_timeout(
                os.getenv("NEKO_CHANNEL_REPLY_TIMEOUT", "300"),
            ),
            on_reply_sent=on_reply_sent,
            show_tool_details=kwargs.get("show_tool_details", True),
            filter_tool_messages=kwargs.get("filter_tool_messages", False),
            filter_thinking=kwargs.get("filter_thinking", False),
        )

    def _record_pending_reply(
        self,
        request_id: str | None,
        text: str,
        message_type: str | None,
    ) -> None:
        if not request_id:
            return
        normalized = text.strip()
        if not normalized:
            return
        entries = self._pending_reply_texts.setdefault(request_id, [])
        if entries and entries[-1] == (normalized, message_type):
            return
        entries.append((normalized, message_type))

    def _compose_pending_reply(self, request_id: str | None) -> str:
        if not request_id:
            return ""
        entries = self._pending_reply_texts.get(request_id) or []
        if not entries:
            return ""
        for text, message_type in reversed(entries):
            if message_type not in _TOOL_MESSAGE_TYPES:
                return text
        return entries[-1][0]

    def build_agent_request_from_native(self, native_payload):
        """Convert N.E.K.O payload to AgentRequest."""
        payload = native_payload if isinstance(native_payload, dict) else {}

        channel_id = payload.get("channel_id") or self.channel
        meta_value = payload.get("meta")
        meta = meta_value if isinstance(meta_value, dict) else {}
        sender_id = self._normalize_sender_id(payload.get("sender_id"))
        session_id = self._normalize_session_id(
            payload.get("session_id"),
            sender_id,
            meta,
        )

        content_parts = []

        text = payload.get("text", "")
        if text:
            content_parts.append(TextContent(type=ContentType.TEXT, text=text))

        attachments = payload.get("attachments")
        if not isinstance(attachments, list):
            attachments = []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            raw_type = att.get("type")
            raw_url = att.get("url")
            att_type = (
                str(raw_type).lower()
                if isinstance(raw_type, str) and raw_type
                else "file"
            )
            url = str(raw_url) if isinstance(raw_url, str) and raw_url else ""
            if not url:
                continue

            if att_type == "image":
                content_parts.append(
                    ImageContent(type=ContentType.IMAGE, image_url=url),
                )
            elif att_type == "video":
                content_parts.append(
                    VideoContent(type=ContentType.VIDEO, video_url=url),
                )
            elif att_type == "audio":
                content_parts.append(
                    AudioContent(type=ContentType.AUDIO, data=url),
                )
            else:
                content_parts.append(
                    FileContent(type=ContentType.FILE, file_url=url),
                )

        if not content_parts:
            content_parts = [TextContent(type=ContentType.TEXT, text="")]

        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    async def start(self):
        """Start the HTTP server."""
        if not self.enabled:
            return

        self._app = web.Application()
        self._app.router.add_post("/neko/send", self._handle_send)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        logger.info(
            "neko channel started on http://%s:%s",
            self.host,
            self.port,
        )

    async def stop(self):
        """Stop the HTTP server."""
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._app = None
        logger.info("neko channel stopped")

    async def send(self, to_handle, text, meta=None):
        """Buffer replies and return them via HTTP when the run ends."""
        meta = meta or {}
        request_id = meta.get("request_id")
        if not request_id and to_handle:
            queue = self._pending_sender_replies.get(to_handle)
            while queue and queue[0].done():
                queue.popleft()
        self._record_pending_reply(
            request_id,
            text,
            meta.get("_message_type"),
        )

    async def on_event_message_completed(
        self,
        request,
        to_handle,
        event,
        send_meta,
    ) -> None:
        event_meta = dict(send_meta or {})
        event_meta["_message_type"] = getattr(event, "type", None)
        await self.send_message_content(to_handle, event, event_meta)

    async def _run_process_loop(
        self,
        request,
        to_handle,
        send_meta,
    ) -> None:
        request_id = (send_meta or {}).get("request_id")
        last_response = None
        try:
            async for event in self._process(request):
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                if obj == "message" and status == RunStatus.Completed:
                    await self.on_event_message_completed(
                        request,
                        to_handle,
                        event,
                        send_meta,
                    )
                elif obj == "response":
                    last_response = event
                    await self.on_event_response(request, event)

            err_msg = self._get_response_error_message(last_response)
            if err_msg:
                await self._on_consume_error(
                    request,
                    to_handle,
                    f"Error: {err_msg}",
                )

            final_reply = self._compose_pending_reply(request_id)
            if not final_reply:
                final_reply = "[NekoClaw 已完成，但没有返回可显示的文本结果]"
            future = (
                self._pending_replies.get(request_id) if request_id else None
            )
            if future is not None and not future.done():
                future.set_result(final_reply)

            if self._on_reply_sent:
                args = self.get_on_reply_sent_args(request, to_handle)
                self._on_reply_sent(self.channel, *args)
        except Exception:
            logger.exception("neko channel consume_one failed")
            await self._on_consume_error(
                request,
                to_handle,
                "An error occurred while processing your request.",
            )
            final_reply = self._compose_pending_reply(request_id)
            if not final_reply:
                final_reply = (
                    "An error occurred while processing your request."
                )
            future = (
                self._pending_replies.get(request_id) if request_id else None
            )
            if future is not None and not future.done():
                future.set_result(final_reply)

    async def _consume_one_request(self, payload: Any) -> None:
        request = self._payload_to_request(payload)
        if isinstance(payload, dict):
            request.channel_meta = dict(payload.get("meta") or {})
        to_handle = self.get_to_handle_from_request(request)
        await self._before_consume_process(request)
        send_meta = dict(getattr(request, "channel_meta", None) or {})
        await self.refresh_webhook_or_token()
        await self._run_process_loop(request, to_handle, send_meta)

    async def _handle_health(self, _request: web.Request) -> web.Response:
        """Health endpoint."""
        return web.json_response({"status": "healthy", "channel": "neko"})

    async def _handle_send(self, request: web.Request) -> web.Response:
        """Handle incoming messages from N.E.K.O."""
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response(
                {"error": "Invalid payload: expected object"},
                status=400,
            )
        if (
            "meta" in payload
            and payload.get("meta") is not None
            and not isinstance(payload.get("meta"), dict)
        ):
            return web.json_response(
                {"error": "Invalid meta: expected object"},
                status=400,
            )
        if (
            "attachments" in payload
            and payload.get("attachments") is not None
            and not isinstance(payload.get("attachments"), list)
        ):
            return web.json_response(
                {"error": "Invalid attachments: expected array"},
                status=400,
            )

        meta = payload.get("meta") or {}
        sender_id = self._normalize_sender_id(payload.get("sender_id"))
        session_id = self._normalize_session_id(
            payload.get("session_id"),
            sender_id,
            meta,
        )
        payload["sender_id"] = sender_id
        payload["session_id"] = session_id

        reply_timeout: float | None = self.reply_timeout
        reply_timeout = self.parse_reply_timeout(
            meta.get("reply_timeout", reply_timeout),
            default=reply_timeout,
        )

        request_id = str(uuid.uuid4())[:8]
        meta["request_id"] = request_id
        payload["meta"] = meta

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending_replies[request_id] = future
        self._pending_sender_replies.setdefault(sender_id, deque()).append(
            future,
        )

        try:
            if self._enqueue is None:
                raise RuntimeError("Neko channel enqueue callback is not set")
            self._enqueue(payload)

            try:
                reply = await asyncio.wait_for(future, timeout=reply_timeout)
            except asyncio.TimeoutError:
                reply = "[超时：NekoClaw 未在规定时间内响应]"

            return web.json_response(
                {
                    "reply": (
                        self.bot_prefix + reply if self.bot_prefix else reply
                    ),
                    "sender_id": sender_id,
                    "session_id": session_id,
                    "request_id": request_id,
                },
            )

        finally:
            self._pending_replies.pop(request_id, None)
            self._pending_reply_texts.pop(request_id, None)
            queue = self._pending_sender_replies.get(sender_id)
            if queue:
                filtered_queue = deque(
                    pending_future
                    for pending_future in queue
                    if pending_future is not future
                )
                if filtered_queue:
                    self._pending_sender_replies[sender_id] = filtered_queue
                else:
                    self._pending_sender_replies.pop(sender_id, None)
