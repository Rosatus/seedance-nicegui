# Windows Conda 打包指南

本指南用于在可控 Windows 构建机上生成 onedir 包，再分发到无法访问外网、但可以访问公司内网视频生成任务端点的终端。不要把真实内网域名、API Key、任务 ID、签名 URL 或历史响应写入源码、文档或发布包说明。

## 1. 准备环境

在 Windows 打包电脑上安装 Anaconda 或 Miniconda，然后打开 Anaconda Prompt，进入项目目录：

```powershell
cd path\to\seedance
```

创建环境：

```powershell
conda env create -f environment.yml
conda activate seedance-build
```

如果环境已经存在，更新环境：

```powershell
conda activate seedance-build
conda env update -f environment.yml --prune
```

## 2. 本地运行检查

配置内网端点和凭据：

```powershell
$env:SEEDANCE_API_BASE_URL = "https://<intranet-host>/<private-path>/tasks"
$env:SEEDANCE_API_KEY = "<your-intranet-credential>"
```

```powershell
python app.py
```

看到 NiceGUI 本地地址后，在浏览器打开检查界面是否正常。停止服务使用 `Ctrl+C`。

## 3. 打包 onedir

```powershell
python -m pytest
python -m py_compile app.py tests/test_app.py
python -m nicegui.scripts.pack --onedir --name seedance --clean --noconfirm app.py
```

打包完成后，可执行文件在：

```text
dist\seedance\seedance.exe
```

## 4. 压缩分发

```powershell
Compress-Archive -Path dist\seedance -DestinationPath dist\seedance-windows-x64-onedir.zip -Force
```

分发时使用整个 `dist\seedance` 目录，或使用上面生成的 zip。不要只复制 `seedance.exe`，因为 onedir 包还依赖同目录下的 `_internal` 文件。

## 5. 注意事项

- Windows 版本需要在 Windows 上打包，Linux 打出来的 PyInstaller 产物不能作为 Windows exe 使用。
- `seedance.spec` 是平台相关文件，Windows 打包时可以让 `nicegui.scripts.pack` 自动重新生成。
- 这个应用通常不涉及浏览器跨域问题，因为浏览器访问的是本机 NiceGUI，真正请求内网任务端点的动作由 Python 后端 `httpx` 发起。
- 如果提交任务失败，优先检查 Windows 机器的内网连通性、VPN、代理、TLS 证书和网关白名单。
- 打包产物不应该内置真实端点或密钥；建议由终端使用环境变量或界面输入运行时配置。
