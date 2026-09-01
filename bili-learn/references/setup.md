# 配置指南（备用后端）

主后端 **必剪(Bcut)** 完全免费、无需任何配置。以下仅在 bcut 限流或想换识别引擎时使用。

## Groq Whisper（推荐备用，免费）

Groq 提供免费的 `whisper-large-v3-turbo`（英文优秀，中文可用）：

1. 注册 https://console.groq.com （免费，1 分钟）
2. https://console.groq.com/keys 创建 API key（`gsk_` 开头）
3. 两种方式之一配置：
   - 更新 `~/.pi/agent/auth.json` 中 `groq.key` 的值
   - 或设置环境变量 `GROQ_API_KEY`

使用：`python asr.py <audio> --backend groq --lang zh`

## SiliconFlow SenseVoice（中文优秀，有免费额度）

1. 注册 https://cloud.siliconflow.cn
2. 创建 API key，设置环境变量 `SILICONFLOW_API_KEY`

使用：`python asr.py <audio> --backend siliconflow`

## 任意 OpenAI 兼容端点

设置三个环境变量后用 `--backend custom`：

```bash
ASR_BASE_URL=https://your-endpoint.com/v1
ASR_API_KEY=sk-xxx
ASR_MODEL=whisper-large-v3
```

## 字幕获取（B站官方CC/AI字幕需要登录）

fetch.py 会自动尝试 edge→chrome→firefox 的浏览器 cookies。若都失败：

1. 浏览器装扩展 "Get cookies.txt LOCALLY"，登录 B站后导出 `.cookies.txt`
2. 保存为 `~/.pi/bili-cookies.txt`（或任意路径，用 `--cookies <路径>` 传入）
3. 重跑 fetch.py

> 注：Chrome v127+ 的 DPAPI 加密和运行中的 Edge 会导致读取失败，cookies.txt 文件方式最稳。

## 翻译 LLM 后端

translate.py 自动按顺序尝试（key 从 `~/.pi/agent/auth.json` 读取）：

1. OpenRouter `z-ai/glm-5.2:free`（免费模型，偶尔限流）
2. DeepSeek `deepseek-chat`（极便宜，约 ¥0.001/视频）
3. Moonshot（kimi）

可用 `--backend deepseek` 强制指定，或 `--model` 换模型。

## 限流说明（必剪公益接口）

- 12 小时窗口内：最多 100 次调用、最多 6 小时音频
- asr.py 自动跟踪用量（`~/.bili-notes/.bcut_usage.json`），超限时报错并提示
- 一个 2 小时视频 ≈ 14 块调用 ≈ 2.4 小时音频额度，日常使用充裕
