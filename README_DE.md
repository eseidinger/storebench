# StoreBench

**Native Stores vs. PostgreSQL — reproduzierbare Datenbankexperimente mit nativen Skripten, Python und Kotlin.**

Status: erster Projektentwurf, 2. November 2026. Infrastruktur, Implementierungen und Benchmarks sind geplant; es liegen noch keine Messergebnisse vor.

## Projektidee

StoreBench untersucht, wann ein spezialisierter Data Store gegenüber einer passenden PostgreSQL-Lösung einen messbaren Vorteil bietet und wie gut sich beide Varianten aus nativen Skripten, Python und Kotlin verwenden lassen. Typische, eigenständige Use Cases bilden die Grundlage. Das Projekt ist weder fachlich noch technisch an bestehende Portfolio-Use-Cases gebunden.

Der Name verbindet den Untersuchungsgegenstand „Data Stores“ mit einer reproduzierbaren „Benchmark Workbench“. Der vorgeschlagene Repository-Name lautet `storebench`.

Das Ergebnis ist eine Entscheidungshilfe: **Welcher Store passt bei welcher Datenmenge, Last, Funktionsanforderung und Implementierungssprache — und wann genügt PostgreSQL?** Ein allgemeiner Sieger wird nicht vorausgesetzt.

## Ziele und Leitfragen

- Native Datenmodelle und Funktionen spezialisierter Stores mit einer sinnvoll modellierten und indizierten PostgreSQL-Variante vergleichen.
- Für jeden Use Case fachlich gleichwertige Implementierungen als native Skripte sowie in Python und Kotlin bereitstellen.
- Bedienbarkeit, Typisierung, Fehlerbehandlung, Nebenläufigkeit, Transaktionen und Entwicklungsaufwand nachvollziehbar bewerten.
- Latenz, Durchsatz und Ressourcenbedarf messen und Unterschiede zwischen Store, Treiber, Protokoll und Laufzeit auseinanderhalten.
- Alle Stores lokal in Docker-Containern mit expliziten Ressourcenlimits betreiben.
- Eine automatisierte Performance-Testumgebung mit reproduzierbaren Daten, Lastprofilen und Berichten aufbauen.

Zunächst werden Einzelinstanzen untersucht. Hochverfügbarkeit, verteilte Cluster, Cloud-Kosten und ein produktiver Plattform-Rollout gehören nicht zum ersten Umfang.

## Bezug zur Developer Platform

StoreBench ist ein eigenständiges Experimentierprojekt für den Data-Store-Katalog der Developer Platform. Die vorhandenen Plattformunterlagen nennen Dokument-, Graph- und Vektorlabs als mögliche Erweiterungen; sie belegen noch keinen bereitgestellten Katalog spezialisierter Stores. Die nachfolgende Auswahl ist deshalb ein Vorschlag und keine Aussage über bereits verfügbare Plattformservices.

Ausführbare Funktionsbeispiele sind für [Dokumente](docs/documents.md), [Graphen](docs/graph.md), [Vektoren](docs/vector.md), [Volltextsuche](docs/search.md) und [Blob-Speicherung](docs/blob.md) vorhanden. Der Graph-Pfad umfasst Apache AGE, Neo4j und HugeGraph mit nativen Skripten sowie direkten Python- und Kotlin-Clients. Die erste Ausführung erfolgt direkt über lokales Docker Compose. Ergebnisse können später Architekturentscheidungen, Ressourcenprofile und Beispiele für die Plattform liefern. Die Benchmark-Läufe benötigen keine Plattformbereitstellung. Quellen zum Kontext: [Produktübersicht](../developer-platform/docs/product/overview.md) und [UC-05: technische Alternativen vergleichen](../developer-platform/docs/product/use-cases.md).

Der geplante [Entwurf der Dokument-Workloads](docs/document-workloads.de.md) beschreibt größere Datenprofile und Szenariomixe für spätere Messungen.

Die qualitative Gegenüberstellung der direkten Clients steht unter [Entwicklerperspektive: PostgreSQL und spezialisierte Stores](docs/developer-experience.de.md).

Interaktive Datenbankwerkzeuge und integrierte Weboberflächen stehen unter [Lokaler Zugriff](docs/access.md).

## Stores und typische Use Cases

### Kernumfang

| Bereich | Spezialisierter Store | PostgreSQL-Vergleich | Typischer Use Case und Operationen |
| --- | --- | --- | --- |
| Dokumente | CouchDB | JSONB mit passenden GIN-/Ausdrucksindizes; eine relationale Variante als separates Experiment | Produktkatalog mit variablen Attributen: Produkte anlegen, verschachtelte Felder filtern, Teiländerungen durchführen und Kategorien aggregieren. |
| Graphen | Neo4j und Apache HugeGraph | Knoten-/Kantentabellen, indizierte Joins und rekursive CTEs | Abhängigkeitsanalyse von Softwarepaketen: direkte und transitive Abhängigkeiten, Auswirkungen einer Änderung und begrenzte Pfadsuche. |
| Vektoren | Qdrant | PostgreSQL mit pgvector; exakte Suche sowie geeigneter ANN-Index | Ähnliche Dokumente finden: Top-k-Nachbarn, Metadatenfilter, Vektoren aktualisieren und Trefferqualität bewerten. |
| Volltextsuche | OpenSearch | `tsvector`, `tsquery`, GIN und Ranking | Wissensartikel durchsuchen: Volltextabfragen, Filter, Ranking und Wiederfinden nach Indexaktualisierung. |
| Blob-Speicherung | RustFS (S3-kompatible API) | PostgreSQL `bytea` mit Metadatenspalten; Large Objects als separates Experiment | Dateien per Schlüssel speichern und lesen: Upload, vollständiges und bereichsweises Lesen, Metadatenabfrage, Überschreiben und Löschen. |

PostgreSQL-JSONB unterstützt Indexierung; rekursive CTEs bilden eine Grundlage für Graphabfragen. pgvector ist eine separat ausgewiesene Erweiterung und gehört nicht zum PostgreSQL-Kern. Technische Grundlagen: [JSONB](https://www.postgresql.org/docs/current/datatype-json.html), [rekursive Abfragen](https://www.postgresql.org/docs/current/queries-with.html), [pgvector](https://github.com/pgvector/pgvector).

### Geplante Erweiterungen

| Bereich | Kandidat | PostgreSQL-Vergleich | Typischer Use Case |
| --- | --- | --- | --- |
| Key-Value / kurzlebiger Zustand | Redis | Tabelle mit Primärschlüssel, atomaren Updates und expliziter Ablauf-/Bereinigungslogik | Session-Lookups, TTL und atomare Zähler bei konkurrierenden Zugriffen. Cache- und dauerhafte Profile getrennt betrachten. |
| Analytik | ClickHouse | Relationale Faktentabelle, Partitionierung und bedarfsgerechte Indizes | Ereignisdaten ingestieren und über Zeiträume, Kategorien und hohe Kardinalitäten aggregieren. |

Die Erweiterungen folgen erst nach einem vollständigen Benchmark-Pfad im Kernumfang. Die [PostgreSQL-Volltextsuche](https://www.postgresql.org/docs/current/textsearch.html) ist die funktionale Ausgangsbasis für den OpenSearch-Vergleich. Weitere Stores werden nur mit eigenem Workload und Vergleichsvertrag aufgenommen.

## Drei Implementierungswege

„Nativ“ bezeichnet zwei unterschiedliche Dinge: den spezialisierten Store gegenüber PostgreSQL sowie dessen eigene Abfrage-, Skript- oder API-Schnittstelle gegenüber einer Sprachintegration. StoreBench weist beides getrennt aus.

| Store | Native Skripte / direkte Schnittstelle | Python | Kotlin |
| --- | --- | --- | --- |
| PostgreSQL | SQL über `psql`, einschließlich pgvector-Abfragen | Psycopg | JDBC mit pgJDBC |
| CouchDB | Versionierte REST-Requests, Mango-Abfragen und Views | Direkter HTTP-Client | Java-HTTP-Client aus Kotlin |
| Neo4j | Cypher-Dateien über `cypher-shell` | Neo4j-Python-Treiber | Neo4j-Java-Treiber aus Kotlin |
| Apache HugeGraph | Gremlin über die REST-API | Direkter HTTP-Client mit REST und Gremlin | Java-HTTP-Client mit REST und Gremlin aus Kotlin |
| Qdrant | Versionierte JSON-Requests gegen REST, per Skript ausgeführt | Qdrant-Python-Client | Qdrant-Java-Client aus Kotlin |
| OpenSearch | Versionierte JSON-Requests gegen die Such-REST-API | OpenSearch-Python-Client | OpenSearch-Java-Client aus Kotlin |
| RustFS | S3-kompatible Requests per CLI oder signiertem HTTP-Skript | AWS SDK für Python (Boto3) mit RustFS-Endpunkt | AWS SDK für Java aus Kotlin mit RustFS-Endpunkt |

Qdrant benötigt keine erfundene eigene Skriptsprache: direkte API-Requests bilden hier den nativen Referenzweg. Bei Kotlin ist sichtbar zu unterscheiden zwischen Kotlin-spezifischer API und Java-Interoperabilität. Grundlagen: [CouchDB HTTP API](https://docs.couchdb.org/en/stable/api/), [Neo4j Java](https://neo4j.com/docs/java-manual/current/query-simple/), [HugeGraph-Clients und -APIs](https://hugegraph.apache.org/docs/clients/), [Qdrant-Clients](https://api.qdrant.tech/), [RustFS-S3-Kompatibilität](https://docs.rustfs.com/en/reference/s3-compatibility).

Jede Variante enthält Setup, Dateneinspielung, Operationen und Ergebnisvalidierung. Die erste Sprachbaseline verwendet direkte Treiber ohne ORM oder umfangreiches Anwendungsframework. Coroutine-, Async-, Pooling- und Framework-Varianten werden als eigene Versuche ausgewiesen, damit ihre Effekte erkennbar bleiben.

Die Use Cases nutzen serverseitige Abfragen und Aggregationen, wo fachlich sinnvoll. Eine gemeinsame Schnittstelle vereinheitlicht Eingaben und Ergebnisse, ohne alle Stores auf eine generische CRUD-API zu reduzieren. Abfragepläne, Indizes und Datenmodelle bleiben einsehbar.

## Fachliche Vergleichbarkeit

Jeder Workload erhält einen versionierten Vertrag mit Eingaben, erwarteten Ergebnissen, Sortierung, Limits, Konsistenz, Fehlerfällen und erlaubten Abweichungen. Eine schnelle, aber fachlich andere Implementierung gilt nicht als gleichwertiges Ergebnis.

- **Dokumente:** gleiche Feldtypen, Null-/Missing-Semantik, Filter, Projektionen und Änderungsregeln. JSONB- und relationale PostgreSQL-Modelle erhalten separate Resultate.
- **Graphen:** gleiche Richtung, maximale Pfadtiefe, Zyklusbehandlung und Duplikatregeln. Erreichbarkeit, kürzeste Pfade und Aufzählung aller Pfade sind unterschiedliche Workloads.
- **Vektoren:** dieselben vorab erzeugten Embeddings, Distanzfunktion, Filter und Top-k-Werte. Ein exakter Referenzlauf liefert die Ground Truth. ANN-Varianten werden bei vergleichbarem Recall@k bewertet; als erster Zielwert gilt mindestens 0,95. Embedding-Erzeugung liegt außerhalb der Datenbankmessung. pgvector dokumentiert den Zusammenhang zwischen ANN-Parametern, Recall und Geschwindigkeit in seiner [Referenz](https://github.com/pgvector/pgvector).
- **Volltextsuche:** Analyzer, Tokenisierung, Sprache, Filter, Ranking-Regeln und Ergebnislimits abgleichen. Relevanz und Sichtbarkeit nach Änderungen getrennt von der Abfragelatenz messen.
- **Blob-Speicherung:** Objektbytes, Schlüssel, Metadaten, Überschreib-/Löschverhalten, Bereichsgrenzen und Sichtbarkeit nach Schreibvorgängen abgleichen. PostgreSQL `bytea` und RustFS anhand desselben Dateivertrags vergleichen; Transaktions- und Multipart-Semantik getrennt berichten.
- **Dauerhaftigkeit:** Commit-Bestätigung, Flush-/Journal-Verhalten und Sichtbarkeit nach Schreiboperationen werden dokumentiert. Nicht gleichwertige Garantien werden getrennt berichtet.
- **Spätere TTL-Workloads:** Logisches Ablaufen versus physischer Löschung ist eine zusätzliche Qualitätsdimension.

Optimierte Indizes und realistische Einstellungen sind auf beiden Seiten erlaubt. Standardkonfiguration und Tuning werden getrennt gemessen; Aufbauzeit, Speicherbedarf und Schreibkosten der Optimierungen gehören zum Ergebnis.

## Lokale Docker-Umgebung

Docker Compose stellt Stores, Runner und Beobachtung bereit. Pro Messung läuft genau ein Zielstore mit einem aktiven Client. PostgreSQL und der jeweilige Gegenkandidat werden nacheinander unter demselben Profil gemessen. Weitere Stores bleiben gestoppt.

Die folgenden Werte sind vorgeschlagene Startprofile, keine bereits vermessenen Mindestanforderungen:

| Komponente | Standardprofil | Größeres Vergleichsprofil |
| --- | --- | --- |
| Zielstore | 2 CPU-Kerne, 4 GiB RAM | 4 CPU-Kerne, 8 GiB RAM |
| Python-/Kotlin-Runner bzw. nativer Client | 2 CPU-Kerne, 2 GiB RAM | unverändert |
| Lastgenerator | 2 CPU-Kerne, 2 GiB RAM | unverändert; Kapazität vorab prüfen |
| Monitoring gesamt | bis 1 CPU-Kern, 2 GiB RAM | unverändert |

Diese Budgets sind getrennt vorgesehen. Für das Standardprofil ist ein Host mit ungefähr 12 logischen CPUs und 24 GiB RAM eine erste Planungsgröße; die reale Eignung wird vor Messbeginn geprüft. CPU-Quoten allein garantieren keine exklusiven Kerne. Wenn möglich, werden Store und Lastgenerator auf getrennte CPU-Sets gelegt.

Weitere Festlegungen:

- CPU- und RAM-Grenzen explizit in Compose setzen, beispielsweise über `cpus` und `mem_limit`, und die wirksamen Grenzen vor jedem Lauf prüfen. Docker beschreibt diese Optionen in der [Compose-Referenz](https://docs.docker.com/reference/compose-file/services/).
- Images per Version und Digest sowie Python-, JDK-, Kotlin- und Treiberversionen fixieren; keine `latest`-Tags in freigegebenen Experimenten.
- Persistente Daten in gleichartigen Docker-Volumes auf demselben Datenträger ablegen. Unter Windows vorzugsweise im Linux-Dateisystem der Docker-/WSL-Umgebung; Host-Bind-Mounts nicht mit Linux-Volumes vermischen.
- Betriebssystem, CPU-Architektur, Docker-/Compose-Version, VM-/WSL-Grenzen, Dateisystem, Datenträger und Netzwerkpfad im Laufmanifest erfassen.
- Swap-Verhalten explizit festlegen, Store-Caches und JVM-Heap innerhalb der Limits dimensionieren sowie OOM, Throttling und Host-Druck protokollieren.
- Identische Netzwerkstrecken verwenden. Authentifizierung und TLS-Einstellungen je Vergleich konstant halten.
- Healthchecks und fachliche Bereitschaft prüfen; ein offener Port genügt nicht als Startbedingung.

## Performance-Testumgebung

### Messschichten

1. **Native Referenz und Diagnose:** Store-eigene Skripte, Query-Pläne und gegebenenfalls Engine-Timings zeigen, welche Operation tatsächlich ausgeführt wird. Für Messungen werden Verbindungen wiederverwendet; ein neuer CLI-Prozess pro Operation wäre eine gesonderte Startzeitmessung. Native Werkzeuge mit unzureichender Zeitauflösung liefern nur Batch-Durchsatz, keine erfundenen Einzeloperation-Perzentile.
2. **Direkter Client-Benchmark:** Langlebige Python- und Kotlin-Runner messen identische Operationen direkt über den Treiber. Die Zeit umfasst Pool-Wartezeit, Serialisierung, Netzwerk, Store-Verarbeitung und vollständiges Lesen des vereinbarten Ergebnisses. Verbindungsaufbau und Prozessstart werden separat gemessen.
3. **Anwendungsbenchmark:** Ein externer Lastgenerator ruft dünne Python- und Kotlin-HTTP-Adapter mit demselben Vertrag auf. Er misst den gesamten Anwendungspfad und kann realistische Ankunftsraten unabhängig von der Antwortzeit erzeugen.

Für Schicht 3 ist k6 mit Arrival-Rate-Szenarien vorgesehen. [k6 beschreibt dieses offene Lastmodell](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/). Schicht 2 benötigt einen eigenen protokollnahen Runner; k6 wird nicht als universeller Direktclient für alle Datenbankprotokolle vorausgesetzt.

Die Schichten werden separat ausgewertet. Native CLI-Zeiten sind keine automatische Untergrenze für Treiberlatenz. Unterschiede zwischen Python und Kotlin werden zunächst als Unterschiede des vollständigen Client-Stacks berichtet. Für Aussagen über die Sprache müssen Protokoll, Pooling, Batchgröße und Nebenläufigkeit möglichst übereinstimmen. Besonders bei Qdrant sind REST und gRPC explizit auszuweisen; der [Java-Client verwendet gRPC](https://qdrant.tech/documentation/quickstart/).

### Daten und Lastprofile

- Deterministische Generatoren mit festem Seed, versioniertem Schema, Prüfsummen und einer für alle Clients identischen Operationsfolge.
- Kleine Smoke-Daten, mittlere Datenmengen und ein größeres Profil oberhalb des verfügbaren Store-Caches. Ausgangspunkte für Dokumente sind 10.000, 100.000 und 1.000.000 Datensätze; Payload-Größe und tatsächliche Bytes werden zusätzlich festgehalten. Graphgröße, Gradverteilung und Vektordimension benötigen eigene Profile.
- Gleichverteilte und schiefe Zugriffe mit Hotspots, verschiedene Selektivitäten sowie kleine und große Ergebnismengen. Keine reine Wiederholung eines einzigen Cache-Hits.
- Read-only, Write-only und ein definierter Mix, zunächst 80 % Reads / 20 % Writes; Bulk-Import getrennt vom Online-Betrieb.
- Nebenläufigkeitsstufen 1, 8 und 32 als Startpunkt. Zusätzlich abgestufte angebotene Operationsraten bis über die Sättigungsgrenze; eine Vorprüfung bestimmt sinnvolle Raten pro Use Case.
- Warmbetrieb, Neustartverhalten und gesondert definierte Cold-Cache-Versuche. Ein Containerneustart leert nicht automatisch den Dateisystemcache des Hosts.

### Ablauf eines gültigen Laufs

1. Host-Kapazität, Konfiguration, Ressourcenlimits und Generatorleistung prüfen; unveränderliches Laufmanifest erzeugen.
2. Zielstore in einen definierten Ausgangszustand bringen, Daten und Indizes aufbauen sowie Konformitätsprüfungen ausführen.
3. Als erste Vorgabe mindestens zwei Minuten aufwärmen und danach mindestens fünf Minuten messen. Verlängern, wenn Stabilität oder Stichprobengröße nicht ausreichen; identische Regeln für alle Varianten verwenden.
4. Pro Konfiguration mindestens fünf unabhängige Messläufe ausführen. Reihenfolge der Varianten randomisieren und veränderte Daten vor Wiederholungen zurücksetzen.
5. Mindestens einen 30-minütigen Dauertest für den ersten vollständigen Use Case durchführen, um etwa Speicherwachstum oder Wartungseffekte sichtbar zu machen.
6. Rohdaten, Histogramme, Ressourcenzeitreihen, Query-Pläne und Manifest archivieren; Bericht automatisiert erstellen.

Der Lastgenerator erfasst angebotene, gestartete und erfolgreich abgeschlossene Operationen, Timeouts, Fehler und nicht gestartete Requests. Ein überlasteter Generator darf nicht als Store-Grenze interpretiert werden. Das offene Lastmodell und die Erfassung der Wartezeit sollen verhindern, dass eine langsamer werdende Zielkomponente durch sinkende Ankunftsraten günstiger erscheint. Bei k6 ist insbesondere [dropped_iterations](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/) auszuwerten.

### Metriken und Auswertung

| Dimension | Erfasste Größen |
| --- | --- |
| Antwortzeit | p50, p95, p99; Startzeit und Verbindungsaufbau separat; Zahl der Beobachtungen |
| Kapazität | angebotene und erreichte Operationen/s, Sättigungspunkt, Fehler- und Timeoutquote |
| Ressourcen | Store- und Client-CPU, RAM, I/O, Netzwerk, CPU-Throttling, GC und Pool-Wartezeit |
| Datenhaltung | Daten-/Indexgröße, Importzeit, Indexaufbauzeit und Wartungsaufwand |
| Qualität | Ergebniskorrektheit, Recall@k, gegebenenfalls Suchrelevanz und Aktualitätsverzug |
| Bedienbarkeit | Integrationsaufwand, API-Qualität, Typisierung, Diagnose und notwendiger Zusatzcode |

Als anfänglicher gemeinsamer Vergleichspunkt sind p95 ≤ 100 ms und eine Fehlerquote ≤ 0,1 % vorgesehen. Je Workload werden diese Ziele vor Messbeginn bestätigt oder begründet angepasst. Berichtet wird der maximale nachhaltige Durchsatz innerhalb der festgelegten Ziele und bei erfüllten Qualitätsanforderungen, nicht nur der höchste kurzzeitige Durchsatz.

Für jeden Messpunkt werden Einzelläufe, Median und Streuung ausgewiesen. Konfidenzintervalle stützen sich auf unabhängige Wiederholungen. p99 wird nur bei ausreichender Stichprobengröße interpretiert; Perzentile werden nicht einfach über Läufe gemittelt.

Performance-Unterschiede werden als Latenz- und Durchsatzverhältnisse mit klar benannter Referenz ausgewiesen, beispielsweise Kotlin/Python bei identischem Store oder nativer Store/PostgreSQL bei identischem Client. Ohne kontrollierte Bedingungen und erkennbare Abgrenzung zur Messstreuung wird keine sprachbedingte Performance-Einbuße behauptet.

## Bewertung der Sprachintegration

Jeder Use Case erhält neben Messwerten einen kurzen Erfahrungsbericht mit denselben Aufgaben in allen Implementierungen:

- Verbindung herstellen, Credentials konfigurieren und Pool verwalten.
- Datentypen abbilden, inklusive JSON, Zeitstempeln, IDs und Vektoren.
- Parametrisierte Abfragen, Transaktionen oder atomare Änderungen umsetzen.
- Ergebnisse streamen, Batch-Operationen ausführen und Nebenläufigkeit begrenzen.
- Timeouts, Abbruch, Fehlercodes, Wiederholungen und Ressourcenfreigabe behandeln.
- Tests, Logging und Diagnose integrieren.

Eine Skala von 1 (erheblicher Zusatzaufwand) bis 5 (direkt und gut unterstützt) ist eine qualitative Einschätzung mit konkreten Belegen. Kotlin-native Unterstützung, Java-Interop und selbst geschriebene Brücken werden getrennt benannt. Entwicklungszeit und Umfang des handgeschriebenen Integrationscodes dienen als Kontext; sie sind kein alleiniger Qualitätsmaßstab. Es gibt keinen undurchsichtigen Gesamtscore aus Geschwindigkeit und Bedienbarkeit.

## Geplante Projektstruktur

```text
storebench/
├── README.md
├── docs/                   # Methodik, Architektur und Entscheidungen
├── infrastructure/         # Compose, Ressourcenprofile, Store-Konfigurationen
├── workloads/              # Verträge, Generatorprofile und Erwartungswerte
├── implementations/
│   ├── native/             # SQL, CouchDB REST, Cypher und direkte API-Requests
│   ├── python/             # Direkte Treiber und dünne HTTP-Adapter
│   └── kotlin/             # Direkte Treiber und dünne HTTP-Adapter
├── benchmarks/             # Orchestrierung, Direktmessung und k6-Szenarien
├── observability/          # Lokaler Docker-Stats-Sampler und Auswertung
├── tests/                  # Konformität und Prüfung der Messinstrumentierung
└── results/                # Manifeste, Rohdaten und generierte Berichte
```

Dies ist eine Zielstruktur. Die fünf Kern-Use-Cases besitzen lokale Compose-Umgebungen und Funktionsskripte. Für alle fünf Kern-Use-Cases gibt es außerdem direkte Python- und Kotlin-Clients; die Benchmark-Infrastruktur ist geplant. Die spätere lokale Bedienung soll einen vollständigen Ablauf aus Start, Datenerzeugung, Konformitätsprüfung, Benchmark und Bericht ermöglichen. Ausführbare Befehle werden mit der Implementierung ergänzt.

## Umsetzung und Abnahmekriterien

| Phase | Ergebnis | Abnahme |
| --- | --- | --- |
| 1 — Messfundament und Dokumente | Docker-Profile, Generator, CouchDB/JSONB, drei Implementierungswege, Direkt- und Anwendungsmessung | Ein sauberer Checkout reproduziert einen vollständigen Lauf mit validierten Ergebnissen, wirksamen Limits und Bericht. |
| 2 — Graphen | Neo4j und HugeGraph gegen PostgreSQL, mehrere Tiefen und Gradverteilungen | Alle drei Implementierungswege liefern die vereinbarten Ergebnisse; Abfragepläne und Sättigungsmessungen liegen vor. |
| 3 — Vektoren | Qdrant gegen pgvector, exakte Referenz und ANN-Profile | Recall, Filtersemantik und Protokolle sind dokumentiert; Performance wird bei vergleichbarer Qualität ausgewertet. |
| 4 — Volltextsuche | OpenSearch gegen PostgreSQL-Volltextsuche, abgestimmte Analyzer und Relevanzprüfungen | Suchergebnisse und Sichtbarkeit nach Änderungen erfüllen den vereinbarten Vertrag; Indexkosten und nachhaltige Performance sind dokumentiert. |
| 5 — Blob-Speicherung | RustFS gegen PostgreSQL `bytea`, unterschiedliche Objektgrößen und Lese-/Schreibmuster | Bytes, Bereichsabfragen, Metadaten und Überschreib-/Löschverhalten erfüllen den Vertrag; Durchsatz, Latenz und Speicherbedarf sind dokumentiert. |
| 6 — Erweiterungen und Transfer | Ausgewählte Redis- oder Analytik-Workloads; Empfehlungen für die Developer Platform | Jede Empfehlung benennt Einsatzgrenzen, Ressourcenbedarf, Integrationsaufwand und die zugrunde liegenden Messläufe. |

Das Projekt ist im Kernumfang erfolgreich, wenn die Use Cases für Dokumente, Graphen, Vektoren, Volltextsuche und Blob-Speicherung jeweils als native Skripte, in Python und in Kotlin vorliegen, gegen PostgreSQL geprüft wurden und vollständig reproduzierbare Berichte liefern. Auch das Ergebnis „PostgreSQL genügt“ ist ein wertvolles Resultat.
