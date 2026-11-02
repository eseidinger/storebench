\set ON_ERROR_STOP on
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT drop_graph('dependencies', true) WHERE EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'dependencies');
SELECT create_graph('dependencies');
SELECT * FROM cypher('dependencies', $$ CREATE (:Package {name: 'app'}) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ CREATE (:Package {name: 'api'}) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ CREATE (:Package {name: 'web'}) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ CREATE (:Package {name: 'auth'}) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ CREATE (:Package {name: 'core'}) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ CREATE (:Package {name: 'ui'}) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ MATCH (a:Package {name: 'app'}), (b:Package {name: 'api'}) CREATE (a)-[:DEPENDS_ON]->(b) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ MATCH (a:Package {name: 'app'}), (b:Package {name: 'web'}) CREATE (a)-[:DEPENDS_ON]->(b) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ MATCH (a:Package {name: 'api'}), (b:Package {name: 'auth'}) CREATE (a)-[:DEPENDS_ON]->(b) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ MATCH (a:Package {name: 'auth'}), (b:Package {name: 'core'}) CREATE (a)-[:DEPENDS_ON]->(b) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ MATCH (a:Package {name: 'web'}), (b:Package {name: 'core'}) CREATE (a)-[:DEPENDS_ON]->(b) $$) AS (result agtype);
SELECT * FROM cypher('dependencies', $$ MATCH (a:Package {name: 'web'}), (b:Package {name: 'ui'}) CREATE (a)-[:DEPENDS_ON]->(b) $$) AS (result agtype);
