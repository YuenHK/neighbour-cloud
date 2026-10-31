"""Voice-friendly case references and deterministic local service routing."""
import re
import unicodedata

DIGITS = dict(zip('零〇一二兩三四五六七八九', '001223456789', strict=True))
NUMBER = r'[0-9零〇一二兩三四五六七八九十百千萬万]+'
PROGRESS_PROMPT = '我幫你查。請講個案數字編號，或者座數、樓層同單位就得，唔使另外搵同事。'


def number_value(text):
    text = unicodedata.normalize('NFKC', text)
    if text.isdecimal():
        return str(int(text))
    if all(c in DIGITS or c.isdecimal() for c in text):
        return ''.join(DIGITS.get(c, c) for c in text)
    total = section = digit = 0
    for char in text:
        if char in DIGITS or char.isdecimal():
            digit = int(DIGITS.get(char, char))
        elif char in '十百千':
            section += (digit or 1)*{'十': 10, '百': 100, '千': 1000}[char]
            digit = 0
        elif char in '萬万':
            total += (section+digit)*10000
            section = digit = 0
        else:
            return ''
    return str(total+section+digit)


def unit_reference(text):
    text = unicodedata.normalize('NFKC', text).upper()
    unit = re.search(rf'(?:[A-Z]|{NUMBER})[座棟栋](?:\s*(?:{NUMBER}|[A-Z])(?:樓|楼|層|层|室|單位|单位|號|号)?\s*){{0,3}}', text)
    if not unit:
        # A volunteered floor/flat is useful even when the estate has no block
        # or its block has not yet been supplied. Never invent a block prefix.
        unit = re.search(rf'{NUMBER}[樓楼層层]\s*(?:{NUMBER}|[A-Z])(?:室|單位|单位|號|号)', text)
    if not unit:
        return ''
    value = re.sub(r'\s+', '', unit[0]).replace('栋', '座').replace('棟', '座').replace('楼', '樓').replace('層', '樓').replace('层', '樓')
    value = value.replace('單位', '室').replace('单位', '室').replace('號', '室').replace('号', '室')
    value = re.sub(NUMBER, lambda match: number_value(match[0]), value).rstrip('；，,。')
    if re.search(r'樓[A-Z0-9]+$', value) or re.fullmatch(r'[A-Z0-9]+座\d+', value):
        value += '室'
    return value


def spoken_number(value):
    return '、'.join(str(value))


def routing_team(kind, message):
    if kind == 'hazard':
        return '保安緊急跟進'
    if kind == 'human_support':
        return '住戶支援'
    if kind == 'water' or re.search(r'維修|维修|壞|坏|故障|鎖匙|钥匙|冷氣|冷气|水喉', message):
        return '維修跟進'
    if kind == 'litter' or re.search(r'清潔|清洁|污糟', message):
        return '清潔跟進'
    if re.search(r'噪音|嘈|爭執|争执|保安', message):
        return '保安跟進'
    return '管理處跟進'


def progress_query(text, history, store):
    if re.search(r'補充|补充|更正', text) and not re.search(r'查.*進度|查.*进度|查詢.*進度|查询.*进度', text):
        return None
    pending = (len(history) >= 2 and history[-2]['role'] == 'assistant' and
               (history[-2]['content'] == PROGRESS_PROMPT or history[-2]['content'].startswith('呢個單位有多過一個個案：')))
    if not pending and not re.search(r'進度|进度|跟進成點|跟进|處理成點|处理情况|搞掂未|查詢求助|查询求助|(?:編號|编号)[:：\s]*[a-fA-F0-9]{8,32}|(?:查|問|睇|看).*(?:個案|个案|案件)|(?:個案|个案|案件|編號|编号).*[0-9零〇一二兩三四五六七八九十百千萬万]', text):
        return None
    normalized = unicodedata.normalize('NFKC', text)
    legacy = re.search(r'(?:編號|编号|求助|進度|进度)[:：\s]*([a-f0-9]{8,32})(?![a-f0-9])', normalized, re.IGNORECASE)
    if legacy and (re.search('[a-f]', legacy[1], re.IGNORECASE) or re.match(r'求助', legacy[0])):
        return store.progress(legacy[1].lower(), unit=unit_reference(normalized), legacy=True) or '暫時對唔上呢個舊編號，講返座數同單位，我再幫你查。'
    marked = re.search(rf'(?:編號|编号|個案|个案|案件)[係是為为：:\s]*({NUMBER}(?:[、，,\s]+{NUMBER})*)', normalized)
    suffix = re.search(rf'({NUMBER})[號号](?:個案|个案|案件)', normalized)
    runs = [re.sub(r'[、，,\s]', '', marked[1])] if marked else [suffix[1]] if suffix else re.findall(NUMBER, normalized)
    numbers = [number_value(value) for value in runs]
    unit = unit_reference(normalized)
    # Tiny numbers require an explicit case marker, or an unambiguous answer to
    # our number prompt. A floor, flat or phone number is not a case number.
    short_allowed = bool(marked or suffix or (pending and re.fullmatch(rf'\s*{NUMBER}\s*[。！!]?\s*', normalized)))
    candidates = [value for value in numbers if value.isdecimal() and 1 <= int(value) and
                  (1 if short_allowed else 6) <= len(value) <= 12]
    if candidates:
        return store.progress(candidates[0], unit=unit) or '暫時對唔上呢個編號同單位，請講多次數字編號，我再幫你查。'
    if unit:
        return store.unit_progress(unit)
    return PROGRESS_PROMPT
