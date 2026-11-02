import httpx
import test_azure_voice

from edge_hub import azure_voice

prepared = test_azure_voice.prepared


class Arrival(httpx.SyncByteStream):
    def __init__(self):
        self.segments = 0

    def __iter__(self):
        for raw in (b'\0'*512, b'\0'*511, b'\0'*9001):
            self.segments += 1
            yield raw


def test_first_pcm_before_4096_byte_fill_preserves_every_sample_and_one_reservation(prepared):
    stream = Arrival()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream)))
    chunks = azure_voice.pcm_chunks('公開測試，慢慢講。', client=client)
    first = next(chunks)
    assert len(first) == 512 and stream.segments == 1
    rest = list(chunks)
    assert len(first) + sum(map(len, rest)) == 10024
    assert all(len(chunk) % 2 == 0 and len(chunk) <= 4096 for chunk in [first, *rest])
    assert azure_voice.status()['used'] == azure_voice.billable_characters('公開測試，慢慢講。')
    client.close()


def test_cancel_does_not_synthesize_or_reserve_second_time(prepared):
    calls = []
    def route(request):
        calls.append(request)
        return httpx.Response(200, stream=Arrival())
    client = httpx.Client(transport=httpx.MockTransport(route))
    chunks = azure_voice.pcm_chunks('公開測試。', client=client)
    next(chunks)
    chunks.close()
    assert len(calls) == 1
    assert b'zh-HK-HiuMaanNeural' in calls[0].content
    client.close()
