\set ON_ERROR_STOP on
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
-- Direct dependencies of app.
SELECT name::text FROM cypher('dependencies', $$ MATCH (:Package {name: 'app'})-[:DEPENDS_ON]->(p:Package) RETURN p.name ORDER BY p.name $$) AS (name agtype);
-- Distinct transitive dependencies, paths of length 1..4.
SELECT name::text FROM cypher('dependencies', $$ MATCH (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(p:Package) RETURN DISTINCT p.name ORDER BY p.name $$) AS (name agtype);
-- Packages affected by a change to core (reverse reachability).
SELECT name::text FROM cypher('dependencies', $$ MATCH (p:Package)-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN DISTINCT p.name ORDER BY p.name $$) AS (name agtype);
-- All paths from app to core with at most four edges; duplicate destinations are meaningful here.
SELECT path FROM cypher('dependencies', $$ MATCH path = (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN path $$) AS (path agtype);
