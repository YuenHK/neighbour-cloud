"""Bounded sentence delivery for ordinary chat; never rewrites sourced information."""
import re
from difflib import SequenceMatcher


def no_more_questions(history):
    prior = history[-2]['content'] if len(history) >= 2 and history[-2]['role'] == 'assistant' else ''
    requested = any(item['role'] == 'user' and re.search(r'唔使.*問|唔好.*問|不要.*问|只想.*(?:聽|听|陪)|隨便傾|随便聊', item['content']) for item in history[-6:])
    return bool(re.search(r'[？?]', prior) or requested)


class ChatSentences:
    def __init__(self, history):
        self.previous_sentences = [re.sub(r'[\s，。！？,.!?～~]+', '', sentence) for item in history[-6:] if item['role'] == 'assistant' for sentence in re.split(r'[。！？!?\n]', item['content']) if len(sentence.strip()) >= 10]
        self.fear_mentioned = bool(re.search(r'驚|害怕|恐懼|緊張|紧张', history[-1]['content']))
        self.pending = ''
        self.accepted = False
        self.questions = 0
        self.no_questions = no_more_questions(history)
        self.old_questions = {re.sub(r'[\s，。！？,.!?]+', '', question) for item in history[-6:]
            if item['role'] == 'assistant' for question in re.findall(r'[^。！？?\n]*[？?]', item['content'])}

    def review(self, sentence):
        if not self.fear_mentioned:
            sentence = re.sub(r'(?:唔好驚|唔使驚|咪驚)(?:到)?[，,、\s]*|唔好緊張[，,、\s]*', '', sentence)
        sentence = re.sub(r'[～~]+$', '。', sentence.rstrip())
        normalized_sentence = re.sub(r'[\s，。！？,.!?～~]+', '', sentence)
        if len(normalized_sentence) >= 10 and any(SequenceMatcher(None, normalized_sentence, previous).ratio() >= .8 for previous in self.previous_sentences):
            return ''
        # A local avatar cannot have witnessed or monitored real-world events.
        if re.search(r'我(?:哋)?(?:以前|曾經|之前)?(?:都)?(?:見過|去過|試過|住過|養過|食過|影過)|我(?:都)?(?:可以|會)?幫你(?:留意|監察|跟蹤|記錄位置)', sentence):
            return ''
        if re.search(r'我哋(?:細個|小時候|由細到大).*?(?:一齊|一起)|我哋(?:一齊|一起)長大|仲記唔記得我哋|我哋(?:屋苑|後面|附近)', sentence):
            return ''
        if re.search(r'[？?]', sentence):
            normalized = re.sub(r'[\s，。！？,.!?]+', '', sentence)
            if self.no_questions or self.questions or normalized in self.old_questions or re.search(r'你住|邊座|幾樓|邊個單位|點樣幫你|點幫你', sentence):
                return ''
            self.questions += 1
        if sentence.strip():
            self.accepted = True
        return sentence

    def feed(self, text):
        self.pending += text
        ready = []
        while (match := re.match(r'^[\s\S]*?[。！？!?；;\n]', self.pending)):
            sentence = match[0]
            self.pending = self.pending[len(sentence):]
            reviewed = self.review(sentence)
            if reviewed:
                ready.append(reviewed)
        return ready

    def finish(self):
        tail = self.review(self.pending) if self.pending else ''
        self.pending = ''
        if tail:
            return [tail]
        return [] if self.accepted else ['好，我哋慢慢傾，你照自己步伐講就得。']
