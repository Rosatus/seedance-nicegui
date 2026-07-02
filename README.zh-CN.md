# Seedance NiceGUI

[English](README.md) | 简体中文

Seedance NiceGUI 是一个本地 Web 工作台，用于向企业内网中的 Seedance 兼容视频生成任务端点提交请求、上传参考图片/音频、查看请求体、记录任务 ID 并轮询任务状态。

这个项目专门服务于“生成端点部署在公司内网、运行环境无法访问外网”的场合。仓库不包含任何真实公司域名、内网路径、API Key、任务 ID、签名下载链接或历史响应样例；部署时必须由使用方通过环境变量或界面输入自己的内网任务 API。

## 功能

- NiceGUI 本地单页工作台；浏览器访问本应用，Python 后端调用私有任务端点。
- 支持文本 Prompt、图片附件、音频附件，并自动转换为 data URL。
- 支持多模态、首帧、首尾帧三种附件角色模式。
- 支持模型、比例、时长、分辨率、水印、生成音频、TLS 校验等常用参数。
- 支持高级参数：`frames`、`seed`、`camera_fixed`、`return_last_frame`、`service_tier`、`execution_expires_after`、`draft`、`priority`、`callback_url`、`safety_identifier`、`tools`。
- 请求预览会折叠 base64 内容，避免界面展示超长素材数据。
- 提交成功后自动记录任务 ID，可手动查询或 1 秒自动轮询 `queued`、`running`、`unknown` 任务。
- 支持 Windows onedir 打包，方便分发到无外网内网终端。

## 适用场景

适用：

- 视频生成 API 网关位于公司内网。
- 目标终端无法访问公网。
- 需要一个轻量本地界面，避免用户手写 JSON 请求。
- API 形态接近任务接口：`POST /tasks` 创建任务，`GET /tasks/{task_id}` 查询任务。

不适用：

- 托管服务、账号系统或凭据管理系统。
- 长期保存素材、Prompt、任务历史或密钥。当前应用状态主要保存在进程内，刷新或重启后不会持久化。

## 安装

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
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

## 离线部署

生产使用时建议在可访问依赖源的构建机上提前准备依赖或打包产物，再复制到无外网终端。

推荐方式：

- 直接使用 [GitHub Releases](https://github.com/Rosatus/seedance-nicegui/releases) 中的打包产物。
- 按 [WINDOWS_CONDA_BUILD.md](WINDOWS_CONDA_BUILD.md) 构建 Windows onedir 包。
- 准备离线 wheelhouse：

```bash
python -m pip download -d wheelhouse .
```

复制到内网终端后：

```bash
python -m venv .venv
source .venv/bin/activate
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

如果你的网关字段不同，可以在 `app.py` 中扩展解析函数。

## 安全说明

- 不要提交真实内网域名、路径、密钥、任务 ID、签名媒体 URL、历史 curl 命令或完整任务响应。
- 运行时凭据来自环境变量或界面输入；应用不会主动持久化这些凭据。
- 如果误泄露密钥，应立即在网关侧吊销并轮换；删除 Git 历史不能保证凭据失效。

## 许可证

本项目使用 GNU Affero General Public License v3.0，详见 [LICENSE](LICENSE)。
