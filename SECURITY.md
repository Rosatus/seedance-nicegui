# Security Policy

## 支持范围

当前支持主分支和最新 GitHub Release。

## 报告漏洞

请通过 GitHub Security Advisory 或私下联系维护者报告漏洞。不要在公开 issue 中粘贴真实内网端点、API Key、任务 ID、签名下载链接或完整任务响应。

## 密钥与端点处理

本项目不会在源码中内置真实任务端点或凭据。部署方应通过以下方式配置：

- `SEEDANCE_API_BASE_URL`
- `SEEDANCE_API_KEY`
- 界面中的“任务 API（内网端点）”和“API Key”输入框

如果凭据被提交到仓库或粘贴到公开 issue，应立即在内网网关侧吊销并轮换。删除 Git 历史不能保证已泄露的凭据失效。
