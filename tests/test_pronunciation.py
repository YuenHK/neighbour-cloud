from local_audio_gateway.pronunciation import prepare_speech


def test_empty_traditional_entry_uses_voiced_simplified(tmp_path):
    lexicon = tmp_path / 'lexicon.txt'
    lexicon.write_text('請 \n请 ts\n係 h\n卫 w\n', encoding='utf-8')
    spoken, missing = prepare_speech('請係衛。', lexicon)
    assert spoken == '请係卫。'
    assert missing == ()


def test_unknown_character_is_explicit_and_not_silently_dropped(tmp_path):
    lexicon = tmp_path / 'lexicon.txt'
    lexicon.write_text('你 n\n', encoding='utf-8')
    spoken, missing = prepare_speech('你好', lexicon)
    assert spoken == '你好'
    assert missing == ('好',)


def test_latin_name_is_spelled_with_supported_letters(tmp_path):
    lexicon = tmp_path / 'lexicon.txt'
    lexicon.write_text('a a\nn n\ns s\no o\n', encoding='utf-8')
    assert prepare_speech('Anson', lexicon) == ('a n s o n', ())
