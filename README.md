# 自己.skill

> 与其蒸馏别人，不如蒸馏自己。欢迎加入数字永生。

## 声明：
本项目是基于https://github.com/notdog1998/yourself-skill 仓库的自用skills，主要修改点为：删除了除微信外的上传途径，同时优化提示词使agent更侧重于学习理解用户的回复方式而不是单纯的输出用户口癖。并且优化记忆库筛选，会自动删去无意义低质量的聊天内容

`create-yourself` 是一个运行在 Cursor / Claude Code 场景中的自我蒸馏 Skill：
- 输入你的微信聊天记录与自我描述
- 生成可运行的 `Self Memory + Persona` 数字副本
- 同步产出 `memory_chunks.jsonl` 用于向量检索召回

---

## 快速开始

### 1) 安装

在仓库根目录执行：

```bash
mkdir -p .claude/skills
git clone https://github.com/asJEI/yourself-skill .claude/skills/create-yourself
```

或全局安装：

```bash
git clone https://github.com/asJEI/yourself-skill ~/.claude/skills/create-yourself
```

---

## 通用路径配置（推荐）

为了兼容不同用户下载到任意目录后直接可用，建议统一使用以下环境变量：

- `SKILL_ROOT`：skill 仓库根目录
- `OUTPUT_ROOT`：生成的 skill 输出目录
- `TMP_DIR`：中间文件目录

### Bash / zsh

```bash
export SKILL_ROOT="${SKILL_ROOT:-$PWD}"
export OUTPUT_ROOT="${OUTPUT_ROOT:-$PWD/.claude/skills}"
export TMP_DIR="${TMP_DIR:-/tmp}"
```

### PowerShell

```powershell
$env:SKILL_ROOT = if ($env:SKILL_ROOT) { $env:SKILL_ROOT } else { (Get-Location).Path }
$env:OUTPUT_ROOT = if ($env:OUTPUT_ROOT) { $env:OUTPUT_ROOT } else { (Join-Path (Get-Location).Path ".claude/skills") }
$env:TMP_DIR = if ($env:TMP_DIR) { $env:TMP_DIR } else { $env:TEMP }
```

---

## 使用

在对话中触发：

```text
/create-yourself
```

按提示填写：
1. 代号/昵称（必填）
2. 基本信息（可选）
3. 自我画像（可选）

然后选择数据源：
- 微信导出（txt/html/csv/json）
- 直接粘贴/口述

完成后通过 `/{slug}` 调用生成的自我 Skill。

---

## 微信解析与向量记忆（推荐命令）

```bash
python "${SKILL_ROOT}/tools/wechat_parser.py" \
  --file "{path}" \
  --target "我" \
  --output "${TMP_DIR}/wechat_out.txt" \
  --memory-output "${TMP_DIR}/memory_chunks.jsonl" \
  --memory-max-user 320 \
  --memory-max-semantic 360 \
  --memory-max-turn 220 \
  --memory-max-term 60 \
  --format auto
```

若本人昵称不是“我”，可补充：
- `--self-name`
- `--self-id`
- `--self-field`

---

## 当前解析器能力

- 自动过滤低价值内容（系统提示、媒体占位、纯符号水词等）
- 生成可上传向量库的 `memory_chunks.jsonl`
- chunk 元数据补充语义标签：
  - `catchphrase_tags`
  - `topic_tags`
  - `scene_tags`
  - `emotion_tags`
- 支持可配置 chunk 上限，提升大样本召回覆盖率
- 输出覆盖统计（类型占比、主题/场景覆盖）

---

## 输出结构

默认输出到 `${OUTPUT_ROOT}/{slug}/`：

- `SKILL.md`：可直接调用的完整 Skill
- `self.md`：自我记忆（Part A）
- `persona.md`：人格模型（Part B）
- `worldbook.md`：风格约束（Part C）
- `memory_chunks.jsonl`：向量检索语料
- `meta.json`：元数据
- `versions/`：版本快照

---

## 管理命令

- `/list-selves`：列出已生成的自我 Skill
- `/{slug}`：完整模式（像你一样思考与表达）
- `/{slug}-self`：自我档案模式
- `/{slug}-persona`：人格表达模式
- `/yourself-rollback {slug} {version}`：回滚版本
- `/delete-yourself {slug}`：删除

---

## 适配格式

支持：
- WeChatMsg 导出：`txt/html/csv`
- 留痕导出：`json`
- 手动粘贴：`plaintext`

不支持直接读取 `.db/.sqlite`，请先导出为文本或 JSON。

---

## 最佳实践

- 优先提供“你自己发送”的大量消息
- 包含不同场景（闲聊、冲突、求助、深夜独处）更有利于还原
- 不要只追求口癖模仿；口癖只是壳子，核心是学习“别人问你时你会怎么回复”
- 如果结果不像你，直接用“我不会这样说”进行纠正迭代
- 向量召回时优先用 `role=user_self` + `priority=high` 条目

---

## 免责声明

本项目用于自我观察与表达建模，不构成心理、医疗、法律或投资建议。  
请勿输入你不希望长期保留的敏感数据。

---

## License

MIT
