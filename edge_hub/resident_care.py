"""Listen first; request outreach only after the resident chooses it."""
import re

from edge_hub.resident_cases import unit_reference

CARE_OFFER = '你想唔想我幫你安排管理人員主動聯絡你？'
CARE_LOCATION = '可以，我幫你跟進聯絡安排。你住邊座、幾樓、邊個單位？唔方便講單位，亦可以留電話。'
PHONE = r'(?:\+?852[ -]?)?[2-9]\d{3}[ -]?\d{4}'


def care_plan(history):
    text = history[-1]['content'].strip()
    prior = history[-2]['content'] if len(history) > 1 and history[-2]['role'] == 'assistant' else ''
    offered = prior.endswith(CARE_OFFER)
    pending = prior == CARE_LOCATION
    declined = bool(re.search(r'唔使|唔想|不用|不要|不想|取消|算啦|只想.*(?:聽|听|陪|傾)|想.*繼續.*傾|想(?:你|同你).*(?:陪|傾|聽|听|聊)', text))
    direct = bool(re.search(r'(?:幫我|帮我|安排|希望|想|請|请).*(?:管理人員|管理人员|管理處|管理处|職員|职员|社工).*(?:聯絡|联系|聯繫|联络|搵我|找我|傾|陪)', text)) and not declined
    consent = bool(re.match(r'^(?:我)?(?:好(?:呀|啊|嘅|的)?|可以(?:呀|啊)?|想(?:呀|啊|你幫我|你幫手)?|需要|麻煩你|麻烦你|幫我|帮我|安排|係(?:呀|啊)?|是的|同意|願意|愿意)(?:[，,。！!\s]|$|安排|聯絡|联系|幫|帮|你幫|你帮|我住|我係|我是)', text))
    if (offered or pending) and declined:
        if pending:
            return {'answer': '好，暫時唔安排聯絡。多謝你講清楚，我留喺度陪你，你可以慢慢講。'}
        return {'context': '居民暫時不想安排管理人員聯絡；先專心聽，承接剛才的煩惱，不再問單位或勸他轉交。'}
    if pending or direct or (offered and consent):
        original = text
        if pending and len(history) >= 3:
            original = history[-3]['content']
            for item in reversed(history[:-1]):
                if item['role'] == 'user' and re.search(r'孤單|孤独|壓力|压力|煩惱|烦恼|唔開心|不開心|不开心|心煩', item['content']):
                    original = item['content']
                    break
        for index in range(len(history)-2, 0, -1):
            if history[index]['role'] == 'assistant' and history[index]['content'].endswith(CARE_OFFER):
                original = history[index-1]['content']
                break
        unit = unit_reference(text) or unit_reference(original)
        phone = re.search(PHONE, text) or re.search(PHONE, original)
        if not (unit.endswith('室') or phone):
            if pending:
                return {'context': '已問過聯絡方式，居民未提供；唔好再追問住址、單位或聯絡安排，先承接佢而家講嘅話題。'}
            return {'answer': CARE_LOCATION}
        return {'case': {'kind': 'human_support', 'location': unit,
            'contact': phone[0] if phone else '',
            'message': '請管理人員主動聯絡住戶（居民已在對話同意）。居民需要：'+original[:800]}}
    recent_offer = any(item['role'] == 'assistant' and (item['content'].endswith(CARE_OFFER) or item['content'] == CARE_LOCATION)
                       for item in history[-12:])
    distress = re.search(r'唔開心|不開心|不开心|煩惱|烦恼|心煩|心烦|壓力|压力|孤單|孤独|委屈|冇人理|沒人理|好難受|很難受|好傷心|很伤心|想傾訴|想倾诉', text)
    operational = re.search(r'漏水|垃圾|噪音|壞咗|故障|壞了|坏了', text)
    hypothetical = re.search(r'如果|假如|例如', text)
    if distress and not operational and not declined and not recent_offer and not hypothetical:
        if any(item['role'] == 'user' and re.search(r'唔開心|不開心|不开心|煩惱|烦恼|心煩|心烦|壓力|压力|孤單|孤独|委屈|冇人理|好難受|好傷心', item['content']) for item in history[:-1]):
            return {'context': '繼續承接居民講過嘅具體感受同事情，自然傾偈；唔再套用首次安慰句，唔問住址、點幫你或安排職員聯絡。'}
        reflection = '聽落呢排真係唔容易。唔使諗好點講先開口，你慢慢講，我會用心聽。'
        if re.search(r'壓力|压力', text) and re.search(r'覺得好?孤單|觉得很?孤独|好孤單|很孤独', text):
            reflection = '壓力咁大，仲覺得孤單，真係唔容易。唔使急住諗辦法，我哋慢慢傾。'
        elif re.search(r'覺得好?孤單|觉得很?孤独|好孤單|很孤独', text):
            reflection = '覺得孤單嗰陣，想有人傾吓都好自然。你慢慢講，日常小事都可以傾。'
        return {'answer': reflection, 'kind': 'reflection'}
    return {}

