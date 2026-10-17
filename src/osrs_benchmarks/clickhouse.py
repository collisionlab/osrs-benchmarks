"""ClickHouse over its HTTP interface: inserts and schema migrations."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from importlib import resources

DATABASE = "benchmarks"


class ClickHouse:
    def __init__(self, url, user="default", password=""):
        self.url = url.rstrip("/") + "/"
        self.user = user
        self.password = password

    def request(self, query, body=b"", **settings):
        params = urllib.parse.urlencode({"query": query, **settings})
        request = urllib.request.Request(self.url + "?" + params, data=body, method="POST", headers={
            "X-ClickHouse-User": self.user, "X-ClickHouse-Key": self.password})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ClickHouse: {e.read().decode().strip()}") from None

    def insert(self, table, rows, token):
        """Insert rows; a retry with the same token is a no-op (the tables deduplicate)."""
        if not rows:
            return
        body = "".join(json.dumps(row) + "\n" for row in rows).encode()
        self.request(f"INSERT INTO {DATABASE}.{table} FORMAT JSONEachRow", body,
                     insert_deduplication_token=token)

    def select(self, query):
        return [json.loads(line) for line in self.request(query + " FORMAT JSONEachRow").splitlines()]


def migrations():
    """(version, name, statements) for each migration, in order."""
    found = []
    for entry in resources.files(__package__).joinpath("migrations").iterdir():
        match = re.fullmatch(r"(\d+)_(\w+)\.sql", entry.name)
        if not match:
            continue
        text = "\n".join(line for line in entry.read_text().splitlines()
                         if not line.lstrip().startswith("--"))
        statements = [s.strip() for s in text.split(";") if s.strip()]
        found.append((int(match[1]), match[2], statements))
    return sorted(found)


def migrate(client, log=print):
    """Apply the migrations the database has not recorded yet."""
    client.request(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")
    client.request(f"CREATE TABLE IF NOT EXISTS {DATABASE}.schema_migrations "
                   "(version UInt32, name String, applied_at DateTime('UTC') DEFAULT now()) "
                   "ENGINE = MergeTree ORDER BY version")
    applied = {row["version"] for row in client.select(
        f"SELECT version FROM {DATABASE}.schema_migrations")}
    for version, name, statements in migrations():
        if version in applied:
            continue
        log(f"applying migration {version:04d}_{name}")
        for statement in statements:
            client.request(statement)
        client.insert("schema_migrations", [{"version": version, "name": name}], f"migration-{version}")
    log("schema is up to date")
