import re
import numpy as np
from rapidfuzz.fuzz import token_set_ratio
from app import db, openai_client as ai

def normalize(text):
    text = str(text).casefold().replace('ä','ae').replace('ö','oe').replace('ü','ue').replace('ß','ss')
    text = re.sub(r'(?<=\d)\s*[x*/]\s*(?=\d)', 'x', text)
    text = re.sub(r'(?<=\d)\s*(mm|cm)\b', '', text)
    return ' '.join(re.findall(r'[a-z0-9]+(?:x[0-9]+)*', text))

def dimensions(text):
    return set(re.findall(r'\b(?:m)?\d+(?:x\d+)+\b', normalize(text)))

def rrf(*rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, number in enumerate(ranking, 1): scores[number] = scores.get(number, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda n: (-scores[n], n))

def local_rank(query, rows, fts_numbers=()):
    q = normalize(query); qdims = dimensions(query); tokens = set(q.split())
    fts = set(fts_numbers)
    def score(row):
        text = normalize(row['search_text'])
        value = token_set_ratio(q, text) / 100 + (0.3 if row['number'] in fts else 0)
        value += 0.2 * len(tokens & set(text.split())) / max(len(tokens), 1)
        if q and q in (normalize(row['number']), normalize(row['ean'])): value += 3
        if qdims and qdims & dimensions(text): value += 2
        return value
    return [r['number'] for r in sorted(rows, key=lambda r: (-score(r), r['number']))]

def validate_ranking(items, candidates, conn):
    allowed = {r['number'] for r in candidates}; result = []; seen = set()
    for item in items:
        number = item.number if hasattr(item, 'number') else item.get('number', '')
        confidence = item.confidence if hasattr(item, 'confidence') else item.get('confidence', '')
        reason = item.reason if hasattr(item, 'reason') else item.get('reason', '')
        if number not in allowed or number in seen or confidence not in ('hoch','mittel','unsicher'): continue
        row = conn.execute('SELECT * FROM articles WHERE number=?', (number,)).fetchone()
        if row:
            result.append({**dict(row), 'confidence': confidence, 'reason': str(reason).split('\n')[0][:200]})
            seen.add(number)
        if len(result) == 8: break
    return result

def search(query, category='', rerank=False, use_ai=False):
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM articles' + (' WHERE category=?' if category else ''), (category,) if category else ())]
        if not rows: return [], 'local'
        terms = re.findall(r'[\w]+', normalize(query))
        fts = []
        if terms:
            expression = ' OR '.join('"' + t + '"' for t in terms[:20])
            fts = [r[0] for r in conn.execute('SELECT number FROM article_fts WHERE article_fts MATCH ? LIMIT 500', (expression,))]
        # Bound fuzzy work when FTS finds candidates; retain exact identifiers and dimensions.
        fts_set = set(fts)
        normalized_query = normalize(query)
        query_dimensions = dimensions(query)
        pool = [r for r in rows if r['number'] in fts_set or normalized_query in (normalize(r['number']), normalize(r['ean'])) or (query_dimensions and query_dimensions & dimensions(r['search_text']))] if fts else rows
        local = local_rank(query, pool, fts)[:100]
        ordered = local; mode = 'local'
        if use_ai and ai.available():
            try:
                vectors = {r['hash']: np.frombuffer(r['vector'], dtype=np.float32) for r in conn.execute('SELECT hash, vector FROM embeddings WHERE provider=? AND model=? AND dimensions=?', ('openai', ai.MODEL, ai.DIMENSIONS))}
                indexed = [r for r in rows if r['hash'] in vectors and vectors[r['hash']].shape == (ai.DIMENSIONS,)]
                if indexed:
                    vector = ai.embed([query], query=True)[0]
                    matrix = np.stack([vectors[r['hash']] for r in indexed])
                    scores = matrix @ vector / np.maximum(np.linalg.norm(matrix, axis=1) * np.linalg.norm(vector), 1e-9)
                    semantic = [indexed[i]['number'] for i in np.argsort(-scores)[:100]]
                    ordered = rrf(local, semantic); mode = 'semantic'
            except Exception: mode = 'local'
        by_id = {r['number']: r for r in rows}; candidates = [by_id[n] for n in ordered[:20] if n in by_id]
        if rerank and mode == 'semantic' and candidates:
            try:
                items = ai.rerank(query, [{k:r[k] for k in ('number','name','extra','category')} for r in candidates[:15]])
                ranked = validate_ranking(items, candidates[:15], conn)
                if ranked: return ranked, 'ai'
            except Exception: mode = 'local'
        return [{**r, 'confidence':'unsicher', 'reason':''} for r in (candidates if mode != 'local' else [by_id[n] for n in local[:20]])], mode
