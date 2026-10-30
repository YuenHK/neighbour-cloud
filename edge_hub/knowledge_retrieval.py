"""Small local BM25 index of approved estate facts, with explicit abstention gates.

BM25S (MIT, https://github.com/xhluca/bm25s) is used only for ranking. Neither
scores nor a close match establish that an unrecorded rule or condition is true.
"""
import re

from edge_hub.cantonese_terms import normalize
from edge_hub.knowledge_relevance import EVIDENCE, INTENTS
from edge_hub.knowledge_relevance import relevant as old_relevant

TOPICS = ('泳池', '會所', '停車場', '升降機', '垃圾房', '管理處', '健身室', '網球場')
CONDITIONS = ('颱風', '打風', '黑雨', '暴雨', '公眾假期')
INTENT_WORDS = {**INTENTS, 'hours': INTENTS['hours']+r'|幾時|開放到幾點|閂門',
                'price': INTENTS['price']+r'|幾錢|點計錢|入場費'}


def canonical(text):
    value = normalize(text)
    for source, target in (('管理辦事處', '管理處'), ('健身房', '健身室'),
                           ('游泳地方', '泳池'), ('游泳', '泳池'), ('游水', '泳池')):
        value = value.replace(source, target)
    value = re.sub(r'(?<!停)車場', '停車場', value)
    value = re.sub(r'停車(?!場)', '停車場', value)
    value = re.sub(r'垃圾(?!房)', '垃圾房', value)
    return value


def topics(value):
    return {topic for topic in TOPICS if topic in value}


def intents(value):
    return {intent for intent, pattern in INTENT_WORDS.items() if re.search(pattern, value)}


def compatible(question, row):
    """Also protect existing exact-keyword answers from wrong context/conditions."""
    if not old_relevant(question, row):
        return False
    query = canonical(question)
    indexed = canonical(row['title']+' '+' '.join(row['keywords']))
    whole = indexed+' '+canonical(row['answer'])
    requested, found = topics(query), topics(indexed)
    if requested and found and not requested.issubset(found):
        return False
    if any(condition in query and condition not in whole for condition in CONDITIONS):
        return False
    if re.search(r'住戶|居民|業主|租戶', query) and '訪客' in indexed and not re.search(r'住戶|居民|業主|租戶', indexed):
        return False
    return not ('訪客' in query and re.search(r'住戶|業主|租戶', indexed) and '訪客' not in indexed)


def tokens(text):
    value = canonical(text)
    result = re.findall(r'[a-z0-9]{2,}', value)
    for run in re.findall(r'[\u3400-\u9fff]+', value):
        result.extend(run[index:index+2] for index in range(len(run)-1))
    return result


class FactIndex:
    def __init__(self, rows):
        self.rows = [row for row in rows if row['enabled']]
        self.metadata = []
        self.rank = None
        if not self.rows:
            return
        # No tokenizer download, embedding, external search or resident database.
        import bm25s
        corpus = []
        for row in self.rows:
            indexed = canonical(row['title']+' '+' '.join(row['keywords']))
            self.metadata.append((indexed, topics(indexed), indexed+canonical(row['answer'])))
            terms = tokens(indexed)*2+tokens(row['answer'][:800])
            terms += ['topic_'+topic for topic in topics(indexed)]
            corpus.append(terms or ['__empty_fact__'])
        self.rank = bm25s.BM25(backend='numpy')
        self.rank.index(corpus, show_progress=False)

    def answer(self, question):
        query = canonical(question)
        requested, wanted = topics(query), intents(query)
        if self.rank is None or not requested or not wanted:
            return None
        candidates = []
        for index, row in enumerate(self.rows):
            indexed, found, whole = self.metadata[index]
            if not requested.issubset(found):
                continue
            if not compatible(question, row):
                continue
            if not all(re.search(EVIDENCE[intent], whole) for intent in wanted):
                continue
            # Visitor prices cannot be silently represented as residents' prices.
            if '訪客' in indexed and '訪客' not in query:
                continue
            candidates.append(index)
        if not candidates:
            return None
        scores = self.rank.get_scores(tokens(question)+['topic_'+topic for topic in requested])
        ranked = sorted((index for index in candidates if scores[index] > 0), key=lambda index: -float(scores[index]))
        if not ranked:
            return None
        # Two plausible but different facts require clarification, not a numeric
        # similarity guess. Keep this even when one BM25 score is slightly higher.
        if len({self.rows[index]['answer'] for index in ranked}) != 1:
            return None
        return self.rows[ranked[0]]['answer']
