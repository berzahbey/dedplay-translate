import threading
import time
import traceback

from . import db
from .extract import extract
from .translate import OllamaEngine, RefusalError, detect, needs_translation


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.engine = OllamaEngine()
        self.ready = False
        self.status = {"model": self.engine.model, "engine": "Ollama'ya bağlanılıyor…", "stage": None}

    def _set(self, key, val):
        self.status[key] = val

    def _prepare(self):
        while True:
            try:
                self.engine.ensure_model(lambda s: self._set("engine", s))
                self.status["engine"] = "Hazır"
                self.ready = True
                return
            except Exception as e:
                self.status["engine"] = f"Ollama bekleniyor ({str(e)[:120]})"
                time.sleep(10)

    def run(self):
        threading.Thread(target=self._prepare, daemon=True).start()
        while True:
            job = db.next_job() if self.ready else None
            if not job:
                time.sleep(2)
                continue
            self.process(job)

    def _translate(self, seg, glossary, prev):
        last = None
        for attempt in range(4):
            try:
                return self.engine.translate(seg["src"], seg["kind"], glossary, prev)
            except RefusalError:
                return None
            except Exception as e:
                last = e
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"Paragraf {seg['idx'] + 1} çevrilemedi: {last}")

    def process(self, job):
        jid = job["id"]
        db.set_status(jid, "running")
        try:
            if job["total"] == 0:
                self.status["stage"] = "Metin çıkarılıyor"
                path = db.upload_path(jid, job["filename"])
                title, blocks = extract(path, job["src_lang"], lambda s: self._set("stage", s))
                segs = [(kind, text, detect(text)) for kind, text in blocks]
                db.insert_segments(jid, title, segs)
            self.status["stage"] = "Çevriliyor"

            t = time.time()
            for seg in db.pending_segments(jid):
                if db.get_status(jid) != "running":
                    return
                failed = False
                if needs_translation(seg["src"], seg["lang"]):
                    out = self._translate(seg, db.glossary_pairs(), db.prev_out(jid, seg["idx"]))
                    if out is None:
                        failed = True
                        out = "[Çevrilemedi] " + seg["src"]
                else:
                    out = seg["src"]
                now = time.time()
                db.save_segment(jid, seg["idx"], out, len(seg["src"]), now - t)
                t = now
                if failed:
                    db.mark_failed(jid)
                    j = db.get_job(jid)
                    if j["failed"] >= 5 and j["failed"] > j["done"] * 0.5:
                        db.set_error(jid, "Paragrafların çoğu çevrilemiyor. Dosya taranmış ya da metni okunamayan "
                                          "bir PDF olabilir (resimden okuma başarısız).")
                        return
            db.finish(jid)
        except Exception as e:
            traceback.print_exc()
            if db.get_status(jid):
                db.set_error(jid, str(e)[:500])
        finally:
            self.status["stage"] = None


worker = Worker()
