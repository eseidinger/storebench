import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import java.nio.charset.StandardCharsets.UTF_8
import java.security.MessageDigest
import java.sql.DriverManager
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider
import software.amazon.awssdk.core.sync.RequestBody
import software.amazon.awssdk.regions.Region
import software.amazon.awssdk.services.s3.S3Client
import software.amazon.awssdk.services.s3.S3Configuration
import software.amazon.awssdk.services.s3.model.S3Exception

private val root = Path.of("").toAbsolutePath().normalize().resolve("../../..").normalize()
private val manifest = ObjectMapper().readTree(Files.readString(root.resolve("workloads/blob/manifest.json")))
private val objects = manifest["objects"].toList()
private val bucket = manifest["bucket"].asText()

private fun check(value: Boolean, message: String) {
    if (!value) error(message)
}

private fun payload(item: JsonNode): ByteArray = when (item["kind"].asText()) {
    "text" -> item["value"].asText().toByteArray(UTF_8)
    "empty" -> byteArrayOf()
    "sha256_pattern" -> {
        val seed = MessageDigest.getInstance("SHA-256").digest("StoreBench blob pattern v1".toByteArray(UTF_8))
        ByteArray(item["size"].asInt()) { seed[it % seed.size] }
    }
    else -> error("Unknown blob kind: ${item["kind"]}")
}

private fun digest(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
    .digest(bytes).joinToString("") { (it.toInt() and 0xff).toString(16).padStart(2, '0') }

private interface Store : AutoCloseable {
    val name: String
    fun seed()
    fun keys(): List<String>
    fun head(key: String): Triple<Long, String, String>?
    fun get(key: String, span: Pair<Int, Int>? = null): ByteArray?
    fun overwrite(item: JsonNode)
    fun delete(key: String)
}

private class Postgres : Store {
    override val name = "PostgreSQL"
    private val connection = DriverManager.getConnection(
        "jdbc:postgresql://${System.getenv("STOREBENCH_BLOB_PG_HOST") ?: "127.0.0.1"}:${System.getenv("STOREBENCH_BLOB_PG_PORT") ?: "5436"}/storebench",
        "storebench", "storebench_local"
    )

    override fun close() = connection.close()

    override fun seed() {
        connection.autoCommit = false
        try {
            connection.createStatement().use {
                it.execute("DROP TABLE IF EXISTS blobs")
                it.execute("CREATE TABLE blobs (key text PRIMARY KEY, data bytea NOT NULL, content_type text NOT NULL, owner_name text NOT NULL)")
            }
            connection.prepareStatement("INSERT INTO blobs (key, data, content_type, owner_name) VALUES (?, ?, ?, ?)").use { statement ->
                for (item in objects) {
                    statement.setString(1, item["key"].asText())
                    statement.setBytes(2, payload(item))
                    statement.setString(3, item["content_type"].asText())
                    statement.setString(4, item["owner"].asText())
                    statement.addBatch()
                }
                check(statement.executeBatch().size == objects.size, "PostgreSQL insert count mismatch")
            }
            connection.commit()
        } catch (error: Exception) {
            connection.rollback()
            throw error
        } finally {
            connection.autoCommit = true
        }
        println("Kotlin/PostgreSQL: inserted ${objects.size} objects")
    }

    override fun keys(): List<String> = connection.createStatement().use { statement ->
        statement.executeQuery("SELECT key FROM blobs ORDER BY key").use { rows ->
            val keys = mutableListOf<String>()
            while (rows.next()) keys.add(rows.getString(1))
            keys
        }
    }

    override fun head(key: String): Triple<Long, String, String>? =
        connection.prepareStatement("SELECT octet_length(data), content_type, owner_name FROM blobs WHERE key = ?").use { statement ->
            statement.setString(1, key)
            statement.executeQuery().use { rows ->
                if (rows.next()) Triple(rows.getLong(1), rows.getString(2), rows.getString(3)) else null
            }
        }

    override fun get(key: String, span: Pair<Int, Int>?): ByteArray? {
        val sql = if (span == null) "SELECT data FROM blobs WHERE key = ?"
            else "SELECT substring(data FROM ? FOR ?) FROM blobs WHERE key = ?"
        connection.prepareStatement(sql).use { statement ->
            if (span == null) statement.setString(1, key)
            else {
                statement.setInt(1, span.first + 1)
                statement.setInt(2, span.second - span.first + 1)
                statement.setString(3, key)
            }
            statement.executeQuery().use { rows -> return if (rows.next()) rows.getBytes(1) else null }
        }
    }

    override fun overwrite(item: JsonNode) {
        connection.prepareStatement("UPDATE blobs SET data = ?, content_type = ?, owner_name = ? WHERE key = ?").use { statement ->
            statement.setBytes(1, payload(item))
            statement.setString(2, item["content_type"].asText())
            statement.setString(3, item["owner"].asText())
            statement.setString(4, item["key"].asText())
            check(statement.executeUpdate() == 1, "PostgreSQL overwrite did not affect one object")
        }
    }

    override fun delete(key: String) {
        connection.prepareStatement("DELETE FROM blobs WHERE key = ?").use { statement ->
            statement.setString(1, key)
            check(statement.executeUpdate() == 1, "PostgreSQL delete did not affect one object")
        }
    }
}

private class RustFS : Store {
    override val name = "RustFS"
    private val client = S3Client.builder()
        .endpointOverride(URI.create(System.getenv("STOREBENCH_RUSTFS_ENDPOINT") ?: "http://127.0.0.1:9002"))
        .region(Region.US_EAST_1)
        .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create(
            "storebench_local", "storebench_secret_local")))
        .serviceConfiguration(S3Configuration.builder().pathStyleAccessEnabled(true).build())
        .build()

    override fun close() = client.close()

    override fun seed() {
        try {
            client.headBucket { it.bucket(bucket) }
        } catch (error: S3Exception) {
            if (error.statusCode() != 404) throw error
            client.createBucket { it.bucket(bucket) }
        }
        for (key in keys()) delete(key)
        for (item in objects) put(item)
        println("Kotlin/RustFS: uploaded ${objects.size} objects")
    }

    private fun put(item: JsonNode) {
        client.putObject({ request -> request.bucket(bucket).key(item["key"].asText())
            .contentType(item["content_type"].asText()).metadata(mapOf("owner" to item["owner"].asText())) },
            RequestBody.fromBytes(payload(item)))
    }

    override fun keys(): List<String> = client.listObjectsV2Paginator { it.bucket(bucket) }
        .contents().map { it.key() }.sorted()

    override fun head(key: String): Triple<Long, String, String>? {
        try {
            val result = client.headObject { it.bucket(bucket).key(key) }
            return Triple(result.contentLength(), result.contentType(), result.metadata()["owner"] ?: "")
        } catch (error: S3Exception) {
            if (error.statusCode() == 404) return null
            throw error
        }
    }

    override fun get(key: String, span: Pair<Int, Int>?): ByteArray? {
        try {
            val request = software.amazon.awssdk.services.s3.model.GetObjectRequest.builder().bucket(bucket).key(key)
            if (span != null) request.range("bytes=${span.first}-${span.second}")
            return client.getObjectAsBytes(request.build()).asByteArray()
        } catch (error: S3Exception) {
            if (error.statusCode() == 404) return null
            throw error
        }
    }

    override fun overwrite(item: JsonNode) = put(item)
    override fun delete(key: String) { client.deleteObject { it.bucket(bucket).key(key) } }
}

private fun checkItem(store: Store, item: JsonNode): Pair<Int, String> {
    val expected = payload(item)
    val actual = store.get(item["key"].asText()) ?: error("${store.name} object missing: ${item["key"]}")
    check(actual.contentEquals(expected), "${store.name} bytes mismatch: ${item["key"]}")
    check(store.head(item["key"].asText()) == Triple(expected.size.toLong(), item["content_type"].asText(), item["owner"].asText()),
        "${store.name} metadata mismatch: ${item["key"]}")
    return actual.size to digest(actual)
}

private fun checkRange(store: Store): Pair<Int, String> {
    val span = manifest["range"]
    val key = span["key"].asText()
    val start = span["start"].asInt()
    val end = span["end"].asInt()
    val source = objects.first { it["key"].asText() == key }
    val expected = payload(source).copyOfRange(start, end + 1)
    val actual = store.get(key, start to end) ?: error("${store.name} range object missing")
    check(actual.contentEquals(expected), "${store.name} range bytes mismatch")
    return actual.size to digest(actual)
}

private fun run(store: Store) {
    for (item in objects) {
        val (size, hash) = checkItem(store, item)
        println("Kotlin/${store.name} get ${item["key"].asText()}: $size bytes, sha256=$hash")
    }
    val (size, hash) = checkRange(store)
    println("Kotlin/${store.name} range: $size bytes, sha256=$hash")
    store.overwrite(manifest["overwrite"])
    store.delete(manifest["delete"].asText())
}

private fun verify(store: Store) {
    val expected = objects.filter { it["key"].asText() != manifest["delete"].asText() }
        .associateBy { it["key"].asText() }.toMutableMap()
    expected[manifest["overwrite"]["key"].asText()] = manifest["overwrite"]
    check(store.keys() == expected.keys.sorted(), "${store.name} object keys mismatch")
    for (item in expected.values) checkItem(store, item)
    checkRange(store)
    check(store.head(manifest["delete"].asText()) == null, "${store.name} deleted object still exists")
    println("Kotlin/${store.name} blob check passed")
}

fun main(args: Array<String>) {
    check(args.size == 2 && args[0] in listOf("seed", "run", "verify") && args[1] in listOf("postgres", "rustfs", "both"),
        "Usage: blob {seed|run|verify} {postgres|rustfs|both}")
    for (target in (if (args[1] == "both") listOf("postgres", "rustfs") else listOf(args[1]))) {
        val store: Store = if (target == "postgres") Postgres() else RustFS()
        store.use { client ->
            when (args[0]) {
                "seed" -> client.seed()
                "run" -> run(client)
                "verify" -> verify(client)
            }
        }
    }
}
