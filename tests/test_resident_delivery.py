import asyncio
import json

import httpx

from edge_hub.resident_delivery import ChatSentences
from edge_hub.resident_inference import native_local


def history(text='隨便傾吓，唔使成日問我問題。'):
    return [{'role': 'user', 'content': text}]


def test_partial_sentence_is_not_lost_and_no_question_request_keeps_acknowledgement():
    output = ChatSentences(history())
    assert output.feed('好呀，') == []
    assert output.feed('我哋慢慢傾。你住邊？') == ['好呀，我哋慢慢傾。']
    assert output.finish() == []


def test_repeated_question_and_back_to_back_interrogation_are_not_delivered():
    output = ChatSentences([{'role': 'user', 'content': '見到隻貓'}, {'role': 'assistant', 'content': '隻貓瞓喺邊？'}, {'role': 'user', 'content': '睇住佢幾放鬆'}])
    assert output.feed('悠閒嘅感覺幾好。隻貓瞓喺邊？你住邊座？') == ['悠閒嘅感覺幾好。']


def test_chat_cannot_claim_personal_experience_or_unperformed_monitoring():
    output = ChatSentences(history('今日見到貓'))
    assert output.feed('我哋以前見過一隻黃貓。我可以幫你留意未來有冇類似情況。睇住佢咁悠閒，個人都會慢返啲。') == ['睇住佢咁悠閒，個人都會慢返啲。']
    assert output.finish() == []


def test_empty_reviewed_reply_has_a_complete_gentle_fallback():
    output = ChatSentences(history())
    assert output.feed('你想我點幫你？') == []
    assert output.finish() == ['好，我哋慢慢傾，你照自己步伐講就得。']


def test_only_one_new_question_is_allowed_but_conversation_can_continue():
    output = ChatSentences(history('我鍾意畫畫'))
    assert output.feed('你鍾意畫啲咩？用咩顏色？') == ['你鍾意畫啲咩？']


def test_native_messages_have_no_fictional_history_and_a_stable_cache_prefix():
    captured = []
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, text=json.dumps({'message': {'content': '我哋慢慢傾。'}, 'done': True}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            for message in ('見到隻貓', '今日幾開心'):
                await native_local({'messages': history(message), 'zhiwei_response_style': 'voice'}, context='已核對資料：公開測試', client=client)
    asyncio.run(run())
    assert captured[0]['messages'][0] == captured[1]['messages'][0]
    assert [m['content'] for m in captured[0]['messages'] if m['role'] == 'user'] == ['見到隻貓']
    assert '已核對資料' in captured[0]['messages'][-1]['content']
    assert captured[0]['messages'][-1]['role'] == 'system'
    assert '好鄰居' in captured[0]['messages'][0]['content']
    assert '共同童年' in captured[0]['messages'][0]['content']


def test_familiar_neighbor_does_not_fabricate_shared_childhood():
    output = ChatSentences(history('今日見到細個玩開嗰個公園'))
    assert output.feed('我哋細個一齊喺嗰度玩。仲記唔記得我哋追蝴蝶？我哋附近有條新小路。舊地方會勾起好多回憶。') == ['舊地方會勾起好多回憶。']
    assert output.finish() == []


def test_real_resident_detail_can_be_followed_without_an_interview():
    output = ChatSentences(history('行完公園飲杯茶，幾舒服'))
    assert output.feed('行完再慢慢飲杯茶，呢個節奏幾好。') == ['行完再慢慢飲杯茶，呢個節奏幾好。']


def test_sourced_context_bypasses_chat_filter_and_preserves_links():
    text = '來源：https://example.org/page?q=public。你可查看來源。'
    def respond(request):
        return httpx.Response(200, text=json.dumps({'message': {'content': text}, 'done': True}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await native_local({'messages': history('公開問題')}, context='已搜尋來源：https://example.org/page?q=public', client=client)
            assert json.loads(response.body)['choices'][0]['message']['content'] == text
    asyncio.run(run())


def test_a_near_copy_of_the_previous_reply_is_not_repeated():
    output = ChatSentences([{'role': 'user', 'content': '見到貓'}, {'role': 'assistant', 'content': '真係，有隻貓咁安靜瞓到攤晒，街頭都變成小天地。'}, {'role': 'user', 'content': '想隨便傾吓'}])
    assert output.feed('真係，有隻貓瞓到攤晒，街頭都變成小天地。') == []
    assert output.finish() == ['好，我哋慢慢傾，你照自己步伐講就得。']


def test_unprompted_fear_reassurance_is_removed_and_spoken_punctuation_is_plain():
    output = ChatSentences(history('見到隻貓'))
    assert output.feed('咪驚到，見到貓都幾得意～。') == ['見到貓都幾得意～。']
    output = ChatSentences(history('見到隻貓'))
    output.feed('幾得意～')
    assert output.finish() == ['幾得意。']
