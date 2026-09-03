-- =====================================================================
-- FlexSysHR — Phase 0 Schema Introspection (SQL layer)
-- Ref: Phase 0 Technical Design Freeze v0.3 §2.6
-- Run:  psql -d <DB> -f sig_sql.sql > sig_sql_output.txt 2>&1
-- Rule: paste RAW output into phase1/introspection_report.md. No editing.
-- =====================================================================

\pset pager off
\timing on
\set ON_ERROR_STOP off
-- ON_ERROR_STOP is OFF deliberately: a failing query (e.g. a column that does not exist)
-- is itself a finding. Keep the error text in the output; do not delete it.
\echo '=================== CONTEXT ==================='
SELECT current_database() AS db, current_user AS usr, now() AS run_at, version() AS pg_version;

\echo ''
\echo '=================== SIG-10: environment ==================='
SELECT name, latest_version, state
  FROM ir_module_module
 WHERE state = 'installed'
 ORDER BY name;

SELECT id, name, partner_id FROM res_company ORDER BY id;

\echo ''
\echo '--- system / company timezone hints ---'
SELECT key, value FROM ir_config_parameter WHERE key IN ('database.uuid','web.base.url') ORDER BY key;

\echo ''
\echo '=================== SIG-01: hr_attendance columns ==================='
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_name = 'hr_attendance'
 ORDER BY ordinal_position;

\echo ''
\echo '--- ORM-level field metadata for hr.attendance ---'
-- NOTE: selection values are covered by SIG-08 (ir_model_fields_selection) and by the ORM script.
-- Do NOT read f.selection_ids here: it is a One2many, not a physical column.
SELECT f.name, f.ttype, f.required, f.readonly, f.store, f.relation
  FROM ir_model_fields f
  JOIN ir_model m ON m.id = f.model_id
 WHERE m.model = 'hr.attendance'
 ORDER BY f.name;

\echo ''
\echo '=================== SIG-02: hr_attendance constraints & indexes (DEC-005 GOVERNING) ==================='
SELECT conname, contype, pg_get_constraintdef(oid) AS definition
  FROM pg_constraint
 WHERE conrelid = 'hr_attendance'::regclass
 ORDER BY contype, conname;

SELECT indexname, indexdef
  FROM pg_indexes
 WHERE tablename = 'hr_attendance'
 ORDER BY indexname;

\echo ''
\echo '--- Odoo-declared SQL constraints on hr.attendance ---'
-- SELECT * on purpose: column set of ir_model_constraint varies between versions.
SELECT c.*
  FROM ir_model_constraint c
  JOIN ir_model m ON m.id = c.model
 WHERE m.model = 'hr.attendance';

\echo ''
\echo '=================== SIG-11: PREFLIGHT for DEC-005 ==================='
\echo '--- Any employee with more than one OPEN attendance blocks the index ---'
SELECT employee_id, COUNT(*) AS open_records
  FROM hr_attendance
 WHERE check_out IS NULL
 GROUP BY employee_id
HAVING COUNT(*) > 1
 ORDER BY open_records DESC;

\echo '--- Overlapping attendances (informational) ---'
SELECT a.employee_id, a.id AS id_a, b.id AS id_b, a.check_in, a.check_out, b.check_in, b.check_out
  FROM hr_attendance a
  JOIN hr_attendance b
    ON a.employee_id = b.employee_id
   AND a.id < b.id
   AND a.check_in < COALESCE(b.check_out, 'infinity'::timestamp)
   AND b.check_in < COALESCE(a.check_out, 'infinity'::timestamp)
 LIMIT 50;

\echo ''
\echo '=================== SIG-03: hr_work_location ==================='
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_name = 'hr_work_location'
 ORDER BY ordinal_position;

SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'hr_work_location'::regclass;

\echo ''
\echo '=================== SIG-04: hr_employee ==================='
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_name = 'hr_employee'
   AND column_name IN ('user_id','company_id','work_location_id','resource_calendar_id','tz','active','department_id')
 ORDER BY column_name;

\echo ''
\echo '--- does hr_employee expose tz directly or via resource_resource? ---'
SELECT column_name FROM information_schema.columns
 WHERE table_name = 'resource_resource' AND column_name IN ('tz','user_id','company_id');

\echo ''
\echo '=================== SIG-05: portal group ==================='
SELECT d.module || '.' || d.name AS xmlid, g.id, g.name
  FROM res_groups g
  JOIN ir_model_data d ON d.res_id = g.id AND d.model = 'res.groups'
 WHERE d.name ILIKE '%portal%'
 ORDER BY xmlid;

\echo ''
\echo '=================== SIG-07: ACL on target models ==================='
SELECT m.model, a.name, g.name AS group_name,
       a.perm_read, a.perm_write, a.perm_create, a.perm_unlink
  FROM ir_model_access a
  JOIN ir_model m ON m.id = a.model_id
  LEFT JOIN res_groups g ON g.id = a.group_id
 WHERE m.model IN ('hr.attendance','hr.employee','hr.work.location')
 ORDER BY m.model, g.name NULLS FIRST;

\echo ''
\echo '--- record rules ---'
SELECT m.model, r.name, r."global", r.domain_force,
       r.perm_read, r.perm_write, r.perm_create, r.perm_unlink
  FROM ir_rule r
  JOIN ir_model m ON m.id = r.model_id
 WHERE m.model IN ('hr.attendance','hr.employee','hr.work.location')
 ORDER BY m.model, r.name;

\echo ''
\echo '=================== SIG-08: in_mode / out_mode selection values ==================='
-- presence check first (a missing column below is a finding, not a script bug)
SELECT column_name FROM information_schema.columns
 WHERE table_name = 'hr_attendance' AND column_name IN ('in_mode','out_mode')
 ORDER BY column_name;

SELECT DISTINCT in_mode  FROM hr_attendance ORDER BY 1;
SELECT DISTINCT out_mode FROM hr_attendance ORDER BY 1;

SELECT f.name, s.value, s.sequence
  FROM ir_model_fields_selection s
  JOIN ir_model_fields f ON f.id = s.field_id
  JOIN ir_model m ON m.id = f.model_id
 WHERE m.model = 'hr.attendance' AND f.name IN ('in_mode','out_mode')
 ORDER BY f.name, s.sequence;

\echo ''
\echo '=================== SIG-09: worked_hours storage ==================='
-- SELECT * on purpose: compute/depends columns are not guaranteed across versions.
SELECT f.*
  FROM ir_model_fields f
  JOIN ir_model m ON m.id = f.model_id
 WHERE m.model = 'hr.attendance' AND f.name IN ('worked_hours','check_in','check_out');

\echo ''
\echo '=================== DATA VOLUME (context for reporting tests) ==================='
SELECT MIN(check_in) AS earliest, MAX(check_in) AS latest, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE check_out IS NULL) AS open_records
  FROM hr_attendance;

\echo '--- attendances spanning local midnight (UTC approximation) ---'
SELECT COUNT(*) AS spanning_utc_midnight
  FROM hr_attendance
 WHERE check_out IS NOT NULL
   AND date_trunc('day', check_in) <> date_trunc('day', check_out);

\echo ''
\echo '=================== END ==================='
