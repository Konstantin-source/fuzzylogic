import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app import db, importer, openai_client as ai
from app.search import normalize, search

@asynccontextmanager
async def lifespan(app):
    if ai.available():
        start_job()
    yield

app = FastAPI(title='Artikelsuche', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')
db.init()
executor = ThreadPoolExecutor(max_workers=1)
jobs = {}
lock = threading.Lock()

@app.get('/')
def index(): return FileResponse(Path(__file__).parent / 'static' / 'index.html')

@app.get('/api/config')
def config():
    with db.connect() as conn:
        categories = [r[0] for r in conn.execute("SELECT DISTINCT category FROM articles WHERE category != '' ORDER BY category")]
        count = conn.execute('SELECT count(*) FROM articles').fetchone()[0]
    return {'categories': categories, 'count': count, 'rerank_default': os.getenv('ENABLE_LLM_RERANK_DEFAULT', 'true').lower() == 'true', 'api_available': ai.available()}

@app.post('/api/preview')
async def preview(file: UploadFile = File(...)):
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024: raise HTTPException(413, 'Datei ist größer als 20 MB.')
    try: columns, records = importer.parse(file.filename or '', data)
    except Exception: raise HTTPException(400, 'Datei konnte nicht gelesen werden. Bitte Format und Spalten prüfen.')
    return {'columns': columns, 'mapping': importer.mapping_for(columns), 'count': len(records)}

def index_embeddings(job_id):
    try:
        with db.connect() as conn:
            rows = conn.execute('SELECT DISTINCT hash, search_text FROM articles WHERE NOT EXISTS (SELECT 1 FROM embeddings WHERE embeddings.hash=articles.hash AND provider=? AND model=? AND dimensions=?)', ('openai', ai.MODEL, ai.DIMENSIONS)).fetchall()
        jobs[job_id].update(total=len(rows), done=0)
        if not ai.available():
            jobs[job_id].update(status='local', message='Lokaler Modus aktiv; Embeddings wurden nicht erstellt.'); return
        for start in range(0, len(rows), 50):
            batch = rows[start:start+50]
            vectors = ai.embed([r['search_text'] for r in batch])
            with db.connect() as conn:
                conn.executemany('INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?)', [(r['hash'], 'openai', ai.MODEL, ai.DIMENSIONS, v.tobytes()) for r,v in zip(batch,vectors)])
            jobs[job_id]['done'] = min(start + len(batch), len(rows))
        jobs[job_id].update(status='done', message='Indexierung abgeschlossen.')
    except Exception:
        jobs[job_id].update(status='local', message='KI nicht erreichbar; lokaler Modus aktiv.')

def start_job():
    job_id = uuid.uuid4().hex
    jobs[job_id] = {'status':'running', 'done':0, 'total':0, 'message':'Indexierung wird vorbereitet.'}
    executor.submit(index_embeddings, job_id)
    return job_id

@app.post('/api/import')
async def do_import(file: UploadFile = File(...), mapping: str = Form(...)):
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024: raise HTTPException(413, 'Datei ist größer als 20 MB.')
    try:
        columns, records = importer.parse(file.filename or '', data)
        selected = json.loads(mapping)
        if not isinstance(selected, dict): raise ValueError('Ungültiges Mapping.')
        with lock: count = importer.import_rows(columns, records, selected)
    except (ValueError, TypeError, KeyError) as exc: raise HTTPException(400, str(exc))
    except Exception: raise HTTPException(400, 'Datei konnte nicht importiert werden.')
    return {'count': count, 'job': start_job()}

@app.get('/api/jobs/{job_id}')
def job(job_id: str):
    if job_id not in jobs: raise HTTPException(404, 'Auftrag nicht gefunden.')
    return jobs[job_id]

@app.get('/api/search')
def do_search(q: str, category: str = '', rerank: bool = False, use_ai: bool = False):
    if not q.strip() or len(q) > 300: return {'results': [], 'mode':'local'}
    results, mode = search(q, category, rerank, use_ai)
    for r in results:
        r.pop('hash', None); r.pop('search_text', None)
    return {'results':results, 'mode':mode}

class Synonym(BaseModel):
    term: str = Field(min_length=1, max_length=200)

@app.post('/api/articles/{number}/synonyms')
def add_synonym(number: str, body: Synonym):
    term = body.term.strip()
    if not term: raise HTTPException(400, 'Begriff darf nicht leer sein.')
    with lock, db.connect() as conn:
        row = conn.execute('SELECT * FROM articles WHERE number=?', (number,)).fetchone()
        if not row: raise HTTPException(404, 'Artikel nicht gefunden.')
        conn.execute('INSERT OR IGNORE INTO synonyms VALUES (?,?)', (number, term))
        terms = [r[0] for r in conn.execute('SELECT term FROM synonyms WHERE number=? ORDER BY term', (number,))]
        text = ' '.join([row[k] for k in ('number','name','extra','category','unit','ean','location')] + terms)
        digest = hashlib.sha256(normalize(text).encode()).hexdigest()
        conn.execute('UPDATE articles SET search_text=?, hash=? WHERE number=?', (text,digest,number))
        conn.execute('DELETE FROM article_fts WHERE number=?', (number,))
        conn.execute('INSERT INTO article_fts(number, search_text) VALUES (?,?)', (number,text))
    return {'job': start_job()}
