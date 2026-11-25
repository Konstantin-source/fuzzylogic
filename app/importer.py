import csv
import hashlib
import io
import json
import re
import unicodedata
from openpyxl import load_workbook
from app import db

FIELDS = {'number': ['artikelnummer','artnr','artikelnr','artikel nr','sku','nummer'], 'name': ['bezeichnung','artikelbezeichnung','name','beschreibung'], 'extra': ['zusatztext','zusatz','langtext','masse','maße'], 'category': ['warengruppe','gruppe','kategorie'], 'unit': ['einheit','me'], 'ean': ['ean','gtin','barcode'], 'location': ['lagerort','lagerplatz','ort']}

def key(s):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', s.casefold()).encode('ascii', 'ignore').decode())

def suggest(columns):
    normalized = {key(c): c for c in columns}
    return {field: next((normalized[key(a)] for a in aliases if key(a) in normalized), '') for field, aliases in FIELDS.items()}

def parse(filename, content):
    if filename.lower().endswith('.xlsx'):
        sheet = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
        rows = list(sheet.values)
        if not rows: raise ValueError('Die Datei ist leer.')
        columns = [str(c or '').strip() for c in rows[0]]
        records = [[str(v).strip() if v is not None else '' for v in row] for row in rows[1:]]
    elif filename.lower().endswith('.csv'):
        for encoding in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
            try:
                text = content.decode(encoding); break
            except UnicodeDecodeError: continue
        try: dialect = csv.Sniffer().sniff(text[:8192], delimiters=';,\t')
        except csv.Error: dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text, newline=''), dialect))
        if not rows: raise ValueError('Die Datei ist leer.')
        columns, records = [c.strip() for c in rows[0]], rows[1:]
    else: raise ValueError('Nur CSV und XLSX werden unterstützt.')
    if not columns or any(not c for c in columns) or len(columns) != len(set(columns)):
        raise ValueError('Spaltennamen müssen eindeutig und nicht leer sein.')
    return columns, [dict(zip(columns, row)) for row in records if any(str(v).strip() for v in row)]

def mapping_for(columns):
    signature = json.dumps(columns, ensure_ascii=False)
    with db.connect() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key=?', ('mapping:' + signature,)).fetchone()
    return json.loads(row['value']) if row else suggest(columns)

def import_rows(columns, records, mapping):
    if not mapping.get('number') or not mapping.get('name') or any(v and v not in columns for v in mapping.values()):
        raise ValueError('Artikelnummer und Bezeichnung müssen gültigen Spalten zugeordnet sein.')
    with db.connect() as conn:
        syn = db.synonyms(conn)
        articles = []
        seen = set()
        for record in records:
            values = {f: str(record.get(mapping.get(f, ''), '') or '').strip() for f in FIELDS}
            number = values['number']
            if not number or not values['name']: raise ValueError('Jeder Artikel benötigt Artikelnummer und Bezeichnung.')
            if number in seen: raise ValueError('Artikelnummern müssen eindeutig sein.')
            seen.add(number)
            search_text = ' '.join([*values.values(), *syn.get(number, [])])
            from app.search import normalize
            digest = hashlib.sha256(normalize(search_text).encode()).hexdigest()
            articles.append((*values.values(), search_text, digest))
        if not articles: raise ValueError('Keine Artikel gefunden.')
        conn.execute('DELETE FROM article_fts')
        conn.execute('DELETE FROM articles')
        conn.executemany('INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?)', articles)
        conn.executemany('INSERT INTO article_fts(number, search_text) VALUES (?,?)', [(a[0], a[7]) for a in articles])
        conn.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('mapping:' + json.dumps(columns, ensure_ascii=False), json.dumps(mapping, ensure_ascii=False)))
    return len(articles)
