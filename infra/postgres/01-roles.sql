REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE ehrfs FROM PUBLIC;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ehrfs_migrator') THEN
    CREATE ROLE ehrfs_migrator LOGIN PASSWORD 'ehrfs_migrator_local_only' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ehrfs_app') THEN
    CREATE ROLE ehrfs_app LOGIN PASSWORD 'ehrfs_app_local_only' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ehrfs_worker') THEN
    CREATE ROLE ehrfs_worker LOGIN PASSWORD 'ehrfs_worker_local_only' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ehrfs_readonly') THEN
    CREATE ROLE ehrfs_readonly LOGIN PASSWORD 'ehrfs_readonly_local_only' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;

GRANT CONNECT ON DATABASE ehrfs TO ehrfs_migrator, ehrfs_app, ehrfs_worker;
GRANT CREATE ON DATABASE ehrfs TO ehrfs_migrator;
GRANT CONNECT ON DATABASE ehrfs TO ehrfs_readonly;
GRANT ehrfs_migrator, ehrfs_app, ehrfs_worker TO ehrfs_owner;

CREATE SCHEMA IF NOT EXISTS control AUTHORIZATION ehrfs_migrator;
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION ehrfs_migrator;
CREATE SCHEMA IF NOT EXISTS omop AUTHORIZATION ehrfs_migrator;
GRANT USAGE ON SCHEMA control, audit, omop TO ehrfs_app, ehrfs_worker, ehrfs_readonly;

SET ROLE ehrfs_migrator;
ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ehrfs_app, ehrfs_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT SELECT, INSERT ON TABLES TO ehrfs_app, ehrfs_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA omop GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ehrfs_app, ehrfs_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA control, audit, omop GRANT SELECT ON TABLES TO ehrfs_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA control, audit, omop GRANT USAGE, SELECT ON SEQUENCES TO ehrfs_app, ehrfs_worker;
RESET ROLE;
