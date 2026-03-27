# -*- coding: utf-8 -*-
"""Unit tests for Neko channel."""
from __future__ import annotations

from agentscope_runtime.engine.schemas.agent_schemas import ContentType

from copaw.app.channels.neko.channel import NekoChannel
from copaw.config.config import NekoConfig


async def _noop_process(_request):
    for _ in ():
        yield _


def test_neko_from_config():
    channel = NekoChannel.from_config(
        process=_noop_process,
        config=NekoConfig(
            enabled=True,
            bot_prefix="[N]",
            host="0.0.0.0",
            port=8090,
            reply_timeout=120.0,
        ),
    )

    assert channel.enabled is True
    assert channel.bot_prefix == "[N]"
    assert channel.host == "0.0.0.0"
    assert channel.port == 8090
    assert channel.reply_timeout == 120.0


def test_neko_build_agent_request_from_native():
    channel = NekoChannel(
        process=_noop_process,
        enabled=True,
    )

    request = channel.build_agent_request_from_native(
        {
            "sender_id": "user-1",
            "session_id": "sess-1",
            "text": "hello",
            "attachments": [
                {"type": "image", "url": "https://example.com/a.png"},
                {"type": "file", "url": "https://example.com/a.pdf"},
            ],
            "meta": {"source": "test"},
        },
    )

    assert request.channel == "neko"
    assert request.user_id == "user-1"
    assert request.session_id == "sess-1"
    assert request.channel_meta == {"source": "test"}
    assert len(request.input) == 1
    assert len(request.input[0].content) == 3
    assert request.input[0].content[0].type == ContentType.TEXT
    assert request.input[0].content[0].text == "hello"
    assert request.input[0].content[1].type == ContentType.IMAGE
    assert request.input[0].content[2].type == ContentType.FILE
