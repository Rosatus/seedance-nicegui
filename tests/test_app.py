import base64

import pytest

from app import (
    API_BASE_URL_ENV_VAR,
    API_KEY_ENV_VAR,
    Attachment,
    DEFAULT_API_BASE_URL,
    DEFAULT_PROMPT,
    TaskRecord,
    UnsupportedAttachmentError,
    build_request_body,
    display_reference_label,
    extract_download_url,
    extract_status,
    extract_task_id,
    infer_attachment_kind,
    normalize_submit_count,
    pollable_task_ids,
    prompt_reference_label,
    task_status_icon,
    upsert_task_record,
)


def test_default_prompt_is_concise_template() -> None:
    assert "进度总览 Dashboard" not in DEFAULT_PROMPT
    assert len(DEFAULT_PROMPT.splitlines()) <= 8
    assert "主体：" in DEFAULT_PROMPT
    assert "动作：" in DEFAULT_PROMPT
    assert "镜头：" in DEFAULT_PROMPT
    assert "限制：" in DEFAULT_PROMPT


def test_default_endpoint_configuration_is_sanitized() -> None:
    assert API_BASE_URL_ENV_VAR == "SEEDANCE_API_BASE_URL"
    assert API_KEY_ENV_VAR == "SEEDANCE_API_KEY"
    assert "agent-api" not in DEFAULT_API_BASE_URL.lower()
    assert "volces-video" not in DEFAULT_API_BASE_URL.lower()


def test_build_request_body_orders_attachments_and_data_urls() -> None:
    first_png = Attachment(
        id="a1",
        name="one.png",
        mime_type="image/png",
        kind="image",
        role="reference_image",
        data=b"first-image",
    )
    second_wav = Attachment(
        id="a2",
        name="voice.wav",
        mime_type="audio/wav",
        kind="audio",
        role="reference_audio",
        data=b"audio-bytes",
    )

    body = build_request_body(
        prompt="图片 1 做主体，音频 1 做旁白",
        attachments=[first_png, second_wav],
        model="doubao-seedance-2-0-260128",
        generate_audio=True,
        ratio="16:9",
        duration=15,
        watermark=False,
    )

    assert body["model"] == "doubao-seedance-2-0-260128"
    assert body["generate_audio"] is True
    assert body["ratio"] == "16:9"
    assert body["duration"] == 15
    assert body["watermark"] is False
    assert body["content"][0] == {"type": "text", "text": "图片 1 做主体，音频 1 做旁白"}
    assert body["content"][1]["type"] == "image_url"
    assert body["content"][1]["role"] == "reference_image"
    assert body["content"][1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(b"first-image").decode("ascii")
    )
    assert body["content"][2]["type"] == "audio_url"
    assert body["content"][2]["role"] == "reference_audio"
    assert body["content"][2]["audio_url"]["url"] == (
        "data:audio/wav;base64," + base64.b64encode(b"audio-bytes").decode("ascii")
    )


def test_build_request_body_assigns_first_frame_role_in_first_frame_mode() -> None:
    image = Attachment("a1", "first.png", "image/png", "image", "reference_image", b"first")

    body = build_request_body(
        prompt="用图片 1 作为首帧",
        attachments=[image],
        model="doubao-seedance-2-0-260128",
        generate_audio=True,
        ratio="16:9",
        duration=15,
        watermark=False,
        generation_mode="first_frame",
    )

    assert body["content"][1]["type"] == "image_url"
    assert body["content"][1]["role"] == "first_frame"


def test_build_request_body_assigns_first_and_last_frame_roles() -> None:
    first = Attachment("a1", "first.png", "image/png", "image", "reference_image", b"first")
    last = Attachment("a2", "last.png", "image/png", "image", "reference_image", b"last")

    body = build_request_body(
        prompt="图片 1 首帧，图片 2 尾帧",
        attachments=[first, last],
        model="doubao-seedance-2-0-260128",
        generate_audio=True,
        ratio="16:9",
        duration=15,
        watermark=False,
        generation_mode="first_last_frame",
    )

    assert [block["role"] for block in body["content"][1:]] == ["first_frame", "last_frame"]


def test_build_request_body_rejects_extra_images_in_strict_frame_modes() -> None:
    images = [
        Attachment("a1", "first.png", "image/png", "image", "reference_image", b"first"),
        Attachment("a2", "last.png", "image/png", "image", "reference_image", b"last"),
        Attachment("a3", "extra.png", "image/png", "image", "reference_image", b"extra"),
    ]

    with pytest.raises(ValueError, match="首尾帧模式需要恰好 2 张图片"):
        build_request_body(
            prompt="test",
            attachments=images,
            model="doubao-seedance-2-0-260128",
            generate_audio=True,
            ratio="16:9",
            duration=15,
            watermark=False,
            generation_mode="first_last_frame",
        )


def test_build_request_body_excludes_advanced_options_when_disabled() -> None:
    body = build_request_body(
        prompt="test",
        attachments=[],
        model="doubao-seedance-2-0-260128",
        generate_audio=True,
        ratio="16:9",
        duration=15,
        watermark=False,
        advanced_enabled=False,
        advanced_options={
            "resolution": "4k",
            "return_last_frame": True,
            "priority": 7,
            "tools": [{"type": "web_search"}],
        },
    )

    assert "resolution" not in body
    assert "return_last_frame" not in body
    assert "priority" not in body
    assert "tools" not in body


def test_build_request_body_includes_resolution_as_base_option() -> None:
    without_resolution = build_request_body(
        prompt="test",
        attachments=[],
        model="doubao-seedance-2-0-260128",
        generate_audio=True,
        ratio="16:9",
        duration=15,
        watermark=False,
        resolution="",
        advanced_enabled=False,
    )
    with_resolution = build_request_body(
        prompt="test",
        attachments=[],
        model="doubao-seedance-2-0-260128",
        generate_audio=True,
        ratio="16:9",
        duration=15,
        watermark=False,
        resolution="1080p",
        advanced_enabled=False,
    )

    assert "resolution" not in without_resolution
    assert with_resolution["resolution"] == "1080p"


def test_build_request_body_includes_clean_advanced_options_when_enabled() -> None:
    body = build_request_body(
        prompt="test",
        attachments=[],
        model="doubao-seedance-2-0-260128",
        generate_audio=False,
        ratio="adaptive",
        duration=15,
        watermark=True,
        advanced_enabled=True,
        advanced_options={
            "resolution": "4k",
            "frames": 57,
            "seed": -1,
            "camera_fixed": True,
            "return_last_frame": True,
            "service_tier": "",
            "execution_expires_after": 172800,
            "draft": False,
            "callback_url": "",
            "safety_identifier": "hashed-user",
            "priority": 5,
            "tools": [{"type": "web_search"}],
        },
    )

    assert body["resolution"] == "4k"
    assert body["frames"] == 57
    assert "duration" not in body
    assert body["seed"] == -1
    assert body["camera_fixed"] is True
    assert body["return_last_frame"] is True
    assert "service_tier" not in body
    assert body["execution_expires_after"] == 172800
    assert body["draft"] is False
    assert "callback_url" not in body
    assert body["safety_identifier"] == "hashed-user"
    assert body["priority"] == 5
    assert body["tools"] == [{"type": "web_search"}]


def test_normalize_submit_count_for_single_and_gacha_modes() -> None:
    assert normalize_submit_count(False, None) == 1
    assert normalize_submit_count(False, 5) == 1
    assert normalize_submit_count(True, 3) == 3
    assert normalize_submit_count(True, 0) == 1
    assert normalize_submit_count(True, 100) == 20


def test_prompt_reference_labels_follow_request_order_per_kind() -> None:
    attachments = [
        Attachment("1", "a.png", "image/png", "image", "reference_image", b"a"),
        Attachment("2", "b.mp3", "audio/mpeg", "audio", "reference_audio", b"b"),
        Attachment("3", "c.jpg", "image/jpeg", "image", "reference_image", b"c"),
    ]

    assert prompt_reference_label(attachments, attachments[0].id) == "图片 1"
    assert prompt_reference_label(attachments, attachments[1].id) == "音频 1"
    assert prompt_reference_label(attachments, attachments[2].id) == "图片 2"


def test_display_reference_labels_follow_generation_mode() -> None:
    attachments = [
        Attachment("1", "a.png", "image/png", "image", "reference_image", b"a"),
        Attachment("2", "b.png", "image/png", "image", "reference_image", b"b"),
        Attachment("3", "c.mp3", "audio/mpeg", "audio", "reference_audio", b"c"),
    ]

    assert display_reference_label(attachments, attachments[0], "multimodal") == "图片 1"
    assert display_reference_label(attachments, attachments[1], "multimodal") == "图片 2"
    assert display_reference_label(attachments, attachments[2], "multimodal") == "音频 1"
    assert display_reference_label(attachments[:1], attachments[0], "first_frame") == "首帧"
    assert display_reference_label(attachments[:2], attachments[0], "first_last_frame") == "首帧"
    assert display_reference_label(attachments[:2], attachments[1], "first_last_frame") == "尾帧"


def test_extract_task_id_from_common_response_shapes() -> None:
    assert extract_task_id({"id": "root-id"}) == "root-id"
    assert extract_task_id({"task_id": "root-task"}) == "root-task"
    assert extract_task_id({"data": {"id": "nested-id"}}) == "nested-id"
    assert extract_task_id({"data": {"task_id": "nested-task"}}) == "nested-task"
    assert extract_task_id({"result": {"task": {"id": "deep-id"}}}) == "deep-id"
    assert extract_task_id({"result": "not-a-dict"}) is None


def test_extract_status_and_download_url_from_gateway_or_ark_shapes() -> None:
    ark_payload = {
        "id": "cgt-1",
        "status": "succeeded",
        "content": {
            "video_url": "https://example.com/video.mp4",
            "last_frame_url": "https://example.com/last.png",
        },
    }
    gateway_payload = {"data": {"task": ark_payload}}

    assert extract_status(gateway_payload) == "succeeded"
    assert extract_download_url(gateway_payload) == "https://example.com/video.mp4"


def test_task_registry_tracks_submitted_and_manual_tasks_for_polling() -> None:
    tasks: dict[str, TaskRecord] = {}

    upsert_task_record(tasks, task_id="submitted-id", payload={"id": "submitted-id"}, source="submitted")
    upsert_task_record(
        tasks,
        task_id="manual-id",
        payload={"id": "manual-id", "status": "running"},
        source="manual",
    )
    upsert_task_record(
        tasks,
        task_id="done-id",
        payload={
            "id": "done-id",
            "status": "succeeded",
            "content": {"video_url": "https://example.com/done.mp4"},
        },
        source="submitted",
    )

    assert pollable_task_ids(tasks) == ["submitted-id", "manual-id"]
    assert tasks["done-id"].download_url == "https://example.com/done.mp4"
    assert tasks["done-id"].status == "succeeded"


def test_task_status_icons_cover_known_and_unknown_states() -> None:
    assert task_status_icon("queued") == "hourglass_empty"
    assert task_status_icon("running") == "spinner"
    assert task_status_icon("succeeded") == "check_circle"
    assert task_status_icon("failed") == "error"
    assert task_status_icon("expired") == "block"
    assert task_status_icon("cancelled") == "block"
    assert task_status_icon("unexpected") == "help"


def test_infer_attachment_kind_rejects_unsupported_types() -> None:
    assert infer_attachment_kind("photo.webp", "image/webp") == "image"
    assert infer_attachment_kind("voice.m4a", "audio/mp4") == "audio"

    with pytest.raises(UnsupportedAttachmentError):
        infer_attachment_kind("notes.txt", "text/plain")
