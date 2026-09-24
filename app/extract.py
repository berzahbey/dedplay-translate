import collections
import io
import os
import re
import unicodedata

OCR_LANGS = {"ar": "ara", "en": "eng", "fr": "fra", "auto": "ara+eng"}

PAGE_NUM = re.compile(r"^[\s\-–—\[\(]*(\d{1,4}|[ivxlcdm]{1,7}|[٠-٩۰-۹]{1,4})[\s\-–—\]\)]*$", re.I)
HEADING_WORDS = re.compile(
    r"^(chapter|part|book|introduction|preface|conclusion|bölüm|kısım|fasıl|giriş|önsöz|sonuç|"
    r"chapitre|partie|الباب|باب|الفصل|فصل|كتاب|مقدمة|المقدمة|خاتمة|الخاتمة|تمهيد)\b",
    re.I,
)
END_PUNCT = tuple('.!?؟:;"”»)]…۔')


def norm(t):
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("\u00ad", "").replace("\ufeff", "")
    t = re.sub(r"[ \t\u00a0\u200f\u200e]+", " ", t)
    return t.strip()


def join_lines(raw):
    raw = re.sub(r"(\w)[-‐]\n(\w)", r"\1\2", raw)
    return norm(raw.replace("\n", " "))


def is_heading_like(t):
    return len(t) < 90 and not t.endswith((".", "!", "?", "؟", ";", ",")) and bool(
        HEADING_WORDS.match(t) or (t.isupper() and len(t) > 3)
    )


def merge_paragraphs(blocks):
    out = []
    for kind, t in blocks:
        if (out and kind == "p" and out[-1][0] == "p"
                and not out[-1][1].endswith(END_PUNCT)
                and len(out[-1][1]) > 40):
            out[-1] = ("p", out[-1][1] + " " + t)
        else:
            out.append((kind, t))
    return out


def ocr_image(img, src_lang):
    import pytesseract
    lang = OCR_LANGS.get(src_lang, "ara+eng")
    text = pytesseract.image_to_string(img, lang=lang, config="--psm 3")
    paras = [join_lines(p) for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if p and not PAGE_NUM.match(p)]


def from_image(path, src_lang):
    from PIL import Image
    img = Image.open(path)
    img.load()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    blocks = [("h" if is_heading_like(p) else "p", p) for p in ocr_image(img, src_lang)]
    return None, merge_paragraphs(blocks)


def from_pdf(path, src_lang, progress=None):
    import fitz
    from PIL import Image

    doc = fitz.open(path)
    title = (doc.metadata or {}).get("title") or None
    pages = []
    for n, page in enumerate(doc):
        if progress:
            progress(f"Sayfa okunuyor {n + 1}/{len(doc)}")
        h = page.rect.height
        items = []
        for b in page.get_text("blocks", sort=True):
            if b[6] != 0:
                continue
            t = join_lines(b[4])
            if not t:
                continue
            edge = b[3] < h * 0.09 or b[1] > h * 0.91
            items.append((t, edge))
        if sum(len(t) for t, _ in items) < 40:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            items = [(p, False) for p in ocr_image(img, src_lang)]
        pages.append(items)

    def key(t):
        return re.sub(r"[\d٠-٩]+", "", t).strip().lower()

    counts = collections.Counter(key(t) for items in pages for t, edge in items if edge)
    limit = max(3, int(len(pages) * 0.3))
    repeated = {k for k, c in counts.items() if c >= limit and k}

    blocks = []
    for items in pages:
        for t, edge in items:
            if PAGE_NUM.match(t):
                continue
            if edge and (key(t) in repeated or len(t) < 4):
                continue
            blocks.append(("h" if is_heading_like(t) else "p", t))
    if not blocks:
        raise ValueError("PDF'ten metin çıkarılamadı.")
    return title, merge_paragraphs(blocks)


def from_epub(path):
    from bs4 import BeautifulSoup
    from ebooklib import ITEM_DOCUMENT, epub

    book = epub.read_epub(path, options={"ignore_ncx": True})
    meta = book.get_metadata("DC", "title")
    title = meta[0][0] if meta else None
    blocks = []
    tags = ["h1", "h2", "h3", "h4", "p", "li", "blockquote"]
    for idref, _ in book.spine:
        item = book.get_item_with_id(idref)
        if not item or item.get_type() != ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for s in soup(["script", "style", "sup"]):
            s.decompose()
        found = False
        for tag in soup.find_all(tags):
            if tag.find(tags):
                continue
            t = norm(tag.get_text(" "))
            if not t or PAGE_NUM.match(t):
                continue
            found = True
            blocks.append(("h" if tag.name.startswith("h") else "p", t))
        if not found and soup.body:
            for line in soup.body.get_text("\n").split("\n"):
                t = norm(line)
                if t and not PAGE_NUM.match(t):
                    blocks.append(("p", t))
    return title, blocks


def from_docx(path):
    import docx

    d = docx.Document(path)
    title = d.core_properties.title or None
    blocks = []
    for p in d.paragraphs:
        t = norm(p.text)
        if not t or PAGE_NUM.match(t):
            continue
        style = (p.style.name if p.style is not None else "").lower()
        kind = "h" if style.startswith(("heading", "başlık", "title")) else "p"
        blocks.append((kind, t))
    return title, blocks


def from_txt(path):
    raw = open(path, "rb").read()
    text = raw.decode("latin-1")
    for enc in ("utf-8-sig", "cp1256", "cp1254"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    blocks = []
    for para in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        t = join_lines(para)
        if t and not PAGE_NUM.match(t):
            blocks.append(("h" if is_heading_like(t) else "p", t))
    return None, blocks


def extract(path, src_lang="auto", progress=None):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        title, blocks = from_pdf(path, src_lang, progress)
    elif ext == ".epub":
        title, blocks = from_epub(path)
    elif ext == ".docx":
        title, blocks = from_docx(path)
    elif ext == ".txt":
        title, blocks = from_txt(path)
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
        title, blocks = from_image(path, src_lang)
    else:
        raise ValueError(f"Desteklenmeyen dosya türü: {ext}")
    blocks = [(k, t) for k, t in blocks if t]
    if not blocks:
        raise ValueError("Dosyada çevrilecek metin bulunamadı.")
    return title, blocks
