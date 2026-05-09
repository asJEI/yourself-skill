# 向量记忆库构建规范

## 任务

根据微信聊天记录解析结果，筛选适合上传向量记忆库的内容，生成 `memory_chunks.jsonl` 或检查 `wechat_parser.py --memory-output` 生成的 JSONL。

优先过滤低价值 chunk（表情包/图片占位、系统提示、纯符号水词），保留可表达语言习惯和场景反应的内容。

向量记忆库的作用是：在后续对话中按语义召回用户真实语料、表达习惯、上下文反应和高置信事实，为 AI 回答提供参考。

关键原则：口癖只是壳子，**别人问用户时用户会怎么回复** 才是核心。因此向量库不能只收集高频词和口头禅，还必须保留足够的上下文回合，用于学习用户在具体触发条件下的接话、拒绝、反问、安慰、沉默和转移话题方式。

---

## 数据来源优先级

1. **上下文回合**：最高优先级，用于检索「对方怎么说 → 用户怎么回」的场景化反应，这是学习如何回答的核心。
2. **用户消息**：高优先级，是蒸馏用户语言风格和行为模式的主语料。
3. **用户消息语义切分**：高优先级，用于检索常用表达结构、转折方式、吐槽方式、解释方式。
4. **网络词/缩写候选**：低优先级，用于解释和注释，不直接作为人格结论。
5. **其他消息**：只作为上下文，不单独上传为用户记忆，除非和用户回复组成上下文回合。

---

## JSONL 条目格式

每行一个 JSON 对象：

```json
{
  "id": "semantic_0001_xxxxx",
  "type": "semantic_unit",
  "text": "怎么说呢，今天真的有点抽象",
  "metadata": {
    "source": "wechat",
    "role": "user_self",
    "priority": "high",
    "usage": "semantic_style_retrieval",
    "time": "2026-05-07 22:10:05",
    "chat": "某会话",
    "context_before": "今天工作怎么样",
    "context_after": ""
  }
}
```

---

## 上传规则

- 高优先级：上下文回合、场景化互动模式、用户对特定触发的反应。
- 中优先级：用户原话、语义切分、明确口头禅、典型表达方式。
- 低优先级：网络词候选、待确认规则、需要联网解释的词汇。
- 不上传：空消息、撤回提示、纯媒体占位符、系统提示、其他人单独说的话。

---

## 使用方式

1. 优先运行：

```bash
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

2. 如果目标环境提供向量库上传能力，将 `memory_chunks.jsonl` 逐行上传。
3. 上传时保留 `metadata.role` 和 `metadata.priority`，用于检索后判断权重。
4. 召回时只把 `role=user_self` 的内容当作用户表达证据；`role=mixed_context` 只能当作互动场景参考。
5. 检索阶段优先利用 `metadata.catchphrase_tags`、`metadata.topic_tags`、`metadata.scene_tags` 和 `metadata.emotion_tags`，避免只按联系人名召回。
