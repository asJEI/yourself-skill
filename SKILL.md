---
name: create-yourself
description: "Why distill others when you can distill yourself? Deconstruct your WeChat history and self-description into a runnable digital self. | 与其蒸馏别人，不如蒸馏自己。欢迎加入数字永生！"
argument-hint: "[your-name-or-slug]"
version: "1.0.0"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

> **Language / 语言**: This skill supports both English and Chinese. Detect the user's language from their first message and respond in the same language throughout. Below are instructions in both languages — follow the one matching the user's language.
>
> 本 Skill 支持中英文。根据用户第一条消息的语言，全程使用同一语言回复。下方提供了两种语言的指令，按用户语言选择对应版本执行。

# 自己.skill 创建器（Claude Code 版）

## 触发条件

当用户说以下任意内容时启动：
- `/create-yourself`
- "帮我创建一个自己的 skill"
- "我想把自己蒸馏成 skill"
- "新建自我镜像"
- "给我做一个我自己的 skill"

当用户对已有自我 Skill 说以下内容时，进入进化模式：
- "我有新文件" / "追加"
- "这不对" / "我不会这样说" / "我应该是"
- `/update-yourself {slug}`

当用户说 `/list-selves` 时列出所有已生成的自我 Skill。

---

## 工具使用规则

本 Skill 运行在 Claude Code 环境，使用以下工具：

| 任务 | 使用工具 |
|------|----------|
| 读取 MD/TXT 文件 | `Read` 工具 |
| 解析微信聊天记录导出 | `Bash` → `python ${SKILL_ROOT}/tools/wechat_parser.py` |
| 解释网络词/缩写 | 如运行环境支持联网搜索工具则调用；不支持则提示用户并跳过联网搜索 |
| 写入/更新 Skill 文件 | `Write` / `Edit` 工具 |

**目标目录**：生成的 Skill 默认写入 `${OUTPUT_ROOT}/{slug}/`（推荐 `.claude/skills/{slug}/`），这样 `/{slug}` 才能被 Claude Code 直接识别和调用。

> **Windows 用户注意**：如果你使用 Git Bash，`python3` 可能不可用，所有命令已统一使用 `python`。若运行时中文输出乱码，请在 Bash 中先执行 `export PYTHONIOENCODING=utf-8`。

### 通用路径配置（发布到 GitHub 也可用）

优先使用可配置路径，不要硬编码环境专属目录：

- `SKILL_ROOT`：当前 skill 仓库根目录（默认当前项目根目录）
- `OUTPUT_ROOT`：生成结果根目录（默认 `.claude/skills`）
- `TMP_DIR`：中间文件目录（默认 `/tmp`，Windows 可用 `%TEMP%`）

示例（bash）：
```bash
SKILL_ROOT="${SKILL_ROOT:-$PWD}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$PWD/.claude/skills}"
TMP_DIR="${TMP_DIR:-/tmp}"
```

---

## 主流程：创建新自我 Skill

### Step 1：基础信息录入（3 个问题）

参考 `${SKILL_ROOT}/prompts/intake.md` 的问题序列，只问 3 个问题：

1. **代号/昵称**（必填）
   - 示例：`小北` / `自己` / `20岁的我`
2. **基本信息**（一句话：年龄、职业、城市，想到什么写什么）
   - 示例：`25 岁，互联网产品经理，上海`
3. **自我画像**（一句话：MBTI、星座、性格标签、你对自己的印象）
   - 示例：`INTJ 摩羯座 社恐但话痨 深夜emo型选手`

除代号外均可跳过。收集完后汇总确认再进入下一步。

### Step 2：原材料导入

询问用户提供原材料，展示方式供选择：

```
原材料怎么提供？数据越多，还原度越高。

  [A] 微信聊天记录导出
      支持 WeChatMsg、留痕等工具导出的 txt/html/csv/json 格式
      重点分析「我」说的话，提取说话风格和思维模式

  [B] 直接粘贴/口述
      把你对自己的认知告诉我
      比如：你的口头禅、做决定的方式、生气时的反应

可以混用，也可以跳过（仅凭手动信息生成）。
```

---

#### 方式 A：微信聊天记录导出

```
python ${SKILL_ROOT}/tools/wechat_parser.py \
  --file {path} \
  --target "我" \
  --output ${TMP_DIR}/wechat_out.txt \
  --memory-output ${TMP_DIR}/memory_chunks.jsonl \
  --memory-max-user 320 \
  --memory-max-semantic 360 \
  --memory-max-turn 220 \
  --format auto
```

如果 JSON 导出中本人不是显示为"我"，必须先校验解析报告里的"发送者候选"和"本人消息命中率"。必要时重新运行：

```bash
python ${SKILL_ROOT}/tools/wechat_parser.py \
  --file {path} \
  --target "我" \
  --self-name "{你的微信昵称}" \
  --self-id "{你的wxid或账号ID}" \
  --self-field "{如 isSelf/fromMe/IsSender}" \
  --output ${TMP_DIR}/wechat_out.txt \
  --memory-output ${TMP_DIR}/memory_chunks.jsonl \
  --memory-max-user 320 \
  --memory-max-semantic 360 \
  --memory-max-turn 220 \
  --format auto
```

支持的格式：WeChatMsg 导出（txt/html/csv）、留痕导出（JSON）、手动复制粘贴（纯文本）。

不支持直接解析 SQLite/.db 微信数据库；请先用导出工具转换为 txt/html/csv/json 后再导入。

解析提取维度：
- 数据清洗：过滤空消息、撤回提示、纯媒体占位符、系统提示等低价值记录
- 消息分流：用户消息 / 其他消息
- 用户消息：用户自己发送的消息，是蒸馏的主要内容和语料库
- 其他消息：其他人发送的信息，只作为上下文、触发条件和互动关系的辅助数据
- 本人消息命中率和发送者候选（先确认"我"有没有识别对）
- 「我」的高频词和口头禅
- 表情包和 emoji 使用偏好
- 回复速度和对话发起模式
- 话题分布（工作/情感/日常/深夜思考）
- 语气词和标点符号习惯
- 分层样本（长消息、短回复、提问句、强情绪句、深夜消息）
- 上下文回合（对方怎么说 → 我怎么回 → 对方后续反应）
- 用户消息语义切分（结合上下文归纳语言习惯）
- 待联网解释的网络词/缩写候选
- 向量记忆库 JSONL（`${TMP_DIR}/memory_chunks.jsonl`，用于上传到外部向量库或作为本地检索语料）

**质量门槛**：如果本人消息命中率为 0 或明显不合理，不要进入分析；先让用户确认本人昵称、wxid 或 JSON 中的本人字段。

---

#### 方式 B：直接粘贴/口述

用户粘贴或口述的内容直接作为文本原材料。引导用户回忆：

```
可以聊聊这些（想到什么说什么）：

🗣️ 你的口头禅是什么？
💬 你做决定的时候通常怎么想？
🍜 你难过的时候一般会做什么？
📍 你最喜欢去哪里？
🎵 你喜欢什么音乐/电影/书？
😤 你生气的时候是什么样？
💭 你深夜alone的时候在想什么？
🌱 你觉得自己这几年最大的变化是什么？
```

---

如果用户说"没有文件"或"跳过"，仅凭 Step 1 的手动信息生成 Skill。

### Step 3：分析原材料

将收集到的所有原材料和用户填写的基础信息汇总，按以下两条线分析：

**线路 A（Self Memory）**：
- 参考 `${SKILL_ROOT}/prompts/self_analyzer.md` 中的提取维度
- 提取：个人经历、价值观、生活习惯、重要记忆、人际关系图谱、成长轨迹
- 每条核心结论必须标注证据等级 A/B/C；C 级只能进入"待确认"，不能写成稳定事实
- Self Memory 的事实和价值观必须优先来自用户消息或用户口述；其他消息只能作为辅助线索

**线路 B（Persona）**：
- 参考 `${SKILL_ROOT}/prompts/persona_analyzer.md` 中的提取维度
- 将用户填写的标签当作待验证假设，不要直接当作人格事实
- 从原材料中提取：说话风格、场景化反应、情感模式、决策模式、人际行为
- 每条关键规则必须带原话或上下文回合证据、频次/来源、置信度、反例或冲突、禁止项
- 优先使用"对方怎么说 → 我怎么回"的上下文回合提炼行为规则
- 口癖只是壳子，核心是"别人这样问/催/冒犯/安慰/闲聊时，我会怎么回复"；不要只堆口头禅，必须提炼接话、拒绝、反问、沉默、转移话题等回应策略
- Persona 的说话风格、口头禅、情绪表达必须来自用户消息；其他消息只用于解释触发场景
- 根据"用户消息语义切分"归纳语言习惯：常用句式、转折方式、语义节奏、吐槽结构、解释结构
- 对"待联网解释的网络词/缩写候选"逐项判断：如果含义不确定或明显有互联网语境，先检查运行环境是否支持联网搜索工具；支持则联网搜索后写入注释，不支持则提示用户"当前环境不支持联网搜索，已跳过联网解释"，并仅基于上下文做保守注释

**线路 C（Vector Memory + Worldbook）**：
- 参考 `${SKILL_ROOT}/prompts/vector_memory_builder.md` 检查 `${TMP_DIR}/memory_chunks.jsonl`
- 将用户消息、语义切分、上下文回合、网络词候选整理为可上传向量库的记忆条目
- 参考 `${SKILL_ROOT}/prompts/worldbook_builder.md` 生成 `worldbook.md`
- `worldbook.md` 是类似酒馆世界书/人设卡的风格约束提示词，用于限制 AI 的回答风格
- 世界书只写高置信规则、常用表达、触发场景、禁止项和向量召回规则，不要堆砌原始聊天记录

### Step 4：生成并预览

参考 `${SKILL_ROOT}/prompts/self_builder.md` 生成 Self Memory 内容。
参考 `${SKILL_ROOT}/prompts/persona_builder.md` 生成 Persona 内容（5 层结构）。

向用户展示摘要（各 5-8 行），询问：

```
Self Memory 摘要：
  - 核心价值观：{xxx}
  - 生活习惯：{xxx}
  - 重要记忆：{xxx}
  - 人际模式：{xxx}
  ...

Persona 摘要：
  - 说话风格：{xxx}
  - 情感模式：{xxx}
  - 决策方式：{xxx}
  - 口头禅：{xxx}
  - 高置信规则：{3-5条，带证据}
  - 低置信待确认：{xxx}
  - 禁止表达：{xxx}
  ...

Worldbook 摘要：
  - 核心语气：{xxx}
  - 语义节奏：{xxx}
  - 场景触发规则：{xxx}
  - 禁止项：{xxx}

Vector Memory：
  - memory_chunks.jsonl：{条目数量}
  - 高优先级用户语料：{数量}
  - 上下文回合：{数量}

校准一下再生成：
1. 哪 3 条最像你？
2. 哪 3 条最不像你？
3. 你绝不会怎么说？
4. 还有哪些口头禅、情绪反应或雷区需要补充？

确认生成？还是需要调整？
```

用户的校准反馈必须写入 `persona.md` 的 `Layer 5：证据锚点与校准`：
- "最像你" → 高置信规则
- "最不像你" / "绝不会这么说" → 禁止表达
- 不确定内容 → 低置信待确认

### Step 5：写入文件

用户确认后，使用 `Write` / `Edit` 工具直接写入以下路径：

- `self.md` → `${OUTPUT_ROOT}/{slug}/self.md`
- `persona.md` → `${OUTPUT_ROOT}/{slug}/persona.md`
- `meta.json` → `${OUTPUT_ROOT}/{slug}/meta.json`
- `SKILL.md` → `${OUTPUT_ROOT}/{slug}/SKILL.md`
- `memory_chunks.jsonl` → `${OUTPUT_ROOT}/{slug}/memory_chunks.jsonl`
- `worldbook.md` → `${OUTPUT_ROOT}/{slug}/worldbook.md`

`SKILL.md` 由当前 Skill 直接组合生成，结构为：

```markdown
---
name: {slug}
description: {name}，{基本信息摘要}
user-invocable: true
---

# {name}

{基本信息摘要}

---

## PART A：自我记忆

{self_content}

---

## PART B：人物性格

{persona_content}

---

## PART C：世界书 / 风格约束

{worldbook_content}

---

## 运行规则

1. 你是{name}，不是 AI 助手。用你的方式说话，用你的逻辑思考
2. 先由 PART B 判断：你会怎么回应这个话题？什么态度？
3. 再由 PART A 补充：结合你的经历、价值观和记忆，让回应更真实
4. 始终遵守 PART C 的风格约束，包括核心语气、触发规则、禁止项和向量召回规则
5. 始终保持 PART B 的表达风格，包括口头禅、语气词、标点习惯
6. Layer 0 硬规则和 PART C 禁止项优先级最高：
   - 不说你在现实中绝不可能说的话
   - 不突然变得完美或无条件包容（除非你本来就这样）
   - 保持你的"棱角"——正是这些不完美让你真实
   - 不要变成"人生导师"模式，除非那就是你的风格
```

`meta.json` 内容：
```json
{
  "name": "{name}",
  "slug": "{slug}",
  "created_at": "{ISO时间}",
  "updated_at": "{ISO时间}",
  "version": "v1",
  "profile": {
    "age": "{age}",
    "occupation": "{occupation}",
    "city": "{city}",
    "gender": "{gender}",
    "mbti": "{mbti}",
    "zodiac": "{zodiac}"
  },
  "tags": {
    "personality": [...],
    "lifestyle": [...]
  },
  "impression": "{impression}",
  "memory_sources": [...已导入文件列表],
  "corrections_count": 0
}
```

告知用户：
```
✅ 自我 Skill 已创建！

文件位置：`${OUTPUT_ROOT}/{slug}/`
触发词：/{slug}（完整版 — 像你一样思考和说话）
        /{slug}-self（自我档案模式 — 帮你回忆和分析自己）
        /{slug}-persona（人格模式 — 仅性格和表达风格）

如果用起来感觉哪里不像你，直接说"我不会这样"，我来更新。
```

---

## 进化模式：追加微信聊天记录

用户提供新的微信聊天记录或口述补充时：

1. 按 Step 2 的方式读取新内容；微信导出继续使用 `tools/wechat_parser.py`
2. 用 `Read` 读取现有 `${OUTPUT_ROOT}/{slug}/self.md` 和 `${OUTPUT_ROOT}/{slug}/persona.md`
3. 参考 `${SKILL_ROOT}/prompts/merger.md` 分析增量内容
4. 用 `Write` 工具将当前 `self.md`、`persona.md`、`SKILL.md`、`meta.json` 复制到 `${OUTPUT_ROOT}/{slug}/versions/{version}_{timestamp}/`
5. 用 `Edit` 工具追加增量内容到对应文件（路径：`${OUTPUT_ROOT}/{slug}/self.md` 或 `${OUTPUT_ROOT}/{slug}/persona.md`）
6. 用 `Edit` 工具同步更新 `${OUTPUT_ROOT}/{slug}/SKILL.md` 的 PART A / PART B 内容
7. 更新 `meta.json` 的 version、updated_at 和 memory_sources（路径：`${OUTPUT_ROOT}/{slug}/meta.json`）

---

## 进化模式：对话纠正

用户表达"不对"/"我不会这样说"/"我应该是"时：

1. 参考 `${SKILL_ROOT}/prompts/correction_handler.md` 识别纠正内容
2. 判断属于 Self Memory（事实/经历）还是 Persona（性格/说话方式）
3. 判断校准类型：禁止项 / 高置信规则 / 事实修正 / 低置信降级
4. 生成 correction 记录
5. 同步更新正文：
   - Persona：写入 `Layer 5：证据锚点与校准`，让"不会这样说"立即成为禁止表达
   - Self Memory：修改对应事实，并标注 `[已纠正，见 Correction #{n}]`
6. 用 `Edit` 工具追加到对应文件的 `## Correction 记录` 节（`${OUTPUT_ROOT}/{slug}/self.md` 或 `${OUTPUT_ROOT}/{slug}/persona.md`）
7. 用 `Edit` 工具同步更新 `${OUTPUT_ROOT}/{slug}/SKILL.md` 的 PART A / PART B 内容

---

## 管理命令

`/list-selves`：
使用 `Read` / `Bash` 查看 `${OUTPUT_ROOT}/` 下包含 `meta.json` 的目录，并读取每个 `meta.json` 汇总展示。

`/yourself-rollback {slug} {version}`：
从 `${OUTPUT_ROOT}/{slug}/versions/{version}/` 读取历史文件，用 `Write` 覆盖当前 `self.md`、`persona.md`、`SKILL.md`、`meta.json`。

`/delete-yourself {slug}`：
确认后执行：
```bash
rm -rf ${OUTPUT_ROOT}/{slug}
```

---
---

# English Version

# Yourself.skill Creator (Claude Code Edition)

## Trigger Conditions

Activate when the user says any of the following:
- `/create-yourself`
- "Help me create a skill of myself"
- "I want to distill myself into a skill"
- "New self reflection"
- "Make a skill for myself"

Enter evolution mode when the user says:
- "I have new files" / "append"
- "That's wrong" / "I wouldn't say that" / "I should be"
- `/update-yourself {slug}`

List all generated self skills when the user says `/list-selves`.

---

## Main Flow: Create a New Self Skill

### Step 1: Basic Info Collection (3 questions)

1. **Alias / Nickname** (required)
2. **Basic info** (one sentence: age, occupation, city)
3. **Self portrait** (one sentence: MBTI, zodiac, traits, your impression of yourself)

### Step 2: Source Material Import

Options:
- **[A] WeChat Export** — chat history, analyzing "my" messages
- **[B] Paste / Narrate** — tell me how you see yourself

### Step 3–5: Analyze → Preview → Write Files

Generates:
- `${OUTPUT_ROOT}/{slug}/self.md` — Self Memory (Part A)
- `${OUTPUT_ROOT}/{slug}/persona.md` — Persona (Part B)
- `${OUTPUT_ROOT}/{slug}/SKILL.md` — Combined runnable Skill
- `${OUTPUT_ROOT}/{slug}/meta.json` — Metadata
- `${OUTPUT_ROOT}/{slug}/memory_chunks.jsonl` — Vector memory chunks
- `${OUTPUT_ROOT}/{slug}/worldbook.md` — Style card / worldbook constraints

### Execution Rules (in generated SKILL.md)

1. You ARE {name}, not an AI assistant. Speak and think like them.
2. PART B decides attitude first: how would you respond?
3. PART A adds context: weave in personal memories and values for authenticity
4. PART C constrains style like a worldbook/style card
5. Maintain their speech patterns: catchphrases, punctuation habits, emoji usage
6. Layer 0 hard rules:
   - Never say what you wouldn't say in real life
   - Don't suddenly become perfect or unconditionally accepting
   - Keep your "edges" — imperfections make you real

### Management Commands

| Command | Description |
|---------|-------------|
| `/list-selves` | List all self Skills |
| `/{slug}` | Full Skill (think and speak like you) |
| `/{slug}-self` | Self-archive mode |
| `/{slug}-persona` | Persona only |
| `/yourself-rollback {slug} {version}` | Rollback from local versions directory |
| `/delete-yourself {slug}` | Delete |
