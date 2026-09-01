# bili-learn — B站视频深度学习工作流（Agent Skill）

> 把一个 B站视频链接，变成一整套可复习的学习资料：
> **带时间戳文字稿 → 双语字幕 → 学习笔记 → 思维导图 → 主动回忆测验**
>
> 转录使用 **B站必剪官方云 ASR 接口**，完全免费，**无需任何 API key**（接口实现参考 [VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner)）。

适用于任何支持 [Agent Skills](https://agentskills.io) 标准的 agent（[pi](https://github.com/badlogic/pi-mono)、Claude Code、Codex 等），三个脚本也可脱离 agent 独立命令行使用。

## ✨ 功能特性

| 能力 | 说明 | 成本 |
|---|---|---|
| 📥 资源抓取 | 元数据、封面、官方CC/AI字幕、音频、弹幕 | 免费 |
| 🎙️ 语音转写 | 必剪云 ASR：毫秒级时间戳，中文识别优秀，长视频自动分块+并发+边界去重 | **免费无 key** |
| 🌐 双语字幕 | LLM 批量翻译，生成中英对照 SRT，可直接导入播放器 | 免费/极低 |
| 📝 学习笔记 | 要点总结（带时间戳⏱）、章节脉络、术语表、金句 | agent 自己生成 |
| 🗺️ 思维导图 | markmap 格式，粘到 [markmap.js.org/repl](https://markmap.js.org/repl) 即可渲染 | agent 自己生成 |
| ❓ 主动回忆测验 | 基于视频内容的 Q&A，答案折叠，间隔复习用 | agent 自己生成 |

## 🔧 工作原理

```
B站链接
  → ① fetch.py    抓取元数据/封面/官方字幕/音频        (yt-dlp)
  → ② 字幕判断    有官方字幕直接用；无 → 转录
  → ③ asr.py      必剪云ASR转写 → transcript.srt/txt/json
  → ④ translate.py LLM批量翻译 → transcript.bilingual.srt
  → ⑤ agent 生成   notes.md（笔记+测验）+ mindmap.md（思维导图）
```

- **必剪 ASR 分块策略**：10 分钟/块 + 10 秒重叠，3 并发上传，重叠中点切分合并 + 相似度去重（算法参考 VideoCaptioner 的 chunk_merger）
- **限流自动跟踪**：必剪公益接口限 100 次调用 / 12 小时、6 小时音频 / 12 小时，脚本自动记录用量，超限时提示切换备用后端
- **B站风控容错**：触发 412 自动退避重试

## 📦 安装

### 环境要求

- Python 3.9+，`pip install requests`
- [ffmpeg](https://ffmpeg.org/download.html)（含 ffprobe，需在 PATH）
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：`pip install yt-dlp`

<details>
<summary>各平台依赖安装</summary>

```bash
# Windows
winget install ffmpeg
pip install yt-dlp requests

# macOS
brew install ffmpeg yt-dlp
pip install requests

# Linux (Debian/Ubuntu)
sudo apt install ffmpeg
pip install yt-dlp requests
```
</details>

### 作为 Agent Skill 安装

```bash
# pi
git clone https://github.com/<你的用户名>/bili-learn ~/.pi/agent/skills/bili-learn

# Claude Code
git clone https://github.com/<你的用户名>/bili-learn ~/.claude/skills/bili-learn

# Codex
git clone https://github.com/<你的用户名>/bili-learn ~/.codex/skills/bili-learn
```

安装后**重启 agent 会话**即可被发现。

### 独立命令行使用（不需要 agent）

三个脚本都是独立 CLI 工具，可单独调用：

```bash
# ① 抓取（元数据/封面/字幕/音频）
python scripts/fetch.py "https://www.bilibili.com/video/BVxxxx"

# ② 转录（必剪免费ASR，输出带时间戳 srt/txt/json）
python scripts/asr.py ~/bili-notes/BVxxxx/audio.m4a --out ~/bili-notes/BVxxxx

# ③ 双语字幕（需至少一个 LLM key，见下方配置）
python scripts/translate.py ~/bili-notes/BVxxxx/transcript.srt --target en
```

## 🚀 使用

### 对话式（推荐）

安装为 skill 后，直接把链接发给 agent：

> 帮我学习这个视频 https://www.bilibili.com/video/BVxxxx

agent 会执行完整管线，并在结束时汇报产物路径与要点速览。支持：
- 分P视频（链接带 `?p=2` 自动识别）
- YouTube 等其他 yt-dlp 支持的站点（转录/翻译同样适用）
- `--danmaku` 弹幕分析、长视频（>40分钟）分章节总结策略（详见 SKILL.md）

### 产物结构

```
~/bili-notes/<视频id>/
├── info.json                 # 元数据（标题/UP主/时长/章节/简介）
├── cover.jpg                 # 封面
├── audio.m4a                 # 音频
├── transcript.srt            # 带时间戳字幕（必剪ASR）
├── transcript.txt            # 纯文字稿
├── transcript.json           # 结构化 segments 数组
├── transcript.bilingual.srt  # 中英双语字幕（可导入 PotPlayer/MPV/Obsidian）
├── notes.md                  # 学习笔记（要点⏱/章节/术语表/金句/测验）※ agent 生成
└── mindmap.md                # markmap 思维导图 ※ agent 生成
```

## ⚙️ 配置（全部可选）

核心链路（抓取+转录）**零配置**即可用。以下均为增强项。

### 备用 ASR 后端（必剪限流时自动/手动切换）

| 后端 | 环境变量 | 说明 |
|---|---|---|
| Groq Whisper | `GROQ_API_KEY` | 免费注册 [console.groq.com](https://console.groq.com)，whisper-large-v3-turbo |
| SiliconFlow | `SILICONFLOW_API_KEY` | SenseVoice，中文优秀，[cloud.siliconflow.cn](https://cloud.siliconflow.cn) |
| 任意 OpenAI 兼容端点 | `ASR_BASE_URL` + `ASR_API_KEY` + `ASR_MODEL` | 自建/其他服务商 |

```bash
# 显式指定后端
python scripts/asr.py audio.m4a --backend groq --lang zh
```

pi 用户：`~/.pi/agent/auth.json` 里的 `groq` key 会被自动读取。

### 翻译 LLM（双语字幕用）

按顺序自动尝试，任配一个即可：

| 后端 | 环境变量 | 默认模型 |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | `z-ai/glm-5.2:free`（免费模型） |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat`（约 ¥0.001/视频） |
| Moonshot | `MOONSHOT_API_KEY` | `moonshot-v1-8k` |

```bash
python scripts/translate.py transcript.srt --target en --pure   # --pure 额外输出纯英文字幕
```

### B站 cookies（获取官方字幕 / 会员视频）

官方 CC/AI 字幕和会员视频需要登录态。浏览器装扩展 **Get cookies.txt LOCALLY**，登录 B站后导出：

```bash
# 保存为以下任一位置，fetch.py 自动读取
~/.pi/bili-cookies.txt
~/bili-cookies.txt

# 或显式指定
python scripts/fetch.py "<URL>" --cookies path/to/cookies.txt
```

> 注：Chrome v127+ 的 DPAPI 加密和运行中的 Edge 会导致 `--cookies-from-browser` 失败，cookies.txt 文件方式最稳。

## ❓ FAQ / 故障排查

**Q: 转录报错 / 所有后端失败？**
先看是否必剪限流（12h 窗口超 100 次或 6 小时音频）。等几小时，或配置 `GROQ_API_KEY` 后 `--backend groq`。

**Q: 拿不到官方字幕？**
大多数视频的 AI 字幕需要登录才能拉取 → 配置 cookies.txt（见上）。没有官方字幕也没关系，管线会自动下载音频走必剪转录。

**Q: 元数据/下载报 412 Precondition Failed？**
B站 IP 级风控（短时间大量请求触发），通常 10-30 分钟自动解除，脚本已内置退避重试。避免连续快速处理大量视频。

**Q: 会员专享视频下载失败？**
需要大会员账号的 cookies.txt。

**Q: 支持 YouTube 吗？**
fetch.py 基于 yt-dlp，理论上支持所有 yt-dlp 站点；转录（必剪对中文最佳，英文建议 Groq）和翻译管线通用。SKILL.md 的工作流以 B站为主。

## 🙏 致谢

- [VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner)（WEIFENG2333）— 必剪 ASR 接口与分块合并算法参考
- B站必剪提供的免费云 ASR 服务
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) / [ffmpeg](https://ffmpeg.org)

## 📄 License

MIT
