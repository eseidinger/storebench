import com.fasterxml.jackson.databind.ObjectMapper
import java.nio.file.Files
import java.nio.file.Path
import java.sql.DriverManager
import org.apache.hc.core5.http.HttpHost
import org.opensearch.client.json.jackson.JacksonJsonpMapper
import org.opensearch.client.opensearch.OpenSearchClient
import org.opensearch.client.opensearch._types.Refresh
import org.opensearch.client.opensearch._types.SortOrder
import org.opensearch.client.opensearch._types.FieldValue
import org.opensearch.client.opensearch._types.mapping.Property
import org.opensearch.client.opensearch._types.query_dsl.Operator
import org.opensearch.client.opensearch._types.query_dsl.Query
import org.opensearch.client.opensearch.core.IndexRequest
import org.opensearch.client.opensearch.core.UpdateRequest
import org.opensearch.client.transport.httpclient5.ApacheHttpClient5TransportBuilder

private val root = Path.of("").toAbsolutePath().normalize().resolve("../../..").normalize()
private val mapper = ObjectMapper()
private val data = mapper.readTree(Files.readString(root.resolve("workloads/search/articles.json")))
private val articles = data["articles"].toList()
private val mapping = mapper.readTree(Files.readString(root.resolve("implementations/native/search/opensearch/mapping.json")))
private const val index = "storebench_articles"

private fun check(value: Boolean, message: String) {
    if (!value) error(message)
}

private interface Store : AutoCloseable {
    val name: String
    fun seed()
    fun search(category: String? = null): List<Pair<Int, Double>>
    fun update()
    fun article(): Map<String, String>
    fun count(): Long
}

private class Postgres : Store {
    override val name = "PostgreSQL"
    private val connection = DriverManager.getConnection(
        "jdbc:postgresql://${System.getenv("STOREBENCH_SEARCH_PG_HOST") ?: "127.0.0.1"}:${System.getenv("STOREBENCH_SEARCH_PG_PORT") ?: "5435"}/storebench",
        "storebench", "storebench_local"
    )

    override fun close() = connection.close()

    override fun seed() {
        connection.autoCommit = false
        try {
            connection.createStatement().use {
                it.execute("DROP TABLE IF EXISTS articles")
                it.execute("""CREATE TABLE articles (
                    id integer PRIMARY KEY, title text NOT NULL, body text NOT NULL, category text NOT NULL,
                    search_vector tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', title), 'A') ||
                        setweight(to_tsvector('english', body), 'B')
                    ) STORED
                )""")
            }
            connection.prepareStatement("INSERT INTO articles (id, title, body, category) VALUES (?, ?, ?, ?)").use { statement ->
                for (article in articles) {
                    statement.setInt(1, article["id"].asInt())
                    statement.setString(2, article["title"].asText())
                    statement.setString(3, article["body"].asText())
                    statement.setString(4, article["category"].asText())
                    statement.addBatch()
                }
                check(statement.executeBatch().size == articles.size, "PostgreSQL insert count mismatch")
            }
            connection.createStatement().use {
                it.execute("CREATE INDEX articles_search_idx ON articles USING gin (search_vector)")
                it.execute("CREATE INDEX articles_category_idx ON articles (category)")
            }
            connection.commit()
        } catch (error: Exception) {
            connection.rollback()
            throw error
        } finally {
            connection.autoCommit = true
        }
        println("Kotlin/PostgreSQL: inserted ${articles.size} articles")
    }

    override fun search(category: String?): List<Pair<Int, Double>> {
        val sql = """SELECT id, ts_rank(search_vector, plainto_tsquery('english', ?)) AS rank
            FROM articles WHERE search_vector @@ plainto_tsquery('english', ?)""" +
            (if (category == null) "" else " AND category = ?") + " ORDER BY rank DESC, id ASC LIMIT 10"
        connection.prepareStatement(sql).use { statement ->
            statement.setString(1, data["query"].asText())
            statement.setString(2, data["query"].asText())
            if (category != null) statement.setString(3, category)
            statement.executeQuery().use { rows ->
                val result = mutableListOf<Pair<Int, Double>>()
                while (rows.next()) result.add(rows.getInt(1) to rows.getDouble(2))
                return result
            }
        }
    }

    override fun update() {
        connection.prepareStatement("UPDATE articles SET body = ? WHERE id = ?").use { statement ->
            statement.setString(1, data["update"]["body"].asText())
            statement.setInt(2, data["update"]["id"].asInt())
            check(statement.executeUpdate() == 1, "PostgreSQL update did not affect one article")
        }
    }

    override fun article(): Map<String, String> {
        connection.prepareStatement("SELECT title, body, category FROM articles WHERE id = ?").use { statement ->
            statement.setInt(1, data["update"]["id"].asInt())
            statement.executeQuery().use { rows ->
                check(rows.next(), "PostgreSQL article 5 missing")
                return mapOf("title" to rows.getString(1), "body" to rows.getString(2), "category" to rows.getString(3))
            }
        }
    }

    override fun count(): Long = connection.createStatement().use { statement ->
        statement.executeQuery("SELECT count(*) FROM articles").use { rows ->
            rows.next()
            rows.getLong(1)
        }
    }
}

private class OpenSearchStore : Store {
    override val name = "OpenSearch"
    private val transport = ApacheHttpClient5TransportBuilder.builder(HttpHost("http",
        System.getenv("STOREBENCH_OPENSEARCH_HOST") ?: "127.0.0.1",
        (System.getenv("STOREBENCH_OPENSEARCH_PORT") ?: "9201").toInt()))
        .setMapper(JacksonJsonpMapper()).build()
    private val client = OpenSearchClient(transport)

    override fun close() = transport.close()

    override fun seed() {
        if (client.indices().exists { it.index(index) }.value()) client.indices().delete { it.index(index) }
        val settings = mapping["settings"]
        val properties = mapping["mappings"]["properties"]
        client.indices().create { request -> request.index(index)
            .settings { it.numberOfShards(settings["number_of_shards"].asInt())
                .numberOfReplicas(settings["number_of_replicas"].asInt()) }
            .mappings { m -> m
                .properties("title", Property.of { p -> p.text { t -> t.analyzer(properties["title"]["analyzer"].asText()) } })
                .properties("body", Property.of { p -> p.text { t -> t.analyzer(properties["body"]["analyzer"].asText()) } })
                .properties("category", Property.of { p -> p.keyword { it } }) }
        }
        for (article in articles) {
            val document = mapOf(
                "title" to article["title"].asText(),
                "body" to article["body"].asText(),
                "category" to article["category"].asText()
            )
            client.index(IndexRequest.Builder<Map<String, String>>().index(index)
                .id(article["id"].asText()).document(document).build())
        }
        client.indices().refresh { it.index(index) }
        println("Kotlin/OpenSearch: inserted ${articles.size} articles")
    }

    override fun search(category: String?): List<Pair<Int, Double>> {
        val multi = Query.of { q -> q.multiMatch { m -> m
            .query(data["query"].asText()).fields("title^3", "body").operator(Operator.And) } }
        val query = if (category == null) multi else Query.of { q -> q.bool { b -> b
            .must(multi)
            .filter(Query.of { f -> f.term { t -> t.field("category").value(FieldValue.of(category)) } }) } }
        val response = client.search({ request -> request.index(index).size(10).query(query)
            .sort { s -> s.score { it.order(SortOrder.Desc) } }
            .sort { s -> s.field { it.field("_id").order(SortOrder.Asc) } }
        }, Map::class.java)
        return response.hits().hits().map { (it.id()?.toInt() ?: error("OpenSearch hit has no ID")) to (it.score() ?: 0.0) }
    }

    override fun update() {
        val request = UpdateRequest.Builder<Map<String, String>, Map<String, String>>()
            .index(index).id(data["update"]["id"].asText())
            .doc(mapOf("body" to data["update"]["body"].asText()))
            .refresh(Refresh.WaitFor).build()
        @Suppress("UNCHECKED_CAST")
        val mapClass = Map::class.java as Class<Map<String, String>>
        val response = client.update(request, mapClass)
        check(response.result().jsonValue() == "updated", "OpenSearch update failed: ${response.result()}")
    }

    override fun article(): Map<String, String> {
        val response = client.get({ it.index(index).id(data["update"]["id"].asText()) }, Map::class.java)
        check(response.found(), "OpenSearch article 5 missing")
        val source = response.source() ?: error("OpenSearch article 5 has no source")
        return mapOf("title" to source["title"].toString(), "body" to source["body"].toString(),
            "category" to source["category"].toString())
    }

    override fun count(): Long = client.count { it.index(index) }.count()
}

private fun run(store: Store) {
    val before = store.search()
    val guideBefore = store.search("guide")
    check(before.map { it.first } == listOf(6) && guideBefore.isEmpty(),
        "${store.name} before-update results mismatch; seed before run")
    println("Kotlin/${store.name} before update: $before")
    println("Kotlin/${store.name} guide before update: $guideBefore")
    store.update()
    val after = store.search()
    val guideAfter = store.search("guide")
    check(after.map { it.first } == listOf(6, 5) && guideAfter.map { it.first } == listOf(5),
        "${store.name} after-update results mismatch")
    println("Kotlin/${store.name} after update: $after")
    println("Kotlin/${store.name} guide after update: $guideAfter")
}

private fun verify(store: Store) {
    check(store.count() == articles.size.toLong(), "${store.name} article count mismatch")
    check(store.search().map { it.first } == listOf(6, 5), "${store.name} ranked results mismatch")
    check(store.search("guide").map { it.first } == listOf(5), "${store.name} filtered results mismatch")
    val article = store.article()
    val original = articles.first { it["id"].asInt() == data["update"]["id"].asInt() }
    check(article["title"] == original["title"].asText() && article["category"] == original["category"].asText(),
        "${store.name} title or category changed")
    check(article["body"] == data["update"]["body"].asText(), "${store.name} body update missing")
    println("Kotlin/${store.name} search check passed")
}

fun main(args: Array<String>) {
    check(args.size == 2 && args[0] in listOf("seed", "run", "verify") && args[1] in listOf("postgres", "opensearch", "both"),
        "Usage: search {seed|run|verify} {postgres|opensearch|both}")
    for (target in (if (args[1] == "both") listOf("postgres", "opensearch") else listOf(args[1]))) {
        val store: Store = if (target == "postgres") Postgres() else OpenSearchStore()
        store.use { client ->
            when (args[0]) {
                "seed" -> client.seed()
                "run" -> run(client)
                "verify" -> verify(client)
            }
        }
    }
}
