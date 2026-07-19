# Faz 35 / Etik Speak test-only ESO reader.
# Dedicated AppRole may read exactly one KV v2 document; it cannot list,
# create, update, delete, or reach another product path.
path "kv/data/platform/etik-speak" {
  capabilities = ["read"]
}

path "kv/metadata/platform/etik-speak" {
  capabilities = ["read"]
}
