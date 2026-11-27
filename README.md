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

Beim Tippen werden ausschließlich lokale Vorschläge angezeigt. Erst **Suchen** oder `Enter` startet zusätzlich die KI-Suche: Das Modell schlägt bis zu drei Suchbegriffe vor, mit denen der lokale Katalog erneut durchsucht wird. Einzelne hinterlegte, gerichtete Produktbeziehungen ergänzen diese Begriffe; etwa kann ein Rahmen für einen Keilrahmen auch ein Schattenfugenrahmen sein. Die Begriffe und zusätzlichen Treffer erscheinen getrennt von den direkten Treffern. Der Bereich lässt sich einklappen und zeigt zunächst höchstens vier Treffer. Die Vorschläge sind keine bestätigten Eigenschaften und sollten geprüft werden. Wenn aktiviert, sortiert das KI-Reranking die ausgewählten Kandidaten zusätzlich. Ein weiteres `Enter` kopiert den ersten direkten Treffer. Mit `/` das Suchfeld fokussieren und mit `Esc` leeren.

Die KI-Suche benötigt bei jedem Absenden eine Anfrage für alternative Begriffe und, sofern passende Embeddings vorliegen, eine Embedding-Anfrage; bei aktiviertem Reranking kommt eine weitere Modellanfrage hinzu. Diese Anfragen benötigen Zeit und können Kosten verursachen. Die Suchanfrage und beim Reranking die Kandidatendaten werden an OpenAI übermittelt. Die direkten Treffer bleiben bei API-Fehlern nutzbar. `OPENAI_REASONING_EFFORT=none` begrenzt den Reasoning-Aufwand; `low` und `medium` sind ebenfalls möglich. Die Kopierfunktion unterstützt auch HTTP im LAN. Suchverlauf und letzte fünf Suchbegriffe liegen im Browser.

Artikel-Vektoren werden bei Bedarf im Arbeitsspeicher normalisiert und wiederverwendet. Der Vergleich mit einem normalisierten Suchvektor erfolgt per Skalarprodukt. Beim Import und nach Änderungen an Embeddings wird der Speicherindex verworfen und bei Bedarf neu aufgebaut. Modell oder Dimensionsänderungen erzeugen einen eigenen Cache; die Standards sind 768 Dimensionen.

## Entwicklung

### Produktfamilien und Maße

Beim Import und beim ersten Start mit einem bestehenden Katalog leitet die App Familien lokal aus den Artikelbezeichnungen ab. Beim Suchen erhält das Modell bis zu zwölf zur Anfrage ausgewählte Familiennamen samt Beispielbezeichnungen und bekannten Verwendungen aus der gewählten Warengruppe. Es kann diese Namen für weitere Katalogsuchen wählen. Die Zuordnung ist heuristisch. Prüfe den Familiennamen im Dialog, bevor du über **Für Familie merken** einen Ausdruck hinterlegst. Der Begriff gilt sofort für die lokale Suche und nach einem Reimport auch für neue Mitglieder derselben Familie. Vorhandene Artikel-Embeddings können weiterverwendet werden.

Bei Varianten zeigt die erste Karte die bestplatzierte Artikelnummer. Weitere passende Varianten derselben Modellbezeichnung, Ausführung und Warengruppe lassen sich aufklappen. Die Anzahl bezieht sich auf die gefundenen Treffer. Maßangaben mit Einheit werden umgerechnet, z. B. 60 cm in 600 mm. Bei den drei SelectLine-Maßspalten ohne Einheit kannst du in Portainer optional `CATALOG_DIMENSION_UNIT=mm` setzen, **wenn alle drei Spalten in Millimetern gepflegt werden**. Standardmäßig bleiben diese Werte einheitenlos.

### Browser-Erweiterung und Kompaktfenster

1. In der aktualisierten Webapp **Browser-Erweiterung laden** wählen und die ZIP-Datei in einen dauerhaften Ordner entpacken.
2. In Chrome ab Version 116 unter `chrome://extensions` oder in aktuellem Edge unter `edge://extensions` den Entwicklermodus einschalten, **Entpackte Erweiterung laden** wählen und den Ordner mit der `manifest.json` öffnen.
3. Den Katalog über internes HTTPS oder auf localhost öffnen und anmelden. Im Katalog-Tab per Rechtsklick auf das Erweiterungssymbol **Diesen Tab als Artikelkatalog verbinden** wählen. Diesen Tab geöffnet lassen. Nach einem Browserneustart erneut verbinden.
4. In einer Browser-Mail Text markieren und per Rechtsklick **Im Artikelkatalog suchen** wählen. Die Seitenleiste sucht lokal und bietet die Artikelnummer zum Kopieren an. **KI-Suche** sendet eine zusätzliche, explizite Anfrage über den Katalogserver. Ein Klick auf das Erweiterungssymbol öffnet auch ein Suchfeld zum Einfügen.

Die Erweiterung nutzt die bestehende Anmeldung im verbundenen Tab. Die letzte Markierung (bis 300 Zeichen) liegt pro Fenster im Sitzungsspeicher des Browsers. Für die native SelectLine-Anwendung lässt sich in der Webapp **Kompaktfenster öffnen** wählen und Text aus der Zwischenablage einfügen.

### Suchqualität messen

Im Checkout oder in der Portainer-Konsole des aktualisierten App-Containers führt `python -m tools.evaluate_search` 30 beschriftete Anfragen gegen einen temporären synthetischen Katalog aus. Die Ausgabe zählt die erwartete Artikelnummer unter den ersten sichtbaren Karten (Top 1 und Top 3) und misst die Laufzeit der lokalen Backend-Suche.

Für eigene Testfälle eine private JSON-Datei außerhalb des Repositorys anlegen, z. B. mit `{"cases":[{"query":"mein Suchtext","expected":["meine Artikelnummer"]}]}`. `DATA_DIR` auf eine aktuelle Katalogkopie setzen und `python -m tools.evaluate_search --cases PFAD` aufrufen. Für einen Vergleich von 300 und 768 Dimensionen zusätzlich `--dimensions 300 768` angeben. Dafür müssen beide Indizes vollständig vorliegen und ein API-Schlüssel gesetzt sein. Der Vergleich sendet pro Testfall und Dimension eine Suchanfrage für das Query-Embedding an OpenAI. Er misst die Hybridsuche samt API-Latenz, ohne Reranking. Das Werkzeug baut keine Artikelindizes auf.

### Lokal starten

Python 3.12: `pip install -r requirements.txt`, dann `pytest`. Für den lokalen Start `APP_USERNAME` und `APP_PASSWORD` als Umgebungsvariablen setzen und `uvicorn app.main:app --reload --no-access-log` ausführen. `DATA_DIR` kann für lokale Entwicklung das Datenverzeichnis festlegen. API-Schlüssel gehören ausschließlich in die lokale `.env`, nicht in das Repository. Die Demo-Datei ist die einzige freigegebene CSV; produktive Exporte müssen außerhalb des Repositorys bleiben.
