from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import requests
import pytest

from online_streaming import stream_asr_processor
from online_preprocess.asr_xfyun import (
    OST_HOST,
    TASK_CREATE_URI,
    TASK_QUERY_URI,
    UPLOAD_HOST,
    XfyunASRClient,
    XfyunASRConfig,
    _audio_encoding,
    _normalize_lattice,
    _sha256_digest,
    transcribe_audio_with_xfyun,
)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)
        self.content = self.text.encode("utf-8")

    def json(self) -> dict:
        return self.payload


def _config(**overrides) -> XfyunASRConfig:
    values = {
        "app_id": "appid",
        "api_key": "apikey",
        "api_secret": "secret",
        "poll_interval_seconds": 0.1,
        "timeout_seconds": 2.0,
        "request_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return XfyunASRConfig(**values)


def _sample_result() -> dict:
    return {
        "file_length": 16462,
        "lattice": [
            {
                "begin": "0",
                "end": "470",
                "spk": "段落-0",
                "json_1best": {
                    "st": {
                        "bg": "0",
                        "ed": "470",
                        "sc": "1.00",
                        "rt": [
                            {
                                "ws": [
                                    {"cw": [{"w": "听说", "wc": "1.0000", "wp": "n"}], "wb": 1, "we": 40},
                                    {"cw": [{"w": "。", "wc": "0.0000", "wp": "p"}], "wb": 40, "we": 40},
                                    {"cw": [{"w": "", "wc": "0.0000", "wp": "g"}], "wb": 40, "we": 40},
                                ]
                            }
                        ],
                    }
                },
            }
        ],
    }


def _fake_session(responses: list[dict]) -> tuple[requests.Session, list[requests.PreparedRequest]]:
    session = requests.Session()
    sent: list[requests.PreparedRequest] = []

    def fake_send(prepared: requests.PreparedRequest, timeout: float | None = None) -> FakeResponse:
        sent.append(prepared)
        assert timeout is not None
        return FakeResponse(responses.pop(0))

    session.send = fake_send  # type: ignore[method-assign]
    return session, sent


def test_sha256_digest_matches_xfyun_format() -> None:
    assert _sha256_digest(b"") == "SHA-256=47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU="


def test_audio_encoding_uses_raw_for_wav_and_lame_for_mp3() -> None:
    assert _audio_encoding(Path("audio.wav")) == "raw"
    assert _audio_encoding(Path("audio.pcm")) == "raw"
    assert _audio_encoding(Path("audio.mp3")) == "lame"


def test_signed_headers_include_expected_hmac_signature() -> None:
    client = XfyunASRClient(_config())
    date = "Wed, 05 Jan 2022 09:29:14 GMT"
    headers = client._signed_headers(UPLOAD_HOST, "/file/upload", b"abc", "application/json", date=date)
    digest = _sha256_digest(b"abc")
    origin = f"host: {UPLOAD_HOST}\ndate: {date}\nPOST /file/upload HTTP/1.1\ndigest: {digest}"
    expected_signature = base64.b64encode(hmac.new(b"secret", origin.encode("utf-8"), hashlib.sha256).digest()).decode(
        "utf-8"
    )

    assert headers["Digest"] == digest
    assert headers["Date"] == date
    assert headers["Host"] == UPLOAD_HOST
    assert f'signature="{expected_signature}"' in headers["Authorization"]


def test_normalize_lattice_to_transcript_segments() -> None:
    segments = _normalize_lattice(_sample_result())

    assert segments == [
        {
            "start": 0.0,
            "end": 0.47,
            "text": "听说。",
            "speaker": "段落-0",
            "confidence": 1.0,
            "words": [
                {"word": "听说", "start": 0.01, "end": 0.4, "score": 1.0},
                {"word": "。", "start": 0.4, "end": 0.4, "score": 0.0},
            ],
        }
    ]


def test_small_upload_create_query_and_write_outputs(tmp_path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"RIFFfake-wave")
    responses = [
        {"code": 0, "data": {"url": "https://xfyun.example/audio.wav"}, "message": "success"},
        {"code": 0, "data": {"task_id": "task-1"}, "message": "success"},
        {"code": 0, "data": {"task_status": "3", "result": _sample_result()}, "message": "success"},
    ]
    session, sent = _fake_session(responses)
    client = XfyunASRClient(_config(), session=session)

    segments = transcribe_audio_with_xfyun(
        audio_path=audio_path,
        output_srt=tmp_path / "transcript.srt",
        output_json=tmp_path / "transcript.json",
        client=client,
    )

    assert segments[0]["text"] == "听说。"
    assert (tmp_path / "transcript.srt").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8")) == segments
    metadata = json.loads((tmp_path / "transcript.json.meta.json").read_text(encoding="utf-8"))
    assert metadata["backend"] == "xfyun"
    assert metadata["xfyun_task_id"] == "task-1"
    assert sent[0].url == f"https://{UPLOAD_HOST}/file/upload"
    assert sent[1].url == f"https://{OST_HOST}{TASK_CREATE_URI}"
    assert sent[2].url == f"https://{OST_HOST}{TASK_QUERY_URI}"
    assert "Authorization" in sent[0].headers
    create_payload = json.loads(sent[1].body)
    assert create_payload["data"]["encoding"] == "raw"


def test_multipart_upload_flow_for_large_files(tmp_path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"12345678")
    responses = [
        {"code": 0, "data": {"upload_id": "upload-1"}, "message": "success"},
        {"code": 0, "message": "success"},
        {"code": 0, "message": "success"},
        {"code": 0, "data": {"url": "https://xfyun.example/audio.wav"}, "message": "success"},
        {"code": 0, "data": {"task_id": "task-1"}, "message": "success"},
        {"code": 0, "data": {"task_status": "3", "result": _sample_result()}, "message": "success"},
    ]
    session, sent = _fake_session(responses)
    client = XfyunASRClient(_config(small_upload_limit_bytes=1, upload_chunk_bytes=4), session=session)

    segments = client.transcribe(audio_path)

    assert segments[0]["text"] == "听说。"
    assert sent[0].url == f"https://{UPLOAD_HOST}/file/mpupload/init"
    assert sent[1].url == f"https://{UPLOAD_HOST}/file/mpupload/upload"
    assert sent[2].url == f"https://{UPLOAD_HOST}/file/mpupload/upload"
    assert sent[3].url == f"https://{UPLOAD_HOST}/file/mpupload/complete"


def test_stream_backend_raises_when_xfyun_fails(monkeypatch, tmp_path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"RIFFfake-wave")

    def fail_xfyun(**kwargs):
        raise RuntimeError("xfyun unavailable")

    monkeypatch.setattr(stream_asr_processor, "transcribe_audio_with_xfyun", fail_xfyun)

    with pytest.raises(RuntimeError, match="xfyun unavailable"):
        stream_asr_processor._transcribe_audio_with_backend(
            backend="xfyun",
            audio_path=audio_path,
            output_srt=tmp_path / "transcript.srt",
            output_json=tmp_path / "transcript.json",
            whisperx_model="medium",
            device="cpu",
            compute_type="int8",
            language=None,
            model_dir=None,
            align_model_dir=None,
            batch_size=1,
            force=True,
            runtime=None,
        )
