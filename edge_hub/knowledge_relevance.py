"""Public-fact topic/intent guard. Missing evidence is not an answer."""
import re

from edge_hub.cantonese_terms import normalize

TOPICS = ('泳池', '會所', '停車場', '升降機', '垃圾房', '管理處')
INTENTS = {
    'hours': r'開放時間|幾點|幾時|營業時間|开放时间|营业时间|關門|開門',
    'price': r'收費|收费|幾錢|多少钱|費用|费用|價錢|价格',
    'contact': r'電話|电话|聯絡|联系|搵邊個',
    'location': r'喺邊|在哪|位置|地址',
}
EVIDENCE = {
    'hours': r'開放|开放|營業|营业|時間|时间|上午|下午|晚上|\d+[點时時]|[0-2]?\d:[0-5]\d',
    'price': r'收費|收费|費用|费用|價錢|价格|元|免費|免费',
    'contact': r'電話|电话|聯絡|联系|\d{8}',
    'location': r'位置|地址|座|樓|楼|層|层|大堂|平台',
}


def relevant(question, row):
    query = normalize(question)
    indexed = normalize(row['title']+' '+' '.join(row['keywords']))
    answer = normalize(row['answer'])
    requested = {topic for topic in TOPICS if topic in query}
    found = {topic for topic in TOPICS if topic in indexed}
    if requested and found and not requested.intersection(found):
        return False
    for intent, pattern in INTENTS.items():
        if re.search(pattern, query) and not re.search(EVIDENCE[intent], indexed+answer):
            return False
    return True
