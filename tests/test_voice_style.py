from local_audio_gateway.voice_style import spoken_cantonese


def test_common_estate_english_terms_and_web_citations_are_spoken_naturally():
    text = 'A座Wi-Fi用唔到，掃QR Code開APP。來源：[天文台](https://www.hko.gov.hk/)。'
    spoken = spoken_cantonese(text)
    assert 'A座無線網絡' in spoken and '二維碼' in spoken and '應用程式' in spoken
    assert '來源：天文台' in spoken and 'https://' not in spoken
    assert text.startswith('A座Wi-Fi')


def test_times_phone_numbers_and_ordinary_cantonese_are_not_silently_changed():
    text = '今日 15:30 到 A 座，電話 23456789，唔使急。'
    assert spoken_cantonese(text) == text
    assert spoken_cantonese('費用 HK$100.50') == '費用 100.50港元'
