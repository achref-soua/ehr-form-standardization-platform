# OMOP Common Data Model 5.4.2 PostgreSQL schema

These four SQL files are an unmodified vendored copy of the PostgreSQL assets from the
[OHDSI CommonDataModel v5.4.2 release](https://github.com/OHDSI/CommonDataModel/releases/tag/v5.4.2).
They are licensed under Apache-2.0 by OHDSI.

The migration replaces `@cdmDatabaseSchema` with `omop`, applies the DDL, primary keys, and
indices, and leaves the upstream foreign-key script available for validation after a compatible
Athena vocabulary has been loaded. Applying vocabulary foreign keys before that point would reject
the CDM-defined `concept_id = 0` representation for unavailable mappings.

| File | SHA-256 |
| --- | --- |
| `OMOPCDM_postgresql_5.4_ddl.sql` | `ae99be6e79edfad5f17ef71edda176281b45e3aa9e400e7a9f829103f5ec4771` |
| `OMOPCDM_postgresql_5.4_primary_keys.sql` | `ffe6cc10f04a713ea86825dccfc1d8b8a981ba6037fc69cb9df4c80ce2f1970d` |
| `OMOPCDM_postgresql_5.4_indices.sql` | `8a3537f971c75e9e33c3d1d13b041d4e5de8532dc1607bc31349af3679a66eec` |
| `OMOPCDM_postgresql_5.4_constraints.sql` | `dedae8072ef585e25e0ab2624f557e37e5ddd2d51e75810af58b02e990a4f293` |

The downloaded v5.4.2 release archive used for this import had SHA-256
`91f59fe949cfe948e1e4c5aeb6255e4bea3dc7e998ac40f733524f268da9e672`.
