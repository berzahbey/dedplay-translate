import json
import os
import re

import requests

ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
LETTER = re.compile(r"[^\W\d_]")
TR_CHARS = re.compile(r"[çğışöüÇĞİŞÖÜ]")
TR_WORDS = re.compile(r"\b(ve|bir|bu|ile|için|olan|olarak|da|de|ki|gibi|daha|çok|ise|değil)\b", re.I)
TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u08D3-\u08FF\u0640]")
QURAN_MARKS = re.compile(r"[\u06D6-\u06ED\u08D3-\u08FF\u0671]")
ALEF = str.maketrans({"ٱ": "ا", "أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"})

SYSTEM = """Sen dini, felsefi, tarihî ve sosyolojik eserler konusunda uzman, deneyimli bir çevirmensin. Arapça, İngilizce ve Fransızca metinleri Türkçeye çeviriyorsun.

Kurallar:
- Anlamı eksiksiz ve sadakatle aktar. Özetleme, cümle atlama, yorum veya açıklama ekleme.
- Akıcı, doğal ve kaliteli bir Türkçe kullan; çeviri kokan, devrik cümlelerden kaçın. Yazarın üslubunu ve ciddiyetini koru.
- İslami ilimlerin yerleşik Türkçe terimlerini kullan (tevhid, vahdet-i vücûd, kelâm, fıkıh, zikir, nefs, marifet vb.).
- Özel isimleri Türkçedeki yerleşik yazımıyla yaz (Muhammad → Muhammed, Ibn Arabi → İbnü'l-Arabî, al-Ghazali → Gazzâlî).
- Ayet ve hadisleri anlamca çevir; sure/ayet numaraları ve kaynak gösterimlerini (Buhârî, Müslim vb.) aynen koru.
- Metinde zaten Türkçe olan kısımları değiştirmeden bırak.
- Terim listesi verilirse o karşılıkları mutlaka kullan.
- Yalnızca çeviriyi yaz. Başlık, not, tırnak, "Çeviri:" gibi ekler koyma."""


def arabic_ratio(text):
    letters = len(LETTER.findall(text)) or 1
    return len(ARABIC.findall(text)) / letters


def detect(text):
    if arabic_ratio(text) > 0.3:
        return "ar"
    words = max(1, len(text.split()))
    if len(TR_CHARS.findall(text)) / words > 0.15 or len(TR_WORDS.findall(text)) / words > 0.08:
        return "tr"
    return "xx"


def needs_translation(text, lang):
    if not LETTER.search(text):
        return False
    if lang == "tr" and arabic_ratio(text) < 0.05:
        return False
    return True


def split_sentences(text):
    return [s for s in re.split(r"(?<=[.!?؟…۔])\s+", text) if s.strip()]


def split_long(text, maxlen=1500):
    if len(text) <= maxlen:
        return [text]
    chunks, cur = [], ""
    for s in split_sentences(text):
        while len(s) > maxlen:
            cut = s.rfind(" ", 0, maxlen)
            cut = cut if cut > 0 else maxlen
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(s[:cut])
            s = s[cut:].strip()
        if cur and len(cur) + len(s) + 1 > maxlen:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def is_quranic(text):
    return len(QURAN_MARKS.findall(text)) >= 2


def _match_key(s):
    return TASHKEEL.sub("", s).translate(ALEF).lower()


def _match_keys(s):
    # Osmani yazimdaki kucuk elif hem elif hem yok sayilarak denenir
    return {_match_key(s), _match_key(s.replace("\u0670", "ا"))}


def matching_terms(glossary, text):
    keys = _match_keys(text)
    return [(s, t) for s, t in glossary if any(_match_key(s) in k for k in keys)]


def clean_output(out, src):
    out = out.strip()
    out = re.sub(r"^(<<<|>>>)|(<<<|>>>)$", "", out).strip()
    out = re.sub(r"^(Çeviri|Türkçe çeviri|Türkçesi)\s*:\s*", "", out, flags=re.I)
    if len(out) > 1 and out[0] == out[-1] and out[0] in "\"'“”" and src[:1] not in "\"'“”":
        out = out[1:-1].strip()
    return out


class OllamaEngine:
    def __init__(self):
        self.url = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        self.model = os.environ.get("LLM_MODEL", "gemma3:12b")
        self.num_ctx = int(os.environ.get("LLM_CTX", "4096"))
        self.threads = int(os.environ.get("LLM_THREADS", "0"))

    def ensure_model(self, status):
        r = requests.get(f"{self.url}/api/tags", timeout=10)
        r.raise_for_status()
        names = {m.get("name") for m in r.json().get("models", [])}
        if self.model in names or f"{self.model}:latest" in names:
            return
        status(f"{self.model} indiriliyor…")
        with requests.post(f"{self.url}/api/pull", json={"model": self.model, "stream": True},
                           stream=True, timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise RuntimeError(d["error"])
                if d.get("total") and d.get("completed"):
                    pct = d["completed"] * 100 // d["total"]
                    status(f"{self.model} indiriliyor… %{pct}")

    def translate(self, text, kind, glossary, prev):
        return " ".join(self._one(c, kind, glossary, prev) for c in split_long(text))

    def _one(self, text, kind, glossary, prev):
        parts = []
        terms = matching_terms(glossary, text)
        if terms:
            parts.append("Terim listesi (bu karşılıkları kullan):\n" +
                         "\n".join(f"- {s} → {t}" for s, t in terms))
        if prev and kind == "p":
            parts.append("Bir önceki paragrafın çevirisi (yalnızca bağlam için, tekrar yazma):\n" + prev[-400:])
        what = "başlığı" if kind == "h" else "metni"
        parts.append(f"Aşağıdaki {what} Türkçeye çevir:\n<<<\n{text}\n>>>")

        options = {
            "temperature": 0.2,
            "top_p": 0.9,
            "repeat_penalty": 1.05,
            "num_ctx": self.num_ctx,
            "num_predict": min(3000, max(200, int(len(text) * 1.3))),
        }
        if self.threads:
            options["num_thread"] = self.threads
        r = requests.post(
            f"{self.url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "keep_alive": "30m",
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "\n\n".join(parts)},
                ],
                "options": options,
            },
            timeout=900,
        )
        r.raise_for_status()
        out = clean_output(r.json()["message"]["content"], text)
        if not out:
            raise RuntimeError("Model boş cevap döndü")
        return out
