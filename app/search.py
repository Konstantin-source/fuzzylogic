import re
import threading
from functools import lru_cache
import numpy as np
from rapidfuzz.fuzz import token_set_ratio
from app import db, families, openai_client as ai

_vector_lock = threading.Lock()
_vector_cache = None

def invalidate_embedding_cache():
    global _vector_cache
    with _vector_lock:
        _vector_cache = None

def embedding_index(conn):
    """Build once per catalogue revision; cached rows and query use unit vectors."""
    global _vector_cache
    key = (str(db.DATA_DIR.resolve()), ai.MODEL, ai.DIMENSIONS)
    with _vector_lock:
        if _vector_cache is not None and _vector_cache[0] == key:
            return _vector_cache[1:]
        vectors, hashes = [], []
        sql = '''SELECT DISTINCT e.hash, e.vector FROM embeddings e
                 JOIN articles a ON a.hash=e.hash
                 WHERE e.provider=? AND e.model=? AND e.dimensions=?'''
        for row in conn.execute(sql, ('openai', ai.MODEL, ai.DIMENSIONS)):
            vector = np.frombuffer(row['vector'], dtype=np.float32)
            if vector.shape == (ai.DIMENSIONS,) and np.isfinite(vector).all():
                hashes.append(row['hash'])
                vectors.append(vector)
        matrix = np.stack(vectors) if vectors else np.empty((0, ai.DIMENSIONS), dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        np.divide(matrix, np.maximum(norms, 1e-9), out=matrix)
        index = {digest: i for i, digest in enumerate(hashes)}
        _vector_cache = (key, matrix, index)
        return matrix, index

@lru_cache(maxsize=50000)
def normalize(text):
    text = str(text).casefold().replace('ä','ae').replace('ö','oe').replace('ü','ue').replace('ß','ss')
    text = re.sub(r'(?<=\d)\s*[x*/]\s*(?=\d)', 'x', text)
    text = re.sub(r'(?<=\d)\s*(mm|cm)\b', '', text)
    return ' '.join(re.findall(r'[a-z0-9]+(?:x[0-9]+)*', text))

def dimensions(text):
    return set(re.findall(r'\b(?:m)?\d+(?:x\d+)+\b', normalize(text)))

def related_search_terms(query):
    """Narrow, directional hints for common product-use relationships."""
    text = normalize(query)
    if families.seeks_outer_frame(text):
        # Preserve a specified colour; this relationship is a suggestion, not an assertion.
        colour = (' ' + families.colour(query)).rstrip()
        return ['Schattenfugenrahmen' + colour, 'Schattenfuge' + colour]
    return []

def rrf(*rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, number in enumerate(ranking, 1): scores[number] = scores.get(number, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda n: (-scores[n], n))

def local_rank(query, rows, fts_numbers=(), wanted=()):
    q = normalize(query); tokens = set(q.split())
    requested = families.measures(query, next(iter(wanted)) if len(wanted) == 1 else '')
    requested_colour = families.colour(query)
    fts = set(fts_numbers)
    def score(row):
        text = normalize(row['search_text'])
        value = token_set_ratio(q, text) / 100 + (0.3 if row['number'] in fts else 0)
        value += 0.2 * len(tokens & set(text.split())) / max(len(tokens), 1)
        if q and q in (normalize(row['number']), normalize(row['ean'])): return 100
        if row['family'] in wanted:
            value += 8
        if requested_colour:
            actual = families.colour(row['name'] + ' ' + row['extra'])
            value += 1.5 if requested_colour == actual else -0.5 if actual else 0
        value += families.measure_score(requested, row)
        return value
    return [r['number'] for r in sorted(rows, key=lambda r: (-score(r), r['number']))]

def semantic_rank(conn, rows, query):
    matrix, indexes = embedding_index(conn)
    indexed = [row for row in rows if row['hash'] in indexes]
    if not indexed:
        return []
    vector = ai.embed([query], query=True)[0]
    scores = matrix @ (vector / max(np.linalg.norm(vector), 1e-9))
    scores = np.asarray([scores[indexes[row['hash']]] for row in indexed])
    return [indexed[i]['number'] for i in np.argsort(-scores)[:100]]

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

def ai_search(query, category='', rerank=False):
    """Search the catalog using generated terms; generated text is never treated as an article."""
    hints = related_search_terms(query)
    available = ai.available()
    with db.connect() as conn:
        vocab = families.vocabulary(conn, category)
        wanted = families.intent(query, vocab)
        options = families.shortlist(conn, query, vocab, wanted, category) if available else []
    generated = []
    failed = False
    if available:
        try:
            generated = ai.expand_query(query, options)
        except Exception:
            failed = True
    terms, seen_terms = [], set()
    for term in hints + generated:
        normalized = normalize(term)
        if normalized and normalized not in seen_terms:
            terms.append(term)
            seen_terms.add(normalized)
    if not terms:
        message = ('KI-Suche nicht verfügbar. Lokale Treffer bleiben sichtbar.' if not available or failed
                   else 'Die KI hat keine zusätzlichen Suchbegriffe gefunden.')
        return {'results': [], 'terms': [], 'mode': 'local', 'message': message}
    notice = 'KI nicht erreichbar; verwandte Begriffe werden lokal gesucht.' if not available or failed else ''
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM articles' + (' WHERE category=?' if category else ''), (category,) if category else ())]
        by_id = {row['number']: row for row in rows}
        rankings = []
        selected = set(wanted)
        for term in generated:
            selected.update(families.intent(term, vocab))
        if selected:
            members = [r for r in rows if r['family'] in selected]
            rankings.append(local_rank(query, members, wanted=wanted or selected)[:20])
        for term in terms:
            tokens = re.findall(r'[\w]+', normalize(term))[:12]
            if not tokens:
                continue
            # Prefix matches also find longer catalogue abbreviations and compounds.
            expression = ' OR '.join('"' + t + '"' + ('*' if len(t) >= 4 else '') for t in tokens)
            if category:
                sql = ('SELECT article_fts.number FROM article_fts JOIN articles a ON a.number=article_fts.number '
                       'WHERE article_fts MATCH ? AND a.category=? ORDER BY bm25(article_fts) LIMIT 500')
                found = [r[0] for r in conn.execute(sql, (expression, category))]
            else:
                found = [r[0] for r in conn.execute('SELECT number FROM article_fts WHERE article_fts MATCH ? ORDER BY bm25(article_fts) LIMIT 500', (expression,))]
            pool = [by_id[number] for number in found if number in by_id]
            rankings.append(local_rank(term, pool, found)[:15])
        # Preserve a semantic route for the user's original wording if indexed.
        if available and not failed:
            try:
                semantic = semantic_rank(conn, rows, query)
                if semantic:
                    rankings.append(semantic[:20])
            except Exception:
                pass  # Generated search terms still work when embeddings are unavailable.
        # Interleave independently retrieved lists so one wording cannot hide all others.
        ordered, seen = [], set()
        for position in range(max((len(r) for r in rankings), default=0)):
            for ranking in rankings:
                if position < len(ranking) and ranking[position] not in seen:
                    number = ranking[position]
                    if number in by_id:
                        ordered.append(number)
                        seen.add(number)
                if len(ordered) >= 20:
                    break
            if len(ordered) >= 20:
                break
        candidates = [by_id[number] for number in ordered]
        plain = [{**row, 'confidence': 'unsicher', 'reason': ''} for row in candidates]
        if rerank and candidates and available and not failed:
            try:
                fields = ('number','name','extra','category','matchcode','width','height','length')
                items = ai.rerank(query, [{k:row[k] for k in fields} for row in candidates[:15]])
                ranked = validate_ranking(items, candidates[:15], conn)
                ranked_ids = {row['number'] for row in ranked}
                if ranked:
                    ordered_results = ranked + [row for row in plain if row['number'] not in ranked_ids]
                    # Keep a locally suggested relationship visible even if the LLM omits it.
                    if (hints or selected) and rankings and rankings[0]:
                        suggested_id = rankings[0][0]
                        suggested = next((row for row in ordered_results if row['number'] == suggested_id), None)
                        if suggested and suggested_id not in {row['number'] for row in ordered_results[:4]}:
                            ordered_results = [suggested] + [row for row in ordered_results if row['number'] != suggested_id]
                    return {'results': ordered_results, 'terms': terms, 'mode': 'ai', 'message': notice}
            except Exception:
                return {'results': plain, 'terms': terms, 'mode': 'terms', 'message': 'KI-Sortierung nicht verfügbar; Treffer bitte prüfen.'}
        return {'results': plain, 'terms': terms, 'mode': 'terms' if available and not failed else 'local', 'message': notice}

def search(query, category='', rerank=False, use_ai=False):
    with db.connect() as conn:
        wanted = families.intent(query, families.vocabulary(conn, category))
        terms = re.findall(r'[\w]+', normalize(query))
        fts = []
        if terms:
            expression = ' OR '.join('"' + t + '"' for t in terms[:20])
            scope = ' AND a.category=?' if category else ''
            fts = [r[0] for r in conn.execute('SELECT a.number FROM article_fts JOIN articles a ON a.number=article_fts.number '
                                              'WHERE article_fts MATCH ?' + scope + ' ORDER BY bm25(article_fts) LIMIT 500',
                                              (expression, category) if category else (expression,))]
        filters, params = [], []
        if category:
            filters.append('category=?')
            params.append(category)
        # With a possible formatted SKU, retain normalized identifier matching beyond the FTS limit.
        possible_identifier = not wanted and any(ch.isdigit() for ch in query)
        if (fts or wanted) and not use_ai and not possible_identifier:
            clauses = ['number=? COLLATE NOCASE', 'ean=?']
            params.extend((query, query))
            for field, values in (('number', fts), ('family', sorted(wanted))):
                if values:
                    clauses.append(field + ' IN (' + ','.join('?' for _ in values) + ')')
                    params.extend(values)
            filters.append('(' + ' OR '.join(clauses) + ')')
        sql = 'SELECT * FROM articles' + (' WHERE ' + ' AND '.join(filters) if filters else '')
        rows = [dict(r) for r in conn.execute(sql, params)]
        if not rows:
            return [], 'local'
        local = local_rank(query, rows, fts, wanted)[:100]
        ordered = local; mode = 'local'
        if use_ai and ai.available():
            try:
                semantic = semantic_rank(conn, rows, query)
                if semantic:
                    ordered = rrf(local, semantic); mode = 'semantic'
            except Exception: mode = 'local'
        by_id = {r['number']: r for r in rows}; candidates = [by_id[n] for n in ordered[:20] if n in by_id]
        if rerank and mode == 'semantic' and candidates:
            try:
                items = ai.rerank(query, [{k:r[k] for k in ('number','name','extra','category','matchcode','width','height','length')} for r in candidates[:15]])
                ranked = validate_ranking(items, candidates[:15], conn)
                if ranked: return ranked, 'ai'
            except Exception: mode = 'local'
        return [{**r, 'confidence':'unsicher', 'reason':''} for r in (candidates if mode != 'local' else [by_id[n] for n in local[:20]])], mode
