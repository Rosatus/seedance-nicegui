from __future__ import annotations

import base64
import copy
import html
import json
import mimetypes
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


API_BASE_URL_ENV_VAR = "SEEDANCE_API_BASE_URL"
API_KEY_ENV_VAR = "SEEDANCE_API_KEY"
DEFAULT_API_BASE_URL = os.getenv(API_BASE_URL_ENV_VAR, "").strip()
DEFAULT_MODEL = "doubao-seedance-2-0-260128"
GENERATION_MODE_MULTIMODAL = "multimodal"
GENERATION_MODE_FIRST_FRAME = "first_frame"
GENERATION_MODE_FIRST_LAST_FRAME = "first_last_frame"
GENERATION_MODE_LABELS = {
    "多模态模式": GENERATION_MODE_MULTIMODAL,
    "首帧模式": GENERATION_MODE_FIRST_FRAME,
    "首尾帧模式": GENERATION_MODE_FIRST_LAST_FRAME,
}
DEFAULT_PROMPT = """主题：描述要生成的视频主题和核心目标。
素材：说明首帧、尾帧或参考图片/音频的使用方式。
主体：写清主要人物、物体或场景元素。
动作：描述从开始到结束的关键动作变化。
场景：说明时间、地点、环境和氛围。
风格：写明写实、电影感、广告片、动画等视觉风格。
镜头：描述运镜、景别、节奏和转场。
限制：列出不要出现的内容、画面问题或文字要求。"""

SUPPORTED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/gif",
}
SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/x-wav",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
ACTIVE_TASK_STATUSES = {"queued", "running", "unknown"}
TERMINAL_TASK_STATUSES = {"succeeded", "failed", "expired", "cancelled"}


class UnsupportedAttachmentError(ValueError):
    pass


@dataclass(slots=True)
class Attachment:
    id: str
    name: str
    mime_type: str
    kind: str
    role: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass(slots=True)
class TaskRecord:
    id: str
    source: str
    status: str = "unknown"
    download_url: str = ""
    last_frame_url: str = ""
    error: Any = None
    payload: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


@dataclass
class PageState:
    prompt: str = DEFAULT_PROMPT
    attachments: list[Attachment] = field(default_factory=list)
    last_task_id: str = ""
    last_request_json: str = ""
    last_response_json: str = ""
    last_error: str = ""
    busy: bool = False
    querying: bool = False
    tasks: dict[str, TaskRecord] = field(default_factory=dict)


def infer_attachment_kind(filename: str, content_type: str | None) -> str:
    normalized_type = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename).suffix.lower()

    if normalized_type in SUPPORTED_IMAGE_MIME_TYPES or (
        normalized_type.startswith("image/") and suffix in IMAGE_EXTENSIONS
    ):
        return "image"
    if normalized_type in SUPPORTED_AUDIO_MIME_TYPES or (
        normalized_type.startswith("audio/") and suffix in AUDIO_EXTENSIONS
    ):
        return "audio"
    if normalized_type in {"", "application/octet-stream"}:
        if suffix in IMAGE_EXTENSIONS:
            return "image"
        if suffix in AUDIO_EXTENSIONS:
            return "audio"

    raise UnsupportedAttachmentError(f"Unsupported attachment type: {filename} ({content_type or 'unknown'})")


def normalize_mime_type(filename: str, content_type: str | None, kind: str) -> str:
    guessed_type = (content_type or mimetypes.guess_type(filename)[0] or "").split(";")[0].strip().lower()
    if kind == "image":
        if guessed_type == "image/jpg":
            return "image/jpeg"
        if guessed_type in SUPPORTED_IMAGE_MIME_TYPES:
            return guessed_type
        suffix_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".gif": "image/gif",
        }
        return suffix_map.get(Path(filename).suffix.lower(), "image/png")

    if kind == "audio":
        if guessed_type == "audio/x-wav":
            return "audio/wav"
        if guessed_type in SUPPORTED_AUDIO_MIME_TYPES:
            return guessed_type
        suffix_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
        }
        return suffix_map.get(Path(filename).suffix.lower(), "audio/mpeg")

    raise UnsupportedAttachmentError(f"Unsupported attachment kind: {kind}")


def role_for_kind(kind: str) -> str:
    if kind == "image":
        return "reference_image"
    if kind == "audio":
        return "reference_audio"
    raise UnsupportedAttachmentError(f"Unsupported attachment kind: {kind}")


def make_attachment(filename: str, content_type: str | None, data: bytes) -> Attachment:
    kind = infer_attachment_kind(filename, content_type)
    mime_type = normalize_mime_type(filename, content_type, kind)
    return Attachment(
        id=uuid.uuid4().hex,
        name=Path(filename).name,
        mime_type=mime_type,
        kind=kind,
        role=role_for_kind(kind),
        data=data,
    )


def data_url_for_attachment(attachment: Attachment) -> str:
    encoded = base64.b64encode(attachment.data).decode("ascii")
    return f"data:{attachment.mime_type};base64,{encoded}"


def prompt_reference_label(attachments: list[Attachment], attachment_id: str) -> str:
    image_index = 0
    audio_index = 0
    for attachment in attachments:
        if attachment.kind == "image":
            image_index += 1
            label = f"图片 {image_index}"
        elif attachment.kind == "audio":
            audio_index += 1
            label = f"音频 {audio_index}"
        else:
            continue
        if attachment.id == attachment_id:
            return label
    raise KeyError(f"Attachment not found: {attachment_id}")


def display_reference_label(attachments: list[Attachment], attachment: Attachment, generation_mode: str) -> str:
    mode = generation_mode or GENERATION_MODE_MULTIMODAL
    if attachment.kind != "image" or mode == GENERATION_MODE_MULTIMODAL:
        return prompt_reference_label(attachments, attachment.id)

    image_attachments = [item for item in attachments if item.kind == "image"]
    image_index = next((index for index, item in enumerate(image_attachments) if item.id == attachment.id), -1)

    if mode == GENERATION_MODE_FIRST_FRAME and image_index == 0:
        return "首帧"
    if mode == GENERATION_MODE_FIRST_LAST_FRAME:
        if image_index == 0:
            return "首帧"
        if image_index == 1:
            return "尾帧"
    return prompt_reference_label(attachments, attachment.id)


def attachment_block(attachment: Attachment, *, role: str | None = None) -> dict[str, Any]:
    if attachment.kind == "image":
        return {
            "type": "image_url",
            "role": role or attachment.role,
            "image_url": {"url": data_url_for_attachment(attachment)},
        }
    if attachment.kind == "audio":
        return {
            "type": "audio_url",
            "role": role or attachment.role,
            "audio_url": {"url": data_url_for_attachment(attachment)},
        }
    raise UnsupportedAttachmentError(f"Unsupported attachment kind: {attachment.kind}")


def content_blocks_for_generation_mode(attachments: list[Attachment], generation_mode: str) -> list[dict[str, Any]]:
    mode = generation_mode or GENERATION_MODE_MULTIMODAL
    if mode == GENERATION_MODE_MULTIMODAL:
        return [attachment_block(attachment) for attachment in attachments]

    image_attachments = [attachment for attachment in attachments if attachment.kind == "image"]
    non_image_attachments = [attachment for attachment in attachments if attachment.kind != "image"]

    if mode == GENERATION_MODE_FIRST_FRAME:
        if len(image_attachments) != 1:
            raise ValueError("首帧模式需要恰好 1 张图片。")
        if non_image_attachments:
            raise ValueError("首帧模式不支持音频或其他非图片附件。")
        return [attachment_block(image_attachments[0], role="first_frame")]

    if mode == GENERATION_MODE_FIRST_LAST_FRAME:
        if len(image_attachments) != 2:
            raise ValueError("首尾帧模式需要恰好 2 张图片。")
        if non_image_attachments:
            raise ValueError("首尾帧模式不支持音频或其他非图片附件。")
        return [
            attachment_block(image_attachments[0], role="first_frame"),
            attachment_block(image_attachments[1], role="last_frame"),
        ]

    raise ValueError(f"未知生成模式：{generation_mode}")


def build_request_body(
    *,
    prompt: str,
    attachments: list[Attachment],
    model: str,
    generate_audio: bool,
    ratio: str,
    duration: int,
    watermark: bool,
    generation_mode: str = GENERATION_MODE_MULTIMODAL,
    resolution: str | None = None,
    advanced_enabled: bool = False,
    advanced_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend(content_blocks_for_generation_mode(attachments, generation_mode))
    body: dict[str, Any] = {
        "model": model,
        "content": content,
        "generate_audio": generate_audio,
        "ratio": ratio,
        "duration": int(duration),
        "watermark": watermark,
    }
    if resolution:
        body["resolution"] = resolution
    if advanced_enabled and advanced_options:
        for key, value in advanced_options.items():
            if value is None or value == "":
                continue
            body[key] = value
        if "frames" in body:
            body.pop("duration", None)
    return body


def redact_request_body(body: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(body)
    for block in redacted.get("content", []):
        for url_field in ("image_url", "audio_url"):
            media = block.get(url_field)
            if isinstance(media, dict) and isinstance(media.get("url"), str):
                url = media["url"]
                prefix = url.split(",", 1)[0] if "," in url else "data:media;base64"
                media["url"] = f"{prefix},<base64:{len(url)} chars>"
    return redacted


def extract_task_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in ("id", "task_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("data", "result", "task"):
        nested = payload.get(key)
        task_id = extract_task_id(nested)
        if task_id:
            return task_id

    return None


def find_value_by_key(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        value = payload.get(key)
        if value is not None:
            return value
        for nested in payload.values():
            nested_value = find_value_by_key(nested, key)
            if nested_value is not None:
                return nested_value
    elif isinstance(payload, list):
        for item in payload:
            nested_value = find_value_by_key(item, key)
            if nested_value is not None:
                return nested_value
    return None


def extract_status(payload: Any) -> str:
    value = find_value_by_key(payload, "status")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return "unknown"


def extract_download_url(payload: Any) -> str:
    for key in ("video_url", "file_url", "url"):
        value = find_value_by_key(payload, key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return ""


def extract_last_frame_url(payload: Any) -> str:
    value = find_value_by_key(payload, "last_frame_url")
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return ""


def extract_task_error(payload: Any) -> Any:
    return find_value_by_key(payload, "error")


def upsert_task_record(
    tasks: dict[str, TaskRecord],
    *,
    task_id: str,
    payload: dict[str, Any] | None,
    source: str,
) -> TaskRecord:
    normalized_id = task_id.strip()
    if not normalized_id:
        raise ValueError("task_id cannot be empty")

    existing = tasks.get(normalized_id)
    if existing is None:
        existing = TaskRecord(id=normalized_id, source=source)
        tasks[normalized_id] = existing
    elif source == "manual" and existing.source != "submitted":
        existing.source = source

    if payload is not None:
        existing.payload = payload
        existing.status = extract_status(payload)
        existing.download_url = extract_download_url(payload)
        existing.last_frame_url = extract_last_frame_url(payload)
        existing.error = extract_task_error(payload)
    existing.updated_at = time.time()
    return existing


def pollable_task_ids(tasks: dict[str, TaskRecord]) -> list[str]:
    return [
        task.id
        for task in tasks.values()
        if task.status.lower() in ACTIVE_TASK_STATUSES and task.status.lower() not in TERMINAL_TASK_STATUSES
    ]


def task_status_icon(status: str) -> str:
    normalized_status = (status or "unknown").lower()
    return {
        "queued": "hourglass_empty",
        "running": "spinner",
        "succeeded": "check_circle",
        "failed": "error",
        "expired": "block",
        "cancelled": "block",
    }.get(normalized_status, "help")


def normalize_submit_count(gacha_enabled: bool, raw_count: Any) -> int:
    if not gacha_enabled:
        return 1
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        return 1
    return max(1, min(count, 20))


def format_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def request_body_path() -> Path:
    return Path(tempfile.gettempdir()) / "video_task_image_audio_base64.json"


async def submit_generation_task(
    *,
    api_base_url: str,
    api_key: str,
    body: dict[str, Any],
    verify_tls: bool,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_seconds, verify=verify_tls) as client:
        response = await client.post(
            api_base_url.rstrip("/"),
            headers={
                "Authorization": api_key.strip(),
                "content-type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        return response.json()


async def query_generation_task(
    *,
    api_base_url: str,
    api_key: str,
    task_id: str,
    verify_tls: bool,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    url = f"{api_base_url.rstrip('/')}/{task_id.strip()}"
    async with httpx.AsyncClient(timeout=timeout_seconds, verify=verify_tls) as client:
        response = await client.get(url, headers={"Authorization": api_key.strip()})
        response.raise_for_status()
        return response.json()


def create_interface() -> None:
    from nicegui import events, ui

    state = PageState()

    ui.add_head_html(
        """
        <style>
        :root {
            --ink: #17211d;
            --muted: #647067;
            --line: #d8e0da;
            --panel: #ffffff;
            --soft: #f4f7f4;
            --accent: #28745a;
            --accent-dark: #1e5b46;
            --danger: #b42318;
        }
        body {
            background:
                linear-gradient(135deg, rgba(40,116,90,0.08), transparent 36%),
                linear-gradient(315deg, rgba(23,33,29,0.06), transparent 30%),
                #f8faf8;
            color: var(--ink);
            font-family: "Geist", "Satoshi", "Segoe UI", Arial, sans-serif;
        }
        .seedance-shell {
            width: min(1920px, calc(100vw - 40px));
            margin: 0 auto;
            padding: 28px 0 42px;
        }
        .seedance-workspace {
            display: grid;
            grid-template-columns: minmax(0, 1.32fr) minmax(0, .86fr) minmax(0, 1.12fr);
            gap: 22px;
            align-items: start;
            width: 100%;
        }
        .seedance-workspace > * {
            width: 100% !important;
            min-width: 0;
            align-self: stretch;
        }
        .seedance-fill-column {
            width: 100% !important;
            align-items: stretch !important;
        }
        .seedance-panel {
            background: rgba(255,255,255,0.92);
            border: 1px solid var(--line);
            border-radius: 18px;
            box-shadow: 0 24px 60px -42px rgba(23,33,29,0.42);
            width: 100%;
            max-width: none;
            box-sizing: border-box;
        }
        .seedance-topline {
            letter-spacing: .08em;
            text-transform: uppercase;
            color: var(--accent-dark);
            font-size: 12px;
            font-weight: 700;
        }
        .seedance-title {
            color: var(--ink);
            font-size: clamp(30px, 4vw, 52px);
            line-height: 1.02;
            font-weight: 760;
            letter-spacing: 0;
        }
        .seedance-subtle {
            color: var(--muted);
        }
        .seedance-section-title {
            font-size: 15px;
            color: var(--ink);
            font-weight: 720;
        }
        .seedance-native-textarea {
            width: 100%;
            box-sizing: border-box;
            min-height: 430px;
            resize: vertical;
            border: 1px solid var(--line);
            border-radius: 16px;
            padding: 18px;
            outline: none;
            background: #fbfdfb;
            color: var(--ink);
            line-height: 1.72;
            font-size: 15px;
            transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
        }
        .seedance-native-textarea:focus,
        .seedance-native-textarea.seedance-drop-active {
            border-color: var(--accent);
            box-shadow: 0 0 0 4px rgba(40,116,90,0.12);
        }
        .seedance-native-textarea.seedance-drop-active {
            transform: translateY(-1px);
        }
        .seedance-attachment-shell {
            border: 1px solid var(--line);
            background: #ffffff;
            border-radius: 14px;
            padding: 12px;
            transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
            cursor: grab;
            width: 100%;
            box-sizing: border-box;
        }
        .seedance-attachment-shell:hover {
            transform: translateY(-1px);
            border-color: rgba(40,116,90,0.42);
            box-shadow: 0 16px 30px -26px rgba(23,33,29,0.58);
        }
        .seedance-attachment-shell:active {
            cursor: grabbing;
        }
        .seedance-attachment-preview {
            width: 92px;
            height: 68px;
            border: 1px solid var(--line);
            border-radius: 12px;
            overflow: hidden;
            background: #eef3ef;
            flex: 0 0 auto;
        }
        .seedance-attachment-preview img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .seedance-attachment-preview-placeholder {
            width: 92px;
            height: 68px;
            border: 1px solid var(--line);
            border-radius: 12px;
            background: #eef3ef;
            color: var(--muted);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 700;
            flex: 0 0 auto;
        }
        .seedance-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 9px;
            border-radius: 999px;
            background: #eef5f0;
            color: var(--accent-dark);
            font-size: 12px;
            font-weight: 700;
        }
        .seedance-task-row {
            border: 1px solid var(--line);
            background: #fbfdfb;
            border-radius: 14px;
            padding: 12px;
            display: grid;
            grid-template-columns: 34px minmax(0, 1fr) auto;
            gap: 12px;
            align-items: start;
            width: 100%;
            box-sizing: border-box;
        }
        .seedance-task-icon {
            width: 34px;
            height: 34px;
            border-radius: 12px;
            background: #eef5f0;
            color: var(--accent-dark);
            display: flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 auto;
        }
        .seedance-task-icon-queued,
        .seedance-task-icon-running,
        .seedance-task-icon-unknown {
            color: #735f18;
            background: #fbf1ce;
        }
        .seedance-task-icon-succeeded {
            color: var(--accent-dark);
            background: #e7f4ec;
        }
        .seedance-task-icon-failed,
        .seedance-task-icon-expired,
        .seedance-task-icon-cancelled {
            color: var(--danger);
            background: #fae8e6;
        }
        .seedance-task-actions {
            display: flex;
            gap: 4px;
            align-items: center;
            justify-content: flex-end;
            flex-wrap: nowrap;
            min-width: max-content;
        }
        .seedance-task-main {
            min-width: 0;
        }
        .seedance-task-id {
            font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
            font-size: 12px;
            color: var(--ink);
            overflow-wrap: anywhere;
        }
        .seedance-status {
            display: inline-flex;
            align-items: center;
            padding: 4px 8px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 760;
            text-transform: uppercase;
            letter-spacing: .04em;
        }
        .seedance-status-queued,
        .seedance-status-running,
        .seedance-status-unknown {
            color: #735f18;
            background: #fbf1ce;
        }
        .seedance-status-succeeded {
            color: var(--accent-dark);
            background: #e7f4ec;
        }
        .seedance-status-failed,
        .seedance-status-expired,
        .seedance-status-cancelled {
            color: var(--danger);
            background: #fae8e6;
        }
        .seedance-output .q-field__control {
            min-height: 300px;
            align-items: flex-start;
        }
        .seedance-output {
            width: 100%;
        }
        .seedance-output textarea {
            font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
            font-size: 12px;
            line-height: 1.55;
        }
        .seedance-error {
            border: 1px solid rgba(180,35,24,0.28);
            color: var(--danger);
            background: rgba(180,35,24,0.06);
            border-radius: 12px;
            padding: 10px 12px;
            font-size: 13px;
        }
        .seedance-ok {
            border: 1px solid rgba(40,116,90,0.22);
            color: var(--accent-dark);
            background: rgba(40,116,90,0.06);
            border-radius: 12px;
            padding: 10px 12px;
            font-size: 13px;
        }
        .seedance-advanced {
            border-top: 1px solid var(--line);
            margin-top: 12px;
            padding-top: 12px;
        }
        .q-btn {
            border-radius: 10px;
            letter-spacing: 0;
        }
        @media (max-width: 1460px) {
            .seedance-workspace {
                grid-template-columns: minmax(0, 1.18fr) minmax(0, .82fr);
            }
            .seedance-task-column {
                grid-column: 1 / -1;
            }
        }
        @media (max-width: 900px) {
            .seedance-shell {
                width: min(100vw - 18px, 760px);
                padding-top: 16px;
            }
            .seedance-workspace {
                grid-template-columns: minmax(0, 1fr);
            }
            .seedance-task-column {
                grid-column: auto;
            }
            .seedance-native-textarea {
                min-height: 320px;
            }
        }
        </style>
        """
    )
    ui.add_body_html(
        """
        <script>
        (() => {
            if (window.seedancePromptBridgeInstalled) return;
            window.seedancePromptBridgeInstalled = true;

            const editorId = 'seedance-prompt-editor';
            const getEditor = () => document.getElementById(editorId);
            const emitPrompt = (value) => {
                if (typeof emitEvent === 'function') {
                    emitEvent('seedance-prompt-changed', {value});
                }
            };
            const insertIntoEditor = (text) => {
                const editor = getEditor();
                if (!editor) return;
                const start = editor.selectionStart ?? editor.value.length;
                const end = editor.selectionEnd ?? editor.value.length;
                const prefix = editor.value.slice(0, start);
                const suffix = editor.value.slice(end);
                const before = prefix && !/\\s$/.test(prefix) ? ' ' : '';
                const after = suffix && !/^\\s/.test(suffix) ? ' ' : '';
                const insertText = `${before}${text}${after}`;
                editor.value = `${prefix}${insertText}${suffix}`;
                const caret = start + insertText.length;
                editor.focus();
                editor.setSelectionRange(caret, caret);
                emitPrompt(editor.value);
            };

            window.seedanceSetPrompt = (value) => {
                const editor = getEditor();
                if (editor) editor.value = value ?? '';
            };
            window.seedanceInsertPromptReference = insertIntoEditor;

            document.addEventListener('input', (event) => {
                if (event.target && event.target.id === editorId) {
                    emitPrompt(event.target.value);
                }
            });
            document.addEventListener('dragstart', (event) => {
                const card = event.target.closest('[data-seedance-ref]');
                if (!card) return;
                event.dataTransfer.setData('text/plain', card.dataset.seedanceRef);
                event.dataTransfer.effectAllowed = 'copy';
            });
            document.addEventListener('dragover', (event) => {
                if (event.target && event.target.id === editorId) {
                    event.preventDefault();
                    event.dataTransfer.dropEffect = 'copy';
                    event.target.classList.add('seedance-drop-active');
                }
            });
            document.addEventListener('dragleave', (event) => {
                if (event.target && event.target.id === editorId) {
                    event.target.classList.remove('seedance-drop-active');
                }
            });
            document.addEventListener('drop', (event) => {
                if (!(event.target && event.target.id === editorId)) return;
                event.preventDefault();
                event.target.classList.remove('seedance-drop-active');
                const text = event.dataTransfer.getData('text/plain');
                if (text) insertIntoEditor(text);
            });
        })();
        </script>
        """
    )

    def prompt_event_value(event: events.GenericEventArguments) -> str:
        if isinstance(event.args, dict):
            return str(event.args.get("value", ""))
        if isinstance(event.args, str):
            return event.args
        return ""

    def sync_prompt_from_browser(event: events.GenericEventArguments) -> None:
        state.prompt = prompt_event_value(event)
        refresh_request_preview()

    def set_prompt_in_browser(value: str) -> None:
        ui.run_javascript(f"window.seedanceSetPrompt({json.dumps(value, ensure_ascii=False)});")

    ui.on("seedance-prompt-changed", sync_prompt_from_browser)

    def ordered_reference_label(attachment: Attachment) -> str:
        return display_reference_label(state.attachments, attachment, selected_generation_mode())

    def selected_generation_mode() -> str:
        return GENERATION_MODE_LABELS.get(str(generation_mode_select.value), GENERATION_MODE_MULTIMODAL)

    def build_current_body() -> dict[str, Any]:
        advanced_options: dict[str, Any] = {}
        if advanced_settings_switch.value:
            if use_frames_switch.value:
                advanced_options["frames"] = int(frames_number.value or 57)
            if use_seed_switch.value:
                advanced_options["seed"] = int(seed_number.value if seed_number.value is not None else -1)
            advanced_options["camera_fixed"] = bool(camera_fixed_switch.value)
            advanced_options["return_last_frame"] = bool(return_last_frame_switch.value)
            if service_tier_select.value:
                advanced_options["service_tier"] = service_tier_select.value
            if execution_expires_number.value:
                advanced_options["execution_expires_after"] = int(execution_expires_number.value)
            advanced_options["draft"] = bool(draft_switch.value)
            callback_url = (callback_url_input.value or "").strip()
            if callback_url:
                advanced_options["callback_url"] = callback_url
            safety_identifier = (safety_identifier_input.value or "").strip()
            if safety_identifier:
                advanced_options["safety_identifier"] = safety_identifier
            if priority_number.value is not None:
                advanced_options["priority"] = int(priority_number.value)
            if web_search_switch.value:
                advanced_options["tools"] = [{"type": "web_search"}]

        return build_request_body(
            prompt=state.prompt,
            attachments=state.attachments,
            model=model_input.value.strip() or DEFAULT_MODEL,
            generate_audio=bool(generate_audio_switch.value),
            ratio=str(ratio_select.value or "16:9"),
            duration=int(duration_number.value or 15),
            watermark=bool(watermark_switch.value),
            generation_mode=selected_generation_mode(),
            resolution=str(resolution_select.value or ""),
            advanced_enabled=bool(advanced_settings_switch.value),
            advanced_options=advanced_options,
        )

    def refresh_request_preview() -> None:
        try:
            body = build_current_body()
            state.last_request_json = format_json(redact_request_body(body))
            state.last_error = ""
        except ValueError as exc:
            state.last_error = str(exc)
            state.last_request_json = f"请求参数错误：{exc}"
        request_preview.value = state.last_request_json
        request_preview.update()

    def refresh_status_messages() -> None:
        return None

    def refresh_task_views() -> None:
        task_panel.refresh()
        refresh_status_messages()

    def refresh_mode_dependent_views() -> None:
        attachment_panel.refresh()
        refresh_request_preview()

    def open_download_url(url: str) -> None:
        ui.run_javascript(f"window.open({json.dumps(url)}, '_blank', 'noopener,noreferrer');")

    def copy_download_url(url: str) -> None:
        ui.run_javascript(f"navigator.clipboard.writeText({json.dumps(url)});")
        ui.notify("下载链接已复制", type="positive")

    def copy_task_id(task_id: str) -> None:
        ui.run_javascript(f"navigator.clipboard.writeText({json.dumps(task_id)});")
        ui.notify("任务 ID 已复制", type="positive")

    def insert_reference(attachment_id: str) -> None:
        attachment = next((item for item in state.attachments if item.id == attachment_id), None)
        if attachment is None:
            return
        label = display_reference_label(state.attachments, attachment, selected_generation_mode())
        ui.run_javascript(f"window.seedanceInsertPromptReference({json.dumps(label, ensure_ascii=False)});")

    def move_attachment(attachment_id: str, delta: int) -> None:
        index = next((idx for idx, item in enumerate(state.attachments) if item.id == attachment_id), -1)
        if index < 0:
            return
        target = index + delta
        if target < 0 or target >= len(state.attachments):
            return
        state.attachments[index], state.attachments[target] = state.attachments[target], state.attachments[index]
        attachment_panel.refresh()
        refresh_request_preview()

    def remove_attachment(attachment_id: str) -> None:
        state.attachments = [attachment for attachment in state.attachments if attachment.id != attachment_id]
        attachment_panel.refresh()
        refresh_request_preview()

    def clear_attachments() -> None:
        state.attachments.clear()
        attachment_panel.refresh()
        refresh_request_preview()

    async def handle_upload(event: events.UploadEventArguments) -> None:
        try:
            data = await event.file.read()
            attachment = make_attachment(event.file.name, event.file.content_type, data)
        except UnsupportedAttachmentError as exc:
            state.last_error = str(exc)
            refresh_status_messages()
            ui.notify("附件类型不支持", type="negative")
            return

        state.attachments.append(attachment)
        state.last_error = ""
        attachment_panel.refresh()
        refresh_request_preview()
        refresh_status_messages()
        ui.notify(f"已添加：{attachment.name}", type="positive")

    def validate_before_request(api_key: str) -> bool:
        state.last_error = ""
        if not (api_url_input.value.strip() or DEFAULT_API_BASE_URL):
            state.last_error = f"缺少任务 API。请在界面中填写内网端点，或设置 {API_BASE_URL_ENV_VAR}。"
        elif not api_key.strip():
            state.last_error = f"缺少 API Key。请在环境变量 {API_KEY_ENV_VAR} 或密钥输入框中提供访问凭据。"
        elif not state.prompt.strip():
            state.last_error = "Prompt 不能为空。"
        elif int(duration_number.value or 0) <= 0:
            state.last_error = "时长必须大于 0。"
        else:
            try:
                build_current_body()
            except ValueError as exc:
                state.last_error = str(exc)
        refresh_status_messages()
        return not state.last_error

    async def poll_one_task(*, task_id: str, api_key: str, source: str, notify: bool) -> None:
        payload = await query_generation_task(
            api_base_url=api_url_input.value.strip() or DEFAULT_API_BASE_URL,
            api_key=api_key,
            task_id=task_id,
            verify_tls=bool(verify_tls_switch.value),
        )
        state.last_response_json = format_json(payload)
        response_output.value = state.last_response_json
        response_output.update()
        state.last_task_id = task_id
        upsert_task_record(state.tasks, task_id=task_id, payload=payload, source=source)
        state.last_error = ""
        refresh_task_views()
        if notify:
            ui.notify("状态已更新", type="positive")

    async def submit_task() -> None:
        api_key = api_key_input.value or ""
        if not validate_before_request(api_key):
            ui.notify("请求参数不完整", type="warning")
            return

        state.busy = True
        submit_button.disable()
        try:
            body = build_current_body()
            state.last_request_json = format_json(redact_request_body(body))
            request_preview.value = state.last_request_json
            request_preview.update()
            submit_count = normalize_submit_count(bool(gacha_switch.value), gacha_count_number.value)
            responses: list[dict[str, Any]] = []
            for index in range(submit_count):
                payload = await submit_generation_task(
                    api_base_url=api_url_input.value.strip() or DEFAULT_API_BASE_URL,
                    api_key=api_key,
                    body=body,
                    verify_tls=bool(verify_tls_switch.value),
                )
                responses.append(payload)
                task_id = extract_task_id(payload)
                if task_id:
                    state.last_task_id = task_id
                    upsert_task_record(state.tasks, task_id=task_id, payload=payload, source="submitted")
                if submit_count > 1:
                    ui.notify(f"抽卡提交 {index + 1}/{submit_count} 已完成", type="positive")
            response_payload: Any = responses[0] if submit_count == 1 else responses
            state.last_response_json = format_json(response_payload)
            response_output.value = state.last_response_json
            response_output.update()
            state.last_error = ""
            refresh_task_views()
            ui.notify(f"已提交 {submit_count} 次", type="positive")
        except httpx.HTTPStatusError as exc:
            state.last_error = f"HTTP {exc.response.status_code}: {exc.response.text[:900]}"
            refresh_status_messages()
            ui.notify("提交失败", type="negative")
        except httpx.HTTPError as exc:
            state.last_error = f"网络请求失败：{exc}"
            refresh_status_messages()
            ui.notify("提交失败", type="negative")
        finally:
            state.busy = False
            submit_button.enable()

    async def query_task() -> None:
        api_key = api_key_input.value or ""
        task_id = (task_id_input.value or "").strip()
        state.last_error = ""
        if not (api_url_input.value.strip() or DEFAULT_API_BASE_URL):
            state.last_error = f"缺少任务 API。请在界面中填写内网端点，或设置 {API_BASE_URL_ENV_VAR}。"
        elif not api_key.strip():
            state.last_error = f"缺少 API Key。请设置 {API_KEY_ENV_VAR} 或在界面中输入密钥。"
        elif not task_id:
            state.last_error = "请先输入任务 ID。"
        if state.last_error:
            refresh_status_messages()
            ui.notify("查询参数不完整", type="warning")
            return

        state.querying = True
        query_button.disable()
        try:
            await poll_one_task(task_id=task_id, api_key=api_key, source="manual", notify=False)
            ui.notify("状态已更新", type="positive")
        except httpx.HTTPStatusError as exc:
            state.last_error = f"HTTP {exc.response.status_code}: {exc.response.text[:900]}"
            refresh_status_messages()
            ui.notify("查询失败", type="negative")
        except httpx.HTTPError as exc:
            state.last_error = f"网络请求失败：{exc}"
            refresh_status_messages()
            ui.notify("查询失败", type="negative")
        finally:
            state.querying = False
            query_button.enable()

    async def query_record_task(task_id: str) -> None:
        api_key = api_key_input.value or ""
        if not (api_url_input.value.strip() or DEFAULT_API_BASE_URL):
            state.last_error = f"缺少任务 API。请在界面中填写内网端点，或设置 {API_BASE_URL_ENV_VAR}。"
            refresh_status_messages()
            ui.notify("查询参数不完整", type="warning")
            return
        if not api_key.strip():
            state.last_error = f"缺少 API Key。请设置 {API_KEY_ENV_VAR} 或在界面中输入密钥。"
            refresh_status_messages()
            ui.notify("查询参数不完整", type="warning")
            return

        state.querying = True
        try:
            source = state.tasks[task_id].source if task_id in state.tasks else "manual"
            await poll_one_task(task_id=task_id, api_key=api_key, source=source, notify=True)
        except httpx.HTTPStatusError as exc:
            state.last_error = f"HTTP {exc.response.status_code}: {exc.response.text[:900]}"
            refresh_status_messages()
            ui.notify("查询失败", type="negative")
        except httpx.HTTPError as exc:
            state.last_error = f"网络请求失败：{exc}"
            refresh_status_messages()
            ui.notify("查询失败", type="negative")
        finally:
            state.querying = False

    def write_request_json() -> None:
        try:
            body = build_current_body()
        except ValueError as exc:
            state.last_error = str(exc)
            request_preview.value = f"请求参数错误：{exc}"
            request_preview.update()
            ui.notify("请求参数不合法", type="warning")
            return
        path = request_body_path()
        path.write_text(format_json(body), encoding="utf-8")
        state.last_request_json = format_json(redact_request_body(body))
        request_preview.value = state.last_request_json
        request_preview.update()
        ui.notify(f"已写入：{path}", type="positive")

    async def auto_poll_tick() -> None:
        if auto_poll_switch.value and state.querying:
            return
        if not auto_poll_switch.value:
            return
        api_key = api_key_input.value or ""
        if not api_key.strip():
            return
        task_ids = pollable_task_ids(state.tasks)
        if not task_ids:
            return

        state.querying = True
        try:
            for task_id in task_ids:
                await poll_one_task(task_id=task_id, api_key=api_key, source=state.tasks[task_id].source, notify=False)
        finally:
            state.querying = False
            refresh_task_views()

    with ui.element("main").classes("seedance-shell"):
        with ui.row().classes("w-full items-end justify-between gap-6 mb-6"):
            with ui.column().classes("gap-2"):
                ui.label("Seedance Task Console").classes("seedance-topline")
                ui.label("视频生成任务工作台").classes("seedance-title")
                ui.label("Prompt、附件顺序、提交与查询集中处理").classes("seedance-subtle text-base")

        with ui.element("section").classes("seedance-workspace w-full"):
            with ui.column().classes("gap-5 min-w-0 w-full seedance-fill-column"):
                with ui.element("section").classes("seedance-panel p-5 w-full"):
                    with ui.column().classes("gap-2"):
                        ui.label("生成模式").classes("seedance-section-title")
                        generation_mode_select = ui.select(
                            list(GENERATION_MODE_LABELS.keys()),
                            value="多模态模式",
                            label="模式",
                        ).props("outlined dense").classes("w-full")
                        ui.label("首帧/首尾帧模式会使用上传图片顺序指定首帧和尾帧。").classes(
                            "seedance-subtle text-sm"
                        )

                with ui.element("section").classes("seedance-panel p-5 w-full"):
                    with ui.row().classes("w-full items-center justify-between mb-3"):
                        ui.label("Prompt").classes("seedance-section-title")
                        ui.label("可接收附件引用拖拽").classes("seedance-subtle text-sm")
                    ui.html(
                        f'<textarea id="seedance-prompt-editor" class="seedance-native-textarea" spellcheck="false">'
                        f"{html.escape(state.prompt)}"
                        "</textarea>"
                    ).classes("w-full")

                with ui.element("section").classes("seedance-panel p-5 w-full"):
                    with ui.row().classes("w-full items-center justify-between mb-4"):
                        ui.label("附件").classes("seedance-section-title")
                        ui.button("清空", icon="delete_sweep", on_click=clear_attachments).props(
                            "flat dense color=red-8"
                        )
                    ui.upload(on_upload=handle_upload, multiple=True, auto_upload=True, max_file_size=80_000_000).props(
                        'accept="image/*,audio/*" label="上传图片或音频" color=green-8'
                    ).classes("w-full")

                    @ui.refreshable
                    def attachment_panel() -> None:
                        if not state.attachments:
                            ui.label("暂无附件").classes("seedance-subtle text-sm mt-4")
                            return

                        with ui.column().classes("w-full gap-3 mt-4"):
                            for index, attachment in enumerate(state.attachments):
                                ref_label = ordered_reference_label(attachment)
                                kind_label = "图片" if attachment.kind == "image" else "音频"
                                safe_ref = html.escape(ref_label, quote=True)
                                with ui.element("div").classes("seedance-attachment-shell").props(
                                    f'draggable=true data-seedance-ref="{safe_ref}"'
                                ):
                                    with ui.row().classes("w-full items-start justify-between gap-3"):
                                        if attachment.kind == "image":
                                            ui.image(data_url_for_attachment(attachment)).classes(
                                                "seedance-attachment-preview"
                                            )
                                        else:
                                            with ui.element("div").classes("seedance-attachment-preview-placeholder"):
                                                ui.label("音频")
                                        with ui.column().classes("gap-1 min-w-0"):
                                            ui.label(ref_label).classes("seedance-pill")
                                            ui.label(attachment.name).classes(
                                                "text-sm font-medium text-[#17211d] break-all"
                                            )
                                            ui.label(
                                                f"{kind_label} · {attachment.mime_type} · {format_bytes(attachment.size)}"
                                            ).classes("seedance-subtle text-xs")
                                        with ui.row().classes("gap-1 shrink-0"):
                                            up_button = ui.button(
                                                icon="keyboard_arrow_up",
                                                on_click=lambda item_id=attachment.id: move_attachment(item_id, -1),
                                            ).props("flat dense color=grey-8")
                                            if index == 0:
                                                up_button.disable()
                                            if index == len(state.attachments) - 1:
                                                down_button = ui.button(icon="keyboard_arrow_down").props(
                                                    "flat dense color=grey-8"
                                                )
                                                down_button.disable()
                                            else:
                                                ui.button(
                                                    icon="keyboard_arrow_down",
                                                    on_click=lambda item_id=attachment.id: move_attachment(item_id, 1),
                                                ).props("flat dense color=grey-8")
                                            ui.button(
                                                icon="link",
                                                on_click=lambda item_id=attachment.id: insert_reference(item_id),
                                            ).props("flat dense color=green-8")
                                            ui.button(
                                                icon="close",
                                                on_click=lambda item_id=attachment.id: remove_attachment(item_id),
                                            ).props("flat dense color=red-8")

                    attachment_panel()

                with ui.element("section").classes("seedance-panel p-5 w-full"):
                    with ui.row().classes("w-full items-center justify-between mb-4"):
                        with ui.column().classes("gap-1"):
                            ui.label("请求预览").classes("seedance-section-title")
                            ui.label("Data URL 已折叠显示").classes("seedance-subtle text-sm")
                        with ui.row().classes("gap-2"):
                            ui.button("写入 JSON", icon="save", on_click=write_request_json).props(
                                "outline color=green-8"
                            )
                    request_preview = ui.textarea(value="").props("readonly outlined autogrow").classes(
                        "seedance-output w-full"
                    )

            with ui.column().classes("gap-5 min-w-0 w-full seedance-fill-column"):
                with ui.element("section").classes("seedance-panel p-5 w-full"):
                    ui.label("接口与生成参数").classes("seedance-section-title mb-3")
                    api_key_input = ui.input(
                        "API Key",
                        value=os.getenv(API_KEY_ENV_VAR, ""),
                        password=True,
                        password_toggle_button=True,
                    ).props("outlined dense").classes("w-full")
                    api_url_input = ui.input(
                        "任务 API（内网端点）",
                        value=DEFAULT_API_BASE_URL,
                        placeholder=f"例如由 {API_BASE_URL_ENV_VAR} 提供的内网 HTTPS 地址",
                    ).props("outlined dense").classes("w-full mt-3")
                    model_input = ui.input("模型", value=DEFAULT_MODEL).props("outlined dense").classes("w-full mt-3")
                    with ui.grid(columns=3).classes("w-full gap-3 mt-3"):
                        ratio_select = ui.select(
                            ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
                            value="16:9",
                            label="比例",
                        ).props("outlined dense")
                        duration_number = ui.number("时长", value=15, min=1, max=60, step=1).props("outlined dense")
                        resolution_select = ui.select(
                            ["", "480p", "720p", "1080p", "4k"],
                            value="",
                            label="分辨率",
                        ).props("outlined dense")
                    with ui.row().classes("w-full items-center justify-between mt-2 gap-2"):
                        generate_audio_switch = ui.switch("生成音频", value=True).props("color=green-8")
                        watermark_switch = ui.switch("水印", value=False).props("color=green-8")
                        verify_tls_switch = ui.switch("TLS 校验", value=True).props("color=green-8")
                    advanced_settings_switch = ui.switch("高级设置", value=False).props("color=green-8")
                    with ui.column().classes("seedance-advanced w-full gap-3") as advanced_settings_panel:
                        ui.label("开启后下列高级参数才会进入请求体").classes("seedance-subtle text-xs")
                        service_tier_select = ui.select(
                            ["", "default", "flex"],
                            value="",
                            label="服务等级（2.0 不建议配置）",
                        ).props("outlined dense").classes("w-full")
                        with ui.grid(columns=2).classes("w-full gap-3"):
                            use_frames_switch = ui.switch("使用 frames 替代 duration").props("color=green-8")
                            frames_number = ui.number("帧数", value=57, min=29, max=289, step=4).props(
                                "outlined dense"
                            )
                        with ui.grid(columns=2).classes("w-full gap-3"):
                            use_seed_switch = ui.switch("指定 seed（2.0 暂不支持）").props("color=green-8")
                            seed_number = ui.number("seed", value=-1, min=-1, max=4294967295, step=1).props(
                                "outlined dense"
                            )
                        with ui.grid(columns=2).classes("w-full gap-3"):
                            execution_expires_number = ui.number(
                                "任务超时秒数",
                                value=172800,
                                min=3600,
                                max=259200,
                                step=3600,
                            ).props("outlined dense")
                            priority_number = ui.number("优先级", value=0, min=0, max=9, step=1).props("outlined dense")
                        callback_url_input = ui.input("回调 URL").props("outlined dense").classes("w-full")
                        safety_identifier_input = ui.input("安全标识 safety_identifier").props(
                            "outlined dense maxlength=64"
                        ).classes("w-full")
                        with ui.row().classes("w-full items-center justify-between gap-2"):
                            camera_fixed_switch = ui.switch("固定镜头（2.0 暂不支持）").props("color=green-8")
                            return_last_frame_switch = ui.switch("返回尾帧").props("color=green-8")
                        with ui.row().classes("w-full items-center justify-between gap-2"):
                            draft_switch = ui.switch("样片模式（仅 1.5 Pro）").props("color=green-8")
                            web_search_switch = ui.switch("联网搜索工具").props("color=green-8")
                    advanced_settings_panel.bind_visibility_from(advanced_settings_switch, "value")

                with ui.element("section").classes("seedance-panel p-5 w-full"):
                    with ui.row().classes("w-full gap-3 items-center"):
                        submit_button = ui.button("提交生成任务", icon="send", on_click=submit_task).props(
                            "unelevated color=green-8"
                        ).classes("flex-1")
                        gacha_switch = ui.switch("抽卡").props("color=green-8")
                        gacha_count_number = ui.number("提交次数", value=3, min=1, max=20, step=1).props(
                            "outlined dense"
                        ).classes("w-28")
                    gacha_count_number.bind_visibility_from(gacha_switch, "value")

                with ui.element("section").classes("seedance-panel p-5 w-full"):
                    with ui.row().classes("w-full items-center justify-between mb-4 gap-3"):
                        with ui.column().classes("gap-1"):
                            ui.label("提交响应").classes("seedance-section-title")
                            ui.label("提交生成任务后的即时返回").classes("seedance-subtle text-sm")
                    response_output = ui.textarea(value="").props("readonly outlined autogrow").classes(
                        "seedance-output w-full"
                    )

            with ui.column().classes("gap-5 min-w-0 w-full seedance-fill-column seedance-task-column"):
                with ui.element("section").classes("seedance-panel p-5 w-full"):
                    with ui.row().classes("w-full items-center justify-between mb-4 gap-3"):
                        with ui.column().classes("gap-1"):
                            ui.label("任务列表").classes("seedance-section-title")
                            ui.label("提交返回的任务和手动查询任务会进入下方列表").classes("seedance-subtle text-sm")
                        auto_poll_switch = ui.switch("1s 自动轮询").props("color=green-8")
                    with ui.row().classes("w-full gap-2 items-start mb-4"):
                        task_id_input = ui.input("手动查询任务 ID", value="").props("outlined dense").classes("flex-1")
                        query_button = ui.button("查询状态", icon="manage_search", on_click=query_task).props(
                            "outline color=green-8"
                        )
                    ui.label("只自动轮询 queued / running / unknown").classes("seedance-subtle text-sm mb-4")

                    @ui.refreshable
                    def task_panel() -> None:
                        if not state.tasks:
                            ui.label("暂无任务。提交后会自动记录任务 ID，也可以手动输入任务 ID 查询。").classes(
                                "seedance-subtle text-sm"
                            )
                            return

                        ordered_tasks = sorted(state.tasks.values(), key=lambda item: item.updated_at, reverse=True)
                        with ui.column().classes("w-full gap-3"):
                            for task in ordered_tasks:
                                status = task.status.lower() or "unknown"
                                status_class = "".join(ch if ch.isalnum() else "-" for ch in status)
                                status_icon = task_status_icon(status)
                                source_label = "提交" if task.source == "submitted" else "手动"
                                updated_text = time.strftime("%H:%M:%S", time.localtime(task.updated_at))
                                with ui.element("div").classes("seedance-task-row"):
                                    with ui.element("div").classes(
                                        f"seedance-task-icon seedance-task-icon-{status_class}"
                                    ):
                                        if status_icon == "spinner":
                                            ui.spinner(size="sm", color="warning")
                                        else:
                                            ui.icon(status_icon).classes("text-[20px]")
                                    with ui.column().classes("gap-1 seedance-task-main"):
                                        with ui.row().classes("items-center gap-2"):
                                            ui.label(status).classes(f"seedance-status seedance-status-{status_class}")
                                            ui.label(f"{source_label} · {updated_text}").classes(
                                                "seedance-subtle text-xs"
                                            )
                                        ui.label(task.id).classes("seedance-task-id")
                                        if task.error:
                                            error_text = (
                                                format_json(task.error)
                                                if isinstance(task.error, (dict, list))
                                                else str(task.error)
                                            )
                                            ui.label(error_text).classes("seedance-error w-full mt-1")
                                    with ui.element("div").classes("seedance-task-actions"):
                                        ui.button(
                                            icon="content_copy",
                                            on_click=lambda item_id=task.id: copy_task_id(item_id),
                                        ).props("flat dense color=grey-8")
                                        ui.button(
                                            icon="refresh",
                                            on_click=lambda item_id=task.id: query_record_task(item_id),
                                        ).props("flat dense color=green-8")
                                        if task.status == "succeeded" and task.download_url:
                                            ui.button(
                                                icon="download",
                                                on_click=lambda url=task.download_url: open_download_url(url),
                                            ).props("flat dense color=green-8")
                                            ui.button(
                                                icon="link",
                                                on_click=lambda url=task.download_url: copy_download_url(url),
                                            ).props("flat dense color=green-8")

                    task_panel()

    generation_mode_select.on_value_change(lambda _: refresh_mode_dependent_views())
    for element in (
        model_input,
        ratio_select,
        duration_number,
        resolution_select,
        generate_audio_switch,
        watermark_switch,
        advanced_settings_switch,
        service_tier_select,
        use_frames_switch,
        frames_number,
        use_seed_switch,
        seed_number,
        execution_expires_number,
        priority_number,
        callback_url_input,
        safety_identifier_input,
        camera_fixed_switch,
        return_last_frame_switch,
        draft_switch,
        web_search_switch,
    ):
        element.on_value_change(lambda _: refresh_request_preview())

    refresh_request_preview()
    refresh_status_messages()
    ui.timer(1.0, auto_poll_tick)
    ui.timer(0.2, lambda: set_prompt_in_browser(state.prompt), once=True)


if __name__ in {"__main__", "__mp_main__"}:
    import sys

    from nicegui import native
    from nicegui import ui

    try:
        ui.run(
            create_interface,
            host="127.0.0.1" if getattr(sys, "frozen", False) else "0.0.0.0",
            port=native.find_open_port() if getattr(sys, "frozen", False) else 8080,
            title="Seedance Task Console",
            reload=False,
            show=bool(getattr(sys, "frozen", False)),
        )
    except KeyboardInterrupt:
        pass
