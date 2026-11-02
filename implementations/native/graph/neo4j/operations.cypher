// Direct dependencies of app.
MATCH (:Package {name: 'app'})-[:DEPENDS_ON]->(p:Package) RETURN p.name AS name ORDER BY name;
// Distinct transitive dependencies, paths of length 1..4.
MATCH (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(p:Package) RETURN DISTINCT p.name AS name ORDER BY name;
// Packages affected by a change to core (reverse reachability).
MATCH (p:Package)-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN DISTINCT p.name AS name ORDER BY name;
// All paths from app to core with at most four edges.
MATCH path = (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN [n IN nodes(path) | n.name] AS package_path ORDER BY package_path;
