"""Local minimisation before cloud dispatch; never mutate cases or transcripts.

Rule-based removal is a layer of protection, not a claim of complete anonymity.
No original values or replacement dictionaries are logged or persisted.
"""
import re
import unicodedata

_NUMBER = r'[0-9零〇一二兩三四五六七八九十百千萬万]+'
_UNIT = re.compile(
    rf'(?:[A-Za-z]|{_NUMBER})[座棟栋](?:\s*(?:{_NUMBER}|[A-Za-z])(?:樓|楼|層|层|室|單位|单位|號|号)?\s*){{0,3}}')
_PATTERNS = (
    ('電郵', re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])')),
    ('身份證', re.compile(r'(?<![A-Za-z0-9])[A-Za-z]{1,2}\s*\d{6}\s*\(?[0-9Aa]\)?(?![A-Za-z0-9])')),
    ('電話', re.compile(r'(?<!\d)(?:\+?852[\s-]*)?[2-9](?:[\s-]*\d){7}(?!\d)')),
    ('住戶單位', _UNIT),
    ('住戶單位', re.compile(rf'{_NUMBER}[樓楼層层]\s*(?:[A-Za-z0-9零〇一二兩三四五六七八九十]+)(?:室|單位|单位|號|号)')),
    ('住戶地址', re.compile(r'(?:住址|住宅地址|我住喺|我住在|住喺|住在)\s*[:：]?\s*[^，,。！？!?；;\n]{2,80}')),
    ('居民稱呼', re.compile(r'(?:我叫|叫我|姓名[:：]|稱呼[:：]|称呼[:：])\s*[^，,。！？!?；;\n]{1,20}')),
)


def redact(text):
    if not isinstance(text, str):
        raise TypeError('invalid_cloud_text')
    # Normalise identifier glyphs, not Cantonese punctuation or ordinary prose.
    value = ''.join(unicodedata.normalize('NFKC', char) if
                    ('０' <= char <= '９' or 'Ａ' <= char <= 'Ｚ' or 'ａ' <= char <= 'ｚ'
                     or char in '＋－＠＿') else char for char in text)
    for label, pattern in _PATTERNS:
        value = pattern.sub('['+label+'已隱去]', value)
    return value


def messages_for_cloud(messages):
    """All roles, including system context, pass through the same last-mile filter."""
    return [{**item, 'content': redact(item['content'])} for item in messages]
