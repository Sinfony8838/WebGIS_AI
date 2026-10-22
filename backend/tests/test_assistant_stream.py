"""SSE protocol tests use synthetic HTTP frames, not real model evidence."""
import io
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from backend.app.config import AppConfig
from backend.app.services.minimax_client import MiniMaxClient
from backend.app.services.interaction_run import InteractionRun, interaction_scope

@pytest.mark.parametrize("anthropic", [False, True])
def test_stream_only_public_text_and_meter_once(tmp_path, anthropic):
    config=AppConfig(root_dir=tmp_path, minimax_api_key="fixture-key", minimax_base_url="https://example.invalid/anthropic" if anthropic else "https://example.invalid/v1")
    client=MiniMaxClient(config)
    if anthropic:
        frames=[{"type":"message_start","message":{"usage":{"input_tokens":12}}},
                {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"private"}},
                {"type":"content_block_delta","delta":{"type":"text_delta","text":"回答"}},
                {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":7}},
                {"type":"message_stop"}]
    else:
        frames=[{"choices":[{"delta":{"reasoning_content":"private"}}]},
                {"choices":[{"delta":{"content":"回答"},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":7}}]
    stream=io.BytesIO(b"".join(("data: "+json.dumps(f)+"\n\n").encode() for f in frames))
    run=InteractionRun("fixture", mode="chat")
    chunks=[]
    with patch("urllib.request.urlopen",return_value=stream), interaction_scope(run):
        assert client.stream_chat_completion([{"role":"user","content":"你好"}],chunks.append)=="回答"
    assert chunks==["回答"]
    assert run.calls==1
    assert run.input_tokens==12 and run.output_tokens==7

@pytest.mark.parametrize("finish", [None,"length"])
def test_incomplete_stream_cannot_claim_success(tmp_path, finish):
    config=AppConfig(root_dir=tmp_path,minimax_api_key="fixture-key",minimax_base_url="https://example.invalid/v1")
    frame={"choices":[{"delta":{"content":"部分回答"},"finish_reason":finish}]}
    run=InteractionRun("fixture",mode="chat")
    stream=io.BytesIO(("data: "+json.dumps(frame)+"\n\n").encode())
    with patch("urllib.request.urlopen",return_value=stream), interaction_scope(run), pytest.raises(RuntimeError):
        MiniMaxClient(config).stream_chat_completion([{"role":"user","content":"你好"}],lambda text:None)
    assert run.calls==1
    assert run.unknown_usage
