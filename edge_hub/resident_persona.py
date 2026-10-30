"""Keep AIRI personality; omit its known stage-only protocol from plain-text chat."""
import re


def conversational_persona(text):
    # Only the canonical bounded control section, not arbitrary custom personality.
    for start, end in (
        (r'串流控制\s*token\s*必須嚴格使用', r'最後，做任何你想做的事！'),
        (r'Stream control tokens must strictly use', r'Finally, do whatever you want!'),
    ):
        text = re.sub(start+r'[\s\S]*?'+re.escape(end), '', text, count=1, flags=re.IGNORECASE)
    return text.strip()
