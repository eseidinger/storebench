# Profiling-Plan für die Benchmark-Tests

Dieses Dokument ergänzt die [geplanten Benchmark-Tests](benchmark-tests.de.md). Es beschreibt ausschließlich lokales Profiling mit Docker Compose: Container-Ressourcen, Client-Zeiten und gezielte Store-Diagnose. Ein Prometheus-/Grafana-Stack ist dafür nicht erforderlich. Benchmark-Runner, Ressourcensampler und Artefaktablage sind noch nicht implementiert; es liegen keine Profile oder Messergebnisse vor.

## 1. Messarchitektur und Vergleichsgrenze

```text
Orchestrierung ──> Lastgenerator ──HTTP (nur Anwendungsschicht)──> Adapter
       │                 oder direkter Python-/Kotlin-Runner ───────────┤
       │                                                    genau ein Zielstore
       ├── Laufmanifest, Fixture und Phasenzeitfenster              │
       ├── Runner-Rohdaten und Histogramme ──> lokales Laufverzeichnis
       ├── Docker-Stats-Sampler ─────────────> container-metrics.jsonl
       └── Store-Snapshots und Profile ──────> lokales Laufverzeichnis
```

Für die direkte Messschicht entfällt der HTTP-Pfeil; ein langlebiger Runner spricht unmittelbar mit dem Store. Laufumgebung, Datenweg, Container-IDs und wirksame Limits stehen im Manifest. Jeder gemessene Container erhält eine Rolle (`store`, `client`, `loadgen`). Pro Messpunkt läuft genau ein Zielstore und ein aktiver Client. Andere Store- und UI-Container bleiben gestoppt. Läuft ein Client direkt auf dem Host, wird das im Manifest vermerkt; seine CPU- und Speichernutzung erfordern eine gesonderte Prozessmessung und dürfen nicht als Container-Metrik ausgegeben werden.

| Profilstufe | Im regulären Vergleich? | Inhalt | Zweck |
| --- | --- | --- | --- |
| P0 Basis | Ja, bei jedem Lauf | Lokale Docker-Stats-Samples für Store und containerisierte Runner, Operations-Rohdaten und Histogramme, Start-/End-Snapshots | Ressourcen- und Antwortzeitdaten innerhalb eines definierten lokalen Umgebungsprofils vergleichen |
| P1 Geringer Zusatzaufwand | Nur wenn vorab aktiviert und in beiden Varianten gleich | Pool-Wartezeit, feste Client-Phasen, ausgewählte Store-Zähler | Lokalisierung ohne Änderung des fachlichen Pfads |
| P2 Tiefenprofil | Nein, eigener Wiederholungslauf desselben Testpunkts | `EXPLAIN ANALYZE`, Neo4j `PROFILE`, OpenSearch Search Profile, Python- und JVM-Profiler, zusätzliche Logs/Traces | Hypothese zu einem Engpass prüfen |

P2-Ergebnisse erklären einen P0-Befund; ihre Latenzen werden nicht als Benchmark-Rangfolge verwendet. Für P1 wird der Overhead mit mindestens einer gepaarten P0-/P1-Probe bei gleicher Last ermittelt und im Bericht angegeben. Ändert die Instrumentierung die Sättigung erkennbar, bleibt sie ebenfalls auf Diagnose-Läufe beschränkt.

## 2. Lokale Container-Metriken

Ein lokaler Sampler liest während jedes Laufs die Docker Engine Stats API für die beteiligten Container und schreibt zeitgestempelte Rohsamples in `container-metrics.jsonl`. Er läuft auf dem Host oder in einem dafür vorgesehenen lokalen Prozess. Der Benchmark-Runner benötigt keinen Zugriff auf den Docker-Socket. Eine erste Zielauflösung ist **ein Sample pro Sekunde**; das tatsächliche Intervall und die Abfragekosten werden vor der Messreihe geprüft und im Manifest festgehalten. Store und Runner erhalten dieselbe Abtastrate. Für die Vergleichbarkeit sind CPU-Verbrauch und Speichernutzung Pflicht; Block-I/O und Netzwerkbytes werden erfasst, wenn Docker sie für den Container liefert.

| Rohwert je Container | Abgeleitete Größe und Darstellung | Interpretation |
| --- | --- | --- |
| Zeitstempel, Container-ID, Startzeit und Neustarts | Eine Zeile pro Sample; Rolle über das Manifest zuordnen | Nach einem Neustart Zählerdifferenzen neu beginnen |
| Kumulierter CPU-Verbrauch und Systemzeit | Verbrauchte CPU-Kerne aus der Differenz zweier Samples; CPU-Limit separat | Prozentwerte aus `docker stats` sind von Kernzahl und Limit abhängig |
| Docker-Speicherwert und Limit | Bytes, Anteil des Limits und beobachteter Peak | Speicherdefinition samt Docker-/cgroup-Version festhalten; Spitzen zwischen Samples können fehlen |
| Kumulierte Block-I/O-Bytes, soweit verfügbar | Lese-/Schreibbytes pro Sekunde und Gesamtbytes | Block-I/O ist nicht gleich logische Datenbank-I/O |
| Kumulierte Netzwerkbytes, soweit verfügbar | Empfangs-/Sendebytes pro Sekunde und Gesamtbytes | Healthchecks und sonstiger Verkehr gehören zur gemessenen Container-Schnittstelle |
| CPU-Throttling, OOM- und cgroup-Ereignisse, soweit verfügbar | Ereignisse und Differenzen je Phase | Fehlende Felder als `null` mit Grund ausweisen |

Raten entstehen nur aus benachbarten gültigen Samples desselben Containers und derselben Container-Startzeit. Zählerrücksetzungen und Messlücken werden markiert. Der Sampler schreibt die Rohwerte fortlaufend; die Auswertung berechnet Median, Peak und Phasenverlauf nach dem Lauf. Mindestens `setup`, `warmup`, `measure` und `cooldown` erhalten Zeitgrenzen. Der Datenaufbau gehört nicht zur Online-Messphase.

Vor dem Lauf werden mit `docker compose -f infrastructure/<use-case>.compose.yaml ps` die beteiligten Container ermittelt und ihre IDs im Manifest gespeichert. Die tatsächlichen CPU-/RAM-Limits werden mit `docker inspect` geprüft. Ein Host-Snapshot hält CPU, RAM, Swap, freien Plattenplatz und Dateisystem fest; Host- oder Lastgenerator-Überlast macht den Lauf für eine Store-Kapazitätsaussage ungeeignet. Die [Linux-cgroup-Dokumentation](https://docs.kernel.org/admin-guide/cgroup-v2.html) beschreibt ergänzende `cpu.stat`, `memory.events` und `io.stat`-Zähler. Falls sie lokal zugänglich sind, können sie als getrennte Diagnosewerte erfasst werden. Ein Wert, der nicht erhoben wurde, wird nie als Null interpretiert.

Die Rohdaten und alle Auswertungen bleiben im lokalen Verzeichnis `results/<run_id>/`. Eine grafische Auswertung kann aus den Dateien erzeugt werden; dafür ist kein laufender Monitoring-Dienst nötig. Da der Sampler noch nicht implementiert ist, sind Dateiformat und Feldnamen ein Zielvertrag und keine bereits ausführbare Schnittstelle.

## 3. Zeitmessung im Client

Jede Operation bekommt eine feste Kennung (`D1` bis `B6`), Variante, Sprache, Store, Eingabeprofil, Status und Ergebnisgröße. Schlüssel oder Query-Text gehören nur in begrenzte Diagnose-Stichproben, nicht in aggregierte Zeitreihen. Zeitspannen innerhalb eines Prozesses werden mit einer **monotonen Uhr** gemessen. UTC dient nur zur Zuordnung von Client-, Container- und Store-Ereignissen; Uhrenabweichung wird im Manifest erfasst. Zeiten aus verschiedenen Prozessen werden nicht blind voneinander subtrahiert.

```json
{"run_id":"...","test_id":"S1","phase":"measure","variant":"python-postgresql","status":"ok","start_utc":"...","elapsed_ns":0,"pool_wait_ns":0,"request_ns":0,"decode_ns":0,"result_count":0,"result_bytes":0}
```

`elapsed_ns` beginnt vor dem Erwerb einer vorhandenen Verbindung und endet nach vollständiger Antwortverarbeitung. Wo der Treiber es zulässt, werden Pool-Wartezeit, Serialisierung, Request/Antwort, Dekodierung und fachliche Prüfung gesondert erfasst. Diese Teilzeiten sind **optionale Beobachtungen**: ihre Grenzen und Überlappungen stehen je Client im Vertrag; ihre Summe wird nicht künstlich zur Gesamtdauer passend gemacht. Startup, Verbindungsaufbau, Import, Indexaufbau und nachgelagerte Verifikation erhalten eigene Ereignistypen. Für Blob-Lesen endet die Operation erst nach Verbrauch aller Bytes; Time-to-first-byte und vollständiger Transfer sind zwei verschiedene Messpunkte.

Der Runner schreibt pro Operation einen Histogrammwert und aggregiert nach Test-ID, Status, Laststufe und Messlauf. Fehler und Timeouts zählen mit eigenem Status; abgebrochene Anfragen verschwinden nicht aus dem Nenner. Die Auflösung der Uhr, Sampling-Lücken, das Histogrammformat und die Kosten der lokalen Datenerfassung werden vor dem ersten Bericht geprüft. Bei der Anwendungsschicht erfasst der externe Generator zusätzlich angebotene, gestartete, abgeschlossene und verworfene Ankünfte.

## 4. Lokaler Betrieb und Artefakte

| Baustein | Lokaler Ablauf |
| --- | --- |
| Zielstore | Einen Store aus dem Compose-Profil starten; Volumes, Image-Version und Limits im Manifest dokumentieren |
| Direkter Runner | Langlebiger Python-/Kotlin-Prozess oder Container mit festgelegtem Daten- und Verbindungspfad |
| Anwendungsschicht | Dünner HTTP-Adapter und getrennter Lastgenerator mit eigenen Ressourcenlimits |
| Ressourcenmessung | Docker-Stats-Sampler für jeden beteiligten Container; Host-Prozesse bei Bedarf gesondert messen |
| Operationen und Histogramme | Lokal puffern und nach Phasen in `operations.jsonl` und Histogrammdateien schreiben |
| Diagnose | Store-API-Snapshots vor/nach dem Lauf; zusätzliche Client-/Store-Profile nur in P2 |
| Ablage | Ein lokales Verzeichnis pro `run_id`, mit Prüfsummen und Vollständigkeitsprüfung nach Laufende |

Der Sampler und Reporter sind geplante StoreBench-Bausteine. Die vorhandenen Compose-Umgebungen und `seed`/`run`/`verify`-Skripte dienen derzeit der Funktionsprüfung; ihre Laufzeiten sind keine Benchmark-Ergebnisse. Logs können als begrenzte lokale Dateien abgelegt werden. Optionale Traces sind nur sinnvoll, wenn ihre Erfassung und Kosten für den jeweiligen P1-/P2-Lauf dokumentiert werden. Weder Collector-Dienste noch Dashboards gehören zum erforderlichen Aufbau.

Ein Diagnose-Snapshot liest lokal verfügbare Store-Statistiken und Konfiguration vor/nach dem Lauf. Er speichert Antwort, Erfassungszeit und Fehler unter `store-snapshots/`. Benötigt eine Statistik erhöhte Store-Rechte, werden diese nur für den lokalen Diagnosezugriff verwendet und nicht im Manifest oder in Artefakten gespeichert. Fehlt die Berechtigung, bleibt die Quelle mit Grund `unavailable`. Ein Snapshot ersetzt kein Backup.

## 5. Diagnose-Werkzeuge nach Schicht

| Schicht | Geplante Technik | Verwendung |
| --- | --- | --- |
| Python-Client | Separater Lauf mit [`cProfile`](https://docs.python.org/3.11/library/profile.html) für Funktionsaufrufe und Laufzeitanteile sowie [`tracemalloc`](https://docs.python.org/3.10/library/tracemalloc.html) bei Speicherwachstum | JSON-Verarbeitung, Vektor-Konvertierung, S3-Transfer und Retries untersuchen; Profiler verändert Laufzeit |
| Kotlin-Client | [JDK Flight Recorder](https://docs.oracle.com/en/java/javase/17/troubleshoot/diagnostic-tools.html), zunächst kurzes `profile`-Recording im P2-Lauf | CPU-Stacks, Allokationen, GC, Threads und Blockieren; Heap- und JIT-Warmzustand dokumentieren |
| PostgreSQL (alle fünf Fälle) | [`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`](https://www.postgresql.org/docs/17/using-explain.html) für repräsentative Leseabfragen; optional [`pg_stat_statements`](https://www.postgresql.org/docs/17/pgstatstatements.html) für aggregierte SQL-Zähler | Plan, tatsächliche Zeilen und Buffer-Hits/-Reads prüfen. `pg_stat_statements` benötigt `shared_preload_libraries`, Neustart und Erweiterung; Aktivierung ist ein eigenes Profil |
| Store-spezifisch | APIs/Profiler in Abschnitt 6 | Indexwahl, interne Sucharbeit, Refresh und Wartung erklären |

`EXPLAIN ANALYZE` führt die SQL-Anweisung tatsächlich aus. Schreibanweisungen werden deshalb nur auf zurücksetzbaren Daten oder in einer bewusst kontrollierten Transaktion diagnostiziert. Plan- und Instrumentierungskosten gehören nicht zur regulären Client-Latenz. Für AGE muss zusätzlich geprüft werden, welcher Teil der eingebetteten Cypher-Ausführung im PostgreSQL-Plan sichtbar wird; es wird kein vollständiger Cypher-Operatorplan vorausgesetzt.

## 6. Profiling je Use Case und Test-ID

### Dokumente: D1–D5

- **D1/D2:** Container-CPU, Speicher, Netzbytes pro übertragenem Dokument und Block-I/O mit Client-Dekodierzeit abgleichen. PostgreSQL: Plan, tatsächliche Zeilen, GIN-/Ausdrucksindex und Buffer-Werte. CouchDB: Indexwahl über [`/{db}/_explain`](https://docs.couchdb.org/en/stable/api/database/find.html), `_find`-Ausführungsdaten und Größe des vollständig übertragenen Ergebnisses. Die heutige clientseitige Sortierung bei CouchDB muss im Profil sichtbar bleiben.
- **D3:** Ersten CouchDB-View-Aufbau und warme View-Abfrage getrennt markieren. PostgreSQL-Aggregationsplan, gelesene Zeilen und temporäre Arbeit prüfen. Container-I/O beim Indexaufbau separat vom Query-Fenster auswerten.
- **D4:** Read-modify-write, `_rev`-Konflikt, Retry und Bestätigung als einzelne Client-Phasen zählen. Bei PostgreSQL Sperr-/Wartezeit und WAL-nahe Zähler heranziehen; bei CouchDB Serverstatistik und Konfliktzahl. Sichtbarkeit nach Bestätigung getrennt testen.
- **D5:** Import-Batches, Index-/View-Aufbau und Online-Mix als eigene Phasen erfassen; Bytes/Dokument, CPU/Dokument und Speicherwachstum berichten. CouchDB stellt [Serverstatistiken über `/_node/_local/_stats`](https://docs.couchdb.org/en/stable/api/server/common.html) bereit; Polling-Intervall an deren interne Aktualisierung anpassen.

### Graph: G1–G6

- **G1/G2:** Container-CPU, Speicher und Ergebnisbytes gegen Startknotengrad, Tiefe und tatsächliche Ergebniskardinalität plotten. Bei Neo4j [`EXPLAIN`/`PROFILE`](https://neo4j.com/docs/cypher-manual/current/planning-and-tuning/execution-plans/) auf repräsentativen Queries für Operatoren und Zeilen verwenden. AGE: SQL-Plan, Buffer-Verbrauch und Client-Zeit für `agtype`-Dekodierung; fehlende Cypher-Details ausdrücklich als Diagnosegrenze nennen.
- **G3/G4:** Ergebniszahl, zurückgelegte Pfade und Abbruch-/Limitgrund protokollieren. Speicherpeak und CPU-Zeit besonders bei hoher Verzweigung beobachten. Ein abgeschnittenes Resultat ist nur mit identischer, deterministischer Begrenzung vergleichbar.
- **G5/G6:** Transaktionsdauer, Sperr-/Wartezeit, Constraint-/Indexaufwand und Importphasen getrennt erfassen. Kein `PROFILE` einer Mutation im unveränderten Messdatensatz ausführen.

### Vektoren: V1–V5

- **V1/V2:** Container-CPU, Speicher und I/O gegen Punktzahl, Dimension, `k` und Filterselektivität auswerten. PostgreSQL-Plan zeigt Scan-/Indexpfad und Buffer; Qdrant liefert [Metriken unter `/metrics` und Zustandsdaten unter `/telemetry`](https://qdrant.tech/documentation/ops-monitoring/monitoring/). REST- und gRPC-Requests separat zählen, weil Python und Kotlin unterschiedliche Protokolle verwenden.
- **V3:** Pro Suchparameter Latenz **und** Recall@k speichern. Indexstatus, Segmentzahl, Speicher/Indexgröße und Filterwirkung dokumentieren. Container-Metriken nur bei gleichem Datenprofil und vergleichbarem Recall gegenüberstellen. Eine einzelne aggregierte Trefferzeit erklärt keinen ANN-Qualitätsunterschied.
- **V4/V5:** Upsert-Bestätigung, Suchsichtbarkeit, Indexaufbau/-optimierung und Bulk-Import getrennt zeitlich markieren. CPU-, I/O- und Speicherverlauf während Optimierung oder Segmentarbeit zu den einzelnen Phasen legen.

### Volltextsuche: S1–S5

- **S1/S2:** PostgreSQL-Plan, GIN-Nutzung, Ranking-Arbeit und Buffer prüfen. Für ausgewählte OpenSearch-Queries die [Search Profile API](https://docs.opensearch.org/latest/api-reference/search-apis/profile/) in einem P2-Lauf verwenden. Sie zeigt interne Query-/Collector-Zeiten, erfasst aber Netzwerk- und Queue-Zeit nicht und verursacht selbst Overhead. Treffergleichheit und nDCG@10 bleiben eigene Qualitätsdaten.
- **S3/S4:** Zeitpunkte `write_sent`, `write_ack`, `search_visible` im Client erfassen. OpenSearch-[Node-Stats](https://docs.opensearch.org/latest/api-reference/nodes-apis/nodes-stats/) für Indexierung, Refresh, Merge, JVM und Caches mit Container-CPU/I/O abgleichen. `refresh=wait_for` ist Teil der heutigen Update-Latenz; in einem eigenen Test können Bestätigung und Sichtbarkeit getrennt werden.
- **S5:** Zeitreihen für Refresh-/Merge-Arbeit und p95/p99-Spitzen über den Dauertest legen. Zusätzliche Profil-Queries nur in P2 ausführen, damit sie die gemessene Suchlast nicht verändern.

### Blobs: B1–B6

- **B1/B2:** Größe, übertragene Bytes, Time-to-first-byte, Gesamtzeit und MiB/s je Objekt-/Range-Klasse erfassen. Container-Netz- und Block-I/O zusammen mit Client-CPU und Speicherpeak zeigen, ob Transfer, Byte-Kopie oder Datenträger dominiert. Checksummenprüfung als separat ausgewiesene Client-Phase aufnehmen.
- **B3/B5:** Einzel- und Multipart-Uploads, Teilgröße, Parallelität, Retry und Abschluss getrennt markieren. PostgreSQL-`bytea`-Plan/Buffer nur ergänzend; Container-Netz-/I/O-Bytes pro Nutzbyte sind die gemeinsame Größe. Streaming gegenüber vollständigem Puffern als getrennte Client-Varianten führen.
- **B4/B6:** Head/List/Delete, fehlende Schlüssel, abgebrochene Uploads und Wiederanlauf als eigene Operationen zählen. Container-Ressourcen und lokale Client-Ereignisse genügen als Basis; zusätzliche RustFS-Telemetrie ist ein gesonderter P2-Versuch. Bestätigte Bytes nach Neustart verifizieren.

## 7. Technischer Ablauf eines Profiling-Laufs

1. **Vorbereitung:** Dieselbe Fixture-Prüfsumme und denselben Operations-Seed wie im Benchmark laden. `environment_profile`, Container-IDs und -Startzeiten, Image-Digests, Limits, cgroup-Version, Client-/Treiber-Version, Indexdefinitionen, Sampler-Intervall und Artefaktziel in `manifest.json` schreiben. Nur benötigte Compose-Services starten und freie Host-Kapazität prüfen.
2. **Start:** Zielstore und Client fachlich bereit melden lassen. Den lokalen Sampler starten und vor dem Warmup mindestens zwei gültige CPU-Samples je Container prüfen. `run_id`, Container-IDs, UTC-Uhren und Phasen-Zeitfenster zuordnen.
3. **Messung:** Aufwärmen und Messen gemäß Benchmark-Plan. Der Runner puffert Einzeloperationen lokal und führt keine synchronen Metrik- oder Artefaktschreibvorgänge im gemessenen Pfad aus. Fehlende Samples, Samplerfehler, Container-Neustarts und verworfene Generator-Requests markieren. Bei kritischen Lücken oder Host-/Generator-Überlast den Lauf wiederholen.
4. **Abschluss:** Nach `measure` Operationen, Histogramme, Konformitätsprüfung, Container-Samples und Store-Snapshots finalisieren. Stichprobenzahlen, Zeitbereich, Prüfsummen und erwartete Operationszahl abgleichen. Ein Schreib- oder Prüfungsfehler bleibt ein sichtbar unvollständiger Lauf.
5. **Diagnose:** Aus P0 eine konkrete Frage ableiten, etwa „D2 erzeugt bei hoher Selektivität mehr übertragene Bytes als erwartet“. Genau diesen Datenstand und Query-Typ in P2 mit Store-Plan bzw. Client-Profiler wiederholen. Profiler-Konfiguration und zusätzlichen Ressourcenverbrauch archivieren.
6. **Bericht:** Pro Test eine gemeinsame Zeitachse mit angebotener Last, p95/p99, Fehlern sowie Store-/Client-/Generator-CPU und Speicher. I/O und Netzwerk nur zeigen, wenn ihre lokale Erfassung bestätigt wurde. Dazu fachliche Qualität und spezifische Diagnosebefunde. Jede Aussage nennt Hostprofil, Messschicht, Profilstufe und Zahl unabhängiger Läufe.

Vorgesehene Artefakte unter `results/<run_id>/`: `manifest.json`, `operations.jsonl` plus Histogramm-Rohdaten, `container-metrics.jsonl`, `store-snapshots/`, `conformance.json`, optional `profiles/` und ein generierter Bericht. Der Reporter speichert Zeitfenster, Sampler-Intervall, Datensatz-Zählung und Prüfsummen. Diese Dateinamen sind ein Plan für die spätere Implementierung, keine bereits vorhandene Infrastruktur.
