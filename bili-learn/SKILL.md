---
name: bili-learn
description: 哔哩哔哩视频深度学习工作流。发送 B站/YouTube 视频链接即可完成：抓取元数据与官方字幕 → 下载音频 → 必剪(Bcut)免费云ASR转写带时间戳文字稿 → LLM生成双语字幕 → 自动产出学习笔记（要点总结、章节大纲、思维导图 markmap、概念图、术语表、主动回忆测验）。转录完全免费无需API key（B站必剪接口，参考 VideoCaptioner 项目）。触发词：B站视频、哔哩哔哩、bilibili链接、看视频学习、视频转文字、视频总结、视频笔记、字幕、转写、transcribe、video notes。
---

# Bili-Learn — B站视频学习工作流

把一个视频链接变成一套可复习的学习资料：**文字稿 → 双语字幕 → 笔记 → 思维导图 → 测验**。

转录使用 B站必剪(Bcut)免费云 ASR 接口（无需任何 API key，参考
[VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner)），Groq/SiliconFlow 作为备用后端。

## 总流程（收到视频链接后按序执行）

```
链接 → ① fetch.py 抓取 → ② 判断字幕来源 → ③ 转写/转录 → ④ 双语字幕 → ⑤ 学习笔记
```

所有产物落在 `~/bili-notes/<视频id>/`。每步的 stdout 都是 JSON 摘要，据此决定下一步。

---

## ① 抓取视频资源

```bash
python <skill>/scripts/fetch.py "<URL>" [--danmaku]
```

- 自动获取：元数据(info.json)、封面(cover.jpg)、官方CC/AI字幕(subs/*.srt)、音频(audio.m4a)
- 字幕需登录才能拿到时会自动尝试浏览器 cookies（edge→chrome→firefox）；也可用 `--cookies 文件`
- `--danmaku` 额外下载弹幕（可选，用于分析观众关注点）

**读 stdout JSON，走分支判断：**

| subs_found | 处理 |
|---|---|
| 有 .srt | ✅ 跳过转录，直接用官方字幕（转 srt 统一命名 `transcript.srt`，若只有英文字幕则中文需走②） |
| 无字幕 + 有音频 | → 执行 ② ASR 转写 |
| 无字幕无音频 | 报错：需登录（让用户提供 cookies）或链接失效 |

## ② ASR 转写（必剪免费接口，无 key）

```bash
python <skill>/scripts/asr.py <audio.m4a路径> --out <视频目录> --backend auto
```

- 默认后端 `bcut`：B站必剪云 ASR，免费无 key，中文识别优秀，毫秒级时间戳
- 自动分块（10分钟/块 + 10秒重叠）+ 并发上传 + 边界去重合并
- 公益接口限流（100次/12h、音频6小时/12h）已自动跟踪；超限时换 `--backend groq`（需配 key，见 setup.md）
- 输出：`transcript.srt`（带时间戳）、`transcript.txt`（纯文字稿）、`transcript.json`（结构化）

## ③ 双语字幕

```bash
python <skill>/scripts/translate.py <视频目录>/transcript.srt --target en [--pure]
```

- LLM 后端自动发现：OpenRouter 免费模型 → DeepSeek（备用），key 从 `~/.pi/agent/auth.json` 读
- 输出 `transcript.bilingual.srt`（中英对照，可直接导入 PotPlayer/MPV/Obsidian）
- `--pure` 同时输出纯英文 `transcript.en.srt`；`--target ja` 可换目标语言

## ④ 学习笔记（agent 自己生成，不用 API）

**先读** `info.json`（标题/UP主/简介/章节）和 `transcript.txt`（长视频读 json 的前 N 段 + 章节附近段落，控制在合理上下文内）。
**然后写 `notes.md`**，结构如下（按视频实际内容裁剪，空章节省略）：

```markdown
---
title: <视频标题>
source: <URL>
uploader: <UP主>
duration: <时长>
date: <YYYY-MM-DD（处理日期）>
tags: [bili-notes, <领域标签>...]
---

# <视频标题>

> [!abstract] 一句话总结
> 30字以内说清这个视频讲了什么。

## 📌 核心要点（3-7条）
- 每条一句话，标注时间点如 `⏱ 12:34`（从 transcript.srt 换算）

## 🗺 章节脉络
按视频实际章节（info.json 的 chapters）或内容逻辑划分，每章 2-3 句概括 + 时间戳

## 🔑 关键概念/术语表
| 术语 | 解释 | 首次出现 |
|---|---|---|
（专业术语、易混淆概念）

## 💡 金句/值得记住的话
> 原话 ⏱ MM:SS

## ❓ 主动回忆测验（答案折叠）
1. 问题……
   - [答案] 要点……
（5-10 个问题，覆盖核心要点，基于视频内容）

## 🔗 延伸
- 相关视频/概念链接（如有）
- 原始资料：[[transcript.srt]] · [[transcript.bilingual.srt]]
```

**再写 `mindmap.md`**（markmap 兼容，粘贴到 https://markmap.js.org/repl 或 Obsidian Markmap 插件即可渲染）：

```markdown
---
markmap:
  colorFreezeLevel: 2
---
# <中心主题>
## <分支1>
### <子点>
## <分支2>
（3层以内，提炼关键词而非整句）
```

**长视频策略**（>40分钟）：先按 `transcript.json` 的时间戳分章节读，逐章总结，最后汇总；笔记每章一条脉络。

## ⑤ 收尾汇报

全部完成后向用户报告：视频标题、时长、各产物路径清单（transcript.srt / bilingual.srt / notes.md / mindmap.md）、
转录后端与耗时、笔记要点速览（3条以内）。

---

## 配置与故障排查

- 免费转录无需任何配置。备用后端（Groq whisper 等）配置见 [references/setup.md](references/setup.md)
- bcut 限流（12h 窗口超 100 次或 6 小时音频）→ 提示用户稍后再用或配置 Groq
- 字幕拿不到（未登录）→ 让用户从浏览器导出 cookies.txt 放到 `~/.pi/bili-cookies.txt`，重跑 fetch.py
- 音频下载失败 → 检查是否会员专享视频（需大会员 cookies）
- 弹幕分析（可选）：`danmaku.xml` 中高频词/密集时段可补充到笔记"观众关注点"

## 边界

- 只处理用户给的视频链接，不自动批量爬取
- 转写大文件耗时：约 1 分钟处理 20-30 分钟音频（bcut 并发）
- 生成笔记前必须实际读取文字稿，禁止凭标题/简介编造内容
