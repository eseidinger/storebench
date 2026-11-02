import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Path
import java.sql.Connection
import java.sql.DriverManager
import java.util.Base64

private val mapper = ObjectMapper()
private val root: Path = Path.of("").toAbsolutePath().normalize().resolve("../../..").normalize()
private val products: List<JsonNode> = mapper.readTree(Files.readString(root.resolve("workloads/documents/products.json"))).toList()
private val expectedIds = listOf("p001", "p003", "p005")
private val expectedTotals = mapOf("apparel" to (2L to 22800L), "footwear" to (2L to 24800L), "gear" to (2L to 19800L))

private fun check(value: Boolean, message: String) {
    if (!value) error(message)
}

private interface Store : AutoCloseable {
    fun seed()
    fun run()
    fun verify()
    override fun close() {}
}

private class Postgres : Store {
    private val connection: Connection = DriverManager.getConnection(
        "jdbc:postgresql://${System.getenv("STOREBENCH_PG_HOST") ?: "127.0.0.1"}:${System.getenv("STOREBENCH_PG_PORT") ?: "5433"}/storebench",
        "storebench", "storebench_local"
    )

    override fun close() = connection.close()

    override fun seed() {
        connection.autoCommit = false
        try {
            connection.createStatement().use { statement ->
                statement.execute("DROP TABLE IF EXISTS products")
                statement.execute("CREATE TABLE products (id text PRIMARY KEY, doc jsonb NOT NULL)")
            }
            connection.prepareStatement("INSERT INTO products (id, doc) VALUES (?, ?::jsonb)").use { statement ->
                for (product in products) {
                    statement.setString(1, product["id"].asText())
                    statement.setString(2, product.toString())
                    statement.addBatch()
                }
                check(statement.executeBatch().size == products.size, "Insert count mismatch")
            }
            connection.createStatement().use { statement ->
                statement.execute("CREATE INDEX products_category_idx ON products ((doc->>'category'))")
                statement.execute("CREATE INDEX products_attributes_gin_idx ON products USING gin ((doc->'attributes'))")
            }
            connection.commit()
        } catch (error: Exception) {
            connection.rollback()
            throw error
        } finally {
            connection.autoCommit = true
        }
        println("Kotlin/PostgreSQL: inserted ${products.size} products")
    }

    private fun product(id: String): JsonNode {
        connection.prepareStatement("SELECT doc::text FROM products WHERE id = ?").use { statement ->
            statement.setString(1, id)
            statement.executeQuery().use { rows ->
                check(rows.next(), "Missing product $id")
                return mapper.readTree(rows.getString(1))
            }
        }
    }

    private fun filtered(): List<String> {
        connection.prepareStatement("SELECT id FROM products WHERE doc->'attributes' @> ?::jsonb ORDER BY id").use { statement ->
            statement.setString(1, "{\"color\":\"blue\",\"waterproof\":true}")
            statement.executeQuery().use { rows ->
                val ids = mutableListOf<String>()
                while (rows.next()) ids.add(rows.getString(1))
                return ids
            }
        }
    }

    private fun totals(): Map<String, Pair<Long, Long>> {
        connection.createStatement().use { statement ->
            statement.executeQuery("SELECT doc->>'category', count(*), sum((doc->>'price_cents')::integer) FROM products GROUP BY 1").use { rows ->
                val result = mutableMapOf<String, Pair<Long, Long>>()
                while (rows.next()) result[rows.getString(1)] = rows.getLong(2) to rows.getLong(3)
                return result
            }
        }
    }

    override fun run() {
        println("product: ${product("p001")}")
        println("blue waterproof: ${filtered()}")
        connection.prepareStatement("UPDATE products SET doc = jsonb_set(doc, '{attributes,waterproof}', 'true'::jsonb) WHERE id = ?").use { statement ->
            statement.setString(1, "p002")
            check(statement.executeUpdate() == 1, "Expected one updated product")
        }
        println("category totals: ${totals()}")
    }

    override fun verify() {
        connection.createStatement().use { statement ->
            statement.executeQuery("SELECT count(*) FROM products").use { rows ->
                rows.next()
                check(rows.getInt(1) == 6, "Expected six products")
            }
        }
        check(product("p001")["name"].asText() == "Trail Jacket", "Lookup mismatch")
        check(filtered() == expectedIds, "Nested filter mismatch")
        val attributes = product("p002")["attributes"]
        check(attributes["color"].asText() == "black" && attributes["size"].asText() == "L" && attributes["waterproof"].asBoolean() && attributes.size() == 3, "Update mismatch")
        check(totals() == expectedTotals, "Category totals mismatch")
        println("Kotlin/PostgreSQL documents check passed")
    }
}

private class CouchDB : Store {
    private val server = System.getenv("STOREBENCH_COUCH_URL") ?: "http://127.0.0.1:5985"
    private val client = HttpClient.newHttpClient()
    private val authorization = "Basic " + Base64.getEncoder().encodeToString("storebench:storebench_local".toByteArray())

    private fun request(method: String, path: String, body: JsonNode? = null, missingOk: Boolean = false): JsonNode? {
        val builder = HttpRequest.newBuilder(URI.create(server + path))
            .header("Authorization", authorization)
            .header("Content-Type", "application/json")
        val publisher = body?.let { HttpRequest.BodyPublishers.ofString(it.toString()) } ?: HttpRequest.BodyPublishers.noBody()
        val response = client.send(builder.method(method, publisher).build(), HttpResponse.BodyHandlers.ofString())
        if (missingOk && response.statusCode() == 404) return null
        check(response.statusCode() in 200..299, "CouchDB HTTP ${response.statusCode()}: ${response.body()}")
        return mapper.readTree(response.body())
    }

    private fun required(method: String, path: String, body: JsonNode? = null): JsonNode =
        request(method, path, body) ?: error("Missing CouchDB response for $path")

    override fun seed() {
        val state = required("GET", "/_cluster_setup")["state"].asText()
        if (state != "cluster_finished") {
            val setup = mapper.createObjectNode()
                .put("action", "enable_single_node").put("bind_address", "0.0.0.0")
                .put("username", "storebench").put("password", "storebench_local")
            check(required("POST", "/_cluster_setup", setup)["ok"].asBoolean(), "CouchDB setup failed")
        }
        request("DELETE", "/products", missingOk = true)
        required("PUT", "/products")
        val docs = mapper.createArrayNode()
        for (product in products) {
            val document = product.deepCopy<ObjectNode>()
            document.put("_id", product["id"].asText())
            docs.add(document)
        }
        val bulk = mapper.createObjectNode().set<JsonNode>("docs", docs)
        val results = required("POST", "/products/_bulk_docs", bulk)
        check(results.size() == products.size && results.all { it["error"] == null }, "Bulk insert failed: $results")
        val native = root.resolve("implementations/native/documents/couchdb")
        required("POST", "/products/_index", mapper.readTree(Files.readString(native.resolve("attributes_index.json"))))
        required("PUT", "/products/_design/catalog", mapper.readTree(Files.readString(native.resolve("category_totals.json"))))
        println("Kotlin/CouchDB: inserted ${products.size} products")
    }

    private fun product(id: String): JsonNode = required("GET", "/products/$id")

    private fun filtered(): List<String> {
        val selector = mapper.createObjectNode().put("attributes.color", "blue").put("attributes.waterproof", true)
        val query = mapper.createObjectNode().set<JsonNode>("selector", selector) as ObjectNode
        query.set<JsonNode>("fields", mapper.createArrayNode().add("id"))
        query.put("limit", 100)
        query.put("use_index", "attributes_color_waterproof")
        return required("POST", "/products/_find", query)["docs"].map { it["id"].asText() }.sorted()
    }

    private fun totals(): Map<String, Pair<Long, Long>> =
        required("GET", "/products/_design/catalog/_view/category_totals?group=true")["rows"].associate {
            it["key"].asText() to (it["value"]["count"].asLong() to it["value"]["sum"].asLong())
        }

    override fun run() {
        println("product: ${product("p001")}")
        println("blue waterproof: ${filtered()}")
        val updated = product("p002").deepCopy<ObjectNode>()
        (updated["attributes"] as ObjectNode).put("waterproof", true)
        check(required("PUT", "/products/p002", updated)["ok"].asBoolean(), "Update failed")
        println("category totals: ${totals()}")
    }

    override fun verify() {
        val rows = required("GET", "/products/_all_docs")["rows"]
        check(rows.count { !it["id"].asText().startsWith("_design/") } == 6, "Expected six products")
        check(product("p001")["name"].asText() == "Trail Jacket", "Lookup mismatch")
        check(filtered() == expectedIds, "Nested filter mismatch")
        val attributes = product("p002")["attributes"]
        check(attributes["color"].asText() == "black" && attributes["size"].asText() == "L" && attributes["waterproof"].asBoolean() && attributes.size() == 3, "Update mismatch")
        check(totals() == expectedTotals, "Category totals mismatch")
        println("Kotlin/CouchDB documents check passed")
    }
}

fun main(args: Array<String>) {
    check(args.size == 2 && args[0] in listOf("seed", "run", "verify") && args[1] in listOf("postgres", "couchdb", "both"),
        "Usage: documents {seed|run|verify} {postgres|couchdb|both}")
    val targets = if (args[1] == "both") listOf("postgres", "couchdb") else listOf(args[1])
    for (target in targets) {
        val store: Store = if (target == "postgres") Postgres() else CouchDB()
        store.use {
            when (args[0]) {
                "seed" -> it.seed()
                "run" -> it.run()
                "verify" -> it.verify()
            }
        }
    }
}
