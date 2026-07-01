# Seedance NiceGUI

Seedance NiceGUI 是一个面向内网部署的本地 Web 工作台，用于向企业内网中的 Seedance 兼容视频生成任务端点提交请求、上传参考图片/音频、查看请求体、记录任务 ID 并轮询任务状态。

这个项目专门服务于“生成端点部署在公司内网、运行环境无法访问外网”的场合。仓库不包含任何真实公司域名、内网路径、API Key、任务 ID、签名下载链接或历史响应样例；部署时必须由使用方通过环境变量或界面输入自己的内网任务 API。

## 功能

- NiceGUI 单页工作台，本机浏览器访问，Python 后端负责向任务端点发起请求。
- 支持文本 Prompt、图片附件、音频附件，并自动转换为 data URL。
- 支持多模态、首帧、首尾帧三种附件角色模式。
- 支持模型、比例、时长、分辨率、水印、TLS 校验等常用参数。
- 支持高级参数开关：frames、seed、camera_fixed、return_last_frame、service_tier、execution_expires_after、draft、priority、callback_url、safety_identifier、tools。
- 请求预览会折叠 base64 内容，避免界面中展示超长素材数据。
- 提交成功后自动记录任务 ID，可手动查询或 1 秒自动轮询 queued / running / unknown 任务。
- 支持 Windows onedir 打包，方便在无外网终端上分发。

## 适用边界

适用：

- 视频生成 API 网关位于公司内网，终端无法访问公网。
- 需要一个轻量本地界面帮助非工程用户组装和提交任务。
- API 形态与常见 Seedance / Ark 风格任务接口兼容：`POST /tasks` 创建任务，`GET /tasks/{task_id}` 查询任务。

不适用：

- 需要内置云厂商公网端点、内置账号体系或托管服务。
- 需要长期保存素材、Prompt、任务历史或密钥。当前应用状态主要保存在进程内，刷新或重启后不会持久化。
- 需要浏览器直接跨域访问任务网关。本项目由 Python 后端调用网关，浏览器只访问本机 NiceGUI。

## 快速开始

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

配置内网端点和密钥：

```bash
export SEEDANCE_API_BASE_URL="https://<intranet-host>/<private-path>/tasks"
export SEEDANCE_API_KEY="<your-intranet-credential>"
```

启动：

```bash
python app.py
```

默认监听 `0.0.0.0:8080`。如果在桌面终端本机使用，浏览器打开：

```text
http://127.0.0.1:8080
```

也可以不设置环境变量，启动后在界面中填写“任务 API（内网端点）”和“API Key”。

## 内网与离线部署

生产使用时建议在可访问依赖源的构建机上提前准备依赖或打包产物，再复制到无外网终端。

### 方式一：复制 onedir 包

Windows 打包流程见 [WINDOWS_CONDA_BUILD.md](WINDOWS_CONDA_BUILD.md)。打包完成后复制整个 `dist/seedance/` 目录到内网终端，不要只复制单个 exe。

### 方式二：准备离线 wheelhouse

在可联网机器上：

```bash
python -m pip download -d wheelhouse ".[dev]"
```

将源码和 `wheelhouse/` 复制到内网终端后：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --no-index --find-links wheelhouse -e .
python app.py
```

Windows PowerShell 对应命令：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --no-index --find-links wheelhouse -e .
python app.py
```

## 配置

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `SEEDANCE_API_BASE_URL` | 是 | 内网任务创建端点，例如 `https://<intranet-host>/<private-path>/tasks`。源码不提供默认真实地址。 |
| `SEEDANCE_API_KEY` | 是 | 内网 API 网关凭据。应用会作为 `Authorization` 请求头发送。 |

界面中输入的值优先用于当前会话；环境变量用于启动时预填。

## API 兼容假设

提交任务：

```http
POST <SEEDANCE_API_BASE_URL>
Authorization: <SEEDANCE_API_KEY>
Content-Type: application/json
```

查询任务：

```http
GET <SEEDANCE_API_BASE_URL>/<task_id>
Authorization: <SEEDANCE_API_KEY>
```

应用会从响应中递归提取常见字段：

- 任务 ID：`id` 或 `task_id`
- 状态：`status`
- 视频下载 URL：`video_url`、`file_url` 或 `url`
- 尾帧 URL：`last_frame_url`
- 错误信息：`error`

如果你的网关字段不同，可以在 `extract_task_id`、`extract_status`、`extract_download_url` 等函数中扩展。

## 开发

运行测试：

```bash
python -m pytest
python -m py_compile app.py tests/test_app.py
```

项目结构：

```text
app.py                  # NiceGUI 应用和任务请求/响应处理逻辑
tests/test_app.py       # 请求体构建、附件、任务解析等单元测试
environment.yml         # Windows/Conda 打包环境
WINDOWS_CONDA_BUILD.md  # Windows onedir 打包说明
.github/workflows/      # CI 和 Release 工作流
```

## 安全与脱敏

- 不要提交真实内网域名、路径、密钥、任务 ID、签名媒体 URL、历史 curl 命令或任务响应。
- `.env`、构建产物、缓存目录和 legacy 历史脚本已被 `.gitignore` 排除。
- 发布前可执行：

```bash
rg -n "Authorization:|X-Tos-|Credential|Signature|https://<real-host>|agent-api" .
```

如果误提交了密钥，应立即在网关侧吊销并轮换；从 Git 历史中删除并不能撤回已经泄露的凭据。

## GitHub Actions

- `ci.yml`：在 push 和 pull request 时安装依赖、运行 pytest 和 py_compile。
- `release.yml`：推送 `v*` 标签时，在 Linux 和 Windows 上运行测试并构建 onedir 包，然后创建 GitHub Release 并上传产物。

本地创建发布标签示例：

```bash
git tag v0.1.0
git push origin v0.1.0
```

## 许可证

本项目使用 GNU Affero General Public License v3.0，详见 [LICENSE](LICENSE)。
