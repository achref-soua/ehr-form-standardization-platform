"""Replace the early bounded OMOP subset with the official 5.4.2 schema."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Connection, text

from ehrfs.omop.schema import install_schema, is_official_schema

revision = "20260829_0004"
down_revision = "20260829_0003"
branch_labels = None
depends_on = None

STAGE_SCHEMA = "omop54_stage"
COPY_STATEMENTS = (
    """
    INSERT INTO omop54_stage.concept (
      concept_id, concept_name, domain_id, vocabulary_id, concept_class_id,
      standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason
    )
    SELECT concept_id, concept_name, domain_id, vocabulary_id, concept_class_id,
      standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason
    FROM omop.concept
    """,
    """
    INSERT INTO omop54_stage.person (
      person_id, gender_concept_id, year_of_birth, race_concept_id,
      ethnicity_concept_id, person_source_value
    )
    SELECT person_id::integer, gender_concept_id, year_of_birth, race_concept_id,
      ethnicity_concept_id, person_source_value
    FROM omop.person
    """,
    """
    INSERT INTO omop54_stage.condition_occurrence (
      condition_occurrence_id, person_id, condition_concept_id, condition_start_date,
      condition_start_datetime, condition_type_concept_id, condition_source_value
    )
    SELECT condition_occurrence_id::integer, person_id::integer, condition_concept_id,
      condition_start_date, condition_start_datetime, condition_type_concept_id,
      condition_source_value
    FROM omop.condition_occurrence
    """,
    """
    INSERT INTO omop54_stage.measurement (
      measurement_id, person_id, measurement_concept_id, measurement_date,
      measurement_datetime, measurement_type_concept_id, value_as_number,
      value_as_concept_id, unit_concept_id, measurement_source_value, unit_source_value
    )
    SELECT measurement_id::integer, person_id::integer, measurement_concept_id,
      measurement_date, measurement_datetime, measurement_type_concept_id,
      value_as_number, value_as_concept_id, unit_concept_id,
      measurement_source_value, unit_source_value
    FROM omop.measurement
    """,
    """
    INSERT INTO omop54_stage.observation (
      observation_id, person_id, observation_concept_id, observation_date,
      observation_datetime, observation_type_concept_id, value_as_number,
      value_as_string, value_as_concept_id, observation_source_value
    )
    SELECT observation_id::integer, person_id::integer, observation_concept_id,
      observation_date, observation_datetime, observation_type_concept_id,
      value_as_number, value_as_string, value_as_concept_id, observation_source_value
    FROM omop.observation
    """,
)


def _table_exists(connection: Connection, table: str) -> bool:
    return bool(connection.scalar(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": table}))


def _copy_bounded_rows(connection: Connection) -> None:
    tables = ("concept", "person", "condition_occurrence", "measurement", "observation")
    for table, statement in zip(tables, COPY_STATEMENTS, strict=True):
        if _table_exists(connection, f"omop.{table}"):
            connection.execute(text(statement))


def _grant_runtime_access(connection: Connection) -> None:
    connection.execute(
        text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_app') THEN
                GRANT USAGE ON SCHEMA omop TO ehrfs_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA omop TO ehrfs_app;
              END IF;
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_worker') THEN
                GRANT USAGE ON SCHEMA omop TO ehrfs_worker;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA omop TO ehrfs_worker;
              END IF;
              IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ehrfs_readonly') THEN
                GRANT USAGE ON SCHEMA omop TO ehrfs_readonly;
                GRANT SELECT ON ALL TABLES IN SCHEMA omop TO ehrfs_readonly;
              END IF;
            END
            $$
            """
        )
    )


def upgrade() -> None:
    connection = op.get_bind()
    if is_official_schema(connection):
        return
    connection.execute(text(f"DROP SCHEMA IF EXISTS {STAGE_SCHEMA} CASCADE"))
    install_schema(connection, schema=STAGE_SCHEMA)
    _copy_bounded_rows(connection)
    connection.execute(text("DROP SCHEMA omop CASCADE"))
    connection.execute(text(f"ALTER SCHEMA {STAGE_SCHEMA} RENAME TO omop"))
    _grant_runtime_access(connection)


def downgrade() -> None:
    # Schema-shrinking downgrades would discard official CDM tables. Recovery is
    # deliberately performed from the checksummed pre-migration backup instead.
    pass
