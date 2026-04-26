# Reconciliation report

- run_id: `1b4f8397-d622-4f70-8d5a-dc50d5b7b345`
- mode:   `dry_run`
- overall verdict: **MATCH**

## `workcube_mikrolink.COMPANY` (year=None)

- scope: `limited` (limit=10)
- verdict: **MATCH**
- row_count_pg: 3
- row_count_mssql: 3
- checksum_pg:    `77740998e6a4a584571abf4be17f55c1`
- checksum_mssql: `77740998e6a4a584571abf4be17f55c1`

Sample diff (top 10):

| source_pk | hash_pg | hash_mssql | match |
|---|---|---|---|
| `["1001"]` | `f3031cc346dc` | `f3031cc346dc` | ✅ |
| `["1002"]` | `f27c93ceeb94` | `f27c93ceeb94` | ✅ |
| `["1003"]` | `9f32ee0550a6` | `9f32ee0550a6` | ✅ |

