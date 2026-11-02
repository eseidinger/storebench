import com.fasterxml.jackson.databind.ObjectMapper
import java.nio.file.Files
import java.nio.file.Path
import java.sql.DriverManager
import io.qdrant.client.ConditionFactory.matchKeyword
import io.qdrant.client.PointIdFactory.id
import io.qdrant.client.QueryFactory.nearest
import io.qdrant.client.ValueFactory.value
import io.qdrant.client.VectorsFactory.vectors
import io.qdrant.client.QdrantClient
import io.qdrant.client.QdrantGrpcClient
import io.qdrant.client.grpc.Collections.Distance
import io.qdrant.client.grpc.Collections.VectorParams
import io.qdrant.client.grpc.Common.Filter
import io.qdrant.client.grpc.Points.PointStruct
import io.qdrant.client.grpc.Points.PointVectors
import io.qdrant.client.grpc.Points.QueryPoints
import io.qdrant.client.grpc.Points.SearchParams
import io.qdrant.client.grpc.Points.UpdatePointVectors
import io.qdrant.client.grpc.Points.UpdateStatus
import io.qdrant.client.grpc.Points.UpsertPoints

private val root = Path.of("").toAbsolutePath().normalize().resolve("../../..").normalize()
private val data = ObjectMapper().readTree(Files.readString(root.resolve("workloads/vector/documents.json")))
private val documents = data["documents"].toList()
private const val collection = "storebench_documents"

private fun check(value: Boolean, message: String) {
    if (!value) error(message)
}

private fun vectorText(values: List<Double>) = values.joinToString(",", "[", "]")
private fun floats(values: List<Double>) = values.map { it.toFloat() }
private fun queryVector() = data["query"].map { it.asDouble() }
private fun updatedVector() = data["update"]["vector"].map { it.asDouble() }

private interface Store : AutoCloseable {
    val name: String
    fun seed()
    fun search(limit: Int, category: String? = null): List<Pair<Int, Double>>
    fun update()
    fun document(): Map<String, String>
    fun count(): Long
}

private class Postgres : Store {
    override val name = "PostgreSQL"
    private val connection = DriverManager.getConnection(
        "jdbc:postgresql://${System.getenv("STOREBENCH_VECTOR_PG_HOST") ?: "127.0.0.1"}:${System.getenv("STOREBENCH_VECTOR_PG_PORT") ?: "5434"}/storebench",
        "storebench", "storebench_local"
    )

    override fun close() = connection.close()

    override fun seed() {
        connection.createStatement().use { it.execute("CREATE EXTENSION IF NOT EXISTS vector") }
        connection.autoCommit = false
        try {
            connection.createStatement().use {
                it.execute("DROP TABLE IF EXISTS documents")
                it.execute("CREATE TABLE documents (id integer PRIMARY KEY, title text NOT NULL, category text NOT NULL, embedding vector(${data["dimension"].asInt()}) NOT NULL)")
            }
            connection.prepareStatement("INSERT INTO documents (id, title, category, embedding) VALUES (?, ?, ?, ?::vector)").use { statement ->
                for (document in documents) {
                    statement.setInt(1, document["id"].asInt())
                    statement.setString(2, document["title"].asText())
                    statement.setString(3, document["category"].asText())
                    statement.setString(4, vectorText(document["vector"].map { it.asDouble() }))
                    statement.addBatch()
                }
                check(statement.executeBatch().size == documents.size, "PostgreSQL insert count mismatch")
            }
            connection.createStatement().use { it.execute("CREATE INDEX documents_category_idx ON documents (category)") }
            connection.commit()
        } catch (error: Exception) {
            connection.rollback()
            throw error
        } finally {
            connection.autoCommit = true
        }
        println("Kotlin/PostgreSQL: inserted ${documents.size} documents")
    }

    override fun search(limit: Int, category: String?): List<Pair<Int, Double>> {
        val sql = "SELECT id, embedding <=> ?::vector AS distance FROM documents" +
            (if (category == null) "" else " WHERE category = ?") +
            " ORDER BY embedding <=> ?::vector, id LIMIT ?"
        connection.prepareStatement(sql).use { statement ->
            val vector = vectorText(queryVector())
            statement.setString(1, vector)
            var index = 2
            if (category != null) statement.setString(index++, category)
            statement.setString(index++, vector)
            statement.setInt(index, limit)
            statement.executeQuery().use { rows ->
                val result = mutableListOf<Pair<Int, Double>>()
                while (rows.next()) result.add(rows.getInt(1) to rows.getDouble(2))
                return result
            }
        }
    }

    override fun update() {
        connection.prepareStatement("UPDATE documents SET embedding = ?::vector WHERE id = ?").use { statement ->
            statement.setString(1, vectorText(updatedVector()))
            statement.setInt(2, data["update"]["id"].asInt())
            check(statement.executeUpdate() == 1, "PostgreSQL update did not affect one document")
        }
    }

    override fun document(): Map<String, String> {
        connection.prepareStatement("SELECT title, category FROM documents WHERE id = ?").use { statement ->
            statement.setInt(1, data["update"]["id"].asInt())
            statement.executeQuery().use { rows ->
                check(rows.next(), "PostgreSQL document 3 missing")
                return mapOf("title" to rows.getString(1), "category" to rows.getString(2))
            }
        }
    }

    override fun count(): Long = connection.createStatement().use { statement ->
        statement.executeQuery("SELECT count(*) FROM documents").use { rows ->
            rows.next()
            rows.getLong(1)
        }
    }
}

private class Qdrant : Store {
    override val name = "Qdrant"
    private val client = QdrantClient(QdrantGrpcClient.newBuilder(
        System.getenv("STOREBENCH_QDRANT_HOST") ?: "127.0.0.1",
        (System.getenv("STOREBENCH_QDRANT_GRPC_PORT") ?: "6335").toInt(), false).build())

    override fun close() = client.close()

    override fun seed() {
        if (client.collectionExistsAsync(collection).get()) {
            check(client.deleteCollectionAsync(collection).get().result, "Qdrant collection deletion failed")
        }
        check(data["distance"].asText() == "Cosine", "Expected cosine distance")
        val parameters = VectorParams.newBuilder().setSize(data["dimension"].asLong()).setDistance(Distance.Cosine).build()
        check(client.createCollectionAsync(collection, parameters).get().result, "Qdrant collection creation failed")
        val points = documents.map { document ->
            PointStruct.newBuilder().setId(id(document["id"].asLong()))
                .setVectors(vectors(floats(document["vector"].map { it.asDouble() })))
                .putPayload("title", value(document["title"].asText()))
                .putPayload("category", value(document["category"].asText()))
                .build()
        }
        val request = UpsertPoints.newBuilder().setCollectionName(collection).setWait(true).addAllPoints(points).build()
        check(client.upsertAsync(request).get().status == UpdateStatus.Completed, "Qdrant upsert failed")
        println("Kotlin/Qdrant: inserted ${points.size} documents")
    }

    override fun search(limit: Int, category: String?): List<Pair<Int, Double>> {
        val request = QueryPoints.newBuilder().setCollectionName(collection).setLimit(limit.toLong())
            .setQuery(nearest(floats(queryVector()))).setParams(SearchParams.newBuilder().setExact(true))
        if (category != null) request.setFilter(Filter.newBuilder().addMust(matchKeyword("category", category)))
        return client.queryAsync(request.build()).get().map { it.id.num.toInt() to it.score.toDouble() }
    }

    override fun update() {
        val point = PointVectors.newBuilder().setId(id(data["update"]["id"].asLong()))
            .setVectors(vectors(floats(updatedVector()))).build()
        val request = UpdatePointVectors.newBuilder().setCollectionName(collection).setWait(true).addPoints(point).build()
        check(client.updateVectorsAsync(request).get().status == UpdateStatus.Completed, "Qdrant vector update failed")
    }

    override fun document(): Map<String, String> {
        val points = client.retrieveAsync(collection, listOf(id(data["update"]["id"].asLong())), true, false, null).get()
        check(points.size == 1, "Qdrant document 3 missing")
        return points[0].payloadMap.mapValues { it.value.stringValue }
    }

    override fun count(): Long = client.countAsync(collection, null, true).get()
}

private fun run(store: Store) {
    println("Kotlin/${store.name} top-3: ${store.search(3)}")
    println("Kotlin/${store.name} guide top-2: ${store.search(2, "guide")}")
    store.update()
    println("Kotlin/${store.name} after update: ${store.search(3)}")
}

private fun verify(store: Store) {
    check(store.count() == documents.size.toLong(), "${store.name} document count mismatch")
    check(store.search(3).map { it.first } == listOf(1, 3, 2), "${store.name} updated top-k mismatch")
    check(store.search(2, "guide").map { it.first } == listOf(1, 6), "${store.name} filtered top-k mismatch")
    val original = documents.first { it["id"].asInt() == data["update"]["id"].asInt() }
    val metadata = store.document()
    check(metadata["title"] == original["title"].asText() && metadata["category"] == original["category"].asText(),
        "${store.name} metadata changed")
    println("Kotlin/${store.name} vector check passed")
}

fun main(args: Array<String>) {
    check(args.size == 2 && args[0] in listOf("seed", "run", "verify") && args[1] in listOf("postgres", "qdrant", "both"),
        "Usage: vector {seed|run|verify} {postgres|qdrant|both}")
    for (target in (if (args[1] == "both") listOf("postgres", "qdrant") else listOf(args[1]))) {
        val store: Store = if (target == "postgres") Postgres() else Qdrant()
        store.use { client ->
            when (args[0]) {
                "seed" -> client.seed()
                "run" -> run(client)
                "verify" -> verify(client)
            }
        }
    }
}
