"""Explicit resident disclosures: immediate support, not psychiatric assessment.

Official service information checked 2026-10-27. No unverified helpline numbers,
external notification, model-generated diagnosis or automatic contact collection.
"""
import hashlib
import re

PREFIX = '【需即時關懷】'
SAFETY_QUESTION = '你而家有冇已經傷害自己，或者正準備立即傷害自己？'
CONTACT_QUESTION = '如果你願意管理人員主動聯絡，可以講單位或電話；唔方便講都可以繼續傾。'
CARE_CONTEXT = ('專門關懷流程：本輪屬情緒／壓力支援，先承接居民具體困擾，溫柔自然地陪傾，唔作疾病診斷。'
                '最多問一個貼題問題了解需要；居民問方法時先提供一項容易做到嘅初階支援，再聽反應。'
                '後台只按實際回條交代，尊重居民拒絕聯絡；自願提供嘅單位由系統保存，唔反覆追問。'
                '唔虛構機構、師傅、電話或已聯絡人；有即時自傷風險先轉安全優先流程。')
FAMILY_URL = 'https://www.swd.gov.hk/tc/pubsvc/family/cat_family/ifs/'
CRISIS_URL = 'https://www.swd.gov.hk/tc/pubsvc/family/cat_family/familycris/'
MONEY_URL = 'https://www.swd.gov.hk/tc/pubsvc/socsecu/comprehens/cssa/'
EMERGENCY = ('如果你已經受傷、服用咗可能有害嘅嘢，或者就快傷害自己，請立即搵身邊人陪住你；'
             '喺香港請打 999 求救，或者請旁邊嘅人代打。可以安全做到嘅話，先離開危險位置同物品，唔好一個人留低。'
             '呢度嘅工作台記錄唔等於已召喚救護車。')


def disclosure(text):
    """Only explicit first-person current statements; ambiguous text stays conversational."""
    if re.search(r'假設|假设|假如|模擬|模拟|測試|测试|例如|新聞|新闻|小說|小说|角色扮演|(?:朋友|鄰居|邻居|有人|佢|他|她).*(?:自殺|自杀|自殘|自残|想死)', text):
        return False
    if re.search(r'(?:冇|沒有|没有|唔會|不會|不会|不想|唔想)(?:再)?(?:自殺|自杀|自殘|自残|傷害自己|伤害自己|跳樓|跳楼|死)', text):
        return False
    return bool(re.search(r'(?:我|自己).{0,35}(?:想自殺|想自杀|想死|唔想活|不想活|活不下去|唔想再活|唔想做人|想結束生命|想结束生命|想輕生|想轻生|有自殺念頭|有自杀念头|想傷害自己|想伤害自己|想自殘|想自残|已經傷害自己|已经伤害自己|想跳[樓楼]|跳[樓楼].{0,6}(?:衝動|冲动|念頭|念头))', text))


def crisis_plan(history):
    text = history[-1]['content'].strip()
    first = next((item['content'] for item in history if item['role'] == 'user' and disclosure(item['content'])), None)
    if first is None:
        return None
    assistants = [item['content'] for item in history[:-1] if item['role'] == 'assistant']
    # Follow only an active support exchange, not an arbitrary old disclosure.
    active = any(SAFETY_QUESTION in item or '身邊人陪住你' in item or '可以先揀一件做得到嘅小事' in item
                 or CONTACT_QUESTION in item or FAMILY_URL in item or '唔使逼自己即刻平靜' in item
                 for item in assistants[-3:])
    if not disclosure(text) and not active:
        return None
    prior = assistants[-1] if assistants else ''
    immediate = bool(re.search(r'已經受傷|已经受伤|已經傷害自己|已经伤害自己|啱啱.*傷害自己|而家就.*(?:自殺|自杀|跳)|已經食咗.*藥|已经吃了.*药', text))
    if SAFETY_QUESTION in prior and re.match(r'^(?:有|係|是|已經|已经|正準備|正准备)', text):
        immediate = True
    if immediate:
        answer = '多謝你即刻講畀我知，依家先顧住你嘅安全。'+EMERGENCY
    elif not assistants or not active:
        answer = '生活逼得咁辛苦，連繼續落去都覺得好難，多謝你肯講出嚟。依家先一齊顧住你嘅安全。'+SAFETY_QUESTION
    elif re.search(r'放鬆|放松|呼吸|平靜|平静|緊張|紧张', text):
        answer = ('我哋可以慢慢嚟，唔使逼自己即刻平靜。先感受雙腳踩住地面，望吓周圍，講出三樣你見到嘅嘢，保持舒服嘅正常呼吸；唔舒服就停。'
                  '同時搵一位信得過嘅人陪住你，呢個練習唔代替真人支援；如果即時有危險，喺香港請打 999。')
    elif re.search(r'電話|电话|熱線|热线|打畀|打俾', text):
        # Never ask a model to invent a crisis number or reuse a redacted
        # placeholder. Only the established local emergency number and the
        # already reviewed official directory are supplied by this route.
        answer = ('如果有即時危險、已經受傷，或者就快傷害自己，喺香港請打 999，亦可以請身邊人代打。'
                  '而家先搵一位信得過嘅人陪住你。其他支援服務嘅聯絡資料要先核實，唔會畀你錯電話；'
                  '社署官方服務資料可以喺呢度查看：'+FAMILY_URL+' 。管理工作台記錄唔等於已召喚緊急服務。')
    elif re.search(r'機構|机构|渠道|社工|經濟|经济|生活費|生活费|錢|钱|辦法|办法|方法|邊度|哪里|求助', text):
        answer = ('唔使你一個人扛晒。可以先搵綜合家庭服務中心社工，一齊整理生活同經濟壓力：'+FAMILY_URL
                  +' 。如果正面對家庭危機，明愛向晴軒有危機介入同支援服務：'+CRISIS_URL
                  +' 。生活開支方面，社工亦可幫你了解綜援等支援，是否合資格要由相關部門評估：'+MONEY_URL+' 。')
    elif CONTACT_QUESTION in prior:
        answer = '多謝你講畀我知。我會保留你選擇嘅聯絡安排；未有職員接手前，我唔會話已有人到場。你亦可以繼續講最困擾你嗰件事。'
    elif re.search(r'(?:幫我|帮我|想|希望|可以|麻煩|麻烦).*(?:管理|職員|职员|聯絡|联系|社工)', text):
        answer = '可以，我會將你願意接受主動聯絡嘅需要交畀住戶支援。'+CONTACT_QUESTION
    else:
        answer = ('聽到你講呢啲，我會認真對待。可以先揀一件做得到嘅小事：搵信得過嘅人陪你，或者一齊搵社工處理壓住你嘅生活難題。'
                  '你而家比較想有人陪住，定先傾眼前最難捱嗰件事？')
    return {'answer': answer, 'disclosure': first[:700], 'contact_pending': CONTACT_QUESTION in prior}


def session_submission(session_id, submission_id):
    return hashlib.sha256(('resident-support:'+session_id).encode()).hexdigest()[:32] if session_id else submission_id
