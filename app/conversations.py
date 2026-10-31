"""Rule-based, multilingual group conversation and reaction engine.

This module intentionally uses local rules/templates; it does not call an AI API.
"""
from __future__ import annotations

import random
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .catalog import normalize_title

EMOJI_PATTERN = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")

# Each intent has multiple authored base replies. Language-specific openers,
# closers and emoji endings multiply the available combinations naturally.
RESPONSES: dict[str, dict[str, list[str]]] = {
    "greeting": {
        "tanglish": [
            "Hey brooo! Enna special inniku?", "Vanakkam nanba! Epdi poitu iruku?",
            "Hii bro! Group la semma active ah iruka?", "Sollu bro, enna news?",
            "Hey macha! Nalla irukiya?", "Welcome bro! Enna anime discussion?",
            "Dei hello! Inniku enna plan?", "Heyyy! Oru nalla vibe la irukom!",
        ],
        "english": [
            "Hey bro! What's happening today?", "Hello! Good to see you here.",
            "Heyyy! How's your day going?", "What's up! Any anime plans today?",
            "Hi there! The group is lively today.", "Hey! What are we chatting about?",
            "Hello bro! Hope your day is going well.", "Yo! Welcome to the chat.",
        ],
        "tamil": [
            "வணக்கம் நண்பா! எப்படி இருக்க?", "ஹாய்! இன்று என்ன விசேஷம்?",
            "வாங்க நண்பா! குழுவில் என்ன பேச்சு?", "வணக்கம்! நாள் எப்படி போகிறது?",
            "ஹாய் நண்பா! எல்லாம் நலமா?", "என்ன நண்பா, இன்று என்ன திட்டம்?",
            "வருக வருக! பேசலாம் நண்பா.", "வணக்கம்! நல்லா இருக்கீங்களா?",
        ],
    },
    "how_are_you": {
        "tanglish": [
            "Nalla iruken bro! Nee epdi iruka?", "Super ah iruken! Un side epdi poguthu?",
            "Naan nalla iruken nanba, nee sollu!", "Mass ah iruken bro! Nee epdi?",
            "Nalla dhan bro, inniku enna plan?", "Fine ah iruken! Nee happy ah irukiya?",
            "Semma nalla iruken bro! Unna pathi sollu.", "Nalla iruken da, group epdi iruku?",
        ],
        "english": [
            "Doing well, thanks! How are you?", "All good here. How's your day going?",
            "I'm doing great! What's new with you?", "Pretty good! How are things on your side?",
            "I'm good, bro. Hope you're doing well too.", "Can't complain! What have you been up to?",
            "Doing fine! Got anything interesting planned?", "All good here. How about you?",
        ],
        "tamil": [
            "நல்லா இருக்கேன் நண்பா! நீ எப்படி இருக்க?", "எல்லாம் நல்லா போகுது. உன் பக்கம்?",
            "நான் நலமா இருக்கேன்! நீ சொல்லு.", "சந்தோஷமா இருக்கேன் நண்பா. நீ எப்படி?",
            "நல்லா இருக்கேன். இன்று என்ன திட்டம்?", "எல்லாம் சூப்பரா இருக்கு! நீங்க எப்படி?",
            "நலம்தான் நண்பா, உங்களைப் பற்றி சொல்லுங்க.", "நல்லா இருக்கேன்! நீங்களும் நலமா?",
        ],
    },
    "what_doing": {
        "tanglish": [
            "Un kooda chat pannitu iruken bro! Nee enna panra?", "Inga group la time pass pannitu iruken 😂",
            "Summa relax pannitu iruken bro. Un scene enna?", "Anime pathi pesalam nu wait pannitu iruken!",
            "Group messages paathutu iruken bro. Nee sollu!", "Onnum illa, chill pannitu iruken. Nee?",
            "Un messages ku reply pannitu iruken nanba!", "Inga active ah iruken bro, enna venum?",
        ],
        "english": [
            "Chatting with everyone here! What about you?", "Just hanging around in the group.",
            "Taking it easy. What are you up to?", "Keeping up with the anime talk here.",
            "Just checking the chat. Anything new?", "Nothing much, just chilling here.",
            "Talking with you now! What are you doing?", "I'm around. What's going on?",
        ],
        "tamil": [
            "உங்களுடன் பேசிக்கொண்டிருக்கிறேன் நண்பா!", "இங்கே குழுவில் நேரம் செலவழிக்கிறேன்.",
            "சும்மா ஓய்வாக இருக்கிறேன். நீங்கள் என்ன செய்கிறீர்கள்?", "அனிமே பற்றி பேசலாம் என்று இருக்கிறேன்.",
            "குழு செய்திகளைப் பார்த்துக்கொண்டிருக்கிறேன்.", "பெரிதாக ஒன்றுமில்லை, ஓய்வாக இருக்கிறேன்.",
            "இப்போது உங்களுடன் பேசிக்கொண்டிருக்கிறேன்!", "இங்கேதான் இருக்கிறேன் நண்பா.",
        ],
    },
    "ate": {
        "tanglish": [
            "Sapten bro! Nee saptiya?", "Innum illa bro, nee saptiya?", "Sapten! Ippo anime time 😂",
            "Food mudinjudhu bro, next enna plan?", "Sapten nanba, nee miss pannadha!", "Aama bro, nee saapadu mudichitiya?",
            "Konjam late ah sapten! Nee?", "Innum saapdala bro, pasikuthu 😅",
        ],
        "english": [
            "Yep, had my food! Have you eaten?", "Not yet! What about you?", "Yes! Now it's anime time.",
            "All done here. Hope you had yours too.", "I have! Don't skip your meal, okay?", "Just finished eating. How about you?",
            "Not yet, still deciding what to eat.", "Yep! Food first, anime next.",
        ],
        "tamil": [
            "சாப்பிட்டேன் நண்பா! நீ சாப்பிட்டாயா?", "இன்னும் சாப்பிடவில்லை. நீங்கள்?", "சாப்பிட்டாச்சு! இப்போது அனிமே நேரம்.",
            "சாப்பாடு முடிந்தது நண்பா. நீங்களும் சாப்பிடுங்கள்.", "ஆமாம், சாப்பிட்டேன். நீங்கள் சாப்பிட்டீர்களா?", "இன்னும் இல்லை, கொஞ்சம் நேரத்தில் சாப்பிடுவேன்.",
            "சாப்பிட்டேன்! நீங்க சாப்பிட மறக்காதீங்க.", "இப்போதுதான் சாப்பிட்டு முடித்தேன்.",
        ],
    },
    "bored": {
        "tanglish": [
            "Appo oru nalla anime start pannu bro! Bore poidum 😂", "Bore ah? Vaanga konjam anime pesalam!",
            "Oru comedy episode paaru bro, mood change aagum!", "Group la pesu bro, time pogum 😁",
            "Un watchlist la irundhu pudhusa edhavadhu start pannu!", "Bore adicha memes share pannu bro 😂",
            "Konjam break eduthu fresh ah va bro!", "Anime recommendation venuma? Nalla titles iruku!",
        ],
        "english": [
            "Pick a fun anime episode, bro! That might help.", "Let's talk anime and beat the boredom.",
            "A comedy episode could be a good choice.", "Drop a meme in the group 😂",
            "Maybe try something new from your watchlist.", "Take a little break and refresh yourself.",
            "Want an anime recommendation?", "Let's find something interesting to talk about.",
        ],
        "tamil": [
            "ஒரு நல்ல அனிமே பாருங்க நண்பா!", "வாங்க, அனிமே பற்றி பேசலாம்.", "கொஞ்சம் நகைச்சுவை பாருங்க, மனநிலை மாறும்.",
            "குழுவில் பேசலாம் நண்பா!", "பிடித்த அனிமேவை மீண்டும் பாருங்க.", "சிறிது ஓய்வு எடுத்துக்கொள்ளுங்கள்.",
            "புதிய அனிமே பரிந்துரை வேண்டுமா?", "ஒரு மீம் பகிருங்கள் நண்பா!",
        ],
    },
    "who": {
        "tanglish": [
            "Naan namma group oda friendly bot bro! 😎", "Naan ANIFLIX group assistant nanba!",
            "Group la help pannavum chat pannavum iruken bro.", "Naan unga group bot! Enna venum sollunga.",
            "Namma group oda virtual nanban nu vachikonga!", "Bot dhan bro, aana friendly ah pesuven 😂",
            "ANIFLIX group la ungaloda chat partner!", "Naan inga irukura group helper bro!",
        ],
        "english": [
            "I'm the group's friendly helper bot!", "I'm the ANIFLIX group assistant.",
            "I'm here to help with group features and chat.", "Just your friendly group bot!",
            "Think of me as a virtual group mate.", "A bot, but I can still keep the chat lively!",
            "I'm the assistant for this group.", "Your friendly helper around here!",
        ],
        "tamil": [
            "நான் நம்ம குழுவின் நண்பனான பாட்!", "நான் ANIFLIX குழு உதவியாளர்.",
            "குழுவிற்கு உதவவும் பேசவும் இங்கே இருக்கிறேன்.", "உங்கள் குழு நண்பன் மாதிரி நினைத்துக்கொள்ளுங்கள்.",
            "நான் இந்தக் குழுவின் உதவி பாட்.", "குழுவில் உதவுவதற்காக இருக்கிறேன் நண்பா.",
            "நான் குழுவின் மெய்நிகர் நண்பன்.", "உங்களுக்கு உதவ இங்கே இருக்கிறேன்!",
        ],
    },
    "thanks": {
        "tanglish": [
            "Paravalla bro! Anytime! ❤️", "Mention pannadha nanba, happy to help!", "No problem bro! 😁",
            "Unakkaga dhan bro! Vera edhavadhu venuma?", "Welcome brooo!", "Santhosham nanba!",
            "Eppovume bro! Take care!", "Adhellam onnum illa, enjoy!",
        ],
        "english": [
            "You're welcome! Happy to help.", "Anytime, bro!", "No problem at all!", "Glad I could help!",
            "You're very welcome. Take care!", "That's what the group is for!", "Always happy to help.", "No worries!",
        ],
        "tamil": [
            "பரவாயில்லை நண்பா!", "எப்போதும் உதவத் தயார்!", "மகிழ்ச்சியுடன் நண்பா!", "நன்றி சொல்ல வேண்டாம்.",
            "உதவ முடிந்ததில் மகிழ்ச்சி!", "எந்த நேரத்திலும் கேளுங்கள்.", "சந்தோஷம் நண்பா!", "வரவேற்கிறேன்!",
        ],
    },
    "sorry": {
        "tanglish": [
            "Paravalla bro, chill!", "No worries nanba, ellam okay!", "Adhellam perusa eduthukadha bro.",
            "It's okay bro! Move on 😁", "Seri vidu bro, no problem!", "Paravalla, nadakardhu dhan.",
            "Okay bro, tension aagadha!", "All good nanba! ❤️",
        ],
        "english": [
            "It's okay, no worries!", "All good, don't stress about it.", "No problem at all.", "That's alright!",
            "It's fine. Let's move on!", "No worries, we're good.", "All okay here!", "Don't worry about it.",
        ],
        "tamil": [
            "பரவாயில்லை நண்பா, கவலைப்படாதீங்க.", "எல்லாம் சரிதான்!", "பிரச்சனை இல்லை நண்பா.", "அதைப் பற்றி கவலை வேண்டாம்.",
            "சரி விடுங்கள், பரவாயில்லை.", "எல்லாம் நன்றாக இருக்கிறது.", "கவலைப்படாதீங்க நண்பா!", "பரவாயில்லை!",
        ],
    },
    "good_morning": {
        "tanglish": [
            "Good morning brooo! Inniku nalla naala irukattum! ☀️", "Kaalai vanakkam nanba!", "Morning! Coffee aacha? 😂",
            "Good morning! Inniku enna anime plan?", "Super morning bro! Stay happy!", "Rise and shine macha!",
            "Morning bro! Day ah enjoy pannu!", "Iniya kaalai vanakkam!",
        ],
        "english": [
            "Good morning! Hope you have a lovely day.", "Morning, bro! Ready for a fresh day?", "Rise and shine!",
            "Good morning! What's the plan today?", "Wishing you a bright and happy morning.", "Morning! Have a great one.",
            "Good morning! Stay cheerful today.", "Hey, morning! Hope everything goes well.",
        ],
        "tamil": [
            "இனிய காலை வணக்கம் நண்பா!", "இன்று நல்ல நாளாக அமையட்டும்!", "காலை வணக்கம்! இன்று என்ன திட்டம்?",
            "புத்துணர்ச்சியுடன் நாளைத் தொடங்குங்கள்!", "இனிய காலை பொழுதாகட்டும்!", "எல்லாம் சிறப்பாக நடக்கட்டும்.",
            "காலை வணக்கம்! மகிழ்ச்சியாக இருங்கள்.", "இன்று இனிய நாளாக அமையட்டும்!",
        ],
    },
    "good_night": {
        "tanglish": [
            "Good night bro! Nalla thoongu! 🌙", "Sweet dreams nanba! Naala pesalam.", "Seri bro, rest edu! Good night!",
            "Night macha! Phone ah vechitu thoongu 😂", "Nalla rest edu bro!", "Good night! Naala fresh ah meet panlam.",
            "Iniya iravu nanba!", "Sleep well brooo!",
        ],
        "english": [
            "Good night! Sleep well.", "Sweet dreams, bro!", "Rest well and have a peaceful night.", "Night! Catch you tomorrow.",
            "Good night! Take care.", "Time to recharge. Sleep well!", "Wishing you a calm night.", "See you tomorrow!",
        ],
        "tamil": [
            "இனிய இரவு வணக்கம் நண்பா!", "நன்றாக ஓய்வெடுங்கள்.", "இனிய கனவுகள்!", "நாளை மீண்டும் பேசலாம்.",
            "அமைதியான இரவாக அமையட்டும்.", "நல்லா தூங்குங்கள் நண்பா!", "இனிய இரவு!", "நாளை சந்திப்போம்.",
        ],
    },
    "bye": {
        "tanglish": [
            "Seri bro, appuram pesalam! Bye!", "Poitu va nanba! Take care!", "Bye macha! Seekiram va!",
            "Okay bro, nalla iru!", "See you brooo!", "Seri da, group la meet panlam!", "Bye bro! Safe ah iru!", "Appuram chat panlam!",
        ],
        "english": [
            "See you later! Take care.", "Bye, bro! Have a good one.", "Catch you later!", "Take care and see you soon.",
            "Alright, talk later!", "Bye! Hope the rest of your day goes well.", "See you around!", "Later, bro!",
        ],
        "tamil": [
            "சரி நண்பா, பிறகு பேசலாம்!", "பத்திரமாக இருங்கள்!", "மீண்டும் சந்திப்போம்.", "சென்று வாருங்கள் நண்பா!",
            "நல்லபடியாக இருங்கள்.", "பிறகு பேசலாம்!", "இனிய நாளாகட்டும்!", "விரைவில் சந்திப்போம்.",
        ],
    },
    "laugh": {
        "tanglish": [
            "Dei yen bro ippadi sirikura? Enna comedy?", "Un sirippu group full ah kekkudhu 😂", "Haha! Semma fun ah iruku bro!",
            "Enna nadakuthu inga? Naanum sirikuren!", "Sirichite iru bro, happy ah iru!", "Idhu dhaan namma group vibe!",
            "Dei 😂 context sollu bro!", "Haha, un reaction vera level!",
        ],
        "english": [
            "Haha! What's so funny? 😂", "That reaction is too good!", "Love the energy in here!", "Okay, now I'm laughing too.",
            "That made the chat funnier!", "What's the story behind that laugh?", "The group vibe is unmatched!", "Haha, good one!",
        ],
        "tamil": [
            "ஏன் நண்பா இப்படி சிரிக்கிறீங்க?", "உங்கள் சிரிப்பு தொற்றிக்கொண்டது!", "அருமையான ரியாக்ஷன்!", "என்ன நகைச்சுவை நடந்தது?",
            "சிரித்துக்கொண்டே இருங்கள் நண்பா!", "குழுவின் கலகலப்பு இதுதான்!", "நானும் சிரித்துவிட்டேன்!", "சூப்பர் நண்பா!",
        ],
    },
    "anime_chat": {
        "tanglish": [
            "Anime topic ah? Bro, un favourite genre enna?", "Action anime na enakku semma pudikkum!", "Un top 3 anime titles sollu bro!",
            "Namma group la anime discussion start pannalam!", "Endha anime ippo paathutu iruka?", "Favourite character yaaru bro?",
            "Anime list la next enna add panna pora?", "Story strong ah irundha anime semma bro!",
        ],
        "english": [
            "Anime talk! What's your favourite genre?", "What's the next anime on your watchlist?", "Tell me your top three anime!",
            "Who's your favourite anime character?", "What are you watching these days?", "I'm always up for an anime discussion.",
            "Do you prefer action, fantasy or adventure?", "A great story makes an anime memorable!",
        ],
        "tamil": [
            "அனிமே பற்றியா? உங்களுக்கு பிடித்த வகை எது?", "உங்கள் பிடித்த மூன்று அனிமே பெயர்களை சொல்லுங்கள்!", "உங்களுக்கு பிடித்த கதாபாத்திரம் யார்?",
            "இப்போது எந்த அனிமே பார்க்கிறீர்கள்?", "அனிமே பற்றி பேசலாம் நண்பா!", "அடுத்ததாக என்ன பார்க்கப் போகிறீர்கள்?",
            "ஆக்ஷன் அனிமே பிடிக்குமா?", "நல்ல கதை இருந்தால் அனிமே இன்னும் சிறப்பு!",
        ],
    },
    "compliment": {
        "tanglish": [
            "Aww thanks bro! Nee dhaan mass! 😁", "Haha nandri nanba!", "Un comment ku thanks bro! ❤️",
            "Semma positive vibe bro!", "Thanks macha, nee vera level!", "Appreciate panren bro!",
            "Romba nandri nanba!", "Nee sonna apram semma happy!",
        ],
        "english": [
            "That's kind of you! Thanks, bro.", "You're too nice! Appreciate it.", "Thanks! Sending good vibes back.",
            "That made my day a little brighter.", "You're awesome too!", "Really appreciate the kind words.",
            "Thanks for the positive energy!", "You're making this chat wholesome!",
        ],
        "tamil": [
            "ரொம்ப நன்றி நண்பா!", "உங்கள் அன்பான வார்த்தைகளுக்கு நன்றி!", "நீங்களும் அருமை நண்பா!", "மகிழ்ச்சியாக இருக்கிறது!",
            "நல்ல வார்த்தைகளுக்கு நன்றி.", "உங்களுக்கும் வாழ்த்துகள்!", "உங்கள் பாராட்டுக்கு நன்றி!", "மிக்க மகிழ்ச்சி நண்பா!",
        ],
    },
    "question": {
        "tanglish": [
            "Nalla kelvi bro! Konjam detail sollu, purinjikitu reply panren.", "Hmm, idha pathi konjam context sollu nanba.",
            "Interesting question bro! Un point of view enna?", "Adhu situation poruthu bro. Konjam explain pannu.",
            "Puriyudhu bro, exact ah edha kekura?", "Nalla doubt! Group la discuss pannalam.",
            "Konjam clear ah sollu bro, correct ah pesalam.", "Idhu interesting ah iruku! Innum konjam sollu.",
        ],
        "english": [
            "Interesting question! Can you share a little more context?", "That depends on the situation. What do you mean exactly?",
            "Good question! What's your take on it?", "I get you. Could you explain which part you mean?",
            "Let's unpack that a little. What are you thinking?", "That's worth discussing! Tell me more.",
            "I might need a bit more context to answer well.", "What made you think of that?",
        ],
        "tamil": [
            "நல்ல கேள்வி நண்பா! கொஞ்சம் கூடுதல் விவரம் சொல்லுங்கள்.", "எந்த விஷயத்தை குறிப்பிட்டு கேட்கிறீர்கள்?",
            "சூழ்நிலையைப் பொறுத்தது. கொஞ்சம் விளக்குங்கள்.", "அதைப் பற்றி இன்னும் கொஞ்சம் பேசலாமா?",
            "உங்கள் கருத்து என்ன நண்பா?", "சுவாரஸ்யமான கேள்வி!", "சரியாக புரிந்துகொள்ள கொஞ்சம் விளக்கம் வேண்டும்.", "நல்ல சந்தேகம் நண்பா!",
        ],
    },
    "casual": {
        "tanglish": [
            "Haha seri bro, sollu innum enna news?", "Adhuvum correct dhan nanba!", "Un point puriyudhu bro.",
            "Apdiya bro? Appuram enna aachu?", "Semma update bro!", "Nalla iruku nanba, continue pannu.",
            "Hmm interesting ah iruku bro!", "Seri bro, adutha topic enna?",
        ],
        "english": [
            "Haha, fair enough! What's next?", "I get what you mean.", "Oh really? What happened after that?",
            "That's an interesting update!", "Makes sense to me.", "Nice! Tell me a little more.",
            "I see where you're coming from.", "Alright, what's the next topic?",
        ],
        "tamil": [
            "அப்படியா நண்பா? அடுத்து என்ன நடந்தது?", "உங்கள் கருத்து புரிகிறது.", "சரி நண்பா, இன்னும் சொல்லுங்கள்.",
            "அது சுவாரஸ்யமாக இருக்கிறது!", "நல்ல விஷயம் நண்பா!", "அப்படித்தான் இருக்கலாம்.",
            "சரி, அடுத்ததாக என்ன பேசலாம்?", "கேட்க நன்றாக இருக்கிறது!",
        ],
    },
}

OPENERS = {
    "tanglish": ["Haha bro, ", "Dei, ", "Aama bro, ", "Ada bro, ", "Macha, ", "Seri nanba, ", "Haha nanba, ", "Brooo, ", "Aiyo, ", "Semma bro, "],
    "english": ["Haha, ", "Hey, ", "Honestly, ", "Well, ", "Bro, ", "You know, ", "Oh, ", "Nice, ", "Okay, ", "Honestly bro, "],
    "tamil": ["அட நண்பா, ", "ஆமாம், ", "சரி நண்பா, ", "ஹாஹா, ", "நல்லது, ", "அப்படியா, ", "நண்பா, ", "சூப்பர், ", "ஓஹோ, ", "ம்ம், "],
}
CLOSERS = {
    "tanglish": [" Nee sollu!", " Appuram enna?", " 😂", " Bro!", " Nalla iru!", " Sollu nanba!", " Semma!", " Paathukalam!", " ❤️", " 😁"],
    "english": [" What about you?", " Tell me more!", " 😂", " That's the vibe!", " Sounds good!", " What happened next?", " Nice one!", " Stay awesome!", " ❤️", " 😁"],
    "tamil": [" நீங்களும் சொல்லுங்கள்!", " அடுத்து என்ன?", " 😊", " நண்பா!", " நன்றாக இருங்கள்!", " அருமை!", " பேசலாம்!", " ❤️", " 😁", " சரி!"],
}
EMOJI_ENDINGS = ["", " 😂", " 😁", " ❤️", " 🤣", " 😭", " 🔥", " 🥲", " 😎", " 👀", " 🤝", " 💚", " ✨", " 🙌", " 🤧", " 😅", " 🍥", " 💯", " 🫡", " 😋"]

INTENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "good_morning": ("good morning", "gm bro", "gm", "kalai vanakkam", "kaalai vanakkam", "காலை வணக்கம்"),
    "good_night": ("good night", "gn bro", "gn", "sweet dreams", "iniya iravu", "இனிய இரவு"),
    "greeting": ("hi", "hlo", "hello", "hii", "hiii", "hey", "heyy", "hi bro", "hey bro", "vanakkam", "வணக்கம்", "yo bro"),
    "how_are_you": ("epdi iruka", "eppadi iruka", "epdi irukinga", "how are you", "how r u", "nalla irukiya", "நலமா இருக்க"),
    "what_doing": ("enna panra", "enna pannura", "what are you doing", "wyd", "what doing", "enna seira"),
    "ate": ("saptiya", "saaptiya", "saptingala", "have you eaten", "did you eat", "saaptacha"),
    "bored": ("bore adikuthu", "bored", "boring", "time pass illa", "semma bore", "bore ah iruku"),
    "who": ("who are you", "yaaru nee", "neenga yaaru", "nee yaaru", "un name enna", "what is your name"),
    "thanks": ("thanks", "thank you", "thx", "nandri", "romba thanks", "நன்றி"),
    "sorry": ("sorry", "my bad", "mannichidu", "mannikavum", "மன்னிக்க"),
    "bye": ("bye", "goodbye", "see you", "poitu varen", "kelamburen", " tata", "போயிட்டு வரேன்"),
    "anime_chat": ("anime", "favourite anime", "favorite anime", "anime paak", "anime discussion", "character"),
    "compliment": ("super bot", "good bot", "nice bot", "semma bot", "mass bro", "you are nice", "nalla iruka"),
}


def detect_language(text: str) -> str:
    if re.search(r"[\u0B80-\u0BFF]", text):
        return "tamil"
    normalized = normalize_title(text)
    if not normalized and EMOJI_PATTERN.search(text):
        return "tanglish"
    tanglish_markers = {
        "bro", "macha", "machi", "nanba", "da", "dei", "iruka", "iruken", "enna", "panra",
        "saptiya", "epdi", "illa", "vanthuta", "pannu", "romba", "seri", "apdi", "inga", "nee",
    }
    words = set(normalized.split())
    if words.intersection(tanglish_markers):
        return "tanglish"
    return "english"


def detect_intent(text: str) -> str | None:
    normalized = normalize_title(text)
    if re.fullmatch(r"(?:ha|haha|hahaha|lol|lmao|rofl|😂|🤣|😹|😆)+", text.strip(), flags=re.IGNORECASE):
        return "laugh"
    if any(token in text for token in ("😂", "🤣", "😹", "😆")):
        return "laugh"
    if text.strip() and all((not char.isalnum()) and not char.isspace() for char in text.strip()):
        if any(token in text for token in ("❤️", "💚", "🥰", "😍", "😘")):
            return "compliment"
        if any(token in text for token in ("👋", "🙋", "🙏")):
            return "greeting"
        if any(token in text for token in ("😭", "🥲", "😢", "😔")):
            return "bored"
        if any(token in text for token in ("🔥", "💯", "👏", "🙌")):
            return "casual"
    if not normalized:
        return None
    for intent, phrases in INTENT_PATTERNS.items():
        for phrase in phrases:
            key = normalize_title(phrase)
            if key and f" {key} " in f" {normalized} ":
                return intent
    if "?" in text or normalized.startswith(("what ", "why ", "how ", "when ", "where ", "who ")):
        return "question"
    if any(token in normalized.split() for token in ("haha", "lol", "lmao", "super", "semma")):
        return "laugh" if "haha" in normalized or "lol" in normalized else "casual"
    # Only short conversational notes use the casual fallback. Long unrelated posts stay quiet.
    if len(normalized.split()) <= 7 and len(normalized) <= 55:
        return "casual"
    return None


@dataclass
class ConversationEngine:
    rng: random.Random = field(default_factory=random.Random)
    history_size: int = 16
    recent_by_user: dict[tuple[int, int], deque[str]] = field(default_factory=lambda: defaultdict(deque))

    @property
    def estimated_variant_count(self) -> int:
        base_count = sum(len(pool) for by_language in RESPONSES.values() for pool in by_language.values())
        return base_count * len(OPENERS["tanglish"]) * len(CLOSERS["tanglish"]) * len(EMOJI_ENDINGS)

    def reply(self, chat_id: int, user_id: int, text: str, custom_replies: list[str] | None = None) -> str | None:
        intent = detect_intent(text)
        if intent is None:
            return None
        language = detect_language(text)
        pool = list((RESPONSES.get(intent) or RESPONSES["casual"]).get(language, RESPONSES["casual"][language]))
        if custom_replies:
            pool.extend(item for item in custom_replies if item.strip())
        recent = self.recent_by_user[(chat_id, user_id)]
        base_candidates = [item for item in pool if item not in recent] or pool
        body = self.rng.choice(base_candidates)

        # Create varied, language-matched combinations while keeping the selected base natural.
        use_opener = self.rng.random() < 0.55
        use_closer = self.rng.random() < 0.55
        emoji_input = bool(EMOJI_PATTERN.search(text))
        use_emoji = emoji_input or self.rng.random() < 0.35
        opener = self.rng.choice(OPENERS[language]) if use_opener else ""
        closer = self.rng.choice(CLOSERS[language]) if use_closer else ""
        ending = self.rng.choice(EMOJI_ENDINGS[1:]) if use_emoji else ""
        reply = f"{opener}{body}{closer}{ending}".strip()
        reply = re.sub(r"([!?.])\s*([!?.])", r"\1", reply)
        recent.append(body)
        while len(recent) > self.history_size:
            recent.popleft()
        return reply

    def media_reply(self, chat_id: int, user_id: int, kind: str, text: str = "") -> str:
        language = detect_language(text) if text else "tanglish"
        media = {
            "gif": {
                "tanglish": ["Dei 😂 semma reaction bro!", "Indha GIF vera level macha! 🤣", "Enna bro, exact ah situation ku match aagudhu!", "Haha! Idha vida best reaction illa!", "Bro, indha GIF ah save pannikanum 😂", "Yen bro ippadi? 🤣"],
                "english": ["That GIF is a perfect reaction 😂", "Haha, this one is too good!", "The timing on that GIF! 🤣", "Okay, that reaction wins.", "This GIF says everything!", "Excellent reaction, bro!"],
                "tamil": ["அருமையான ரியாக்ஷன்! 😂", "இந்த GIF செமையாக இருக்கு!", "இதுதான் சரியான ரியாக்ஷன்!", "ஹாஹா, சூப்பர்!", "இந்த ரியாக்ஷன் வேற லெவல்!", "நல்ல GIF நண்பா!"],
            },
            "sticker": {
                "tanglish": ["Sticker semma bro! 😂", "Indha sticker la un feeling theriyudhu!", "Haha, nalla sticker nanba!", "Sticker reaction accepted bro! 😎", "Dei, idhu cute ah iruku!", "Correct sticker at correct time!"],
                "english": ["Nice sticker! 😂", "That sticker fits perfectly.", "Sticker reaction approved!", "Haha, good one!", "That's a fun sticker.", "Perfect timing for that sticker!"],
                "tamil": ["அருமையான ஸ்டிக்கர்!", "சரியான நேரத்தில் சரியான ஸ்டிக்கர்! 😂", "நல்ல ஸ்டிக்கர் நண்பா!", "இந்த ஸ்டிக்கர் சூப்பர்!", "ஹாஹா, அருமை!", "ரியாக்ஷன் புரிந்துவிட்டது!"],
            },
        }
        pool = media.get(kind, media["gif"])[language]
        key = (chat_id, user_id)
        recent = self.recent_by_user[key]
        choices = [item for item in pool if item not in recent] or pool
        answer = self.rng.choice(choices)
        recent.append(answer)
        while len(recent) > self.history_size:
            recent.popleft()
        return answer


@dataclass
class Cooldown:
    seconds: float = 6.0
    _last: dict[tuple[int, int], float] = field(default_factory=dict)

    def allow(self, chat_id: int, user_id: int, now: float) -> bool:
        key = (chat_id, user_id)
        previous = self._last.get(key, float("-inf"))
        if now - previous < self.seconds:
            return False
        self._last[key] = now
        return True
