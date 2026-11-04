# Entwurf der Dokument-Workloads

Dies ist ein **vorgeschlagener Benchmark-Vertrag**, kein implementierter oder gemessener Workload. Das vorhandene [Fixture mit sechs Produkten und der ausführbare Vertrag](documents.md) bleiben ein Funktions- und Konformitätstest. Dieser Entwurf erweitert denselben Produktkatalog, um CouchDB-Dokumente und PostgreSQL JSONB bei größeren Datenmengen und unterschiedlichen Zugriffsmustern zu vergleichen. Ein relationales PostgreSQL-Modell wäre eine gesonderte Variante.

## Wann ein Lauf repräsentativ ist

Ein repräsentativer Lauf bildet einen Anwendungsablauf ab: gespeicherte Dokumente, tatsächlich verwendete Abfragen, Ergebnismengen, Schreibvorgänge, konkurrierende Zugriffe und Anforderungen an die Sichtbarkeit neuer Daten. Kein einzelner Operationsmix steht für alle Dokumentanwendungen. Die drei Profile unten decken Katalogsuche, Katalogpflege und konkurrierende Bestandsänderungen ab. Ihre Prozentwerte sind **Beispielwerte für den Einstieg**, keine Behauptung über typische Produktivlast. Wenn Daten einer Zielanwendung vorliegen, sollen deren gemessene Verteilungen die Beispielwerte ersetzen. Zeitraum, Stichprobenverfahren und Anonymisierung werden mit dem Lauf veröffentlicht. Ein nicht kalibriertes Profil bleibt als synthetisch gekennzeichnet.

Für jedes Profil wird ein stabiler, versionierter Request-Trace oder ein deterministischer Generator verwendet. Beide Stores erhalten dieselben logischen Anfragen. Gemessen wird die vollständige Clientoperation einschließlich Kodierung, Netzwerktransfer, Dekodierung der Antwort, Konfliktbehandlung und erforderlicher Wiederholungen. Die Ergebnisse werden je Operationsklasse und für das gesamte Profil ausgewiesen, damit schnelle Punktabfragen langsame Filter oder Schreibvorgänge nicht verdecken.

## Daten- und Abfragevertrag

Das Basisdokument enthält `id`, `name`, `category`, `price_cents`, `stock` und ein Objekt `attributes`. `id` ist eine stabile, eindeutige Zeichenfolge; Preise und Bestand sind Ganzzahlen. Fehlende optionale Attribute bleiben weg und werden nicht als JSON-Null gespeichert. Beide Stores erhalten dasselbe logische Dokument und dieselben Feldtypen. In CouchDB entspricht `_id` dem Wert von `id`; `_rev` ist ein Speicherfeld und gehört nicht zum logischen Vergleich. Generierte Dokumente erhalten zusätzlich eine monoton steigende `version` für Änderungs- und Sichtbarkeitsprüfungen. Bei mandantenfähigen Läufen kommt `tenant_id` hinzu. Jede Punktabfrage, jeder Filter, jede Seite und jede Aggregation muss dann auf genau einen Mandanten beschränkt sein; PostgreSQL-Indizes und CouchDB-Abfragen berücksichtigen diese Einschränkung.

Die Kataloge werden aus einem festen Zufalls-Seed und einem versionierten Schema erzeugt. Zusammenhänge, die die Selektivität beeinflussen, bleiben erhalten: Kategorien und verfügbare Attribute, Preise und Bestand je Kategorie sowie die Beliebtheit einer Teilmenge von IDs. Die Dokumentgröße variiert durch plausible optionale Attribute und begrenzte Textfelder, nicht allein durch bedeutungslose Zufallsfüllung. Für die tatsächlich serialisierten Dokumente werden Größenverteilung (p50/p95/p99), Anteile fehlender und nullwertiger Felder, Kategoriehäufigkeiten und Trefferzahlen der Abfragen festgehalten. Die Verteilungen sind für beide Stores gleich. Der Datensatz enthält auch unbekannte IDs, Filter ohne Treffer und Dokumente an den Grenzen der Größenklassen.

| Parameter | Erste Testwerte | Bedeutung |
| --- | --- | --- |
| Kataloggröße | 10.000; 100.000; 1.000.000 Dokumente | Zeigt Speicher- und Indexeffekte; tatsächliche Daten- und Indexgröße berichten. |
| Nutzdatengröße | Kleine, mittlere und große Klassen, z. B. 0,5–2, 2–8 und 8–32 KiB serialisiert | Beeinflusst I/O, Übertragung, Dekodierung und Kosten des Umschreibens. Klassenanteile festhalten. |
| Optionale Felder | Bei ausgewählten Attributen fehlen 0 %, 25 % oder 75 % | Prüft dünn besetzte Schemas und die Bedeutung fehlender Felder. |
| Kategorien | Gleichverteilt oder schief verteilt (größte Kategorie: 40 %) | Verändert Gruppengrößen und Filterhäufigkeit. |
| Filterselektivität | Zielwerte von ungefähr 0,01 %, 1 % und 20 % Treffern | Trennt selektive Indexabfragen von breiten Ergebnismengen. Tatsächliche Selektivität nach der Generierung prüfen. |
| Zugriffsschiefe | Gleichverteilt; 1 % der IDs erhält 50 % der Punktabfragen | Bildet häufig angefragte Produkte ab und verändert Cache-Effekte. |
| Ergebnislimit | 10, 50, 200; Seitentiefe 1, 10, 100 | Verändert Übertragungsvolumen und Kosten tiefer Navigation. |
| Verteilung der Änderungen | Gleichverteilte IDs; 1 % erhält 50 % der Schreibzugriffe | Zeigt Revisionskonflikte, Sperren und Umschreibkosten. |
| Mandantenstruktur | Ein Mandant; viele unterschiedlich große Mandanten | Prüft mandantenbezogene Indizes und Trennung. Das Schema ändert sich; dies ist eine gesondert benannte Variante. |

Diese Parameter sind kontrollierte Vergleichsachsen und werden nicht vollständig miteinander kombiniert. Zunächst wird ein mittleres Basisprofil verwendet und jeweils ein Parameter verändert. Kombinationen können aus den Zugriffsdaten der Zielanwendung abgeleitet werden. Für jeden Lauf werden die genaue Profildatei, Generatorversion, Zufalls-Seed, Schemaversion und Datenprüfsumme veröffentlicht. Läufe mit wesentlich unterschiedlicher tatsächlicher Selektivität oder Anzahl übertragener Bytes werden nicht direkt verglichen.

## Operationen

Alle Lesevorgänge liefern dieselben logischen Felder in derselben Reihenfolge. Eine Operation ist erst erfolgreich, wenn das vollständige Ergebnis empfangen und dekodiert wurde. Eine Änderung ist nur erfolgreich, wenn ihre festgelegte Nachbedingung erfüllt ist. Abfragevorlagen und Parametersätze werden vor der Zeitmessung festgelegt; für keinen Store werden leichtere Prädikate gewählt.

| Kürzel | Logische Operation | Vertrag und notwendige Variation |
| --- | --- | --- |
| P1 | Punktabfrage | Ein Produkt bei aktivem Mandantenmodus über `(tenant_id, id)`, sonst über `id` lesen. Treffer und fehlende IDs getrennt ausweisen; vollständiges Dokument zurückgeben. |
| P2 | Attributfilter | Nach Kategorie und verschachtelten Attributen wie Farbe und Wasserdichtigkeit filtern. Nach `(category, id)` sortieren und die ersten `limit` Treffer mit derselben Projektion zurückgeben. Seltene, häufige und leere Ergebnisse prüfen. |
| P3 | Seitenweise Navigation | Gefilterte Ergebnisse mit einem stabilen Cursor aus `(category, id)` durchlaufen. Der Cursor folgt aus dem letzten gelieferten Datensatz und dem Seitenlimit. Festlegen, ob eine gleichzeitige Änderung ein Produkt zwischen Seiten verschieben darf. Seitentiefe und insgesamt gelieferte Bytes erfassen. |
| P4 | Kategorieübersicht | Je Kategorie im Geltungsbereich Anzahl und Summe von `price_cents` liefern, nach Kategorie sortiert. Die Summe umfasst alle passenden Produkte, nicht nur die aktuelle Seite. |
| P5 | Anlegen | Eine neue eindeutige ID und ein vollständiges Dokument einfügen; Ablehnung doppelter IDs gesondert ausweisen. Nach der Bestätigung per ID prüfen. |
| P6 | Attribut ändern | Ein verschachteltes Attribut ändern, alle übrigen logischen Felder erhalten und `version` erhöhen. Einzelne und konkurrierende Schreiber prüfen. |
| P7 | Bestand ändern | Eine Bestandsdifferenz nur anwenden, wenn aktuelle Version und Regel für nichtnegativen Bestand dies erlauben. Eine abgelehnte Bedingung ist ein eigenes Ergebnis und kein erfolgreicher Schreibvorgang. |
| P8 | Löschen | Eine vorhandene ID löschen; folgende Punktabfragen dürfen sie nicht mehr finden. Kosten für Tombstones oder Bereinigung gegebenenfalls gesondert messen. |

P2 und P3 benötigen in beiden Implementierungen eine indizierte, serverseitige Sortierung, bevor ihre Zeiten als gleichwertige Operationen verglichen werden können. Der bisherige CouchDB-Funktionstest sortiert seine wenigen Filtertreffer im Client. Wenn eine Abfrage-/Indexkombination die gleiche Reihenfolge nicht liefern kann, muss entweder der gemeinsame Vertrag angepasst oder dieser Anwendungspfad getrennt und einschließlich vollständigem Abruf und Client-Sortierung ausgewiesen werden. Ergebnisse dürfen nicht vor dem Sortieren abgeschnitten und anschließend als gleichwertige Top-N-Treffer bezeichnet werden.

P6 und P7 machen unterschiedliche Schreibverfahren sichtbar. CouchDB liest das Dokument und schreibt eine neue Revision; PostgreSQL kann ein bedingtes JSONB-Update mit einer Anweisung ausführen. Logische Vorbedingung und Endzustand sind gleich festzulegen. Alle dafür nötigen Lesevorgänge, Wiederholungen und Antwortprüfungen gehören zur gemessenen Clientoperation. Es gilt eine begrenzte Wiederholungsregel mit gleicher Höchstzahl von Versuchen und gleichem Zeitbudget für Wartepausen. Konflikte, Wiederholungen, nicht erfüllte Bedingungen und ausgeschöpfte Wiederholungen werden gezählt. Für P7 wird geprüft, dass jede bestätigte Bestandsänderung genau einmal im Endzustand enthalten ist und der Bestand nie negativ wird. Erreichte Semantik und unterschiedliche Garantien werden berichtet; verlorene Änderungen dürfen nicht unbemerkt bleiben.

Die Übersicht P4 sowie die Indizes für P2/P3 können Pflegekosten und Sichtbarkeitsverzögerungen verursachen. Indizes und CouchDB-Views werden vor der stationären Lesemessung aufgebaut; Aufbauzeit, Plattenbedarf und Kosten bei Schreibvorgängen werden berichtet. Nach einem Schreibvorgang wird zwischen (1) Bestätigung des Schreibens, (2) Sichtbarkeit per ID und (3) Sichtbarkeit in Filtern und Übersichten unterschieden. Ein Lauf kann sofortige Sichtbarkeit verlangen oder ein festgelegtes Verzögerungsbudget zulassen. Für beide Stores gilt dieselbe *Anwendungsanforderung*; die beobachtete Verzögerung wird als Verteilung erfasst. Eine veraltete Übersicht gilt nicht als korrektes aktuelles Ergebnis.

## Szenarioprofile

Jede Zeile enthält einen reproduzierbaren Mix **logischer Operationen** mit insgesamt 100 %. Die Prozentwerte zählen angeforderte Operationen, nicht interne Datenbankaufrufe: Ein CouchDB-Update mit vorheriger Leseabfrage zählt weiterhin als ein P6 oder P7. IDs für Anlegen und Löschen bleiben vom festen Lesebestand getrennt, sofern das Szenario nicht ausdrücklich Sichtbarkeit prüft. Die Last wird mit kontrollierten angebotenen Raten und mehreren Nebenläufigkeitsstufen ausgeführt; Operationsmix und Schlüsselverteilung bleiben dabei gleich.

| Profil | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | Zweck |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Katalogsuche | 45 % | 30 % | 15 % | 5 % | 1 % | 3 % | 1 % | 0 % | Überwiegend Lesezugriffe, selektive und breite Filter, begrenzte Seitenabfragen. |
| Katalogpflege | 20 % | 15 % | 10 % | 5 % | 15 % | 25 % | 5 % | 5 % | Neue und geänderte Produkte, Indexpflege und Aktualität der Übersichten. |
| Umkämpfter Bestand | 30 % | 10 % | 0 % | 5 % | 0 % | 5 % | 50 % | 0 % | Häufig geänderte IDs, parallele bedingte Schreibzugriffe, Wiederholungen und Konflikte. |

Das Bestandsprofil ist nur dann ein gültiger Performancevergleich, wenn beide Implementierungen dieselbe Nachbedingung der bedingten Änderung erfüllen. Gelingt das innerhalb des Wiederholungsbudgets nicht, wird dies als funktionale Grenze berichtet. Zusätzlich zu diesen Mischlasten gibt es einen Bulk-Import-Test: Einen festen Katalog in eine leere Datenbank in Batches laden und anschließend Index-/View-Aufbau sowie die erste Abfrage getrennt messen. Bulk-Laden ist nicht mit Schreibvorgängen unter stationärer Last gleichzusetzen.

Der Datenbestand bleibt während der Messung begrenzt und reproduzierbar. IDs für P5/P8 werden vorab reserviert; wo das Profil beides enthält, folgen auf angelegte Dokumente spätere Löschvorgänge. P6 wechselt zwischen Attributwerten, P7 gleicht positive und negative Differenzen unter Beachtung der Bestandsuntergrenze aus. Wenn der Katalog absichtlich wächst, wird der Lauf als Import-/Wachstumsprofil bezeichnet; Daten- und Indexwachstum werden über die Zeit berichtet. Der Ablaufplan der Anfragen wird vorab berechnet, ohne dabei Store-Operationen auszuführen. Lese- und Schreibzugriffe beobachten jedoch die während des Laufs erzeugten Zustandsänderungen. Vor jeder Wiederholung werden derselbe Anfangsbestand und derselbe Request-Seed wiederhergestellt.

## Vergleich ausführen und berichten

1. Fixture und Anfragestrom einmal erzeugen; Anzahl, Feldtypen, serialisierte Größen, Trefferzahlen und Prüfsummen unabhängig von den Stores prüfen.
2. Beide Stores aus demselben Fixture laden. Vor der Zeitmessung eine Stichprobe vollständiger Dokumente, exakte Filter-IDs und Reihenfolge, Übersichtssummen, Erhalt unveränderter Felder, bedingte Bestandsänderungen und Löschungen prüfen.
3. Jeweils einen Store mit einem langlebigen Client unter denselben wirksamen CPU-, Speicher-, Datenträger- und Netzwerklimits betreiben. Versionen, Indizes, Clientsprache/Treiber, Dauerhaftigkeitseinstellungen und Abfragepläne festhalten. Native, Python- und Kotlin-Pfade als eigene Messreihen ausweisen.
4. Die gemeinsame [Messmethodik](benchmark-tests.de.md) anwenden: Aufwärmphase, wiederholte Messläufe, Variation von angebotener Rate und Nebenläufigkeit, Rücksetzen nach Schreibvorgängen sowie ein gesonderter Dauertest. Angebotene und abgeschlossene Operationen/s, p50/p95/p99 je Operation, Fehler, Timeouts, Wiederholungen, Sichtbarkeitsverzögerung, übertragene Bytes, CPU, Speicher, I/O sowie Daten- und Indexgröße erfassen.
5. Den höchsten nachhaltigen Durchsatz veröffentlichen, der die vorher festgelegten Grenzen für Latenz, Fehler, Korrektheit und Sichtbarkeit einhält. Einzelne Wiederholungen und unerfüllte Vertragsanforderungen beilegen. Die drei Profile nicht zu einer einzigen Gesamtpunktzahl zusammenfassen.

## Erster implementierter Vorbereitungsschritt

Das versionierte [Profil für die Katalogsuche](../workloads/documents/profiles/storefront-v1.json) legt zunächst 10.000 Produkte, 1.000 logische Anfragen, die acht Operationsanteile sowie Parameter für Kategorien, optionale Felder, Dokumentgrößen, Punktabfragen, Filter und Seiten fest. Der [Generator](../scripts/generate_document_workload.py) erzeugt daraus ohne Datenbankzugriff drei Dateien:

```bash
python3 scripts/generate_document_workload.py
```

Standardziel ist `results/documents/storefront-v1/`; mit `--profile` und `--output` lassen sich Eingabeprofil und Zielverzeichnis angeben. `documents.jsonl` enthält die Anfangsdokumente. `requests.jsonl` enthält die geordnete Anfragefolge mit Eingaben und erwarteten Ergebnissen. `manifest.json` hält Profil-, Generator- und Datei-Prüfsummen sowie tatsächlich erzeugte Verteilungen und Trefferzahlen fest. Das Ergebnisverzeichnis wird nicht versioniert. Die sechs vorhandenen Smoke-Test-Produkte und deren Generator bleiben unverändert.

Die Erwartungswerte in `requests.jsonl` gelten für die **serielle** Ausführung in der angegebenen Reihenfolge. Sie dienen der Konformitätsprüfung. Für spätere parallele Messungen müssen konkurrierende Zustandsänderungen anhand von Invarianten und zulässigen Ergebnissen geprüft werden; die seriellen Einzelwerte dürfen dort nicht ungeprüft als Sollwerte gelten. Das aktuelle Profil enthält keine Löschanfragen (P8 = 0); der Generator weist Profile mit P8-Anteil ab.

## Serielle Konformitätsausführung

Der [Konformitäts-Runner](../benchmarks/documents/conformance.py) lädt `documents.jsonl` und spielt alle 1.000 Anfragen in Reihenfolge gegen PostgreSQL und CouchDB ab. Vor dem Zugriff prüft er die Datei-Prüfsummen. Nach jeder Operation vergleicht er IDs, vollständige logische Dokumente oder Kategorieübersichten mit den Erwartungswerten; beim ersten Fehler bricht er mit Sequenznummer ab. Er verwendet eine eigene PostgreSQL-Tabelle `benchmark_products` und eine eigene CouchDB-Datenbank `benchmark_products`, damit der sechs Produkte umfassende Funktionstest unberührt bleibt. `all` setzt ausschließlich diese Benchmark-Namensräume zurück.

```bash
python3 scripts/generate_document_workload.py
scripts/documents.sh up
python3 -m venv .venv
.venv/bin/pip install -r implementations/python/documents/requirements.txt
.venv/bin/python benchmarks/documents/conformance.py all --store both
```

`--store postgres` oder `--store couchdb` wählt einen Store; `--input` wählt ein anderes Verzeichnis mit Manifest und JSONL-Dateien. `seed` lädt nur die Anfangsdokumente, `replay` spielt nur den Trace ab und `all` führt beides aus. Vor jeder Wiederholung von `replay` ist erneut `seed` nötig, da P5–P7 den Bestand ändern. Die CouchDB-Filter verwenden eine serverseitige Sortierung mit einem ausdrücklich benannten Index auf Kategorie und ID; dieser Index kann bei seltenen Attributfiltern viele Dokumente prüfen. Seine Selektivität und alternative Indizes sind Gegenstand der späteren Performancearbeit. Dieser Runner prüft **Korrektheit**, er misst keine Latenzen oder Durchsatzwerte. Nebenläufigkeitsprüfungen und ein Mess-Runner fehlen noch.
