from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from edge_hub.cloud_credentials import siliconflow_enabled

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FAQ_PATH = PROJECT_ROOT / "config" / "community-faq.json"


class FaqEntry(BaseModel):
    id: str
    category: str
    keywords: list[str]
    answer: str


class FaqResult(BaseModel):
    matched: bool
    answer: str
    source_id: str | None = None
    category: str | None = None


class OfflineFaq:
    def __init__(self, path: Path = DEFAULT_FAQ_PATH) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.fallback = str(data["fallback"])
        self.entries = [FaqEntry.model_validate(entry) for entry in data["entries"]]

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^0-9a-zA-Z\u3400-\u9fff]+", "", text).lower()

    def query(self, question: str) -> FaqResult:
        normalized = self._normalize(question)
        best_entry: FaqEntry | None = None
        best_score = 0

        for entry in self.entries:
            score = sum(
                max(1, len(self._normalize(keyword)))
                for keyword in entry.keywords
                if self._normalize(keyword) in normalized
            )
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is None:
            return FaqResult(matched=False, answer=self.fallback)

        answer = best_entry.answer
        if best_entry.id == 'project-purpose' and any(
            word in normalized for word in ('簡短', '简短', '簡單', '简单', '簡啲', '简点', '一句')
        ):
            answer = '我係屋苑服務台，陪你傾偈、查資料，同幫你跟進事情。'
        if siliconflow_enabled():
            overrides = {
                'offline': '目前啟用硅基流動雲端辨識及文字對話，測試聲音及必要文字會傳送到該平台。'
                '影像及語音合成保持本機處理；離線常見問題仍可使用。',
                'audio-privacy': '目前測試聲音會送到硅基流動作即時辨識；必要對話文字亦會送到該平台。'
                '本機研究日誌不保存原始錄音；雲端資料處理依服務商政策。',
                'ai-model': '目前自由對話使用硅基流動免費文字模型，語音辨識使用雲端 SenseVoice。'
                '安全事件解說優先採用已審核 FAQ 和固定模板。',
            }
            answer = overrides.get(best_entry.id, answer)
        return FaqResult(
            matched=True,
            answer=answer,
            source_id=best_entry.id,
            category=best_entry.category,
        )
