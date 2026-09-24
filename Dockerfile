FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng tesseract-ocr-tur tesseract-ocr-fra \
      libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-core fontconfig \
    && rm -rf /var/lib/apt/lists/*

ADD https://raw.githubusercontent.com/google/fonts/main/ofl/amiriquran/AmiriQuran-Regular.ttf /usr/share/fonts/truetype/amiri-quran/AmiriQuran-Regular.ttf
RUN chmod 644 /usr/share/fonts/truetype/amiri-quran/AmiriQuran-Regular.ttf && fc-cache -f

ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN python app/make_icon.py

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
