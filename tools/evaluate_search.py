"""Run the synthetic search suite or compare existing embedding indices using labelled queries."""
import argparse
import gc
import json
import statistics
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from app import db, families, importer, openai_client as ai, search


FIXTURE = Path(__file__).with_name('search_cases.json')


def seed(rows):
    columns = ['number', 'name', 'extra']
    importer.import_rows(columns, rows, {key: key for key in columns})


def evaluate(cases, semantic=False):
    ranks, times = [], []
    for case in cases:
        start = perf_counter()
        rows, mode = search.search(case['query'], use_ai=semantic)
        times.append((perf_counter() - start) * 1000)
        if semantic and mode != 'semantic':
            raise ValueError('Keine semantischen Ergebnisse. Index und API-Verbindung prüfen.')
        families.prepare_results(rows, case['query'])
        seen, visible = set(), []
        for row in rows:
            key = row['variant_key'] or (row['number'],)
            if key not in seen:
                visible.append(row['number'])
                seen.add(key)
        ranks.append(next((i for i, n in enumerate(visible, 1) if n in case['expected']), 0))
    return ranks, times


def report(label, cases, semantic=False):
    ranks, times = evaluate(cases, semantic)
    top3 = sum(0 < rank <= 3 for rank in ranks)
    print(f'{label} | Top 1: {ranks.count(1)}/{len(ranks)} | Top 3: {top3}/{len(ranks)}'
          f' | Median: {statistics.median(times):.1f} ms | Maximum: {max(times):.1f} ms')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, help='Private JSON-Datei mit cases für den bestehenden Katalog')
    parser.add_argument('--dimensions', type=int, nargs='+', help='Vorhandene Indizes vergleichen (kostenpflichtige Anfrage-Embeddings)')
    args = parser.parse_args()
    fixture = json.loads((args.cases or FIXTURE).read_text(encoding='utf-8'))
    cases = fixture['cases']
    if not cases:
        parser.error('Mindestens einen Testfall angeben.')
    if not args.cases:
        if args.dimensions:
            parser.error('Für die Dimensionsmessung eigene Testfälle und DATA_DIR angeben.')
        with tempfile.TemporaryDirectory() as tmp:
            db.DATA_DIR = Path(tmp)
            db.init()
            seed(fixture['articles'])
            report('Synthetischer Katalog, lokal', cases)
            gc.collect()  # Close SQLite handles before removing the Windows temporary directory.
        return
    if not (db.DATA_DIR / 'catalog.sqlite3').is_file():
        parser.error('DATA_DIR muss auf einen bestehenden, aktualisierten Katalog zeigen.')
    with db.connect() as conn:
        ids = {r[0] for r in conn.execute('SELECT number FROM articles')}
        if any(not set(case['expected']) <= ids or not case['expected'] for case in cases):
            parser.error('Erwartete Artikelnummern fehlen im Katalog oder Testfall.')
        for dim in args.dimensions or []:
            missing = conn.execute('SELECT count(*) FROM articles a WHERE NOT EXISTS (SELECT 1 FROM embeddings e '
                                   'WHERE e.hash=a.hash AND e.model=? AND e.provider=? AND e.dimensions=?)',
                                   (ai.MODEL, 'openai', dim)).fetchone()[0]
            if missing or not ai.available():
                parser.error(f'{dim} Dimensionen erfordern einen vollständigen Index und OpenAI-Zugang.')
    report('Lokal', cases)
    for dim in args.dimensions or []:
        ai.DIMENSIONS = dim
        report(f'Hybrid {dim}', cases, semantic=True)


if __name__ == '__main__':
    sys.exit(main())
