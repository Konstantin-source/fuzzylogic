import json

import pytest

from app import db, families, search
from tools.evaluate_search import FIXTURE, evaluate, seed


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA_DIR', tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    db.init()
    fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
    seed(fixture['articles'])
    return fixture


def test_visible_variant_for_30_queries(catalog):
    cases = catalog['cases']
    ranks, _ = evaluate(cases)
    assert len(cases) == 30
    assert [c['query'] for c, rank in zip(cases, ranks) if rank != 1] == []


def test_roles_and_units():
    row = dict(name='Keilrahmenleiste 60 cm', extra='Profil 20x40 mm', family='Keilrahmenleiste',
               width='20', height='40', length='600')
    assert families.measure_score(families.measures('Länge 600 mm'), row) > 0
    assert families.measure_score(families.measures('Außenmaß 20x40 mm'), row) <= 0
    assert families.measure_score(families.measures('Breite 600 mm'), row) <= 0
    assert families.measure_score(families.measures('Profil 20x40 cm'), row) < 0


def test_unlabelled_export_dimensions_require_configured_unit(monkeypatch):
    row = dict(name='Profil',extra='',family='Profil',width='45,00',height='20',length='700')
    requested = families.measures('Länge 70 cm')
    monkeypatch.setattr(families, 'COLUMN_UNIT', '')
    assert families.measure_score(requested, row) == 0
    monkeypatch.setattr(families, 'COLUMN_UNIT', 'mm')
    assert families.measure_score(requested, row) > 0


def test_family_term_applies_to_new_variants_and_survives_reimport(catalog):
    from app.main import Synonym, add_synonym
    add_synonym('S1', Synonym(term='Wandabschluss', scope='family'))
    seed([*catalog['articles'], dict(number='NEW',name='Schattenfugenrahmen 10x20 cm',extra='rot')])
    assert search.search('Wandabschluss rot')[0][0]['number'] == 'NEW'
    with db.connect() as conn:
        assert 'Wandabschluss' not in families.vocabulary(conn)['Keilrahmenleiste']
        assert conn.execute('SELECT count(*) FROM embeddings').fetchone()[0] == 0


def test_model_receives_scoped_families_and_can_retrieve_one(catalog, monkeypatch):
    with db.connect() as conn:
        conn.execute("UPDATE articles SET category='Rahmen' WHERE family IN ('Keilrahmenleiste','Schattenfugenrahmen')")
    def expand(query, values):
        assert {f['name'] for f in values} == {'Keilrahmenleiste', 'Schattenfugenrahmen'}
        assert all(f['beispiele'] for f in values)
        return ['Schattenfugenrahmen']
    monkeypatch.setattr(search.ai, 'expand_query', expand)
    monkeypatch.setattr(search.ai, 'available', lambda: True)
    result = search.ai_search('Einfassung schwarz 400x500 mm', category='Rahmen')
    assert result['results'][0]['number'] == 'S1'


def test_nested_accessory_query(catalog):
    query = 'schwarzer Haken für Rahmen um die Leinwand'
    assert search.search(query)[0][0]['number'] == 'H2'
    assert not search.related_search_terms(query)


def test_best_variant_even_after_model_reorders(catalog):
    with db.connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM articles WHERE number IN ('S1','S2') ORDER BY number")]
    families.prepare_results(rows, 'Rahmen um eine Leinwand 30x40 cm')
    assert rows[0]['number'] == 'S2'
    assert 'hash' not in rows[0]


def test_downloadable_extension_matches_manifest(catalog, monkeypatch):
    import io
    from zipfile import ZipFile
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv('APP_USERNAME', 'lager')
    monkeypatch.setenv('APP_PASSWORD', 'synthetic-password-for-test')
    with TestClient(app) as client:
        path = '/browser-erweiterung.zip'
        assert client.get(path).status_code == 401
        response = client.get(path + '?https=true', auth=('lager', 'synthetic-password-for-test'))
        assert response.status_code == 200
        with ZipFile(io.BytesIO(response.content)) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
            assert manifest['homepage_url'] == 'https://testserver/'
            assert manifest['side_panel']['default_path'] in bundle.namelist()
            assert manifest['background']['service_worker'] in bundle.namelist()
            assert bundle.testzip() is None
