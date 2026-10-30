"""A single dashboard; provider quota and local reservations stay distinct."""
import json
import math
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from edge_hub.cloud_allowance import LIMITS
from edge_hub.cloud_credentials import credential_path, settings_root
from edge_hub.usage_snapshot import usage_snapshot


def counter(used, limit):
    valid = type(used) is int and used >= 0 and type(limit) is int and limit > 0
    return {'used': used if valid else None, 'limit': limit if valid else None,
            'remaining': max(0, limit-used) if valid else None,
            'percent': round(max(0, limit-used)/limit*100, 1) if valid else None}


def official_dashboard_snapshot(stamp):
    # A dated, manually observed official dashboard reading is not a live quota API.
    path = Path(__file__).resolve().parents[1]/'.runtime/cloudflare-official-snapshot.json'
    try:
        item = json.loads(path.read_text(encoding='utf-8'))
        observed = datetime.fromisoformat(item['observed_at'])
        used = item['used']
        if (observed.date() != stamp.astimezone(UTC).date() or observed > stamp
                or type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 10000):
            return None
        return {'status': 'snapshot', 'used': used, 'limit': 10000, 'remaining': round(10000-used, 2),
                'percent': round((10000-used)/100, 2), 'unit': 'Neurons',
                'source': 'official_dashboard_observation', 'updated_at_ms': int(observed.timestamp()*1000),
                'allocation': '官方頁面記錄，並非即時更新；其後用量可能已增加。'}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def capacity_summary():
    """A labelled planning scenario from a recorded window, never a quota claim."""
    try:
        path = Path(__file__).resolve().parents[1]/'.runtime/quota-capacity-plan.json'
        plan = json.loads(path.read_text(encoding='utf-8'))
        people, turns = plan['daily_people'], plan['turns_each']
        if type(people) is not int or type(turns) is not int or not 0 < people <= 10000 or not 0 < turns <= 100:
            return ''
        sample_turns = plan['sample_spoken_turns']
        neurons, characters = plan['sample_neuron_reservation'], plan['sample_azure_characters']
        if any(type(n) is not int or n <= 0 for n in (sample_turns, neurons, characters)):
            return ''
        daily = round(people*turns/sample_turns*neurons)
        monthly = round(people*turns/sample_turns*characters*31)
        capacity = int(LIMITS['cloudflare_gemma_neuron_reservations'][1]/(turns/sample_turns*neurons))
        return (f'目標每日 {people} 位 × 每位 {turns} 輪：樣本估算 Gemma 約 '
            f'{daily:,}／8,000 本機預留 Neurons／日（約 {capacity} 位，'
            +('偏緊' if daily > 8000 else '仍有餘量')+'）；'
            f'曉曼約 {monthly:,}／400,000 計費字元／31 日。'
            f'若每位每天搜尋一次，約 {people*31:,} credits／31 日；每輪都搜尋則約 {people*turns*31:,}。'
            '按公開三輪對話及先前完整語音試用比例估算；長短、角色設定、上下文及快取會改變消耗，不是官方餘額或容量保證。')
    except (OSError, ValueError, KeyError, TypeError):
        return ''


def overview(tavily, *, voice_configured, database=None, balance=None, now=None):
    stamp = now or datetime.now(UTC)
    hk = timezone(timedelta(hours=8))
    tomorrow = (stamp+timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    next_month = (stamp.replace(day=28)+timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    def reset(interval):
        when = next_month if interval == 'month' else tomorrow
        return when.strftime('%Y-%m-%dT%H:%M:%SZ'), when.astimezone(hk).strftime('%Y-%m-%d %H:%M（香港）')
    database = database or settings_root()/'cloud-usage.sqlite3'
    snapshot = usage_snapshot(database, (stamp.strftime('%Y-%m-%d'), stamp.strftime('%Y-%m')))
    values, readable = snapshot or {}, snapshot is not None

    def guard(meters):
        interval = LIMITS[meters[0]][0]
        counters = [{**counter(values.get((meter, stamp.strftime('%Y-%m' if LIMITS[meter][0] == 'month' else '%Y-%m-%d')), 0) if readable else None, LIMITS[meter][1]),
                     'meter': meter} for meter in meters]
        percentages = [item['percent'] for item in counters]
        return {'status': 'ok' if all(p is not None for p in percentages) else 'unavailable',
                'interval': interval, 'reset_at': reset(interval)[0], 'period': '本機下次重設：'+reset(interval)[1],
                'percent': min(percentages) if all(p is not None for p in percentages) else None,
                'counters': counters}

    data = tavily.get('data') or {}
    rows = [{'id': 'tavily', 'platform': 'Tavily', 'service': '網上搜尋',
        'provider': {**counter(data.get('used'), data.get('limit')),
                     'status': tavily['status'], 'period': data.get('reset_rule'),
                     'updated_at_ms': tavily.get('updated_at_ms')}, 'guard': None,
        'active': True, 'purpose': '居民問最新或未有資料的問題時，自動上網搜尋並附來源。',
        'note': '官方帳戶方案 credits；本系統基本搜尋通常每次 1 credit。',
        'reset_label': f'官方下次重設：{next_month:%Y-%m-%d}（平台未提供時區及精確時刻）'}]
    rows[0]['provider']['unit'] = 'credits'
    if type(data.get('key_limit')) is int and data['key_limit'] > 0:
        rows.append({'id': 'tavily-key', 'platform': 'Tavily', 'service': '此 key 限制',
            'provider': {**counter(data.get('key_used'), data['key_limit']),
                         'status': tavily['status'], 'updated_at_ms': tavily.get('updated_at_ms')},
            'guard': None, 'active': True, 'purpose': '搜尋同時受此 key 上限限制，不能和帳戶額度相加。',
            'note': 'key 限制是否重設未由平台提供，不能當每月重新補充。'})

    def row(identity, platform, service, meters, note, configured=True, *, active=False, purpose='', allocation=None, reset_label=None):
        rows.append({'id': identity, 'platform': platform, 'service': service,
            'provider': {'percent': None, 'status': 'not_reported' if configured else 'not_configured'},
            'guard': guard(meters) if meters else None, 'note': note, 'active': active, 'purpose': purpose,
            'reset_label': reset_label})
        if allocation:
            rows[-1]['provider']['allocation'] = allocation

    row('google-chat', 'Google', 'Google 對話用量',
        ('gemini_chat_requests', 'gemini_chat_characters'),
        '舊 Google 入口歷史用量，不是目前 Cloudflare Gemma 的餘額。', purpose='曾供應居民 Gemma 對話；目前居民路徑已改 Cloudflare。')
    from edge_hub import cloudflare_gemma
    if cloudflare_gemma.selected():
        row('cloudflare-gemma', 'Cloudflare Workers Free', '居民 Gemma 對話',
            ('cloudflare_gemma_neuron_reservations',),
            '本機以 8,000 Neurons 預留估算作保守限制，並非官方已用或餘額。用完停止，不升級或轉付費。',
            active=True, purpose='Gemma 4 26B A4B 理解居民需要、自然聊天，保留本輪上下文。',
            allocation='免費上限：10,000 Neurons／日；官方剩餘未回傳', reset_label='官方下次重設：'+reset('day')[1])
        snapshot = official_dashboard_snapshot(stamp)
        if snapshot:
            rows[-1]['provider'] = snapshot
    from edge_hub import azure_voice
    if azure_voice.configured():
        row('azure-voice', 'Microsoft Azure Speech · Free F0', '廣東話語音（曉曼）',
            ('azure_tts_characters',), '中文每字計 2 個計費字元；本機保守上限 400,000。沒有本機聲線或付費備援。',
            active=True, purpose='將數字人每句回覆合成香港廣東話，供居民收聽。',
            allocation='免費上限：500,000 計費字元／月；官方剩餘未回傳',
            reset_label='官方按月計算，資源精確重設日期未取得；不與本機重設時間混為一談。')
    row('google-voice', 'Google', 'Google 語音用量',
        ('gemini_tts_requests', 'gemini_tts_characters'),
        '歷史計數保留，現在居民朗讀用 Azure 曉曼；不代表仍使用 Google 語音。', voice_configured,
        purpose='曾測試 HKSoft 等廣東話聲線，目前居民未使用。')
    if credential_path().is_file():
        row('siliconflow-chat', 'SiliconFlow', '後備對話服務',
            ('siliconflow_chat_requests', 'siliconflow_input_characters'),
            '操作員工作室備援，不是居民 Gemma 的下一個模型；官方餘額及重設日期未取得。', purpose='原操作員工作室／舊對話備援，居民路徑不會自動切到此平台。')
        row('siliconflow-stt', 'SiliconFlow', '後備語音辨識',
            ('siliconflow_stt_seconds',), '平常使用本機 SenseVoice，居民未消耗此項。', purpose='操作員可用的舊雲端語音辨識備援。')
    for identity, platform, filename, purpose in (
            ('mimo-trial', '小米 MiMo', 'mimo-voice-trial-key.dpapi', '曾測試冰糖粵語，居民現在使用曉曼。'),
            ('openrouter-trial', 'OpenRouter', 'openrouter-free-test-key.dpapi', '免費模型比較；Gemma 試驗限流，未採用。'),
            ('mistral-trial', 'Mistral', 'mistral-free-test-key.dpapi', '文字與語音比較，未接入居民正式流程。'),
            ('glm-trial', '智譜 BigModel', 'glm-free-test-key.dpapi', '免費 GLM 試驗，未接入居民正式流程。')):
        if (settings_root()/filename).is_file():
            row(identity, platform, '試用服務', (), '目前不供應居民服務；剩餘額度及重設時間未核對，不顯示過時試驗數字。', purpose=purpose)
    return {'rows': rows, 'updated_at_ms': int(stamp.timestamp()*1000),
            'active_rows': [item for item in rows if item.get('active')],
            'other_rows': [item for item in rows if not item.get('active')],
            'local_functions': '本機 SenseVoice 負責語音輸入；屋苑資料、個案進度與明確記憶由本機處理，不消耗以上雲端 API 額度。',
            'capacity_summary': capacity_summary(),
            'explanation': '進度條表示剩餘比例。本機保守限制不是平台官方餘額；未取得數字時不估算百分比。'}
