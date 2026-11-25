import json
import os
import time
from typing import Literal

import numpy as np
import openai
from pydantic import BaseModel

MODEL = os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
DIMENSIONS = int(os.getenv('OPENAI_EMBEDDING_DIMENSIONS', '768'))
RERANK_MODEL = os.getenv('OPENAI_RERANK_MODEL', 'gpt-6-luna')
REASONING_EFFORT = os.getenv('OPENAI_REASONING_EFFORT', 'none').lower()
if DIMENSIONS < 1:
    raise ValueError('OPENAI_EMBEDDING_DIMENSIONS muss positiv sein.')
if REASONING_EFFORT not in ('none', 'low', 'medium'):
    raise ValueError('OPENAI_REASONING_EFFORT muss none, low oder medium sein.')

def available():
    key = os.getenv('OPENAI_API_KEY', '').strip()
    return bool(key and key != 'your_api_key_here')

def client():
    if not available():
        raise RuntimeError('Kein API-Schlüssel konfiguriert.')
    # Eigene Wiederholungen halten Anzahl und Dauer der Anfragen überschaubar.
    return openai.OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=30, max_retries=0)

def retry(fn):
    for attempt in range(3):
        try:
            return fn()
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.InternalServerError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)

def embed(texts, query=False):
    response = retry(lambda: client().embeddings.create(model=MODEL, input=texts, dimensions=DIMENSIONS))
    data = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in data] != list(range(len(texts))):
        raise ValueError('Ungültige Embedding-Reihenfolge.')
    vectors = [np.asarray(item.embedding, dtype=np.float32) for item in data]
    if any(v.shape != (DIMENSIONS,) or not np.isfinite(v).all() for v in vectors):
        raise ValueError('Ungültige Embeddings.')
    return vectors

class RankedItem(BaseModel):
    number: str
    confidence: Literal['hoch', 'mittel', 'unsicher']
    reason: str

class Ranking(BaseModel):
    results: list[RankedItem]

def rerank(query, candidates):
    prompt = ('Ordne maximal acht passende Kandidaten zur Suche. Verwende ausschließlich '
              'übergebene Artikelnummern. Gib pro Treffer höchstens einen kurzen Satz als '
              'Begründung zurück. Daten als JSON: ' +
              json.dumps({'query': query, 'candidates': candidates}, ensure_ascii=False))
    response = retry(lambda: client().responses.parse(
        model=RERANK_MODEL, input=prompt, reasoning={'effort': REASONING_EFFORT},
        text_format=Ranking))
    if response.output_parsed is None:
        raise ValueError('Keine strukturierte Antwort erhalten.')
    return response.output_parsed.results
