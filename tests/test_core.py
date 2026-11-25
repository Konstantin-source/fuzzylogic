import os
import pytest
from app import db, importer, search

@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('APP_USERNAME', 'test-user')
    monkeypatch.setenv('APP_PASSWORD', 'test-password-long-enough')
    db.init()

def test_csv_encoding_and_mapping():
    columns, rows = importer.parse('test.csv', 'Artikelnummer;Bezeichnung;Warengruppe\nA1;Winkel für Rohr;Verbinder\n'.encode('cp1252'))
    assert rows[0]['Bezeichnung'] == 'Winkel für Rohr'
    assert importer.suggest(columns)['number'] == 'Artikelnummer'
    assert importer.suggest(columns)['name'] == 'Bezeichnung'

def test_dimensions():
    assert search.dimensions('20x40') == search.dimensions('20 x 40 mm') == search.dimensions('20*40') == search.dimensions('20/40')
    assert search.dimensions('M8x40') == search.dimensions('M8 x 40 mm')

def load():
    columns, rows = importer.parse('test.csv', 'Artikelnummer;Bezeichnung;Zusatztext\nA1;Winkel;20 x 40 mm\nA2;Schraube;M8x40 Edelstahl\n'.encode())
    importer.import_rows(columns, rows, importer.suggest(columns))

def test_local_and_rrf():
    load()
    results, mode = search.search('M8 x 40')
    assert mode == 'local' and results[0]['number'] == 'A2'
    assert search.rrf(['A1','A2'], ['A2','A1'])[0] == 'A1'
    assert search.rrf(['A1','A2'], ['A2'])[0] == 'A2'

def test_reranking_rejects_invented_and_noncandidate_numbers():
    load()
    with db.connect() as conn:
        candidate = dict(conn.execute("SELECT * FROM articles WHERE number='A1'").fetchone())
        ranked = search.validate_ranking([{'number':'FAKE','confidence':'hoch','reason':'erfunden'}, {'number':'A2','confidence':'hoch','reason':'fremd'}, {'number':'A1','confidence':'hoch','reason':'passend'}, {'number':'A1','confidence':'hoch','reason':'doppelt'}], [candidate], conn)
    assert [r['number'] for r in ranked] == ['A1']
    assert ranked[0]['name'] == 'Winkel'

def test_synonyms_survive_reimport():
    load()
    with db.connect() as conn: conn.execute('INSERT INTO synonyms VALUES (?, ?)', ('A1','Eckstück'))
    load()
    results, _ = search.search('Eckstück')
    assert results[0]['number'] == 'A1'

def test_mocked_semantic_reranker_cannot_invent(monkeypatch):
    import numpy as np
    from app import openai_client as ai
    load()
    monkeypatch.setattr(ai, 'available', lambda: True)
    monkeypatch.setattr(ai, 'embed', lambda texts, query=False: [np.ones(ai.DIMENSIONS, dtype=np.float32) for _ in texts])
    monkeypatch.setattr(ai, 'rerank', lambda query, candidates: [{'number':'FAKE','confidence':'hoch','reason':'erfunden'}, {'number':'A1','confidence':'hoch','reason':'passend'}])
    with db.connect() as conn:
        for row in conn.execute('SELECT hash FROM articles').fetchall():
            conn.execute('INSERT INTO embeddings VALUES (?,?,?,?,?)', (row['hash'], 'openai', ai.MODEL, ai.DIMENSIONS, np.ones(ai.DIMENSIONS, dtype=np.float32).tobytes()))
    results, mode = search.search('Winkel', rerank=True, use_ai=True)
    assert mode == 'ai'
    assert [r['number'] for r in results] == ['A1']

def test_api_error_falls_back(monkeypatch):
    import numpy as np
    from app import openai_client as ai
    load()
    monkeypatch.setattr(ai, 'available', lambda: True)
    def fail(*args, **kwargs): raise RuntimeError('offline')
    monkeypatch.setattr(ai, 'embed', fail)
    with db.connect() as conn:
        row = conn.execute('SELECT hash FROM articles LIMIT 1').fetchone()
        conn.execute('INSERT INTO embeddings VALUES (?,?,?,?,?)', (row['hash'], 'openai', ai.MODEL, ai.DIMENSIONS, np.ones(ai.DIMENSIONS, dtype=np.float32).tobytes()))
    results, mode = search.search('Winkel', use_ai=True)
    assert mode == 'local' and results[0]['number'] == 'A1'

def test_upload_search_api():
    from fastapi.testclient import TestClient
    from app.main import app
    import json
    with TestClient(app) as client:
        client.auth = ('test-user', 'test-password-long-enough')
        content = b'Artikelnummer;Bezeichnung;Zusatztext\nX1;Winkel;20x40 mm\n'
        response = client.post('/api/preview', files={'file': ('catalog.csv', content, 'text/csv')})
        assert response.status_code == 200
        response = client.post('/api/import', files={'file': ('catalog.csv', content, 'text/csv')}, data={'mapping': json.dumps(response.json()['mapping'])})
        assert response.status_code == 200
        response = client.get('/api/search', params={'q':'20 x 40 mm'})
        assert response.status_code == 200
        assert response.json()['results'][0]['number'] == 'X1'



def test_embedding_cache_changes_model_and_dimensions(monkeypatch):
    import numpy as np
    from app import main, openai_client as ai
    load()
    calls = []
    monkeypatch.setattr(ai, 'available', lambda: True)
    monkeypatch.setattr(ai, 'embed', lambda texts: calls.append(list(texts)) or [np.ones(ai.DIMENSIONS, dtype=np.float32) for _ in texts])
    def index():
        main.jobs['test'] = {}
        main.index_embeddings('test')
        assert main.jobs['test']['status'] == 'done'
    index()
    index()
    assert len(calls) == 1
    monkeypatch.setattr(ai, 'MODEL', 'different-embedding-model')
    index()
    assert len(calls) == 2
    monkeypatch.setattr(ai, 'DIMENSIONS', 64)
    index()
    assert len(calls) == 3
    with db.connect() as conn:
        variants = conn.execute('SELECT DISTINCT provider, model, dimensions FROM embeddings').fetchall()
    assert len(variants) == 3

def test_legacy_embedding_cache_is_discarded():
    with db.connect() as conn:
        conn.execute('DROP TABLE embeddings')
        conn.execute('CREATE TABLE embeddings (hash TEXT, model TEXT, vector BLOB, PRIMARY KEY(hash, model))')
        conn.execute('INSERT INTO embeddings VALUES (?, ?, ?)', ('hash', 'old-model', b'old'))
    db.init()
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0] == 0
        assert {'provider', 'dimensions'} <= {r['name'] for r in conn.execute('PRAGMA table_info(embeddings)')}

def test_reasoning_effort_and_structured_output(monkeypatch):
    from types import SimpleNamespace
    from app import openai_client as ai
    called = {}
    def parse(**kwargs):
        called.update(kwargs)
        return SimpleNamespace(output_parsed=ai.Ranking(results=[ai.RankedItem(number='A1', confidence='hoch', reason='Passend.')]))
    monkeypatch.setattr(ai, 'client', lambda: SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    monkeypatch.setattr(ai, 'REASONING_EFFORT', 'low')
    assert ai.rerank('Winkel', [{'number':'A1'}])[0].number == 'A1'
    assert called['reasoning'] == {'effort':'low'}
    assert called['text_format'] is ai.Ranking

def test_local_search_never_calls_api(monkeypatch):
    from app import openai_client as ai
    load()
    monkeypatch.setattr(ai, 'available', lambda: True)
    def forbidden(*args, **kwargs):
        pytest.fail('Lokale Suche darf keine API aufrufen')
    monkeypatch.setattr(ai, 'embed', forbidden)
    monkeypatch.setattr(ai, 'rerank', forbidden)
    results, mode = search.search('Winkel', rerank=True)
    assert mode == 'local' and results[0]['number'] == 'A1'


def test_access_control_and_origin_checks():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        for path in ('/', '/api/config', '/api/search?q=x', '/static/app.js'):
            assert client.get(path).status_code == 401
        assert client.get('/api/config', auth=('test-user', 'wrong')).status_code == 401
        assert client.get('/api/config', auth=('test-user', 'test-password-long-enough')).status_code == 200
        assert client.post('/api/preview', auth=('test-user', 'test-password-long-enough'), headers={'origin':'https://outside.invalid'}).status_code == 403
        assert client.get('/api/config', auth=('test-user', 'test-password-long-enough'), headers={'sec-fetch-site':'cross-site'}).status_code == 403
        assert client.get('/api/config', auth=('test-user', 'test-password-long-enough'), headers={'origin':'http://testserver'}).status_code == 200
        assert client.get('/api/config', auth=('test-user', 'test-password-long-enough')).headers['x-frame-options'] == 'DENY'


def test_missing_credentials_refuse_startup(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('APP_PASSWORD')
    with pytest.raises(RuntimeError, match='APP_USERNAME'):
        with TestClient(app):
            pass


def test_selectline_columns_and_searchable_fields():
    content = ('Artikelnummer;EANNummer;Bezeichnung;Zusatz;Matchcode;Artikelgruppe;Mengeneinheit;_BREITE;_HOEHE;_LAENGE\n'
               'S001;0123456789012;Profil;Aluminium;Eckprofil;Profile;Stk;20,000;40,000;0\n').encode('utf-8-sig')
    columns, rows = importer.parse('catalog.csv', content)
    mapping = importer.suggest(columns)
    assert {name: mapping[name] for name in ('ean', 'category', 'unit', 'matchcode', 'width', 'height', 'length')} == {
        'ean':'EANNummer', 'category':'Artikelgruppe', 'unit':'Mengeneinheit', 'matchcode':'Matchcode',
        'width':'_BREITE', 'height':'_HOEHE', 'length':'_LAENGE'}
    assert importer.import_rows(columns, rows, mapping) == 1
    with db.connect() as conn:
        article = conn.execute('SELECT * FROM articles').fetchone()
        assert article['ean'] == '0123456789012'
        assert article['category'] == 'Profile'
        assert article['unit'] == 'Stk'
        assert '20x40' in article['search_text']
    for query in ('Eckprofil', '0123456789012', '20x40'):
        results, _ = search.search(query)
        assert results[0]['number'] == 'S001'


def test_synonym_preserves_selectline_search_fields():
    from fastapi.testclient import TestClient
    from app.main import app
    columns, rows = importer.parse('catalog.csv', b'Artikelnummer;Bezeichnung;Matchcode;_BREITE;_HOEHE\nS001;Profil;Eckprofil;20;40\n')
    importer.import_rows(columns, rows, importer.suggest(columns))
    with TestClient(app) as client:
        response = client.post('/api/articles/S001/synonyms', auth=('test-user', 'test-password-long-enough'), json={'term':'Kurzprofil'})
        assert response.status_code == 200
    for query in ('Eckprofil', '20x40', 'Kurzprofil'):
        results, _ = search.search(query)
        assert results[0]['number'] == 'S001'
    with db.connect() as conn:
        row = conn.execute('SELECT search_text FROM articles WHERE number=?', ('S001',)).fetchone()
        assert all(term in row['search_text'] for term in ('Eckprofil', '20x40', 'Kurzprofil'))


def test_existing_catalog_schema_is_migrated():
    with db.connect() as conn:
        conn.execute('DROP TABLE articles')
        conn.execute("CREATE TABLE articles (number TEXT PRIMARY KEY, name TEXT NOT NULL, extra TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL, ean TEXT NOT NULL, location TEXT NOT NULL, search_text TEXT NOT NULL, hash TEXT NOT NULL)")
        conn.execute("INSERT INTO articles VALUES ('S001','Profil','','','','','','Profil','hash')")
    db.init()
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM articles WHERE number=?', ('S001',)).fetchone()
        assert row['name'] == 'Profil'
        assert all(row[field] == '' for field in ('matchcode', 'width', 'height', 'length'))


def test_import_accepts_empty_description_without_fabricating_data():
    from fastapi.testclient import TestClient
    from app.main import app
    import json
    content = 'Artikelnummer;Bezeichnung;Zusatz\nA1;;Winkel\nA2;Schraube;\n'.encode()
    columns, rows = importer.parse('catalog.csv', content)
    with TestClient(app) as client:
        response = client.post('/api/import', auth=('test-user', 'test-password-long-enough'), files={'file': ('catalog.csv', content, 'text/csv')}, data={'mapping': json.dumps(importer.suggest(columns))})
        assert response.status_code == 200
        assert response.json()['count'] == 2
        assert response.json()['without_name'] == 1
    with db.connect() as conn:
        assert conn.execute('SELECT name FROM articles WHERE number=?', ('A1',)).fetchone()['name'] == ''
    assert search.search('Winkel')[0][0]['number'] == 'A1'


def test_missing_number_rejects_import_and_preserves_existing_catalog():
    load()
    columns, rows = importer.parse('catalog.csv', b'Artikelnummer;Bezeichnung\n;Winkel\n')
    with pytest.raises(ValueError, match='Artikelnummer'):
        importer.import_rows(columns, rows, importer.suggest(columns))
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0] == 2
