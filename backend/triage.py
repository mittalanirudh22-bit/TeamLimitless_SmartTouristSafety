"""Understand an SOS message (typed or spoken) in English, Hindi or Hinglish.

* category: medical, harassment, theft, lost, accident or other -- a character n-gram TF-IDF + logistic regression model
  trained on the short phrases below (written for this project; extend them with real, anonymised messages over time).
  Character n-grams cope with Hinglish spelling variants ("bachao", "bachaao") and with Devanagari.
* urgent: life-threatening cues (bleeding, unconscious, not breathing, weapon, drowning, fire, child missing ...).
* places: names from the city guide mentioned in the message ("near Chowk"), so operators know where to look.

Triage only labels and flags. It never lowers an SOS: every SOS stays CRITICAL and a person decides what to do.
"""
import re, unicodedata
from functools import lru_cache

CATEGORIES = {'medical': 'Medical', 'harassment': 'Harassment or assault', 'theft': 'Theft or robbery',
              'lost': 'Lost or stranded', 'accident': 'Accident or fall', 'other': 'Unspecified'}

PHRASES = {
    'medical': [
        'I need a doctor', 'chest pain', "can't breathe", 'my friend fainted', 'someone collapsed', 'heart attack',
        'severe stomach pain', 'allergic reaction swelling', 'high fever and vomiting', 'snake bite', 'bleeding badly',
        'diabetic and feeling dizzy', 'need an ambulance', 'she is unconscious', 'food poisoning', 'asthma attack',
        'डॉक्टर चाहिए', 'सीने में दर्द है', 'साँस नहीं आ रही', 'बेहोश हो गया', 'एम्बुलेंस भेजो', 'खून बह रहा है',
        'चक्कर आ रहा है', 'बुखार बहुत तेज़ है', 'दवाई चाहिए',
        'doctor chahiye jaldi', 'seene mein dard', 'saans nahi aa rahi', 'behosh ho gaya', 'ambulance bhejo',
        'khoon beh raha hai', 'chakkar aa raha hai', 'tabiyat bahut kharab hai', 'sanp ne kaat liya', 'dawai chahiye',
    ],
    'harassment': [
        'someone is following me', 'a man is harassing me', 'they are touching me', 'I am being stalked',
        "group of men won't leave me alone", 'someone is threatening me', 'he grabbed my arm', 'being attacked',
        'someone is hitting me', 'the driver is not stopping the car', 'taxi driver took a wrong route and will not stop',
        'men are passing comments and following', 'a stranger is forcing me to go with him', 'I feel unsafe someone keeps following',
        'कोई मेरा पीछा कर रहा है', 'एक आदमी परेशान कर रहा है', 'मुझे धमकी दे रहे हैं', 'छेड़छाड़ हो रही है',
        'मुझे मार रहे हैं', 'ड्राइवर गाड़ी नहीं रोक रहा', 'जबरदस्ती कर रहा है',
        'koi peecha kar raha hai', 'ek aadmi pareshan kar raha hai', 'mujhe dhamki de rahe hain', 'chhedkhani ho rahi hai',
        'mujhe maar rahe hain', 'driver gaadi nahi rok raha', 'ladke tang kar rahe hain', 'zabardasti kar raha hai',
    ],
    'theft': [
        'my phone was stolen', 'someone snatched my bag', 'a pickpocket took my wallet', 'I was robbed',
        'my passport is stolen', 'they took my money', 'chain snatching', 'my hotel room was broken into',
        'scammed by a fake guide', 'my luggage was stolen at the station', 'money gone from my card', 'thief ran away with my bag',
        'मेरा फ़ोन चोरी हो गया', 'किसी ने बैग छीन लिया', 'पर्स चोरी हो गया', 'मुझे लूट लिया', 'चेन छीन ली', 'पैसे चुरा लिए',
        'mera phone chori ho gaya', 'kisi ne bag cheen liya', 'purse chori ho gaya', 'mujhe loot liya', 'chain kheench li',
        'paise chura liye', 'jeb kat gayi', 'saman chori ho gaya', 'he is demanding money', 'robber showed a knife and took my phone',
        'chaku dikha ke paise maang raha hai', 'mobile chheen ke bhaag gaya',
    ],
    'lost': [
        'I am lost', "I don't know where I am", 'lost my way in the forest', 'separated from my group', "can't find my friend",
        'my child is missing', 'missed the last bus and stranded', 'my phone is dying and I am lost', "can't find the trail back",
        'stuck on the hill road at night with no transport', 'which way to my hotel I am lost', 'my friend has not come back',
        'मैं रास्ता भटक गया हूँ', 'मुझे नहीं पता मैं कहाँ हूँ', 'मेरा बच्चा खो गया', 'ग्रुप से बिछड़ गया', 'दोस्त नहीं मिल रहा',
        'यहाँ फँस गया हूँ',
        'main rasta bhatak gaya', 'pata nahi main kahan hoon', 'mera bachcha kho gaya', 'group se bichhad gaya',
        'dost nahi mil raha', 'raasta nahi mil raha', 'yahan phas gaya hoon', 'koi gaadi nahi mil rahi',
        'hum raasta bhool gaye', 'jungle mein kho gaye', 'we lost our way', 'no idea how to get back',
    ],
    'accident': [
        'car accident', 'our bike crashed', 'the bus overturned', 'I fell and broke my leg', 'slipped on the waterfall rocks',
        'someone fell into the lake', 'my friend is drowning', 'hit by a vehicle', 'a tree fell on our car',
        'landslide hit our car', 'auto rickshaw accident', 'fell down the stairs at the fort', 'twisted my ankle on the trek',
        'एक्सीडेंट हो गया', 'गाड़ी पलट गई', 'मैं गिर गया और पैर टूट गया', 'कोई झील में डूब रहा है', 'बाइक टकरा गई',
        'accident ho gaya', 'gaadi palat gayi', 'main gir gaya pair toot gaya', 'koi doob raha hai', 'bike takra gayi',
        'phisal ke gir gaye', 'sadak par takkar ho gayi',
    ],
    'other': [
        'help', 'please help', 'I need help', 'call me back', 'help me please', 'send someone', 'emergency',
        'बचाओ', 'मदद करो', 'मदद चाहिए', 'कोई आओ', 'bachao', 'madad karo', 'madad chahiye', 'koi aao jaldi',
    ],
}

URGENT = [
    r'bleed|blood|khoon|खून', r'unconscious|fainted|collapsed|behosh|बेहोश', r"can'?t breathe|not breathing|saans nahi|साँस नहीं",
    r'knife|chaku|chaaku|चाकू', r'\bgun\b|pistol|bandook|बंदूक', r'drown|doob|डूब', r'\bfire\b|aag lag|आग',
    r'heart attack', r'kidnap|apharan|अपहरण|forcing me|zabardasti|जबरदस्ती', r'child is missing|bachcha kho|बच्चा खो',
    r'attacked|hitting me|maar rahe|मार रहे', r'snake bite|sanp ne|साँप',
]
GENERIC = {'lake', 'temple', 'museum', 'palace', 'fort', 'park', 'national', 'city', 'market', 'bazaar', 'bazaars', 'road',
           'near', 'main', 'view', 'gate', 'hill', 'hills', 'falls', 'peak', 'shelters', 'rock', 'stupa', 'old', 'and', 'the',
           'upper', 'east', 'north', 'south', 'west', 'centre', 'center', 'area', 'outlets', 'several'}


def normalize(text):
    t = unicodedata.normalize('NFC', text or '').lower()
    t = re.sub(r"[^\w\s'ऀ-ॿ]", ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


@lru_cache(maxsize=1)
def model():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    X = [normalize(p) for ps in PHRASES.values() for p in ps]
    y = [c for c, ps in PHRASES.items() for _ in ps]
    pipe = make_pipeline(TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4), sublinear_tf=True, min_df=1),
                         LogisticRegression(C=8, max_iter=3000, class_weight='balanced'))
    return pipe.fit(X, y)


def find_places(text, guide):
    """Guide places whose distinctive name words appear in the message, e.g. 'near chowk' -> Chowk Bazaar."""
    if not guide:
        return []
    words = set(normalize(text).replace("'", '').split())
    hits = []
    for p in guide.get('places', []):
        tokens = {w for w in normalize(re.sub(r'\(.*?\)', ' ', p['name']) + ' ' + p['name']).replace("'", '').split()
                  if len(w) >= 4 and w not in GENERIC}
        if tokens & words:
            hits.append(dict(id=p['id'], name=p['name'], latitude=p['lat'], longitude=p['lon']))
    return hits[:3]


def classify(text, guide=None):
    t = normalize(text)
    if not t:
        return dict(category='other', label=CATEGORIES['other'], confidence=0.0, urgent=False, places=[])
    m = model()
    probs = dict(zip(m.classes_, m.predict_proba([t])[0]))
    cat, conf = max(probs.items(), key=lambda kv: kv[1])
    if conf < 0.3:
        cat = 'other'
    return dict(category=cat, label=CATEGORIES[cat], confidence=round(float(conf), 2),
                urgent=any(re.search(p, t) for p in URGENT), places=find_places(text, guide))
