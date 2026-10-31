"""Proactive local staff intake from expressed needs, never a psychiatric diagnosis."""
import hashlib
import re

from edge_hub.cantonese_terms import normalize as normalize_terms
from edge_hub.cantonese_terms import sorting_question
from edge_hub.resident_care import PHONE
from edge_hub.resident_cases import spoken_number, unit_reference

CARE_PREFIX = '【關懷跟進】'
REQUEST_PREFIX = '【居民需要】'
DECLINED = '【居民暫不希望主動聯絡】'
REQUESTED = '【居民希望主動聯絡】'
TOPICS = ('care', 'water', 'litter', 'lift', 'repair', 'noise', 'incident', 'danger', 'fees', 'application', 'assistance')
HYPOTHETICAL = r'如果|假如|假設|假设|例如|模擬|模拟|測試|测试|小說|小说|新聞|新闻|角色扮演'
OPT_OUT = r'(?:唔好|不要|唔想|不想|不用|唔使).{0,10}(?:轉交|转交|通知|記錄|记录|管理|職員|职员|聯絡|联系|搵人|找人|叫人|社工)|取消(?:轉交|转交|聯絡|联系|跟進|跟进)'
OUTREACH = r'(?:幫我|帮我|請|请|想|希望|需要|安排).{0,15}(?:管理|職員|职员|保安|社工).{0,12}(?:聯絡|联系|搵我|找我|跟進|跟进)'


def identity(session, topic):
    return hashlib.sha256(f'resident-auto:{session}:{topic}'.encode()).hexdigest()[:32]


def expressed_need(history, *, reported_context=False):
    text = normalize_terms(history[-1]['content'])
    if re.search(HYPOTHETICAL, text) or re.search(OPT_OUT, text):
        return None
    users = [item['content'] for item in history if item['role'] == 'user']
    previous_opt_out = any(re.search(OPT_OUT, item) for item in users[:-1])
    if previous_opt_out and not re.search(OUTREACH, text):
        return None
    if sorting_question(text):
        return None
    self_report = bool(re.search(r'我(?:哋|們|们)?|自己|最近|呢排|近排', text))
    third_party_only = bool(re.search(r'(?:朋友|鄰居|邻居|同事|家人|媽媽|妈妈|爸爸|佢|他|她).{0,12}(?:壓力|压力|焦慮|焦虑|孤單|孤独|唔開心)', text)) and not re.search(r'我(?:最近|而家|覺得|觉得|感到|有啲|有点|都|好|很)', text)
    self_report = (self_report or bool(re.search(r'壓力好大|好大壓力|压力好大|好焦慮|好焦虑|好孤單|好孤独|頂唔順|捱唔住', text))) and not third_party_only
    distress = bool(re.search(r'壓力|压力|焦慮|焦虑|恐慌|情緒|情绪|孤單|孤独|冇人理|沒人理|好難受|很難受|好傷心|很伤心|撐唔住|撑不住|頂唔順|頂唔住|捱唔住|失眠', text))
    mild = bool(re.search(r'唔開心|不開心|不开心|心煩|心烦|委屈|煩惱|烦恼|心情.{0,4}(?:唔好|唔係幾好|低落)|好煩|好烦|想喊|想哭|迷惘|冇人聽我講', text))
    # A direct disclosure can omit "我" in Cantonese. Third-party and public
    # information exclusions still apply, as do explicit contact opt-outs.
    self_report = self_report or (not third_party_only and bool(re.match(r'^(?:唔知點解|呢排|近排|最近|成日).{0,12}(?:想喊|想哭|心情|低落|迷惘)', text)))
    explicit_condition = bool(re.search(r'我(?:曾經|曾经|已經|已经)?(?:有|患有|被診斷|被诊断).{0,8}(?:抑鬱|抑郁|焦慮症|焦虑症|精神病|精神分裂|躁鬱|躁郁)', text))
    information = bool(re.search(r'係咩|是什麼|是什么|定義|定义|介紹|介绍|機構|机构|熱線|热线', text)) and not re.search(r'我.{0,12}(?:需要|想搵|想找|幫我|帮我)', text)
    negated = bool(re.search(r'(?:冇|沒有|没有|唔覺得|不覺得|不觉得).{0,4}(?:壓力|压力|唔開心|焦慮|焦虑|孤單|孤独|失眠)', text))
    # The operator explicitly requested early support for potential distress,
    # including a first mild disclosure. This is a concern record, not a diagnosis.
    if (explicit_condition or (self_report and not information and not negated and (distress or mild))):
        return {'topic': 'care', 'kind': 'human_support', 'reason': '居民表達情緒／壓力或主動提及支援需要，請職員關懷核實。'}
    if re.search(OUTREACH, text) and any(re.search(r'壓力|压力|孤單|孤独|情緒|情绪|唔開心|難受|失眠', item) for item in users):
        return {'topic': 'care', 'kind': 'human_support', 'reason': '居民希望職員聯絡，先前有表達關懷需要。'}
    if re.search(r'我(?:想|需要|希望).{0,10}(?:社工|真人).{0,12}(?:幫|帮|支援|協助|协助|聯絡|联系|傾|見)', text):
        return {'topic': 'care', 'kind': 'human_support', 'reason': '居民主動希望獲得真人／社工支援，聯絡安排待職員核實。'}
    # A concrete local report may be phrased as a question. A general how-to is not a report.
    local_report = reported_context or bool(re.search(r'我(?:屋企|家|嘅|的|住)|屋企|屋內|屋内|(?:大堂|走廊|停車場|停车场|花園|花园|平台|門口|门口)|(?:見到|看到|發現|发现)|[A-Za-z0-9一二三四五六七八九十]+座|有(?:好多|一堆|成堆|一灘|啲)?(?:垃圾|積水|积水|漏水)|^水喉漏水[。！!]*$', text))
    request = bool(re.search(r'幫我|帮我|幫手|帮忙|搵人|找人|報修|报修|通知|投訴|投诉|處理|处理|安排|我想|我需要|我希望', text))
    for topic, kind, pattern in (
        ('danger', 'hazard', r'火警|著火|着火|煙味|烟味|被困|困住|有人跌低|有人打交|漏電|漏电|火花|插蘇.*(?:焦|黑|煙|燶)|電線.*(?:破|外露|露銅)'),
        ('water', 'water', r'漏水|積水|积水|(?:水喉|水管).*(?:爆|壞|坏|有問題|有问题|塞)'),
        ('litter', 'litter', r'垃圾|污糟|清潔|清洁'),
        ('lift', 'general', r'升降機|電梯|电梯'),
        ('repair', 'general', r'壞咗|壞了|坏了|故障|維修|维修|燈.*(?:唔著|不亮)'),
        ('noise', 'general', r'噪音|半夜.*嘈|樓上.*嘈|楼上.*吵|隔籬屋.*嘈|爭執|争执'),
        ('incident', 'general', r'騷擾|骚扰|擅闖|擅闯|禁區有人|禁区有人|門長開|门长开|門未關|门未关'),
        ('fees', 'general', r'管理費|管理费|欠費|欠费|分期'),
        ('application', 'general', r'申請|申请|續期|续期|辦理|办理'),
    ):
        if topic == 'danger' and not local_report and re.search(r'點樣|如何|係咩|解釋|想知|想了解', text):
            continue
        if topic == 'lift' and re.search(r'點樣用|如何使用|點樣運作|點運作', text):
            continue
        if topic == 'fees' and re.search(r'點樣計|收費標準|計法|幾多錢', text) and not re.search(r'交唔起|分期|欠|多收|收錯', text):
            continue
        facility_fault = topic in ('lift', 'repair') and bool(re.search(r'壞咗|壞了|坏了|故障|停咗|唔郁|唔開門|唔著', text))
        # Negation and completion apply to their own clause/topic, not unrelated hazards.
        clauses = re.split(r'[，,。；;！？!?]|但係|不過|但', text)
        positive = any(re.search(pattern, clause) and not re.search(r'(?:冇|沒有|没有).{0,3}(?:'+pattern+')', clause)
                       and not re.search(r'(?:已經|已|而家|現在).{0,6}(?:處理好|清好|清走|抹乾|搞掂|修好)', clause)
                       for clause in clauses)
        if positive and (local_report or request or facility_fault):
            return {'topic': topic, 'kind': kind, 'reason': '居民現場報告，請保安核實具體事件，不判斷任何人身份或有罪。' if topic == 'incident' else '居民提出需要職員核實或協助的屋苑事項。'}
    if re.search(OUTREACH, text):
        return {'topic': 'assistance', 'kind': 'general', 'reason': '居民希望職員主動聯絡或跟進，詳細需要待核實。'}
    if self_report and re.search(r'(?:冇錢|沒錢|没有钱).{0,10}(?:交租|開飯|开饭|食飯|吃饭|生活)|(?:交唔起|付不起|欠).{0,8}(?:租|管理費|水電)|(?:失業|失业).{0,15}(?:生活|開支|難|困難)', text):
        return {'topic': 'assistance', 'kind': 'general', 'reason': '居民表達生活或經濟困難，需要職員了解可提供的協助；不判定福利資格。'}
    if re.search(r'我(?:哋|們|们)?(?:而家|最近|呢排)?(?:遇到困難|遇到困难|有困難|有困难|需要幫助|需要帮助|需要協助|需要协助)|幫我安排管理|帮我安排管理', text):
        return {'topic': 'assistance', 'kind': 'general', 'reason': '居民直接提出需要協助，細節待職員核實。'}
    return None


def contact_values(text):
    unit = unit_reference(text)
    labels = r'我(?:嘅|的)?(?:電話|电话)|(?:聯絡|联系|搵|找)我|(?:^|[，,；;\s])(?:電話|电话)|可以打|打畀我'
    phone = re.search(rf'(?:{labels})[係是：:\s]*(?P<number>{PHONE})', text)
    standalone = re.search(PHONE, text) if re.fullmatch(r'[\s+\d-]+', text) else None
    unit_volunteered = bool(re.search(r'我(?:住|係|是|嘅單位|的單位|的单位)', text)) or bool(
        re.fullmatch(r'[A-Za-z0-9一二三四五六七八九十百千零〇兩两座棟栋樓楼層层室單位单位號号\s]+', text.strip('，。,.！! ')))
    return unit if unit_volunteered else '', phone['number'] if phone else standalone[0] if standalone else ''


def session_contacts(history):
    """Only the current resident's volunteered values, never assistant guesses."""
    unit = phone = ''
    for item in history:
        if item['role'] != 'user':
            continue
        text = item['content']
        if re.search(HYPOTHETICAL, text):
            continue
        if re.search(OPT_OUT, text):
            unit = phone = ''
            continue
        new_unit, new_phone = contact_values(text)
        unit, phone = new_unit or unit, new_phone or phone
    return unit, phone


def capture_contacts(history, body, store):
    """Capture volunteered detail before a progress/crisis branch can return."""
    if not body.session_id or not body.submission_id:
        return
    text = history[-1]['content']
    if re.search(HYPOTHETICAL, text):
        return
    unit, phone = contact_values(text)
    if not unit and not phone:
        return
    from edge_hub.resident_threads import session_rows
    rows = session_rows(store, body.session_id)
    store.update_automatic_contacts([row['submission_id'] for row in rows], unit=unit, phone=phone)
    for row in rows:
        if row['kind'] == 'human_support':
            store.support_contact(row['submission_id'], f'{unit} {phone}')


def intake(history, body, store, *, unanswered_estate=False):
    """Return a confirmed local receipt separately from model completion success."""
    if not body.session_id or not body.submission_id:
        return None
    text = history[-1]['content'].strip()
    if re.search(HYPOTHETICAL, text):
        return None
    from edge_hub.estate_services import public_information_query
    from edge_hub.resident_threads import REFERENCE, record, replay, select_case, session_rows
    from edge_hub.resident_threads import receipt as issue_receipt
    previous = replay(store, body.session_id, body.submission_id, quote=text)
    if previous:
        result = issue_receipt(store, previous)
        return followup_receipt(result)
    need = expressed_need(history)
    # Public how-to queries must neither create nor append to an earlier report.
    # A clear local incident takes precedence over a broad question-word match.
    if sorting_question(text) or (need is None and public_information_query(text) and not re.search(REFERENCE, text)):
        return None
    declined = bool(re.search(OPT_OUT, text))
    unit, phone = contact_values(text)
    if not declined:
        prior_unit, prior_phone = session_contacts(history)
        unit, phone = unit or prior_unit, phone or prior_phone
    requested = bool(re.search(OUTREACH, text))
    rows = session_rows(store, body.session_id)
    updated = []
    # Volunteered contact / contact preference updates existing session cases, never staff notes.
    if declined or requested or unit or phone:
        updated = store.update_automatic_contacts([row['submission_id'] for row in rows],
            unit=unit, phone=phone, preference=DECLINED if declined else REQUESTED if requested else '')
    if (need is None and unanswered_estate and not declined and not re.search(HYPOTHETICAL, text)
            and not any(re.search(OPT_OUT, item['content']) for item in history if item['role'] == 'user')):
        need = {'topic': 'assistance', 'kind': 'general', 'reason': '屋苑資料暫未核實，居民查詢需要職員回覆。'}
    opted_out = any(re.search(OPT_OUT, item['content']) for item in history if item['role'] == 'user')
    selected = None if declined or (opted_out and not requested) else select_case(store, rows, text, need)
    if need is None and selected is not None:
        need = expressed_need(history, reported_context=True) or {
            'topic': selected['topic'], 'kind': selected['kind'], 'reason': '居民補充本輪已提出的事項。'}
    if need is None:
        if updated:
            return {**updated[0], 'delivered': True,
                'notice': ('已記錄你暫時唔希望職員主動聯絡，會由職員先核實。' if declined
                           else '已補充本輪個案的聯絡安排，等候職員跟進。')}
        return None
    from edge_hub.service_desk import ResidentCase
    place = re.search(r'(?:大堂|走廊|升降機|電梯|电梯|停車場|停车场|花園|花园|平台|門口|门口)[^，。！？\n]{0,12}', text)
    location = unit if need['kind'] == 'human_support' else unit_reference(text) or (place[0] if place else unit)
    prefix = CARE_PREFIX if need['kind'] == 'human_support' else REQUEST_PREFIX
    message = f'{prefix}{need["reason"]}\n居民原話：{text[:900]}\n主動分流，待職員核實；不是醫療診斷，亦未代表已聯絡到人。'
    if requested:
        message += '\n'+REQUESTED
    # A distinct issue uses the stable turn identity, not a reusable topic bucket.
    issue_id = hashlib.sha256(f'resident-issue:{body.session_id}:{body.submission_id}'.encode()).hexdigest()[:32]
    receipt = record(store, ResidentCase(submission_id=issue_id,
        kind=need['kind'], location=location[:120], contact=phone, message=message,
        profile=body.profile, confirmed=True), session=body.session_id, turn=body.submission_id,
        topic=need['topic'], selected=selected, quote=text, outreach_requested=requested)
    return followup_receipt(receipt)


def followup_receipt(receipt):
    return {**receipt, 'delivered': True, 'group': 'care' if receipt['kind'] == 'human_support' else 'requests',
            'notice': f'{"已補充原個案" if receipt["replayed"] else "已交到管理工作台"}，編號 {spoken_number(receipt["case_number"])}。'
                      +('尚未提供單位或電話，方便時可以補充，職員先核實跟進。' if not receipt['contact_available'] else '等候職員接手聯絡。')}
