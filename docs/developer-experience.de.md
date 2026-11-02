# Entwicklerperspektive: PostgreSQL und spezialisierte Stores

Diese qualitative Gegenüberstellung betrachtet die direkten Python- und Kotlin-Clients der fünf StoreBench-Use-Cases. Bewertet werden Datenmodell, Abfragen, Client-APIs, Schreiboperationen und der im Code sichtbare Integrationsaufwand. Die Aussagen beziehen sich auf die implementierten kleinen Funktionsbeispiele, nicht auf alle Möglichkeiten der Stores. Laufzeit, Durchsatz und Ressourcenbedarf sind nicht Gegenstand dieses Dokuments.

Die Clients führen für jeden Store `seed`, `run` und `verify` aus. Der Graph-Vergleich hat eine besondere Grenze: Die PostgreSQL-Seite verwendet **Apache AGE**, also ebenfalls ein Graphmodell. Eine Umsetzung mit gewöhnlichen Knoten- und Kantentabellen sowie rekursiven CTEs existiert noch nicht.

## Dokumente: PostgreSQL JSONB und CouchDB

Code: [Python](../implementations/python/documents/main.py), [Kotlin](../implementations/kotlin/documents/src/main/kotlin/Documents.kt).

| Sprache | PostgreSQL JSONB | CouchDB |
| --- | --- | --- |
| Python | **Vorteil:** Psycopg bindet JSONB direkt ein; verschachtelte Filter, gezielte Änderung und Gruppierung bleiben in SQL. **Nachteil:** JSON-Operatoren, Casts und passende Indexausdrücke müssen beherrscht werden. | **Vorteil:** Dokumente lassen sich als Python-Dictionaries lesen und ändern. **Nachteil:** Der Client implementiert Authentifizierung und HTTP-Fehlerbehandlung selbst. Für Filter und Summen richtet er zusätzlich einen Mango-Index und eine View ein. |
| Kotlin | **Vorteil:** JDBC und die Seed-Transaktion sind explizit und vertraut. **Nachteil:** Der Client schreibt JSON als String, liest es über Jackson zurück und wandelt Abfrageergebnisse manuell um. | **Vorteil:** Jacksons Objektmodell passt zur verschachtelten Dokumentstruktur. **Nachteil:** Der Java-HTTP-Client braucht viel Code für Requests, JSON und Statusprüfungen; Index und View sind weitere Einrichtungsschritte. |

Bei CouchDB lesen beide Clients das Dokument vor der Änderung und schreiben es mit der vorhandenen `_rev` vollständig zurück. Konfliktbehandlung für gleichzeitige Änderungen ist in diesem Beispiel nicht implementiert. PostgreSQL verwendet für dieselbe Änderung `jsonb_set`.

## Graph: PostgreSQL mit Apache AGE und Neo4j

Code: [Python](../implementations/python/graph/main.py), [Kotlin](../implementations/kotlin/graph/src/main/kotlin/Graph.kt). Der relationale PostgreSQL-Graph-Baseline aus dem [Graph-Use-Case](graph.md) bleibt offen.

| Sprache | PostgreSQL/AGE | Neo4j |
| --- | --- | --- |
| Python | **Vorteil:** Der bestehende Psycopg-Zugriff und die PostgreSQL-Verbindung lassen sich nutzen. **Nachteil:** Jede Verbindung braucht `LOAD 'age'` und den AGE-Suchpfad. Cypher wird in SQL eingebettet und das `agtype`-Ergebnis als Text gelesen. | **Vorteil:** Cypher läuft direkt über den Treiber; beim Anlegen der Kanten werden Parameter gebunden. **Nachteil:** Ein zusätzlicher Treiber und Sitzungen sind nötig. Der Client vereinheitlicht die Ergebnisse derzeit dennoch als Strings. |
| Kotlin | **Vorteil:** Der Zugriff bleibt bei JDBC. **Nachteil:** SQL um Cypher, Dollar-Quoting und `agtype`-Konvertierung machen den Code schwer lesbar; der Seed validiert Paketnamen vor dem Einbetten in Cypher. | **Vorteil:** Der Java-Treiber bietet direkte Cypher-Aufrufe und Parameter-Maps. **Nachteil:** Sitzungen und Ergebnisse werden über Java-Interop verarbeitet; die verfügbaren Ergebnistypen nutzt der Client kaum. |

Der hier sichtbare Unterschied betrifft vor allem die **Client-Schnittstelle für denselben Graph-Workload**. Daraus folgt noch keine Aussage über einen rein relationalen PostgreSQL-Ansatz.

## Vektoren: PostgreSQL mit pgvector und Qdrant

Code: [Python](../implementations/python/vector/main.py), [Kotlin](../implementations/kotlin/vector/src/main/kotlin/Vector.kt).

| Sprache | PostgreSQL/pgvector | Qdrant |
| --- | --- | --- |
| Python | **Vorteil:** Vektorsuche, Metadatenfilter und Update passen in parametrisierte SQL-Abfragen. **Nachteil:** Der Client formatiert Vektoren selbst als Text und castet sie zu `vector`; die Distanzsemantik steckt im Operator `<=>`. | **Vorteil:** Collection, Punkte, Filter und `exact=true` sind als Python-Client-Modelle sichtbar. **Nachteil:** Collection-Lebenszyklus, Payload und der Abschluss von Schreiboperationen erfordern zusätzliche API-Schritte. |
| Kotlin | **Vorteil:** JDBC hält Vektoren und Metadaten im vertrauten Tabellenmodell. **Nachteil:** Auch hier werden Vektoren manuell in Text umgewandelt und SQL-Parameter positionsabhängig gesetzt. | **Vorteil:** Der Java-Client bietet konkrete Typen für Punkte und Abfragen. **Nachteil:** gRPC-Protobuf-Builder, `Double`-zu-`Float`-Konvertierung und das Warten auf Futures machen den Client umfangreich. |

Python verwendet für Qdrant REST, Kotlin gRPC. Ein Vergleich der beiden Clients umfasst daher auch unterschiedliche Protokolle. Beide fragen in diesem Beispiel ausdrücklich exakt ab; ANN-Verhalten gehört nicht zu dieser Bewertung.

## Volltextsuche: PostgreSQL und OpenSearch

Code: [Python](../implementations/python/search/main.py), [Kotlin](../implementations/kotlin/search/src/main/kotlin/Search.kt).

| Sprache | PostgreSQL | OpenSearch |
| --- | --- | --- |
| Python | **Vorteil:** Textanalyse, Gewichtung und Rangfolge stehen in Tabellendefinition und SQL; das Update ist ein gewöhnliches `UPDATE`. **Nachteil:** `tsvector`, `tsquery` und Ranking-Ausdruck müssen gezielt zusammengesetzt werden. | **Vorteil:** `multi_match`, Kategorie-Filter und Sortierung lassen sich gut als Python-Dictionaries ausdrücken. **Nachteil:** Mapping und Index werden separat verwaltet; nach Änderungen fordert der Client mit `refresh=wait_for` ausdrücklich Sichtbarkeit für die Suche an. |
| Kotlin | **Vorteil:** JDBC und SQL bleiben mit den anderen PostgreSQL-Clients konsistent. **Nachteil:** Optionale Filter, Parameterpositionen und Ergebnisabbildung werden von Hand verwaltet. | **Vorteil:** Die Java-API bietet typisierte Builder für Mapping und Suche. **Nachteil:** Die Builder brauchen viel Code; beim partiellen Update verwendet der aktuelle Client einen generischen `Map`-Cast. |

PostgreSQL nutzt hier seine eingebaute Volltextsuche ohne zusätzliche Erweiterung. Das Beispiel belegt nur die vereinbarten Treffer und deren Reihenfolge, keine allgemeine Gleichheit der Suchanalyse oder Relevanzmodelle.

## Blobs: PostgreSQL `bytea` und RustFS über S3

Code: [Python](../implementations/python/blob/main.py), [Kotlin](../implementations/kotlin/blob/src/main/kotlin/Blob.kt).

| Sprache | PostgreSQL `bytea` | RustFS/S3 |
| --- | --- | --- |
| Python | **Vorteil:** Bytes und Metadaten liegen in einer Tabelle und werden beim Seed gemeinsam in einer Transaktion geschrieben. **Nachteil:** Objektoperationen werden als SQL formuliert; für den Bytebereich `100–199` rechnet der Client auf SQLs einsbasierte Position `101` um. | **Vorteil:** Boto3 bietet direkte Operationen für Upload, Head, Download, Range und Delete. **Nachteil:** Bucket-Erstellung, Auflistung, 404-Fälle, Credentials und Pfadadressierung benötigen Integrationscode. |
| Kotlin | **Vorteil:** `setBytes` und `getBytes` machen `bytea` gut zugänglich; die Seed-Transaktion ist explizit. **Nachteil:** Head, Range und Delete sind selbst definierte SQL-Abfragen mit JDBC-Zuordnung. | **Vorteil:** Das AWS SDK bildet den Dateivertrag mit eigenen S3-Requests ab. **Nachteil:** Client-Konfiguration und Request-Builder sind umfangreich; ein einzelner Objekt-Request ersetzt keine Transaktion über mehrere Objekte. |

Beide Implementierungen prüfen die vollständigen Bytes, Metadaten und den angeforderten Bereich. Ein S3-`ETag` wird nicht als portabler Inhalts-Hash verwendet.

## Übergreifende Einordnung

- **Einheitliche PostgreSQL-Schnittstelle:** Psycopg beziehungsweise JDBC tragen alle fünf Workloads. Dafür wandern fachliche Details in SQL, Casts und bei AGE in eingebettetes Cypher.
- **Fachspezifische APIs:** Neo4j, Qdrant, OpenSearch und S3 benennen Graph-, Vektor-, Such- und Objektoperationen direkt. Ihre Einrichtung und Fehlerfälle sind zusätzliche Client-Aufgaben. CouchDB bildet Dokumente direkt ab, benötigt im vorliegenden Client aber eigene HTTP-Hilfsfunktionen, Index und View.
- **Sprachunterschied:** Python-Dictionaries passen gut zu JSON- und REST-APIs. In Kotlin hängt der Aufwand stark von der Java-API ab: Neo4j bleibt kompakt; Qdrant und OpenSearch benötigen zahlreiche Builder. Auch JDBC ist in Kotlin ausführlicher als Psycopg in Python.
- **Grenze des Urteils:** Die Beispiele nutzen feste, kleine Daten und einfache Einzel-Clients. Sie belegen die Bedienbarkeit der implementierten Pfade, keine allgemeine Rangfolge der Stores oder vollständige Produktionsintegration.
