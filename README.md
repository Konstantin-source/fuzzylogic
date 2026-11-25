# Artikelsuche

Eine lokale Webanwendung für die Suche in ERP-Artikellisten. SQLite, FTS5 und Fuzzy-Suche funktionieren ohne API-Schlüssel; optional ergänzt OpenAI die semantische Suche und das Reranking.

## Schnellstart

1. `cp .env.example .env`
2. In `.env` den `OPENAI_API_KEY` eintragen. Ohne Schlüssel funktioniert die lokale Suche.
3. `docker compose up -d`

Im Browser `http://localhost:8080` oder im LAN `http://<HOST-IP>:8080` öffnen. Der Host-Port ist über `APP_PORT` konfigurierbar. Die Anwendung hat keine Anmeldung: Nur in einem vertrauenswürdigen Netzwerk betreiben und den Zugriff über Netzwerkregeln beschränken.

## Katalog importieren

Über **Katalog importieren** eine CSV- oder XLSX-Datei auswählen, die erkannten Spalten kontrollieren und den Import starten. Artikelnummer und Bezeichnung sind Pflichtfelder; Artikelnummern müssen eindeutig sein. Der Import ersetzt den bisherigen Katalog vollständig. Das Mapping wird pro Spaltenstruktur gespeichert. `sample_data/demo_catalog.csv` enthält ausschließlich erfundene Beispieldaten. CSV akzeptiert UTF-8, Windows-1252 und Latin-1 sowie Semikolon, Komma und Tabulator. XLSX verwendet das erste Tabellenblatt.

Datenbank, Zuordnungen, Synonyme und Embedding-Cache liegen in `./data` und sind durch `.gitignore` ausgeschlossen. Synonyme bleiben auch nach einem Reimport erhalten. Bei geändertem Text werden nur fehlende Embeddings erneut erstellt. Ohne API oder bei Fehlern wird lokal gesucht; ein erneuter Import oder Neustart setzt die Indexierung fort. Modell und Dimension werden im Cache getrennt; nach einem Wechsel werden Embeddings neu erzeugt. OpenAI erhält bei aktivierter API Artikeltexte zur Embedding-Erstellung und Suchanfragen; beim Reranking zusätzlich die ausgewählten Kandidaten. Nur verwenden, wenn diese Übermittlung für die Daten zulässig ist.

Beim Tippen werden ausschließlich lokale Vorschläge angezeigt. Erst **Suchen** oder `Enter` startet die semantische Suche und gegebenenfalls das KI-Reranking; ein weiteres `Enter` kopiert den ersten Treffer. Mit `/` das Suchfeld fokussieren und mit `Esc` leeren. `OPENAI_REASONING_EFFORT=none` begrenzt den Reasoning-Aufwand; `low` und `medium` sind ebenfalls möglich. API-Nutzung kann Kosten verursachen. Die Kopierfunktion unterstützt auch HTTP im LAN. Suchverlauf und letzte fünf Suchbegriffe liegen im Browser.

## Entwicklung

Python 3.12: `pip install -r requirements.txt`, dann `pytest` und `uvicorn app.main:app --reload`. `DATA_DIR` kann für lokale Entwicklung das Datenverzeichnis festlegen. API-Schlüssel gehören ausschließlich in die lokale `.env`, nicht in das Repository. Die Demo-Datei ist die einzige freigegebene CSV; produktive Exporte müssen außerhalb des Repositorys bleiben.
