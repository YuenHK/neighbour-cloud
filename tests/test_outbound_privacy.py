import asyncio
import json

import httpx

from edge_hub.outbound_privacy import messages_for_cloud, redact


def test_removes_identifiers_from_every_role_without_mutating_local_case():
    private = '我叫阿明，A座十二樓B室漏水，電話9123 4567，電郵ming@example.org，身份證A123456(7)。'
    source = [{'role': role, 'content': private} for role in ('system', 'user', 'assistant')]
    result = messages_for_cloud(source)
    assert all(item['content'] == private for item in source)
    for item in result:
        assert all(value not in item['content'] for value in ('阿明', '十二樓', '9123', 'ming@', 'A123456'))
        assert '漏水' in item['content']


def test_normal_chat_keeps_emotion_context_and_conversation_intact():
    text = '最近照顧家人好攰，頭先講想整香蕉蛋糕；會所有咩活動？'
    assert redact(text) == text
    assert '舊地址' not in redact('我住喺舊地址，想查社區支援。')
    assert '2468' not in redact('電話＋８５２ ２４６８－１３５７')


def test_search_private_query_never_obtains_credentials_or_calls_network(monkeypatch):
    from edge_hub import estate_services
    service = estate_services.ResidentServices(None, None)
    monkeypatch.setattr(estate_services, 'search_key', lambda: (_ for _ in ()).throw(AssertionError('private request left device')))
    result = asyncio.run(service.search('我叫阿明，住A座12樓B室，幫我查支援'))
    assert result['search_status'] == 'private_query_not_sent'
    assert not service.search_pending and not service.search_cache


def test_real_cloudflare_payload_is_scrubbed_before_dispatch(tmp_path, monkeypatch):
    from edge_hub import cloudflare_gemma as cf
    monkeypatch.setattr(cf, 'settings_root', lambda: tmp_path)
    monkeypatch.setattr(cf, 'configuration', lambda: {'account_id': 'synthetic'})
    monkeypatch.setattr(cf, '_crypt', lambda *a, **k: b'synthetic')
    monkeypatch.setattr(cf, 'reserve', lambda m, *_args: None)
    monkeypatch.setattr(cf, '_busy', False)
    monkeypatch.setattr(cf, '_until', 0)
    (tmp_path/'cloudflare-gemma-key.dpapi').write_bytes(b'fake')
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await cf.complete({'stream': False, 'messages': [{'role': 'user', 'content': 'A座12樓B室漏水，電話91234567'}]},
                                         prompt='關心居民', context='聯絡 ming@example.org', client=client)
            assert response.status_code == 200
    asyncio.run(run())
    packed = json.dumps(sent, ensure_ascii=False)
    assert all(value not in packed for value in ('91234567', '12樓', 'ming@example.org'))
    assert '漏水' in packed
