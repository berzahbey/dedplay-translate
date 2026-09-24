import os
import sqlite3
import time

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "ceviri.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

DEFAULT_GLOSSARY = [
    ("صلى الله عليه وسلم", "sallallahu aleyhi ve sellem"),
    ("رضي الله عنه", "radıyallahu anh"),
    ("رضي الله عنها", "radıyallahu anhâ"),
    ("رضي الله عنهم", "radıyallahu anhüm"),
    ("عليه السلام", "aleyhisselâm"),
    ("رحمه الله", "rahimehullah"),
    ("سبحانه وتعالى", "sübhânehû ve teâlâ"),
    ("peace be upon him", "sallallahu aleyhi ve sellem"),
    ("the Prophet", "Hz. Peygamber"),
    ("Prophet Muhammad", "Hz. Muhammed"),
    ("Sufism", "tasavvuf"),
    ("the Qur'an", "Kur'ân"),
]


def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def q(sql, args=(), one=False):
    with conn() as c:
        cur = c.execute(sql, args)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def x(sql, args=()):
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def init():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              filename TEXT, title TEXT, src_lang TEXT, status TEXT,
              total INTEGER DEFAULT 0, done INTEGER DEFAULT 0,
              total_chars INTEGER DEFAULT 0, done_chars INTEGER DEFAULT 0,
              elapsed REAL DEFAULT 0, error TEXT, created REAL, finished REAL);
            CREATE TABLE IF NOT EXISTS segments(
              job_id INTEGER, idx INTEGER, kind TEXT, src TEXT, lang TEXT, out TEXT,
              PRIMARY KEY(job_id, idx));
            CREATE TABLE IF NOT EXISTS glossary(
              id INTEGER PRIMARY KEY AUTOINCREMENT, src TEXT UNIQUE, tgt TEXT);
            """
        )
        if c.execute("SELECT COUNT(*) FROM glossary").fetchone()[0] == 0:
            c.executemany("INSERT INTO glossary(src,tgt) VALUES(?,?)", DEFAULT_GLOSSARY)
        c.execute("UPDATE jobs SET status='queued' WHERE status='running'")


def create_job(filename, src_lang):
    return x(
        "INSERT INTO jobs(filename,title,src_lang,status,created) VALUES(?,?,?,?,?)",
        (filename, os.path.splitext(filename)[0], src_lang, "uploading", time.time()),
    )


def upload_path(job_id, filename):
    safe = os.path.basename(filename).replace("/", "_")
    return os.path.join(UPLOAD_DIR, f"{job_id}_{safe}")


def get_job(job_id):
    return q("SELECT * FROM jobs WHERE id=?", (job_id,), one=True)


def get_status(job_id):
    r = q("SELECT status FROM jobs WHERE id=?", (job_id,), one=True)
    return r["status"] if r else None


def set_status(job_id, status, only_from=None):
    if only_from:
        marks = ",".join("?" * len(only_from))
        x(f"UPDATE jobs SET status=?, error=NULL WHERE id=? AND status IN ({marks})",
          (status, job_id, *only_from))
    else:
        x("UPDATE jobs SET status=? WHERE id=?", (status, job_id))


def set_error(job_id, msg):
    x("UPDATE jobs SET status='error', error=? WHERE id=?", (msg, job_id))


def list_jobs():
    return q("SELECT * FROM jobs WHERE status!='uploading' ORDER BY id DESC")


def next_job():
    return q("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1", one=True)


def insert_segments(job_id, title, segs):
    with conn() as c:
        c.execute("DELETE FROM segments WHERE job_id=?", (job_id,))
        c.executemany(
            "INSERT INTO segments(job_id,idx,kind,src,lang) VALUES(?,?,?,?,?)",
            [(job_id, i, k, s, l) for i, (k, s, l) in enumerate(segs)],
        )
        c.execute(
            "UPDATE jobs SET total=?, total_chars=?, done=0, done_chars=0, title=COALESCE(?,title) WHERE id=?",
            (len(segs), sum(len(s) for _, s, _ in segs), title, job_id),
        )


def pending_segments(job_id):
    return q("SELECT * FROM segments WHERE job_id=? AND out IS NULL ORDER BY idx", (job_id,))


def all_segments(job_id):
    return q("SELECT * FROM segments WHERE job_id=? ORDER BY idx", (job_id,))


def recent_pairs(job_id, n=4):
    rows = q(
        "SELECT kind,src,lang,out FROM segments WHERE job_id=? AND out IS NOT NULL AND out!=src "
        "ORDER BY idx DESC LIMIT ?", (job_id, n))
    return [dict(r) for r in reversed(rows)]


def prev_out(job_id, idx):
    r = q("SELECT out FROM segments WHERE job_id=? AND idx<? AND out IS NOT NULL AND kind='p' "
          "ORDER BY idx DESC LIMIT 1", (job_id, idx), one=True)
    return r["out"] if r else ""


def save_segment(job_id, idx, out, chars, seconds):
    with conn() as c:
        c.execute("UPDATE segments SET out=? WHERE job_id=? AND idx=?", (out, job_id, idx))
        c.execute(
            "UPDATE jobs SET done=done+1, done_chars=done_chars+?, elapsed=elapsed+? WHERE id=?",
            (chars, seconds, job_id),
        )


def finish(job_id):
    x("UPDATE jobs SET status='done', finished=? WHERE id=? AND status='running'", (time.time(), job_id))


def delete_job(job_id):
    job = get_job(job_id)
    with conn() as c:
        c.execute("DELETE FROM segments WHERE job_id=?", (job_id,))
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    if job:
        p = upload_path(job_id, job["filename"])
        if os.path.exists(p):
            os.remove(p)


def glossary():
    return [dict(r) for r in q("SELECT * FROM glossary ORDER BY src")]


def glossary_pairs():
    return [(r["src"], r["tgt"]) for r in q("SELECT src,tgt FROM glossary")]


def add_term(src, tgt):
    with conn() as c:
        c.execute("INSERT INTO glossary(src,tgt) VALUES(?,?) ON CONFLICT(src) DO UPDATE SET tgt=excluded.tgt",
                  (src.strip(), tgt.strip()))


def delete_term(term_id):
    x("DELETE FROM glossary WHERE id=?", (term_id,))
