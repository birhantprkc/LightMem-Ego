from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from email.utils import formatdate
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

from websockets.sync.client import connect

from .io_utils import OnlinePreprocessError, ensure_dir, utc_now_iso, write_json_atomic


TTS_HOST = "tts-api.xfyun.cn"
TTS_URI = "/v2/tts"


class XfyunTTSError(OnlinePreprocessError):
    """Raised when Xfyun TTS cannot produce answer audio."""


@dataclass(frozen=True)
class XfyunTTSConfig:
    app_id: str
    api_key: str
    api_secret: str
    host: str = TTS_HOST
    uri: str = TTS_URI
    aue: str = "lame"
    auf: str = "audio/L16;rate=16000"
    vcn: str = "xiaoyan"
    speed: int = 50
    volume: int = 50
    pitch: int = 50
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0
    max_text_bytes: int = 7800

    @classmethod
    def from_env(cls) -> "XfyunTTSConfig":
        return cls(
            app_id=_first_env("EM2MEM_XFYUN_TTS_APP_ID", "EM2MEM_XFYUN_APP_ID"),
            api_key=_first_env("EM2MEM_XFYUN_TTS_API_KEY", "EM2MEM_XFYUN_API_KEY"),
            api_secret=_first_env("EM2MEM_XFYUN_TTS_API_SECRET", "EM2MEM_XFYUN_API_SECRET"),
            aue=_env_str("EM2MEM_XFYUN_TTS_AUE", "lame"),
            auf=_env_str("EM2MEM_XFYUN_TTS_AUF", "audio/L16;rate=16000"),
            vcn=_env_str("EM2MEM_XFYUN_TTS_VCN", "xiaoyan"),
            speed=_env_int("EM2MEM_XFYUN_TTS_SPEED", 50),
            volume=_env_int("EM2MEM_XFYUN_TTS_VOLUME", 50),
            pitch=_env_int("EM2MEM_XFYUN_TTS_PITCH", 50),
            connect_timeout_seconds=_env_float("EM2MEM_XFYUN_TTS_CONNECT_TIMEOUT_SECONDS", 10.0),
            read_timeout_seconds=_env_float("EM2MEM_XFYUN_TTS_READ_TIMEOUT_SECONDS", 30.0),
            max_text_bytes=_env_int("EM2MEM_XFYUN_TTS_MAX_TEXT_BYTES", 7800),
        )


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    raise XfyunTTSError(f"Missing required Xfyun TTS environment variable: {' or '.join(names)}")


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str) -> set[str]:
    raw = os.getenv(name, default)
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _truncate_utf8(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if max_bytes <= 0 or len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    return truncated, truncated != text


def _auth_url(config: XfyunTTSConfig) -> str:
    date = formatdate(timeval=None, localtime=False, usegmt=True)
    signature_origin = f"host: {config.host}\ndate: {date}\nGET {config.uri} HTTP/1.1"
    signature_sha = hmac.new(
        config.api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")
    authorization_origin = (
        f'api_key="{config.api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
    query = urlencode({"authorization": authorization, "date": date, "host": config.host})
    return f"wss://{config.host}{config.uri}?{query}"


def _business_payload(config: XfyunTTSConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "aue": config.aue,
        "auf": config.auf,
        "vcn": config.vcn,
        "speed": config.speed,
        "volume": config.volume,
        "pitch": config.pitch,
        "tte": "utf8",
    }
    if config.aue == "lame":
        payload["sfl"] = 1
    return payload


def _output_suffix(aue: str) -> str:
    normalized = (aue or "").strip().lower()
    if normalized == "lame":
        return ".mp3"
    if normalized == "raw":
        return ".pcm"
    if normalized.startswith("opus"):
        return ".opus"
    if normalized.startswith("speex"):
        return ".spx"
    return ".audio"


def _media_type(aue: str) -> str:
    normalized = (aue or "").strip().lower()
    if normalized == "lame":
        return "audio/mpeg"
    if normalized == "raw":
        return "audio/L16"
    if normalized.startswith("opus"):
        return "audio/ogg"
    return "application/octet-stream"


def synthesize_text_to_file(
    text: str,
    output_path: Path,
    *,
    config: XfyunTTSConfig | None = None,
) -> dict[str, Any]:
    config = config or XfyunTTSConfig.from_env()
    text = str(text or "").strip()
    if not text:
        raise XfyunTTSError("answer text is empty")

    request_text, truncated = _truncate_utf8(text, config.max_text_bytes)
    if not request_text:
        raise XfyunTTSError("answer text is empty after truncation")

    request_payload = {
        "common": {"app_id": config.app_id},
        "business": _business_payload(config),
        "data": {
            "status": 2,
            "text": base64.b64encode(request_text.encode("utf-8")).decode("utf-8"),
        },
    }

    start = time.perf_counter()
    sid = ""
    audio_chunks: list[bytes] = []
    final_status = None
    deadline = start + max(1.0, config.read_timeout_seconds)
    with connect(
        _auth_url(config),
        open_timeout=config.connect_timeout_seconds,
        close_timeout=5,
        max_size=None,
        proxy=None,
    ) as websocket:
        websocket.send(json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")))
        while True:
            remaining = max(0.1, deadline - time.perf_counter())
            if remaining <= 0.1 and time.perf_counter() >= deadline:
                raise XfyunTTSError(f"Xfyun TTS timed out after {config.read_timeout_seconds:.1f}s")
            message = websocket.recv(timeout=remaining)
            if isinstance(message, bytes):
                audio_chunks.append(message)
                continue
            response = json.loads(str(message))
            sid = str(response.get("sid") or sid)
            code = int(response.get("code") or 0)
            if code != 0:
                raise XfyunTTSError(
                    f"Xfyun TTS failed code={code} message={response.get('message') or ''} sid={sid}"
                )
            data = response.get("data") if isinstance(response.get("data"), dict) else {}
            audio_b64 = str(data.get("audio") or "")
            if audio_b64:
                audio_chunks.append(base64.b64decode(audio_b64))
            final_status = data.get("status")
            if int(final_status or 0) == 2:
                break

    audio_bytes = b"".join(audio_chunks)
    if not audio_bytes:
        raise XfyunTTSError(f"Xfyun TTS returned no audio sid={sid}")

    ensure_dir(output_path.parent)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_bytes(audio_bytes)
    temp_path.replace(output_path)

    elapsed_ms = int(round((time.perf_counter() - start) * 1000))
    metadata = {
        "status": "ok",
        "backend": "xfyun_tts",
        "sid": sid,
        "aue": config.aue,
        "auf": config.auf,
        "vcn": config.vcn,
        "media_type": _media_type(config.aue),
        "bytes": len(audio_bytes),
        "elapsed_ms": elapsed_ms,
        "text_bytes": len(request_text.encode("utf-8")),
        "text_truncated": truncated,
        "created_at": utc_now_iso(),
    }
    write_json_atomic(Path(str(output_path) + ".meta.json"), metadata)
    return metadata


def answer_tts_enabled(client_source: str = "", input_method: str = "") -> bool:
    if not _env_bool("EM2MEM_ANSWER_TTS_ENABLED", True):
        return False
    allowed_sources = _csv_env("EM2MEM_ANSWER_TTS_CLIENT_SOURCES", "glasses,rokid,rokid_glass")
    allowed_methods = _csv_env("EM2MEM_ANSWER_TTS_INPUT_METHODS", "voice,preset")
    source = str(client_source or "").strip().lower()
    method = str(input_method or "").strip().lower()
    return source in allowed_sources and method in allowed_methods


def _answer_text(result: dict[str, Any]) -> str:
    return str(result.get("answer") or result.get("answer_text") or "").strip()


def _answer_audio_url(session_id: str, rel_path: str) -> str:
    return f"/session/{quote(session_id, safe='')}/file?path={quote(rel_path, safe='/')}"


def attach_answer_audio_to_result(
    *,
    result: dict[str, Any],
    sessions_root: Path,
    session_id: str,
    client_source: str = "",
    input_method: str = "",
    task_id: str | None = None,
) -> dict[str, Any]:
    if result.get("answer_audio_url"):
        return result
    if not answer_tts_enabled(client_source=client_source, input_method=input_method):
        return result
    text = _answer_text(result)
    if not text:
        return result

    started = time.perf_counter()
    try:
        config = XfyunTTSConfig.from_env()
        audio_dir = sessions_root / session_id / "stream" / "answer_audio"
        safe_task_id = str(task_id or "").strip() or uuid4().hex
        audio_path = audio_dir / f"{safe_task_id}{_output_suffix(config.aue)}"
        metadata = synthesize_text_to_file(text, audio_path, config=config)
        rel_path = audio_path.relative_to(sessions_root / session_id).as_posix()
        result["answer_audio_path"] = rel_path
        result["answer_audio_url"] = _answer_audio_url(session_id, rel_path)
        result["answer_audio_backend"] = metadata.get("backend", "xfyun_tts")
        result["answer_audio_media_type"] = metadata.get("media_type")
        result["answer_tts"] = metadata
        latency = result.setdefault("latency", {})
        if isinstance(latency, dict):
            latency["answer_tts_ms"] = metadata.get("elapsed_ms")
    except Exception as exc:
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        result["answer_tts"] = {
            "status": "failed",
            "backend": "xfyun_tts",
            "error": str(exc),
            "elapsed_ms": elapsed_ms,
            "created_at": utc_now_iso(),
        }
    return result
