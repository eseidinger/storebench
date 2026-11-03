# Geplante Benchmark-Tests

Dieser Plan konkretisiert die [Messmethodik im README](../README_DE.md) für die fünf StoreBench-Use-Cases. Das [gesonderte Profiling-Dokument](benchmark-profiling.de.md) beschreibt die technische Diagnose und gemeinsame Container-Metriken. Beide Dokumente behandeln **geplante**, noch nicht implementierte oder gemessene Tests. Die kleinen vorhandenen Fixtures und `seed`/`run`/`verify`-Abläufe dienen als Konformitätsprüfung; ihre Zeiten sind keine Benchmark-Ergebnisse.

| Use Case | Vergleich | Vorhandener Vertrag |
| --- | --- | --- |
| Dokumente | PostgreSQL JSONB / CouchDB | [Produkte und Operationen](documents.md) |
| Graph | PostgreSQL mit Apache AGE / Neo4j / Apache HugeGraph (geplant) | [Paketabhängigkeiten](graph.md) |
| Vektoren | PostgreSQL mit pgvector / Qdrant | [Ähnliche Dokumente](vector.md) |
| Volltextsuche | PostgreSQL-Volltextsuche / OpenSearch | [Artikel und Suche](search.md) |
| Blobs | PostgreSQL `bytea` / RustFS über S3 | [Objekte und Dateivertrag](blob.md) |

## Gemeinsame Durchführung

1. **Vertrag erweitern:** Für jeden Test Eingaben, erwartete Ergebnisse, Sortierung, Limits, Fehlerfälle und Sichtbarkeitsregeln versionieren. Generierte Daten erhalten festen Zufalls-Seed, Schema-Version, Größenangaben und Prüfsumme. Ein Referenzlauf prüft vor jeder Messreihe die fachliche Gleichwertigkeit.
2. **Varianten isolieren:** Pro Messung läuft ein Store und ein aktiver Client. PostgreSQL und Gegenkandidat erhalten gleiche wirksame CPU-/RAM-Limits, Datenträgerklasse und Netzstrecke. Images, Treiber, Indizes, Tuning, Caches und Dauerhaftigkeitseinstellungen stehen im Laufmanifest. Standardkonfiguration und Tuning sind getrennte Messreihen.
3. **Messschichten trennen:** Native Skripte dienen der Diagnose von Abfrageplänen und Operationen. Ein langlebiger Python- bzw. Kotlin-Runner misst direkte Client-Aufrufe inklusive Ergebnisübertragung und vollständiger Dekodierung. Ein externer Lastgenerator misst getrennt den vollständigen Pfad über dünne HTTP-Adapter. Prozessstart und Verbindungsaufbau erhalten eigene Tests.
4. **Last variieren:** Zunächst Nebenläufigkeit 1, 8 und 32 sowie niedrige, mittlere und über der Sättigung liegende angebotene Raten. Gleichverteilte und schiefe Schlüsselzugriffe, mehrere Selektivitäten und Ergebnismengen verwenden. Read-only, Write-only und ein definierter 80/20-Mix sind getrennte Szenarien; die genaue Operationsverteilung wird je Use Case festgelegt.
5. **Wiederholen:** Als Startregel mindestens zwei Minuten Aufwärmen, fünf Minuten Messung und fünf unabhängige Läufe je Konfiguration. Reihenfolge der Varianten randomisieren; nach schreibenden Läufen Daten zurücksetzen. Ein 30-minütiger Dauertest folgt für den ersten vollständig umgesetzten Use Case. Kaltstart und kalter Cache sind eigene Versuche mit nachweisbarem Cache-Zustand.
6. **Auswerten:** Je Operation p50/p95/p99, Beobachtungszahl, angebotene und erfolgreich abgeschlossene Operationen/s, Fehler und Timeouts erfassen. Dazu Store-/Client-CPU, RAM, I/O, Netzwerk, Throttling, GC, Pool-Wartezeit sowie Daten- und Indexgröße. Ein vorläufiger Vergleichspunkt ist p95 ≤ 100 ms bei höchstens 0,1 % Fehlern; wo das fachlich nicht passt, wird das Ziel *vor* dem Lauf angepasst. Berichtet wird der nachhaltige Durchsatz innerhalb von Qualitäts- und Fehlergrenzen, mit Einzelläufen und Streuung.

Ein neuer Prozess pro Operation, ein überlasteter Lastgenerator oder bloße Durchsatzwerte aus CLI-Batches liefern keine gültigen Einzeloperationslatenzen. Python/Kotlin-Ergebnisse bezeichnen zunächst den jeweiligen **Client-Stack**; insbesondere Qdrant REST versus gRPC wird getrennt ausgewiesen. Ergebnisse unterschiedlicher Messschichten werden nicht zu einer Rangliste vermischt.

## 1. Dokumente: PostgreSQL JSONB und CouchDB

**Datenprofile:** Den [sechs Produktdatensätzen](../workloads/documents/products.json) folgen deterministisch erzeugte Kataloge mit zunächst 10.000, 100.000 und 1.000.000 Produkten. Variieren: JSON-Payloadgröße, optionale und fehlende Attribute, Kategorieverteilung, Farb-/Wasserdicht-Selektivität und Anteil häufig angefragter Produkte. Integerpreise und Feldtypen bleiben gleich. Als zusätzlicher, separat gekennzeichneter PostgreSQL-Versuch kann ein relationales Schema dienen; es ist noch nicht implementiert.

| Test | Operation und Variation | Qualitätsprüfung und gesonderte Größen |
| --- | --- | --- |
| D1 Punktlesung | Produkt nach ID; gleichverteilte und Hotspot-Zugriffe | Identische Dokumentfelder; Treffer- und Nichttrefferlatenz separat |
| D2 Attributfilter | Verschachtelte Filter wie `color = blue` und `waterproof = true`; seltene/häufige Treffer, verschiedene Limits | Gleiche ID-Menge und definierte Sortierung; Indexnutzung, gelesene Treffer und übertragene Bytes |
| D3 Aggregation | Anzahl und Summe nach Kategorie; wenige/viele Gruppen | Exakte Integer-Ergebnisse; Aufbau und Pflege der CouchDB-View getrennt von warmen Abfragen |
| D4 Änderung | Verschachteltes Attribut eines Dokuments ändern; einzelne und konkurrierende Updates | Erhaltene übrige Felder; PostgreSQL-Commit bzw. CouchDB-`_rev`-Konflikte, Retries und Endzustand; Bestätigungs- und Sichtbarkeitszeit getrennt |
| D5 Import und gemischte Last | Einzel- und Batch-Import; danach 80 % D1/D2/D3 und 20 % D4 mit festgelegten Anteilen | Erfolgreiche Dokumente, Index-/View-Aufbauzeit, Speicherbedarf, Schreibverstärkung und nachhaltiger Durchsatz |

**Vorbedingung:** Die aktuelle CouchDB-Implementierung sortiert Filtertreffer clientseitig. Für D2 muss vor dem Vergleich eine semantisch gleiche, indexgestützte Sortierung serverseitig bereitstehen oder der vollständige Transfer mit Client-Sortierung ausdrücklich als anderer Anwendungspfad ausgewiesen werden. Konflikttests dürfen nicht als gleichwertig gelten, wenn verlorene Updates unbemerkt bleiben.

## 2. Graph: PostgreSQL/AGE, Neo4j und HugeGraph

**Datenprofile:** Aus dem [kleinen DAG](../workloads/graph/packages.json) deterministische gerichtete Graphen erzeugen, z. B. 10.000, 100.000 und 1.000.000 Knoten mit dokumentierter Kantenanzahl. Gradverteilung, Anteil stark vernetzter Knoten, Tiefe und Anzahl alternativer Pfade variieren. Zyklische Graphen erhalten einen eigenen Vertrag mit begrenzter Traversierung und definierter Deduplizierung. HugeGraph ist als weitere Kernvariante geplant; lokal implementiert sind derzeit nur AGE und Neo4j. Eine relationale PostgreSQL-Baseline mit Knoten-/Kantentabellen und rekursiven CTEs ist eine **spätere zusätzliche Variante**; der vorhandene PostgreSQL-Pfad verwendet AGE.

| Test | Operation und Variation | Qualitätsprüfung und gesonderte Größen |
| --- | --- | --- |
| G1 Direkte Nachbarn | Ausgehende Abhängigkeiten; Startknoten mit niedrigem/hohem Grad | Exakte, sortierte Ziel-IDs; Ergebnisgröße und übertragene Bytes |
| G2 Erreichbarkeit | Transitive Abhängigkeiten und umgekehrte Impact-Frage; maximale Tiefen 2, 4 und 8 | Gleiche Menge *unterschiedlicher* Knoten; besuchte Knoten/Kanten und Abfrageplan |
| G3 Kürzester Pfad | Länge und ein deterministisch ausgewählter kürzester Pfad zwischen zwei Knoten | Gleiches Distanzresultat; Gleichstände per expliziter Regel behandeln |
| G4 Pfadauflistung | Alle einfachen Pfade bis zur vereinbarten Tiefe, begrenzte Anzahl und verschiedene Verzweigungen | Gleiche Pfade samt Mehrfachheiten; Limit/Abbruch und Ausgabevolumen erfassen, Pfadexplosion vermeiden |
| G5 Graphänderung | Knoten/Kante anlegen, ändern und löschen; danach G1/G2 | Korrekte Folgewirkung, Transaktions- und Sichtbarkeitsregel, Index-/Constraint-Kosten |
| G6 Import und Mischlast | Batch-Aufbau sowie wiederholte G1–G5 mit fixierten Anteilen | Aufbauzeit, Indexgröße, Fehler und nachhaltiger Durchsatz |

G3 braucht eine neue Implementierung; G4 erfordert über die heutige Prüfung der Pfadlängen hinaus einen kanonischen Pfadvergleich. Cypher- und Gremlin-Abfragen sowie Ergebnislimits müssen denselben fachlichen Vertrag erfüllen.

## 3. Vektoren: PostgreSQL/pgvector und Qdrant

**Datenprofile:** Die [sechs 3D-Vektoren](../workloads/vector/documents.json) bleiben ein Smoke-Test. Neue, versionierte Embeddings mit zunächst 10.000, 100.000 und 1.000.000 Punkten, 128 und 768 Dimensionen sowie Metadatenkategorien vorberechnen. Normierung, Cosine-Metrik, Datentyp und ID-Zuordnung dokumentieren. Erzeugung der Embeddings liegt außerhalb der Abfragezeit.

| Test | Operation und Variation | Qualitätsprüfung und gesonderte Größen |
| --- | --- | --- |
| V1 Exaktes Top-k | Cosine-Suche mit `k = 1, 10, 100`; unterschiedliche Query-Verteilungen | Exakte Referenz-IDs und definierte Tie-Break-Regel; vollständige Ergebnisübertragung |
| V2 Gefiltertes Top-k | Kategorie- und selektivere Metadatenfilter bei denselben k-Werten | Filter und Rangfolge korrekt; Kandidatenanzahl sowie leere Resultate erfassen |
| V3 ANN-Suche | HNSW-/andere tatsächlich verfügbare Indexvarianten mit abgestuften Suchparametern | Recall@k gegen V1, zunächst Ziel ≥ 0,95; Latenz nur bei vergleichbarem Recall und Filterverhalten gegenüberstellen |
| V4 Vektor-/Metadatenänderung | Einzel- und Batch-Updates, anschließend V1/V2/V3 | Neue Vektoren und unveränderte Metadaten; Bestätigung, Suchbarkeit und Indexpflege getrennt messen |
| V5 Laden und gemischte Last | Bulk-Upsert/Import, Indexaufbau, danach Such-/Update-Mix | Import- und Indexaufbauzeit, Vektor-/Indexgröße, Fehler und Durchsatz |

Exakte Suche ist die Ground Truth. Qdrant-REST aus Python und gRPC aus Kotlin bilden eigene Messreihen. Näherungsindizes und ihre Parameter werden pro Store dokumentiert; ein schnelleres, aber fachlich ungenaueres Resultat wird nicht als gleicher Test gewertet.

## 4. Volltextsuche: PostgreSQL und OpenSearch

**Datenprofile:** Aus den [sechs englischen Artikeln](../workloads/search/articles.json) einen größeren versionierten Korpus mit zunächst 10.000, 100.000 und 1.000.000 Dokumenten erstellen. Titel-/Textlänge, Wortfrequenz, Kategorieverteilung und Anteil neuer/geänderter Dokumente variieren. Ein Query-Set enthält seltene und häufige Begriffe, mehrere Wörter, Phrasen, leere Ergebnisse und Kategorie-Filter. Relevanzurteile für eine Teilmenge werden vor dem Lauf festgelegt.

| Test | Operation und Variation | Qualitätsprüfung und gesonderte Größen |
| --- | --- | --- |
| S1 Begriffssuche | Zwei Begriffe mit `AND`, unfiltriert; Top-10 und Top-100 | Treffermenge/Sortierung gemäß Vertrag; Ergebnisgröße, Pläne und Tokenisierung prüfen |
| S2 Filter und Ranking | Kategorie-Filter, gewichtete Titel-/Textsuche, unterschiedlich selektive Queries | Getrennt Treffergleichheit und Relevanzqualität (z. B. nDCG@10) berichten; rohe Scores nicht vergleichen |
| S3 Aktualität | Artikel ändern/einfügen/löschen und wiederholt suchen | Zeit von bestätigter Änderung bis zur Suchsichtbarkeit als Verteilung; bei OpenSearch Refresh-Wartezeit und reine Update-Antwortzeit separat |
| S4 Indexaufbau | Vollständiger Import und anschließende Suchbereitschaft; laufende Nachindexierung | Importdauer, Zeit bis zur Abfragbarkeit, Indexgröße und Ressourcenbedarf |
| S5 Misch- und Dauerlast | Festgelegter Mix aus S1/S2 und S3, zusätzlich längerer Such-Dauertest | Nachhaltiger Durchsatz bei Relevanz-, Sichtbarkeits- und Fehlergrenzen |

Der heutige einzelne Query-Fall reicht nicht aus, um Suchrelevanz allgemein gleichzusetzen. Sprach-Analyzer, Stemming, Stopwörter, Feldgewichte, `AND`-Semantik und Tie-Break-Regel müssen für jede Query dokumentiert werden; Abweichungen erscheinen als Qualitätsresultat und werden nicht durch Latenzwerte verdeckt.

## 5. Blobs: PostgreSQL `bytea` und RustFS/S3

**Datenprofile:** Das [Manifest mit drei kleinen Objekten](../workloads/blob/manifest.json) dient der Konformität. Neue deterministische Bytefolgen und Metadaten für z. B. 1 KiB, 1 MiB, 64 MiB und 1 GiB pro Objekt vorbereiten; Objektanzahl und Gesamtvolumen getrennt begrenzen. Komprimierbare und inkompressible Inhalte sind eigene Profile. Die großen Varianten werden nur auf einem Host mit ausreichendem Speicherplatz gefahren.

| Test | Operation und Variation | Qualitätsprüfung und gesonderte Größen |
| --- | --- | --- |
| B1 Vollständiges Lesen | Kleine und große Objekte; gleichverteilte und Hotspot-Schlüssel | Vollständige Bytezahl und SHA-256; Zeit bis erstes Byte und bis vollständigem Empfang, Durchsatz pro Objektgröße |
| B2 Bereichslesen | 100 B, 4 KiB und 1 MiB an Anfang/Mitte/Ende; ungültige Bereiche separat | Exakte Bytes und Grenzen; übertragene Bytes und Antwortstatus |
| B3 Schreiben/Überschreiben | Einzelobjekte verschiedener Größe und Metadaten; bei großen Objekten Multipart als eigene S3-Variante | Bytes/Metadaten nach Abschluss, Uploadzeit, Sichtbarkeit und Multipart-Overhead getrennt |
| B4 Metadaten/Listen/Löschen | Head, paginierte Auflistung, Delete und anschließender Zugriff | Gleiche Schlüsselmenge und Fehlerfälle; kleine Metadatenabfragen getrennt von Byte-Transfers |
| B5 Parallele Objekte und Mischlast | Gleichzeitige unabhängige Schlüssel, definierter Lese-/Schreibmix | Objekte/s und MiB/s, p95 je Größenklasse, Speicher- und Netzwerkverbrauch |
| B6 Fehler und Wiederanlauf | Abgebrochener Upload, Client-Timeout, Neustart nach bestätigtem Schreiben | Endzustand und Wiederholbarkeit; Dauerhaftigkeitsgarantien pro Store separat ausweisen |

PostgreSQL-Transaktionen über mehrere Zeilen und S3-Operationen pro Objekt sind unterschiedliche Semantiken; B6 berichtet sie getrennt. Bei großen Objekten muss der Runner streamen oder seinen Speicherbedarf messen. Ein S3-`ETag` gilt nicht als allgemeiner Inhalts-Hash. Netzwerk- und Client-Byteverarbeitung gehören bei beiden Varianten zur direkten Clientmessung.

## Reihenfolge der Umsetzung und Ergebnisartefakte

1. Einen wiederverwendbaren Generator, Vertragsprüfer, Laufmanifest und direkten Mess-Runner für **Dokumente** bauen. D1–D3 zuerst, danach Updates und Mischlast.
2. Dieselbe Messinfrastruktur für die übrigen Use Cases verwenden. Vor einer Performanceaussage jeweils die im Abschnitt genannte fachliche Lücke schließen: Graph-Pfadvertrag, Vektor-Ground-Truth/Recall, Suchrelevanz/Aktualität oder vollständige Blob-Bytes.
3. Pro Use Case erst direkte Clientmessungen, danach die Anwendungsbenchmark-Schicht ergänzen. Python und Kotlin, PostgreSQL und Gegenkandidat sowie Standard- und Tuningprofil als getrennte Achsen ausweisen.

Jeder veröffentlichte Messpunkt enthält Fixture-/Generator-Prüfsumme, Eingabeprofil, Operationsmix, Code- und Image-Versionen, wirksame Limits, Abfrage-/Indexkonfiguration, Rohmessungen, Histogramme, Fehlerprotokoll, Ressourcenzeitreihen und Konformitätsergebnis. Der Bericht nennt für jeden Test die verwendete Referenz und zeigt einzelne Wiederholungen, Median und Streuung; er enthält keine Perzentile, die aus Perzentilen einzelner Läufe gemittelt wurden.
