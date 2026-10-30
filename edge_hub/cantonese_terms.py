"""Conservative Cantonese aliases for retrieval and local intake only.

Never overwrite the resident's quotation, saved facts, addresses or identifiers.
"""
import re
import unicodedata

ALIASES = {
    '𨋢': '升降機', '電梯': '升降機', '电梯': '升降機',
    '會所': '會所', '会所': '會所', '康樂室': '會所',
    '泊車': '停車', '泊车': '停車', '停车': '停車',
    '開到幾點': '開放時間', '幾點閂': '開放時間', '幾點開': '開放時間',
    '幾時開': '開放時間', '幾時閂': '開放時間', '幾點收': '開放時間',
    '地下成灘水': '地面積水', '地下有灘水': '地面積水', '成地水': '地面積水',
    '地下一灘水': '地面積水',
    '瞓唔到': '失眠', '瞓唔着': '失眠', '瞓唔著': '失眠',
    '成晚眼光光': '失眠', '日日都冇覺好瞓': '持續失眠',
}


def normalize(text):
    result = unicodedata.normalize('NFKC', text).casefold()
    for source, target in sorted(ALIASES.items(), key=lambda item: -len(item[0])):
        result = result.replace(source, target)
    return ''.join(result.split())


def sorting_question(text):
    value = normalize(text)
    return bool(re.search(r'垃圾|廚餘|厨余|廢紙|废纸|膠樽|胶樽', value)
                and re.search(r'點(?:樣)?|怎[麼么樣样]|如何|應該|应该', value)
                and re.search(r'分類|分类|回收', value)
                and not re.search(r'滿晒|滿咗|滿了|爆滿|污糟|成地|好多垃圾|有垃圾|堆滿|冇人清|壞咗|故障|火花|冒煙|漏水', value))
