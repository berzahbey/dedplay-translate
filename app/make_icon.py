import os
import urllib.request

from PIL import Image, ImageDraw, ImageFont

BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/firasanscondensed/"
OUT = os.path.join(os.path.dirname(__file__), "static")
RED, BLUE = (224, 38, 43), (30, 111, 224)


def font(name, size):
    path = f"/tmp/{name}.ttf"
    if not os.path.exists(path):
        urllib.request.urlretrieve(BASE + name + ".ttf", path)
    return ImageFont.truetype(path, size)


k = 2
S = 1024 * k
img = Image.new("RGB", (S, S), "white")
d = ImageDraw.Draw(img)
d.text((S / 2, 350 * k), "dedplay", font=font("FiraSansCondensed-SemiBold", 192 * k), fill="black", anchor="ms")
cx, cy, r = S / 2, 565 * k, 104 * k
d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RED, width=20 * k)
tri = [(cx - 33 * k, cy - 55 * k), (cx + 62 * k, cy), (cx - 33 * k, cy + 55 * k)]
d.polygon(tri, fill=RED)
d.line(tri + [tri[0], tri[1]], fill=RED, width=14 * k, joint="curve")
d.text((S / 2, 800 * k), "translate", font=font("FiraSansCondensed-Medium", 104 * k), fill=BLUE, anchor="ms")

os.makedirs(OUT, exist_ok=True)
for size in (512, 192, 180, 32):
    img.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, f"icon-{size}.png"))
print("ikon hazır")
