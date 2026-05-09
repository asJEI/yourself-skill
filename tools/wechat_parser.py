#!/usr/bin/env python3
"""微信聊天记录解析器

支持主流导出工具的格式：
- WeChatMsg 导出（txt/html/csv）
- 留痕导出（json）
- 手动复制粘贴（纯文本）

Usage:
    python3 wechat_parser.py --file <path> --target <name> --output <output_path> [--format auto]
"""

import argparse
from collections import Counter
import csv
import hashlib
import html
import json
import re
import os
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_MEMORY_MAX_USER = 320
DEFAULT_MEMORY_MAX_SEMANTIC = 360
DEFAULT_MEMORY_MAX_TURN = 220
DEFAULT_MEMORY_MAX_TERM = 60


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, '').strip()
    if not value:
        return default
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def detect_format(file_path: str) -> str:
    """自动检测文件格式"""
    ext = Path(file_path).suffix.lower()

    if ext == '.json':
        return 'liuhen'  # 留痕导出
    elif ext == '.csv':
        return 'wechatmsg_csv'
    elif ext == '.html' or ext == '.htm':
        return 'wechatmsg_html'
    elif ext == '.db' or ext == '.sqlite':
        return 'unsupported_sqlite'
    elif ext == '.txt':
        # 尝试区分 WeChatMsg txt 和纯文本
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            first_lines = f.read(2000)
        # WeChatMsg 格式通常有时间戳模式
        if re.search(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', first_lines):
            return 'wechatmsg_txt'
        return 'plaintext'
    else:
        return 'plaintext'


def _clean_content(value) -> str:
    """清洗导出内容，保留可用于蒸馏的自然语言文本。"""
    if value in (None, ''):
        return ''
    text = html.unescape(str(value))
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
    text = re.sub(r'</?(div|p|tr|li|section|article|h\d)\b[^>]*>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\r\n?', '\n', text)
    text = re.sub(r'[ \t\u3000]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _is_noise_content(text: str) -> bool:
    """过滤系统提示和无法反映用户表达习惯的消息。"""
    if not text:
        return True
    compact = re.sub(r'\s+', '', text)
    if not compact:
        return True

    # 纯标点、纯数字、超短无信息水词
    if re.fullmatch(r'[\W_]+', compact):
        return True
    if re.fullmatch(r'\d{1,8}', compact):
        return True
    if len(compact) <= 2 and compact in {'哈', '啊', '嗯', '哦', '噢', '呃', '?', '？', '!', '！', '。'}:
        return True

    noise_patterns = (
        r'^以下为新消息$',
        r'撤回了一条消息',
        r'^你已添加了.*现在可以开始聊天了',
        r'^以上是打招呼的内容$',
        r'^\[?(图片|表情|动画表情|语音|视频|文件|位置|链接|名片|合并转发)\]?$',
        r'^(\[动画表情\]|\[图片\]|\[表情\]|\[语音\]|\[视频\])$',
        r'^\[微信红包\]$',
        r'^<微信红包>$',
        r'^收到一条消息$',
        r'^<msg>',
    )
    return any(re.search(pattern, text) for pattern in noise_patterns)


def _is_low_value_chunk(text: str) -> bool:
    cleaned = _clean_content(text)
    if not cleaned:
        return True
    compact = re.sub(r'\s+', '', cleaned)
    if not compact:
        return True
    if len(compact) <= 2 and re.fullmatch(r'[哈呵嗯哦噢啊呀呃]+', compact):
        return True
    if re.fullmatch(r'[\W_]+', compact):
        return True
    return _is_noise_content(cleaned)


def _dedupe_texts(texts: list, limit: int) -> list:
    deduped = []
    seen = set()
    for text in texts:
        cleaned = _clean_content(text)
        if _is_low_value_chunk(cleaned):
            continue
        key = re.sub(r'\s+', ' ', cleaned).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped


def _clean_message(msg: dict) -> dict:
    cleaned = dict(msg)
    cleaned['content'] = _clean_content(cleaned.get('content', ''))
    cleaned['sender'] = _clean_content(cleaned.get('sender', ''))
    cleaned['chat'] = _clean_content(cleaned.get('chat', ''))
    return cleaned


def _first_value(data: dict, keys: list, default=''):
    """从多个候选字段里取第一个非空值，兼容不同导出工具的命名。"""
    for key in keys:
        if key in data and data[key] not in (None, ''):
            return data[key]
    return default


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'y', 'self', 'me', '我', '自己'}
    return False


def _parse_timestamp(value):
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        # 常见导出格式可能是秒或毫秒时间戳
        if value > 10_000_000_000:
            value = value / 1000
        try:
            return datetime.fromtimestamp(value)
        except (OSError, ValueError):
            return None
    text = str(value).strip()
    for fmt in (
        '%Y-%m-%d %H:%M:%S',
        '%Y/%m/%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M',
    ):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _extract_message_list(data):
    """尽量从未知 JSON 结构中找到消息数组。"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    for key in ('messages', 'message', 'msgs', 'msgList', 'data', 'records', 'items', 'list'):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_message_list(value)
            if nested:
                return nested

    # 有些导出按会话分组：{"chatA": [msg...], "chatB": [msg...]}
    merged = []
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            merged.extend(value)
    return merged


def _message_matches_self(msg: dict, target_name: str, self_id: str = '', self_name: str = '', self_field: str = '') -> bool:
    raw = msg.get('raw', {})
    if self_field and self_field in raw:
        return _truthy(raw[self_field])
    if msg.get('is_self') is not None:
        return bool(msg['is_self'])

    sender = str(msg.get('sender', ''))
    sender_id = str(msg.get('sender_id', ''))
    candidates = [sender, sender_id]

    if self_id and self_id in candidates:
        return True
    if self_name and any(self_name in c for c in candidates):
        return True
    return bool(target_name and any(target_name in c for c in candidates))


def _normalize_json_message(raw: dict, target_name: str, self_id: str = '', self_name: str = '', self_field: str = '') -> dict:
    content = _first_value(raw, [
        'content', 'message', 'text', 'msg', 'StrContent', 'strContent', 'msgContent',
        'plainText', 'messageContent'
    ])
    sender = _first_value(raw, [
        'sender', 'nickname', 'senderName', 'from', 'fromName', 'talker', 'talkerName',
        'remark', 'displayName', 'name'
    ])
    sender_id = _first_value(raw, [
        'sender_id', 'senderId', 'fromUserName', 'from_username', 'wxid', 'userName',
        'talkerId', 'fromId'
    ])
    timestamp = _first_value(raw, [
        'time', 'timestamp', 'createTime', 'CreateTime', 'msgTime', 'datetime', 'date'
    ])
    chat = _first_value(raw, [
        'chat', 'room', 'roomName', 'conversation', 'conversationName', 'talker',
        'session', 'contact'
    ])

    is_self = None
    for key in ('isSelf', 'is_self', 'fromMe', 'from_me', 'IsSender', 'isSender', 'self', 'me'):
        if key in raw:
            is_self = _truthy(raw[key])
            break

    msg = {
        'timestamp': str(timestamp) if timestamp is not None else '',
        'sender': str(sender),
        'sender_id': str(sender_id),
        'chat': str(chat),
        'content': _clean_content(content),
        'is_self': is_self,
        'raw': raw,
    }
    msg['is_self'] = _message_matches_self(msg, target_name, self_id, self_name, self_field)
    return msg


def _parse_wechatmsg_text_content(
    content: str,
    target_name: str,
    self_id: str = '',
    self_name: str = '',
    self_field: str = '',
    config: dict = None,
) -> dict:
    """解析 WeChatMsg 导出的 txt 格式

    典型格式：
    2024-01-15 20:30:45 张三
    今天好累啊

    2024-01-15 20:31:02 我
    怎么了？
    """
    messages = []
    current_msg = None

    # WeChatMsg 时间戳 + 发送者模式
    msg_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(.+)$')

    for line in content.splitlines():
        line = line.rstrip('\n')
        match = msg_pattern.match(line)
        if match:
            if current_msg:
                messages.append(current_msg)
            timestamp, sender = match.groups()
            current_msg = {
                'timestamp': timestamp,
                'sender': sender.strip(),
                'sender_id': '',
                'chat': '',
                'is_self': None,
                'content': ''
            }
        elif current_msg and line.strip():
            if current_msg['content']:
                current_msg['content'] += '\n'
            current_msg['content'] += line

    if current_msg:
        messages.append(current_msg)

    for msg in messages:
        msg['is_self'] = _message_matches_self(msg, target_name, self_id, self_name, self_field)

    return analyze_messages(messages, target_name, config)


def parse_wechatmsg_txt(
    file_path: str,
    target_name: str,
    self_id: str = '',
    self_name: str = '',
    self_field: str = '',
    config: dict = None,
) -> dict:
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        return _parse_wechatmsg_text_content(f.read(), target_name, self_id, self_name, self_field, config)


def parse_wechatmsg_html(
    file_path: str,
    target_name: str,
    self_id: str = '',
    self_name: str = '',
    self_field: str = '',
    config: dict = None,
) -> dict:
    """解析 WeChatMsg HTML 导出，先转为可读文本再复用文本解析。"""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        text = _clean_content(f.read())
    return _parse_wechatmsg_text_content(text, target_name, self_id, self_name, self_field, config)


def parse_wechatmsg_csv(
    file_path: str,
    target_name: str,
    self_id: str = '',
    self_name: str = '',
    self_field: str = '',
    config: dict = None,
) -> dict:
    """解析 WeChatMsg CSV 导出，兼容常见字段名。"""
    messages = []
    with open(file_path, 'r', encoding='utf-8-sig', errors='ignore', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            messages.append(_normalize_json_message(row, target_name, self_id, self_name, self_field))
    return analyze_messages(messages, target_name, config)


def parse_liuhen_json(
    file_path: str,
    target_name: str,
    self_id: str = '',
    self_name: str = '',
    self_field: str = '',
    config: dict = None,
) -> dict:
    """解析留痕/WeChatMsg 等 JSON 格式"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    messages = [
        _normalize_json_message(msg, target_name, self_id, self_name, self_field)
        for msg in _extract_message_list(data)
        if isinstance(msg, dict)
    ]

    return analyze_messages(messages, target_name, config)


def parse_plaintext(
    file_path: str,
    target_name: str,
    self_id: str = '',
    self_name: str = '',
    self_field: str = '',
    config: dict = None,
) -> dict:
    """解析纯文本粘贴的聊天记录"""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    return {
        'raw_text': content,
        'target_name': target_name,
        'format': 'plaintext',
        'message_count': 0,
        'analysis': {
            'note': '纯文本格式，需要人工辅助分析'
        }
    }


def _build_context_turns(messages: list, limit: int = 80) -> list:
    turns = []
    seen = set()
    for i, msg in enumerate(messages):
        if not msg.get('is_self') or not msg.get('content'):
            continue
        prev_msg = messages[i - 1] if i > 0 else {}
        next_msg = messages[i + 1] if i + 1 < len(messages) else {}
        if not prev_msg or prev_msg.get('is_self'):
            continue
        my_reply = msg.get('content', '')
        if _is_low_value_chunk(my_reply):
            continue
        key = f"{prev_msg.get('content', '')}||{my_reply}"
        if key in seen:
            continue
        seen.add(key)
        turns.append({
            'time': msg.get('timestamp', ''),
            'chat': msg.get('chat', ''),
            'other_before': prev_msg.get('content', ''),
            'my_reply': my_reply,
            'other_after': next_msg.get('content', '') if next_msg and not next_msg.get('is_self') else '',
        })
        if len(turns) >= limit:
            break
    return turns


def _stratified_samples(target_msgs: list) -> dict:
    samples = {}
    with_content = [m for m in target_msgs if m.get('content')]
    samples['long_messages'] = sorted(with_content, key=lambda m: len(m['content']), reverse=True)[:15]
    samples['short_replies'] = [m for m in with_content if len(m['content']) <= 8][:20]
    samples['questions'] = [m for m in with_content if '？' in m['content'] or '?' in m['content']][:20]
    samples['exclamations'] = [m for m in with_content if '！' in m['content'] or '!' in m['content']][:20]

    night = []
    for msg in with_content:
        dt = _parse_timestamp(msg.get('timestamp'))
        if dt and (dt.hour >= 22 or dt.hour < 5):
            night.append(msg)
    samples['late_night'] = night[:20]
    return samples


def _hour_distribution(messages: list) -> dict:
    counter = Counter()
    for msg in messages:
        dt = _parse_timestamp(msg.get('timestamp'))
        if dt:
            counter[f'{dt.hour:02d}:00'] += 1
    return dict(counter.most_common())


def _infer_topic_tags(text: str) -> list:
    topic_rules = {
        'work': ('工作', '加班', '开会', '项目', '需求', '老板', '同事', 'kpi', 'okr', 'ddl'),
        'emotion': ('难过', 'emo', '破防', '崩溃', '焦虑', '委屈', '开心', '生气'),
        'daily_life': ('吃饭', '睡觉', '下班', '通勤', '买菜', '做饭', '周末', '回家'),
        'study_growth': ('学习', '复盘', '成长', '反思', '计划', '目标', '效率'),
        'money': ('工资', '花钱', '省钱', '预算', '理财', '房租', '贷款'),
        'relationship': ('朋友', '对象', '恋爱', '分手', '家人', '父母', '相亲'),
    }
    lowered = text.lower()
    tags = [tag for tag, words in topic_rules.items() if any(w in lowered for w in words)]
    return tags[:4]


def _infer_scene_tags(text: str) -> list:
    scene_rules = {
        'asking_help': ('帮我', '怎么做', '求你', '能不能', '请教', '救命'),
        'urge_progress': ('快点', '赶紧', '催', '什么时候', '尽快', '今天要'),
        'conflict': ('不是', '不行', '凭什么', '别', '烦', '无语'),
        'comfort': ('没事', '抱抱', '别难过', '会好的', '辛苦了'),
        'daily_chat': ('哈哈', '笑死', '在干嘛', '吃了没', '下班没'),
        'late_night': ('睡了吗', '熬夜', '凌晨', '晚安', '夜里'),
    }
    lowered = text.lower()
    tags = [tag for tag, words in scene_rules.items() if any(w in lowered for w in words)]
    return tags[:4]


def _infer_emotion_tags(text: str) -> list:
    emotion_rules = {
        'positive': ('开心', '好耶', '哈哈', '不错', '舒服'),
        'anxious': ('焦虑', '担心', '怕', '慌', '压力'),
        'angry': ('生气', '烦', '火大', '离谱', '无语'),
        'sad': ('难过', 'emo', '委屈', '崩溃', '想哭'),
        'self_mocking': ('笑死', '我服了', '绷不住', '我真是', '逆天'),
    }
    lowered = text.lower()
    tags = [tag for tag, words in emotion_rules.items() if any(w in lowered for w in words)]
    return tags[:3]


def _extract_catchphrase_tags(text: str) -> list:
    candidates = [
        '怎么说呢', '问题不大', '先这样', '算了', '真的', '其实', '不过',
        '我感觉', '我觉得', '离谱', '抽象', '笑死', '绷不住', '救命',
    ]
    tags = [c for c in candidates if c in text]
    if tags:
        return tags[:4]
    tokens = re.findall(r'[A-Za-z]{2,12}|[\u4e00-\u9fa5]{2,6}', text)
    return tokens[:2]


def _collect_memory_limits(config: dict = None) -> dict:
    config = config or {}
    return {
        'user': int(config.get('memory_max_user') or _env_int('WECHAT_MEMORY_MAX_USER', DEFAULT_MEMORY_MAX_USER)),
        'semantic': int(config.get('memory_max_semantic') or _env_int('WECHAT_MEMORY_MAX_SEMANTIC', DEFAULT_MEMORY_MAX_SEMANTIC)),
        'turn': int(config.get('memory_max_turn') or _env_int('WECHAT_MEMORY_MAX_TURN', DEFAULT_MEMORY_MAX_TURN)),
        'term': int(config.get('memory_max_term') or _env_int('WECHAT_MEMORY_MAX_TERM', DEFAULT_MEMORY_MAX_TERM)),
    }


def _build_user_corpus_samples(target_msgs: list, limit: int) -> list:
    with_content = [m for m in target_msgs if m.get('content') and not _is_low_value_chunk(m.get('content', ''))]
    if not with_content:
        return []
    head = [m['content'] for m in with_content[: max(20, limit // 6)]]
    tail = [m['content'] for m in with_content[-max(20, limit // 6):]]
    long_msgs = [m['content'] for m in sorted(with_content, key=lambda x: len(x.get('content', '')), reverse=True)[: max(30, limit // 5)]]
    questions = [m['content'] for m in with_content if ('？' in m['content'] or '?' in m['content'])][: max(20, limit // 8)]
    exclamations = [m['content'] for m in with_content if ('！' in m['content'] or '!' in m['content'])][: max(20, limit // 8)]
    merged = head + tail + long_msgs + questions + exclamations
    return _dedupe_texts(merged, limit)


def _split_semantic_units(text: str) -> list:
    """按标点、换行和常见转折连接词做轻量语义切分。"""
    text = _clean_content(text)
    if not text:
        return []
    parts = re.split(r'[\n。！？!?；;]+|(?<=，)(?=但是|但|不过|然后|所以|因为|而且|就是|其实)', text)
    units = []
    for part in parts:
        unit = part.strip(' ，,、')
        if len(unit) >= 2:
            units.append(unit)
    return units


def _semantic_chunks(target_msgs: list, messages: list, limit: int = 120) -> list:
    chunks = []
    seen = set()
    index_by_id = {id(msg): i for i, msg in enumerate(messages)}
    for msg in target_msgs:
        idx = index_by_id.get(id(msg), -1)
        prev_msg = messages[idx - 1] if idx > 0 else {}
        next_msg = messages[idx + 1] if idx + 1 < len(messages) else {}
        for unit in _split_semantic_units(msg.get('content', '')):
            if _is_low_value_chunk(unit):
                continue
            unit_key = re.sub(r'\s+', ' ', unit).strip()
            if unit_key in seen:
                continue
            seen.add(unit_key)
            chunks.append({
                'time': msg.get('timestamp', ''),
                'chat': msg.get('chat', ''),
                'unit': unit,
                'context_before': prev_msg.get('content', '') if prev_msg and not prev_msg.get('is_self') else '',
                'context_after': next_msg.get('content', '') if next_msg and not next_msg.get('is_self') else '',
            })
            if len(chunks) >= limit:
                return chunks
    return chunks


def _internet_term_candidates(chunks: list) -> list:
    """提取需要人工/联网解释的网络词、缩写和混合表达候选。"""
    known_terms = {
        'yyds', 'xswl', 'awsl', 'nb', 'emo', 'ddl', 'kpi', 'okr', 'cpu', 'pua',
        'bug', 'flag', '社死', '破防', '上头', '下头', '内耗', '摆烂', '躺平',
        '绝绝子', '蚌埠住', '蚌埠住了', '狠狠', '拿捏', '拉扯', '抓马', '抽象',
        '离谱', '逆天', '真实', '救命', '笑死', '裂开', '麻了', '绷不住',
    }
    known_terms_lower = {term.lower() for term in known_terms}
    counter = Counter()
    for chunk in chunks:
        text = chunk.get('unit', '')
        lowered = text.lower()
        for term in known_terms:
            if term.lower() in lowered:
                counter[term] += 1
        for token in re.findall(r'\b[a-zA-Z][a-zA-Z0-9]{1,12}\b', text):
            lowered_token = token.lower()
            if lowered_token not in {'http', 'https', 'com', 'www'} and lowered_token not in known_terms_lower:
                counter[token] += 1
    return [
        {'term': term, 'count': count}
        for term, count in counter.most_common(30)
    ]


def _chunk_id(prefix: str, text: str, index: int) -> str:
    digest = hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]
    return f'{prefix}_{index:04d}_{digest}'


def _build_vector_memory_chunks(result: dict) -> list:
    """生成适合上传向量记忆库的 JSONL 条目。"""
    chunks = []
    limits = result.get('memory_limits', _collect_memory_limits())
    seen_texts = set()

    def _append_chunk(item: dict):
        text = _clean_content(item.get('text', ''))
        if _is_low_value_chunk(text):
            return
        dedupe_key = re.sub(r'\s+', ' ', text).strip()
        if not dedupe_key or dedupe_key in seen_texts:
            return
        seen_texts.add(dedupe_key)
        item['text'] = text
        metadata = item.setdefault('metadata', {})
        metadata.setdefault('topic_tags', _infer_topic_tags(text))
        metadata.setdefault('scene_tags', _infer_scene_tags(text))
        metadata.setdefault('emotion_tags', _infer_emotion_tags(text))
        metadata.setdefault('catchphrase_tags', _extract_catchphrase_tags(text))
        chunks.append(item)

    for i, text in enumerate(result.get('user_corpus_samples', [])[:limits.get('user', DEFAULT_MEMORY_MAX_USER)], 1):
        _append_chunk({
            'id': _chunk_id('user_msg', text, i),
            'type': 'user_message',
            'text': text,
            'metadata': {
                'source': 'wechat',
                'role': 'user_self',
                'priority': 'high',
                'usage': 'primary_corpus_for_style_and_persona',
            }
        })

    for i, item in enumerate(result.get('semantic_chunks', [])[:limits.get('semantic', DEFAULT_MEMORY_MAX_SEMANTIC)], 1):
        text = item.get('unit', '')
        if not text:
            continue
        _append_chunk({
            'id': _chunk_id('semantic', text, i),
            'type': 'semantic_unit',
            'text': text,
            'metadata': {
                'source': 'wechat',
                'role': 'user_self',
                'priority': 'high',
                'usage': 'semantic_style_retrieval',
                'time': item.get('time', ''),
                'chat': item.get('chat', ''),
                'context_before': item.get('context_before', ''),
                'context_after': item.get('context_after', ''),
            }
        })

    for i, turn in enumerate(result.get('context_turns', [])[:limits.get('turn', DEFAULT_MEMORY_MAX_TURN)], 1):
        text = f"对方：{turn.get('other_before', '')}\n我：{turn.get('my_reply', '')}"
        if turn.get('other_after'):
            text += f"\n对方后续：{turn['other_after']}"
        _append_chunk({
            'id': _chunk_id('turn', text, i),
            'type': 'context_turn',
            'text': text,
            'metadata': {
                'source': 'wechat',
                'role': 'mixed_context',
                'priority': 'medium',
                'usage': 'response_pattern_reference',
                'time': turn.get('time', ''),
                'chat': turn.get('chat', ''),
                'note': 'Other messages are auxiliary context, not user facts.',
            }
        })

    for i, item in enumerate(result.get('internet_term_candidates', [])[:limits.get('term', DEFAULT_MEMORY_MAX_TERM)], 1):
        text = f"{item['term']}（出现 {item['count']} 次）：待结合上下文解释；如运行环境支持联网搜索，可搜索后补充注释。"
        _append_chunk({
            'id': _chunk_id('term', text, i),
            'type': 'internet_term_candidate',
            'text': text,
            'metadata': {
                'source': 'wechat',
                'role': 'annotation_candidate',
                'priority': 'low',
                'usage': 'term_annotation_before_style_generation',
            }
        })

    return chunks


def write_vector_memory_jsonl(result: dict, output_path: str):
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    chunks = _build_vector_memory_chunks(result)
    with open(output_path, 'w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
    return len(chunks)


def analyze_messages(messages: list, target_name: str, config: dict = None) -> dict:
    """分析消息列表，提取关键特征"""
    memory_limits = _collect_memory_limits(config)
    raw_count = len(messages)
    messages = [
        _clean_message(m)
        for m in messages
        if not _is_noise_content(_clean_content(m.get('content', '')))
    ]
    target_msgs = [m for m in messages if m.get('is_self')]
    other_msgs = [m for m in messages if not m.get('is_self')]

    # 提取口头禅（高频词分析）
    all_target_text = ' '.join([m['content'] for m in target_msgs if m.get('content')])

    # 提取语气词
    particles = re.findall(r'[哈嗯哦噢嘿唉呜啊呀吧嘛呢吗么]+', all_target_text)
    particle_freq = {}
    for p in particles:
        particle_freq[p] = particle_freq.get(p, 0) + 1
    top_particles = sorted(particle_freq.items(), key=lambda x: -x[1])[:10]

    # 提取 emoji
    emoji_pattern = re.compile(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
        r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
        r'\U00002702-\U000027B0\U0000FE00-\U0000FE0F'
        r'\U0001F900-\U0001F9FF]+', re.UNICODE
    )
    emojis = emoji_pattern.findall(all_target_text)
    emoji_freq = {}
    for e in emojis:
        emoji_freq[e] = emoji_freq.get(e, 0) + 1
    top_emojis = sorted(emoji_freq.items(), key=lambda x: -x[1])[:10]

    # 消息长度统计
    msg_lengths = [len(m['content']) for m in target_msgs if m.get('content')]
    avg_length = sum(msg_lengths) / len(msg_lengths) if msg_lengths else 0

    # 标点习惯
    punctuation_counts = {
        '句号': all_target_text.count('。'),
        '感叹号': all_target_text.count('！') + all_target_text.count('!'),
        '问号': all_target_text.count('？') + all_target_text.count('?'),
        '省略号': all_target_text.count('...') + all_target_text.count('…'),
        '波浪号': all_target_text.count('～') + all_target_text.count('~'),
    }

    chats = Counter(m.get('chat') or '未知会话' for m in target_msgs)
    senders = Counter(m.get('sender') or m.get('sender_id') or '未知发送者' for m in messages)
    chunks = _semantic_chunks(target_msgs, messages, limit=memory_limits.get('semantic', DEFAULT_MEMORY_MAX_SEMANTIC))
    user_corpus_samples = _build_user_corpus_samples(target_msgs, memory_limits.get('user', DEFAULT_MEMORY_MAX_USER))
    context_turns = _build_context_turns(messages, limit=memory_limits.get('turn', DEFAULT_MEMORY_MAX_TURN))
    auxiliary_context_samples = _dedupe_texts([m['content'] for m in other_msgs if m.get('content')], 150)

    return {
        'target_name': target_name,
        'raw_messages': raw_count,
        'total_messages': len(messages),
        'target_messages': len(target_msgs),
        'other_messages': len(other_msgs),
        'self_match_rate': round(len(target_msgs) / len(messages), 4) if messages else 0,
        'sender_candidates': senders.most_common(20),
        'top_chats': chats.most_common(20),
        'analysis': {
            'top_particles': top_particles,
            'top_emojis': top_emojis,
            'avg_message_length': round(avg_length, 1),
            'punctuation_habits': punctuation_counts,
            'message_style': 'short_burst' if avg_length < 20 else 'long_form',
            'active_hours': _hour_distribution(target_msgs),
        },
        'memory_limits': memory_limits,
        'user_corpus_samples': user_corpus_samples,
        'auxiliary_context_samples': auxiliary_context_samples,
        'semantic_chunks': chunks,
        'internet_term_candidates': _internet_term_candidates(chunks),
        'sample_messages': user_corpus_samples[:80],
        'stratified_samples': _stratified_samples(target_msgs),
        'context_turns': context_turns,
    }


def main():
    parser = argparse.ArgumentParser(description='微信聊天记录解析器')
    parser.add_argument('--file', required=True, help='输入文件路径')
    parser.add_argument('--target', required=True, help='目标对象的名字/昵称（如"我"）')
    parser.add_argument('--output', required=True, help='输出文件路径')
    parser.add_argument('--format', default='auto', help='文件格式 (auto/wechatmsg_txt/liuhen/pywxdump/plaintext)')
    parser.add_argument('--self-id', default='', help='本人 wxid/账号 ID，用于更准确识别自己的消息')
    parser.add_argument('--self-name', default='', help='本人昵称/备注名，用于更准确识别自己的消息')
    parser.add_argument('--self-field', default='', help='JSON 中标记本人消息的字段名，如 isSelf/fromMe/IsSender')
    parser.add_argument('--memory-output', default='', help='可选：输出适合上传向量记忆库的 JSONL 文件')
    parser.add_argument('--memory-max-user', type=int, default=DEFAULT_MEMORY_MAX_USER, help='user_message 最大条数')
    parser.add_argument('--memory-max-semantic', type=int, default=DEFAULT_MEMORY_MAX_SEMANTIC, help='semantic_unit 最大条数')
    parser.add_argument('--memory-max-turn', type=int, default=DEFAULT_MEMORY_MAX_TURN, help='context_turn 最大条数')
    parser.add_argument('--memory-max-term', type=int, default=DEFAULT_MEMORY_MAX_TERM, help='internet_term_candidate 最大条数')

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"错误：文件不存在 {args.file}", file=sys.stderr)
        sys.exit(1)

    fmt = args.format
    if fmt == 'auto':
        fmt = detect_format(args.file)
        print(f"自动检测格式：{fmt}")

    if fmt == 'unsupported_sqlite':
        print("错误：当前版本不支持直接解析 SQLite/.db 微信数据库。请先用导出工具转换为 txt/html/csv/json 后再导入。", file=sys.stderr)
        sys.exit(1)

    parsers = {
        'wechatmsg_txt': parse_wechatmsg_txt,
        'wechatmsg_html': parse_wechatmsg_html,
        'wechatmsg_csv': parse_wechatmsg_csv,
        'liuhen': parse_liuhen_json,
        'plaintext': parse_plaintext,
    }

    parse_func = parsers.get(fmt, parse_plaintext)
    parser_config = {
        'memory_max_user': args.memory_max_user,
        'memory_max_semantic': args.memory_max_semantic,
        'memory_max_turn': args.memory_max_turn,
        'memory_max_term': args.memory_max_term,
    }
    result = parse_func(args.file, args.target, args.self_id, args.self_name, args.self_field, parser_config)
    memory_chunk_count = 0
    if args.memory_output:
        memory_chunk_count = write_vector_memory_jsonl(result, args.memory_output)

    # 输出分析结果
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(f"# 微信聊天记录分析 — {args.target}\n\n")
        f.write(f"来源文件：{args.file}\n")
        f.write(f"检测格式：{fmt}\n")
        f.write(f"原始消息数：{result.get('raw_messages', 'N/A')}\n")
        f.write(f"清洗后消息数：{result.get('total_messages', 'N/A')}\n")
        f.write(f"用户消息数：{result.get('target_messages', 'N/A')}\n")
        f.write(f"其他消息数：{result.get('other_messages', 'N/A')}\n\n")
        f.write("## 数据清洗与分流\n")
        f.write("- 用户消息：用户自己发送的消息，是蒸馏的主要内容和语料库。\n")
        f.write("- 其他消息：其他人发送的信息，只作为理解语境、触发条件和互动关系的辅助数据。\n")
        f.write("- 已过滤：空消息、撤回提示、纯媒体占位符、系统提示等低价值记录。\n\n")
        f.write(f"本人消息命中率：{result.get('self_match_rate', 0):.2%}\n")
        if args.memory_output:
            f.write(f"向量记忆库 JSONL：{args.memory_output}（{memory_chunk_count}条）\n")
            limits = result.get('memory_limits', {})
            f.write(
                "memory 限制配置："
                f"user={limits.get('user', 'N/A')}, "
                f"semantic={limits.get('semantic', 'N/A')}, "
                f"turn={limits.get('turn', 'N/A')}, "
                f"term={limits.get('term', 'N/A')}\n"
            )
        if result.get('target_messages', 0) == 0:
            f.write("⚠️ 未识别到本人消息。请改用 --self-id、--self-name 或 --self-field 指定本人消息判定方式。\n")
        f.write("\n")

        if result.get('sender_candidates'):
            f.write("## 发送者候选（用于校验“我”的识别）\n")
            for sender, count in result['sender_candidates']:
                f.write(f"- {sender}: {count}条\n")
            f.write("\n")

        if result.get('top_chats'):
            f.write("## 会话分布（本人消息）\n")
            for chat, count in result['top_chats']:
                f.write(f"- {chat}: {count}条\n")
            f.write("\n")

        analysis = result.get('analysis', {})

        if analysis.get('top_particles'):
            f.write("## 高频语气词\n")
            for word, count in analysis['top_particles']:
                f.write(f"- {word}: {count}次\n")
            f.write("\n")

        if analysis.get('top_emojis'):
            f.write("## 高频 Emoji\n")
            for emoji, count in analysis['top_emojis']:
                f.write(f"- {emoji}: {count}次\n")
            f.write("\n")

        if analysis.get('punctuation_habits'):
            f.write("## 标点习惯\n")
            for punct, count in analysis['punctuation_habits'].items():
                f.write(f"- {punct}: {count}次\n")
            f.write("\n")

        f.write(f"## 消息风格\n")
        f.write(f"- 平均消息长度：{analysis.get('avg_message_length', 'N/A')} 字\n")
        f.write(f"- 风格：{'短句连发型' if analysis.get('message_style') == 'short_burst' else '长段落型'}\n\n")

        if analysis.get('active_hours'):
            f.write("## 活跃时间分布\n")
            for hour, count in list(analysis['active_hours'].items())[:12]:
                f.write(f"- {hour}: {count}条\n")
            f.write("\n")

        if result.get('sample_messages'):
            f.write("## 用户消息语料库（前50条）\n")
            f.write("以下内容来自用户自己发送的消息，是后续蒸馏说话风格、价值判断和行为模式的主要语料。\n\n")
            for i, msg in enumerate(result['sample_messages'], 1):
                f.write(f"{i}. {msg}\n")

        if result.get('auxiliary_context_samples'):
            f.write("\n## 其他消息辅助数据（前30条）\n")
            f.write("以下内容来自其他人，只用于理解上下文，不直接作为用户人格或记忆结论。\n\n")
            for i, msg in enumerate(result['auxiliary_context_samples'][:30], 1):
                f.write(f"{i}. {msg}\n")

        if result.get('semantic_chunks'):
            f.write("\n## 用户消息语义切分\n")
            f.write("以下片段由用户消息切分得到，用于结合上下文归纳语言习惯、表达结构和常用语义单元。\n\n")
            for i, chunk in enumerate(result['semantic_chunks'][:80], 1):
                f.write(f"{i}. {chunk['unit']}\n")
                if chunk.get('context_before'):
                    f.write(f"   - 上文：{chunk['context_before']}\n")
                if chunk.get('context_after'):
                    f.write(f"   - 下文：{chunk['context_after']}\n")

        if result.get('internet_term_candidates'):
            f.write("\n## 待联网解释的网络词/缩写候选\n")
            f.write("以下词汇可能带有互联网语境、圈层含义或缩写含义。分析时如不确定，且运行环境支持联网搜索，可搜索解释后再注释；不支持则提示用户并跳过联网搜索。\n\n")
            for item in result['internet_term_candidates']:
                f.write(f"- {item['term']}: {item['count']}次\n")

        if result.get('stratified_samples'):
            f.write("\n## 分层样本（用于避免只看前50条）\n")
            sample_titles = {
                'long_messages': '长消息',
                'short_replies': '短回复',
                'questions': '提问句',
                'exclamations': '强情绪/感叹句',
                'late_night': '深夜消息',
            }
            for key, title in sample_titles.items():
                items = result['stratified_samples'].get(key, [])
                if not items:
                    continue
                f.write(f"\n### {title}\n")
                for i, msg in enumerate(items[:10], 1):
                    time = msg.get('timestamp', '')
                    content = msg.get('content', '').replace('\n', ' ')
                    f.write(f"{i}. [{time}] {content}\n")

        if result.get('context_turns'):
            f.write("\n## 上下文回合样本（对方怎么说 → 我怎么回）\n")
            for i, turn in enumerate(result['context_turns'][:30], 1):
                f.write(f"\n### 回合 {i}\n")
                if turn.get('time'):
                    f.write(f"- 时间：{turn['time']}\n")
                if turn.get('chat'):
                    f.write(f"- 会话：{turn['chat']}\n")
                f.write(f"- 对方：{turn['other_before']}\n")
                f.write(f"- 我：{turn['my_reply']}\n")
                if turn.get('other_after'):
                    f.write(f"- 对方后续：{turn['other_after']}\n")

        if args.memory_output:
            generated_chunks = _build_vector_memory_chunks(result)
            type_counter = Counter(chunk.get('type', 'unknown') for chunk in generated_chunks)
            topic_counter = Counter()
            scene_counter = Counter()
            for chunk in generated_chunks:
                metadata = chunk.get('metadata', {})
                for tag in metadata.get('topic_tags', []):
                    topic_counter[tag] += 1
                for tag in metadata.get('scene_tags', []):
                    scene_counter[tag] += 1
            f.write("\n## 向量记忆覆盖统计\n")
            f.write(f"- 去重后总条数：{len(generated_chunks)}\n")
            for key, count in type_counter.most_common():
                f.write(f"- 类型占比 {key}: {count}\n")
            if topic_counter:
                f.write("- 主题覆盖（Top 8）：\n")
                for tag, count in topic_counter.most_common(8):
                    f.write(f"  - {tag}: {count}\n")
            if scene_counter:
                f.write("- 场景覆盖（Top 8）：\n")
                for tag, count in scene_counter.most_common(8):
                    f.write(f"  - {tag}: {count}\n")

    print(f"分析完成，结果已写入 {args.output}")


if __name__ == '__main__':
    main()
