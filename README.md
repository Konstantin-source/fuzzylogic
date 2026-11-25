# Artikelsuche

Eine lokale Webanwendung für die Suche in ERP-Artikellisten. SQLite, FTS5 und Fuzzy-Suche funktionieren ohne API-Schlüssel; optional ergänzt OpenAI die semantische Suche und das Reranking.

## Schnellstart

1. `cp .env.example .env`
2. In `.env` `APP_USERNAME` und ein langes, zufälliges `APP_PASSWORD` (mindestens 16 Zeichen) setzen. Optional den `OPENAI_API_KEY` eintragen; ohne Schlüssel funktioniert die lokale Suche.
3. Das Datenverzeichnis für den Container vorbereiten (siehe „Sicherer Betrieb im Netzwerk“).
4. `docker compose up -d`

Im Browser auf dem Server `http://localhost:8080` öffnen und mit den Zugangsdaten anmelden. Ohne korrekt gesetzte Zugangsdaten startet die App nicht. `APP_PORT` bestimmt den Host-Port; standardmäßig ist er nur auf `127.0.0.1` gebunden.

### Portainer

Für einen Git-basierten Portainer-Stack `docker-compose.portainer.yml` als Compose-Pfad wählen und die Werte aus `.env.example` in Portainer unter **Environment variables** setzen. Es wird keine `.env`-Datei auf dem Server benötigt. Die Variante verwendet ein separates Docker-Volume `artikelsuche_data` statt `./data`; vorhandene Daten werden nicht automatisch übernommen. Bei einem bestehenden Katalog vorher ein Backup erstellen und die Daten gezielt migrieren. Ein Build aus dem Git-Verzeichnis setzt voraus, dass die Portainer-Umgebung Builds unterstützt.

## Sicherer Betrieb im Netzwerk

- Die Anmeldung verwendet HTTP Basic Authentication. Ohne HTTPS werden Benutzername, Passwort und Inhalte unverschlüsselt übertragen. Für den Zugriff anderer Geräte einen internen HTTPS-Reverse-Proxy mit gültigem Zertifikat und Zugriffsbeschränkung vor die App setzen. Den internen App-Port nicht direkt im LAN oder Internet freigeben. Der Proxy muss die `Authorization`- und `Host`-Header korrekt weiterleiten; sein Zugang zu Port 8080 muss zum gewählten Netzwerkaufbau passen.
- Das gemeinsame Konto schützt den gesamten Zugriff, bietet aber **keine getrennten Rollen**: Angemeldete Nutzer können auch den Katalog ersetzen und Synonyme ändern. Für unterschiedliche Berechtigungen ist eine zusätzliche Zugriffskontrolle notwendig. Der Basisschutz enthält keine Sperre gegen Passwortversuche; Netzwerkzugriff begrenzen und gegebenenfalls am Proxy Rate-Limits einrichten.
- `APP_BIND_ADDRESS` nur bewusst ändern; die Bindung an eine LAN-Adresse allein begrenzt nicht, welche Clients zugreifen dürfen. Kein Portforwarding aus dem Internet einrichten. Firewallregeln für Docker prüfen und von einem anderen Gerät aus testen.
- Der Container läuft mit UID 10001, ohne Linux-Capabilities und mit schreibgeschütztem Root-Dateisystem. Das eingebundene `./data` muss für UID 10001 beschreibbar sein. Auf einem Linux-Host vor dem ersten Start beispielsweise `mkdir -p data` und nach Prüfung der Eigentumsverhältnisse `sudo chown 10001:10001 data` ausführen. Bei vorhandenen Daten die Berechtigungen samt enthaltenen SQLite-Dateien gezielt durch die Administration anpassen; keine pauschale Freigabe für alle Benutzer setzen. Unter Docker Desktop gelten die Berechtigungen der jeweiligen Dateifreigabe.
- `.env` und `./data` vor unbefugtem Zugriff schützen. Regelmäßig konsistente Backups der SQLite-Datenbank einschließlich laufender WAL-Transaktionen erstellen und Wiederherstellung testen. Keine Zugangsdaten oder Produktivdaten ins Repository einchecken.

## Katalog importieren

Über **Katalog importieren** eine CSV- oder XLSX-Datei auswählen, die erkannten Spalten kontrollieren und den Import starten. Artikelnummer und Bezeichnung müssen Spalten zugeordnet sein; jede Artikelnummer muss ausgefüllt und eindeutig sein. Artikel mit leerer Bezeichnung werden übernommen und als „Ohne Bezeichnung“ angezeigt; ihre Anzahl wird beim Import angezeigt. Der Import ersetzt den bisherigen Katalog vollständig. Das Mapping wird pro Spaltenstruktur gespeichert. `sample_data/demo_catalog.csv` enthält ausschließlich erfundene Beispieldaten. CSV akzeptiert UTF-8, Windows-1252 und Latin-1 sowie Semikolon, Komma und Tabulator. XLSX verwendet das erste Tabellenblatt.

SelectLine-Spalten wie `EANNummer`, `Artikelgruppe`, `Mengeneinheit`, `Matchcode` und optionale Breiten-, Höhen- und Längenfelder werden vorgeschlagen und können angepasst werden. Matchcode und Maße sind durchsuchbar; eine Maßeinheit wird dabei nicht angenommen. Andere, nicht zugeordnete Exportspalten werden nicht importiert.

Datenbank, Zuordnungen, Synonyme und Embedding-Cache liegen in `./data` und sind durch `.gitignore` ausgeschlossen. Synonyme bleiben auch nach einem Reimport erhalten. Bei geändertem Text werden nur fehlende Embeddings erneut erstellt. Ohne API oder bei Fehlern wird lokal gesucht; ein erneuter Import oder Neustart setzt die Indexierung fort. Modell und Dimension werden im Cache getrennt; nach einem Wechsel werden Embeddings neu erzeugt. OpenAI erhält bei aktivierter API Artikeltexte zur Embedding-Erstellung und Suchanfragen; beim Reranking zusätzlich die ausgewählten Kandidaten. Nur verwenden, wenn diese Übermittlung für die Daten zulässig ist.

Beim Tippen werden ausschließlich lokale Vorschläge angezeigt. Erst **Suchen** oder `Enter` startet die semantische Suche und gegebenenfalls das KI-Reranking; ein weiteres `Enter` kopiert den ersten Treffer. Mit `/` das Suchfeld fokussieren und mit `Esc` leeren. `OPENAI_REASONING_EFFORT=none` begrenzt den Reasoning-Aufwand; `low` und `medium` sind ebenfalls möglich. API-Nutzung kann Kosten verursachen. Die Kopierfunktion unterstützt auch HTTP im LAN. Suchverlauf und letzte fünf Suchbegriffe liegen im Browser.

## Entwicklung

Python 3.12: `pip install -r requirements.txt`, dann `pytest`. Für den lokalen Start `APP_USERNAME` und `APP_PASSWORD` als Umgebungsvariablen setzen und `uvicorn app.main:app --reload --no-access-log` ausführen. `DATA_DIR` kann für lokale Entwicklung das Datenverzeichnis festlegen. API-Schlüssel gehören ausschließlich in die lokale `.env`, nicht in das Repository. Die Demo-Datei ist die einzige freigegebene CSV; produktive Exporte müssen außerhalb des Repositorys bleiben.
