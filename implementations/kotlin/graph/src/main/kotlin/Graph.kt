import com.fasterxml.jackson.databind.ObjectMapper
import java.nio.file.Files
import java.nio.file.Path
import java.sql.DriverManager
import org.neo4j.driver.AuthTokens
import org.neo4j.driver.GraphDatabase

private val root = Path.of("").toAbsolutePath().normalize().resolve("../../..").normalize()
private val fixture = ObjectMapper().readTree(Files.readString(root.resolve("workloads/graph/packages.json")))
private val packages = fixture["packages"].map { it.asText() }
private val dependencies = fixture["dependencies"].map { it[0].asText() to it[1].asText() }

private data class Case(val name: String, val cypher: String, val expected: List<String>)
private val cases = listOf(
    Case("nodes", "MATCH (p:Package) RETURN count(p)", listOf("6")),
    Case("edges", "MATCH ()-[r:DEPENDS_ON]->() RETURN count(r)", listOf("6")),
    Case("direct", "MATCH (:Package {name: 'app'})-[:DEPENDS_ON]->(p:Package) RETURN p.name", listOf("api", "web")),
    Case("transitive", "MATCH (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(p:Package) RETURN DISTINCT p.name", listOf("api", "auth", "core", "ui", "web")),
    Case("impact", "MATCH (p:Package)-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN DISTINCT p.name", listOf("api", "app", "auth", "web")),
    Case("paths", "MATCH path = (:Package {name: 'app'})-[:DEPENDS_ON*1..4]->(:Package {name: 'core'}) RETURN length(path)", listOf("2", "3"))
)

private fun check(value: Boolean, message: String) {
    if (!value) error(message)
}

private interface Store : AutoCloseable {
    val name: String
    fun seed()
    fun query(cypher: String): List<String>
}

private class Age : Store {
    override val name = "AGE"
    private val connection = DriverManager.getConnection(
        "jdbc:postgresql://${System.getenv("STOREBENCH_AGE_HOST") ?: "127.0.0.1"}:${System.getenv("STOREBENCH_AGE_PORT") ?: "5455"}/storebench",
        "storebench", "storebench_local"
    )

    init {
        connection.createStatement().use {
            it.execute("CREATE EXTENSION IF NOT EXISTS age")
            it.execute("LOAD 'age'")
            it.execute("SET search_path = ag_catalog, \"\u0024user\", public")
        }
    }

    override fun close() = connection.close()

    private fun sql(cypher: String, output: Boolean): List<String> {
        check("\u0024\u0024" !in cypher, "Invalid Cypher delimiter")
        val projection = if (output) "value::text" else "*"
        connection.createStatement().use { statement ->
            statement.executeQuery("SELECT $projection FROM cypher('dependencies', \u0024\u0024 $cypher \u0024\u0024) AS (value agtype)").use { rows ->
                val result = mutableListOf<String>()
                if (output) while (rows.next()) result.add(rows.getString(1).trim('"'))
                return result.sorted()
            }
        }
    }

    override fun seed() {
        check(packages.distinct().size == packages.size && packages.all { it.matches(Regex("[A-Za-z_][A-Za-z_0-9]*")) }, "Invalid package names")
        check(dependencies.all { it.first in packages && it.second in packages }, "Unknown dependency endpoint")
        connection.createStatement().use {
            it.execute("SELECT drop_graph('dependencies', true) WHERE EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'dependencies')")
            it.execute("SELECT create_graph('dependencies')")
        }
        for (name in packages) sql("CREATE (:Package {name: '$name'})", false)
        for ((source, target) in dependencies) sql("MATCH (a:Package {name: '$source'}), (b:Package {name: '$target'}) CREATE (a)-[:DEPENDS_ON]->(b)", false)
        println("Kotlin/AGE: inserted ${packages.size} packages and ${dependencies.size} dependencies")
    }

    override fun query(cypher: String) = sql(cypher, true)
}

private class Neo4j : Store {
    override val name = "Neo4j"
    private val driver = GraphDatabase.driver(
        System.getenv("STOREBENCH_NEO4J_URI") ?: "bolt://127.0.0.1:7688",
        AuthTokens.basic("neo4j", "storebench_local")
    )

    init { driver.verifyConnectivity() }
    override fun close() = driver.close()

    override fun seed() {
        driver.session().use { session ->
            session.run("MATCH (n) DETACH DELETE n").consume()
            session.run("CREATE CONSTRAINT package_name IF NOT EXISTS FOR (p:Package) REQUIRE p.name IS UNIQUE").consume()
            for (name in packages) session.run("CREATE (:Package {name: \u0024name})", mapOf("name" to name)).consume()
            for ((source, target) in dependencies) {
                session.run("MATCH (a:Package {name: \u0024source}), (b:Package {name: \u0024target}) CREATE (a)-[:DEPENDS_ON]->(b)",
                    mapOf("source" to source, "target" to target)).consume()
            }
        }
        println("Kotlin/Neo4j: inserted ${packages.size} packages and ${dependencies.size} dependencies")
    }

    override fun query(cypher: String): List<String> = driver.session().use { session ->
        session.run(cypher).list { it[0].asObject().toString() }.sorted()
    }
}

fun main(args: Array<String>) {
    check(args.size == 2 && args[0] in listOf("seed", "run", "verify") && args[1] in listOf("age", "neo4j", "both"),
        "Usage: graph {seed|run|verify} {age|neo4j|both}")
    for (target in (if (args[1] == "both") listOf("age", "neo4j") else listOf(args[1]))) {
        val store: Store = if (target == "age") Age() else Neo4j()
        store.use { client ->
            if (args[0] == "seed") client.seed()
            else for (case in cases) {
                val actual = client.query(case.cypher)
                if (args[0] == "verify") {
                    check(actual == case.expected, "${client.name} ${case.name}: expected ${case.expected}, got $actual")
                    println("Kotlin/${client.name} ${case.name}: OK")
                } else println("Kotlin/${client.name} ${case.name}: $actual")
            }
        }
    }
}
