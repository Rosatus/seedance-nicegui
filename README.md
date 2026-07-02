# Seedance NiceGUI

English | [简体中文](README.zh-CN.md)

Seedance NiceGUI is a local web console for submitting Seedance-compatible video generation tasks to private intranet endpoints. It is designed for enterprise environments where the generation gateway is deployed inside the company network and the user workstation cannot access the public internet.

This repository does not include real company domains, private endpoint paths, API keys, task IDs, signed media URLs, or historical response samples. Operators must provide their own intranet task endpoint and credential at runtime.

## Features

- Local NiceGUI web interface; the browser talks to this app, and the Python backend calls the private task endpoint.
- Prompt editor with image and audio uploads converted to data URLs.
- Multimodal, first-frame, and first-last-frame attachment modes.
- Common generation options: model, ratio, duration, resolution, watermark, audio generation, and TLS verification.
- Optional advanced request fields: `frames`, `seed`, `camera_fixed`, `return_last_frame`, `service_tier`, `execution_expires_after`, `draft`, `priority`, `callback_url`, `safety_identifier`, and `tools`.
- Request preview with base64 payloads collapsed for readability.
- Task tracking with manual query and 1-second polling for `queued`, `running`, and `unknown` tasks.
- Windows onedir packaging support for distribution to offline intranet workstations.

## Intended Use

Use this project when:

- Your video generation API gateway is reachable only from the company intranet.
- The target workstation has no public internet access.
- You need a small local UI for users who should not craft JSON requests by hand.
- Your API follows a task-style shape such as `POST /tasks` to create a job and `GET /tasks/{task_id}` to query it.

This project is not a hosted service, a credential manager, or a long-term task database. It keeps runtime state in memory and does not persist uploaded media, prompts, credentials, or task history.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Configure your private endpoint and credential:

```bash
export SEEDANCE_API_BASE_URL="https://<intranet-host>/<private-path>/tasks"
export SEEDANCE_API_KEY="<your-intranet-credential>"
```

Run the app:

```bash
python app.py
```

The default development server listens on `0.0.0.0:8080`. For local desktop use, open:

```text
http://127.0.0.1:8080
```

You can also leave the environment variables unset and enter the task API and API key directly in the UI.

## Offline Deployment

For production use on workstations without public internet access, build or prepare dependencies on a machine that can reach your package mirror, then copy the result into the intranet environment.

Recommended options:

- Use the packaged release assets from [GitHub Releases](https://github.com/Rosatus/seedance-nicegui/releases).
- Build a Windows onedir package by following [WINDOWS_CONDA_BUILD.md](WINDOWS_CONDA_BUILD.md).
- Prepare an offline wheelhouse:

```bash
python -m pip download -d wheelhouse .
```

Then install on the offline workstation:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --no-index --find-links wheelhouse -e .
python app.py
```

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `SEEDANCE_API_BASE_URL` | Yes | Private task creation endpoint, for example `https://<intranet-host>/<private-path>/tasks`. No real endpoint is bundled with the source. |
| `SEEDANCE_API_KEY` | Yes | Credential for the private API gateway. The app sends it as the `Authorization` request header. |

Values entered in the UI apply to the current session. Environment variables are used only to prefill the UI at startup.

## API Compatibility

Task submission:

```http
POST <SEEDANCE_API_BASE_URL>
Authorization: <SEEDANCE_API_KEY>
Content-Type: application/json
```

Task query:

```http
GET <SEEDANCE_API_BASE_URL>/<task_id>
Authorization: <SEEDANCE_API_KEY>
```

The app recursively extracts common response fields:

- Task ID: `id` or `task_id`
- Status: `status`
- Video URL: `video_url`, `file_url`, or `url`
- Last-frame URL: `last_frame_url`
- Error payload: `error`

If your gateway uses different field names, adjust the extraction helpers in `app.py`.

## Security Notes

- Do not commit real intranet domains, private paths, API keys, task IDs, signed media URLs, curl history, or full gateway responses.
- Runtime credentials are read from environment variables or UI inputs; they are not intentionally persisted by the app.
- If a credential is exposed, revoke and rotate it at the gateway. Removing it from Git history is not enough.

## License

Seedance NiceGUI is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
