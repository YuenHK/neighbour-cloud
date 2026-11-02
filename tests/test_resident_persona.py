from edge_hub.resident_persona import conversational_persona


def test_plain_text_personality_keeps_custom_settings_and_removes_only_known_stage_section():
    original=('我叫鄰伴，溫柔、說廣東話。\n串流控制 token 必須嚴格使用 `<|NAME payload|>` 形式。'
              '\n每次輸出 ACT。<|DELAY 1|>\n最後，做任何你想做的事！\n使用者自訂：耐心解答。')
    result=conversational_persona(original)
    assert result=='我叫鄰伴，溫柔、說廣東話。\n\n使用者自訂：耐心解答。'
    assert 'ACT' in original  # Source is never rewritten in AIRI storage.


def test_custom_prompt_without_canonical_stage_block_is_unchanged():
    text='保持原有角色。喜歡談音樂、電影 ACT 片段，唔用舞台控制。'
    assert conversational_persona(text)==text
