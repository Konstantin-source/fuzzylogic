import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA_DIR / "catalog.sqlite3", timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init():
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS articles (number TEXT PRIMARY KEY, name TEXT NOT NULL, extra TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL, ean TEXT NOT NULL, location TEXT NOT NULL, search_text TEXT NOT NULL, hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS synonyms (number TEXT NOT NULL, term TEXT NOT NULL, PRIMARY KEY(number, term));
        CREATE TABLE IF NOT EXISTS embeddings (hash TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, dimensions INTEGER NOT NULL, vector BLOB NOT NULL, PRIMARY KEY(hash, provider, model, dimensions));
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS article_fts USING fts5(number UNINDEXED, search_text, tokenize='unicode61 remove_diacritics 2');
        ''')
        article_columns = {row['name'] for row in db.execute('PRAGMA table_info(articles)')}
        for name in ('matchcode', 'width', 'height', 'length'):
            if name not in article_columns:
                db.execute(f"ALTER TABLE articles ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        columns = {row['name'] for row in db.execute('PRAGMA table_info(embeddings)')}
        if not {'provider', 'dimensions'} <= columns:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DROP TABLE embeddings')
            db.execute('CREATE TABLE embeddings (hash TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, dimensions INTEGER NOT NULL, vector BLOB NOT NULL, PRIMARY KEY(hash, provider, model, dimensions))')

def synonyms(db):
    result = {}
    for row in db.execute('SELECT number, term FROM synonyms'):
        result.setdefault(row['number'], []).append(row['term'])
    return result
