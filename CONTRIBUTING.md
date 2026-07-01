# Contributing

感谢你改进 Seedance NiceGUI。这个项目默认服务于公司内网、无外网终端和私有任务端点，因此所有贡献都必须保持脱敏和可离线部署的前提。

## 开发流程

1. 安装 Python 3.11 或更高版本。
2. 创建虚拟环境并安装开发依赖：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

3. 修改代码后运行：

```bash
python -m pytest
python -m py_compile app.py tests/test_app.py
```

## 提交要求

- 不提交真实内网端点、公司域名、密钥、任务 ID、签名 URL、历史响应或素材文件。
- 不提交 `.env`、`.venv`、`build`、`dist`、`__pycache__`、`.pytest_cache`。
- 新增请求体字段时，需要补充或更新单元测试。
- 修改响应解析逻辑时，需要覆盖嵌套响应和缺失字段场景。
- 保持应用适合内网部署，不引入运行时必须访问公网的能力。

## 发布

维护者通过推送 `v*` 标签触发 Release 工作流。发布包由 GitHub Actions 构建，不从本地 `dist/` 上传。
