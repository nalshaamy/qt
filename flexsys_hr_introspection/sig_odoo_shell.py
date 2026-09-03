# -*- coding: utf-8 -*-
"""
FlexSysHR — Phase 0 Schema Introspection (ORM layer)
Ref: Phase 0 Technical Design Freeze v0.3 §2.6

READ-ONLY. Creates nothing, writes nothing, commits nothing.

Run (self-hosted):
    odoo shell -c /etc/odoo/odoo.conf -d <DB> --no-http < sig_odoo_shell.py > sig_orm_output.txt 2>&1

Run (Odoo.sh shell):
    odoo-bin shell -d $PGDATABASE --no-http < sig_odoo_shell.py > sig_orm_output.txt 2>&1

Rule: paste RAW output into phase1/introspection_report.md. Do not summarise.
"""
from __future__ import print_function
import datetime
import os
import sys

SEP = "=" * 78


def head(title):
    print("\n" + SEP)
    print(title)
    print(SEP)


def dump_fields(model_name, only=None):
    if model_name not in env:
        print("MODEL NOT PRESENT: %s" % model_name)
        return
    fields = env[model_name].fields_get()
    for name in sorted(fields):
        if only and name not in only:
            continue
        f = fields[name]
        line = "%-32s %-12s store=%-5s req=%-5s ro=%-5s rel=%-24s" % (
            name,
            f.get("type"),
            f.get("store"),
            f.get("required"),
            f.get("readonly"),
            f.get("relation") or "-",
        )
        if f.get("selection"):
            line += " selection=%s" % (f.get("selection"),)
        print(line)


head("CONTEXT")
print("run_at        : %s" % datetime.datetime.utcnow().isoformat() + "Z")
print("database      : %s" % env.cr.dbname)
try:
    import odoo
    print("odoo version  : %s" % odoo.release.version)
    print("odoo series   : %s" % odoo.release.series)
except Exception as exc:  # pragma: no cover
    print("odoo version  : UNKNOWN (%s)" % exc)
print("addons_path   : %s" % os.environ.get("ODOO_ADDONS_PATH", "(see config)"))
print("python        : %s" % sys.version.replace("\n", " "))

head("SIG-06 / SIG-10 — EDITION DETECTION")
enterprise_markers = ["web_enterprise", "hr_attendance_gantt", "account_accountant", "web_studio"]
installed = env["ir.module.module"].search([("state", "=", "installed")])
names = set(installed.mapped("name"))
print("installed modules count : %s" % len(names))
print("enterprise markers found: %s" % sorted(m for m in enterprise_markers if m in names))
print("EDITION GUESS           : %s" % ("ENTERPRISE" if names & set(enterprise_markers) else "COMMUNITY"))
print("\nhr* modules installed:")
for name in sorted(n for n in names if n.startswith("hr")):
    print("  - %s" % name)

head("SIG-01 — hr.attendance FIELDS (full)")
dump_fields("hr.attendance")

head("SIG-01b — GEO FIELD PRESENCE CHECK (expected reusable set)")
expected = [
    "in_latitude", "in_longitude", "in_location", "in_ip_address", "in_browser", "in_mode",
    "out_latitude", "out_longitude", "out_location", "out_ip_address", "out_browser", "out_mode",
]
present = env["hr.attendance"].fields_get().keys() if "hr.attendance" in env else []
for name in expected:
    print("%-18s : %s" % (name, "PRESENT" if name in present else "*** MISSING ***"))

head("SIG-08 — in_mode / out_mode SELECTION VALUES")
if "hr.attendance" in env:
    fg = env["hr.attendance"].fields_get(["in_mode", "out_mode"])
    for name in ("in_mode", "out_mode"):
        if name in fg:
            print("%s -> %s" % (name, fg[name].get("selection")))
        else:
            print("%s -> FIELD ABSENT" % name)

head("SIG-02 — hr.attendance CONSTRAINTS")
model = env["hr.attendance"] if "hr.attendance" in env else None
if model is not None:
    print("_sql_constraints:")
    for con in getattr(model, "_sql_constraints", []):
        print("  %s" % (con,))
    print("\npython @api.constrains methods:")
    for attr in dir(model):
        try:
            method = getattr(model, attr)
        except Exception:
            continue
        constrains = getattr(method, "_constrains", None)
        if constrains:
            print("  %-40s -> %s" % (attr, constrains))
    print("\nir.model.constraint rows:")
    con_model = env["ir.model.constraint"]
    con_fields = [f for f in ("name", "type", "definition", "message") if f in con_model._fields]
    for row in con_model.search([("model", "=", env["ir.model"]._get_id("hr.attendance"))]).read(con_fields):
        print("  %s" % (row,))

head("SIG-03 — hr.work.location FIELDS")
dump_fields("hr.work.location")

head("SIG-04 — hr.employee KEY FIELDS")
dump_fields("hr.employee", only={
    "user_id", "company_id", "company_ids", "work_location_id", "resource_calendar_id",
    "tz", "active", "department_id", "attendance_state", "last_attendance_id",
})

head("SIG-04b — TIMEZONE SOURCE")
emp = env["hr.employee"].search([], limit=1)
if emp:
    print("sample employee id      : %s" % emp.id)
    print("has 'tz' field          : %s" % ("tz" in emp._fields))
    print("resource tz             : %s" % (emp.resource_id.tz if "resource_id" in emp._fields and emp.resource_id else "N/A"))
    print("company                 : %s" % emp.company_id.display_name)
else:
    print("no employee records to sample")

head("SIG-05 — PORTAL GROUP")
portal = env.ref("base.group_portal", raise_if_not_found=False)
print("base.group_portal id    : %s" % (portal.id if portal else "NOT FOUND"))
print("portal users count      : %s" % (len(portal.user_ids) if portal else "N/A"))

head("SIG-07 — ACL ON TARGET MODELS")
for model_name in ("hr.attendance", "hr.employee", "hr.work.location"):
    model_id = env["ir.model"]._get_id(model_name) if model_name in env else None
    if not model_id:
        print("%s: MODEL ABSENT" % model_name)
        continue
    print("\n--- %s ---" % model_name)
    for acl in env["ir.model.access"].search([("model_id", "=", model_id)]):
        print("  %-46s group=%-38s r=%s w=%s c=%s u=%s" % (
            acl.name, acl.group_id.display_name or "GLOBAL",
            acl.perm_read, acl.perm_write, acl.perm_create, acl.perm_unlink))
    rule_model = env["ir.rule"]
    # the 'global' field name differs across versions ('global' / 'global_'); resolve it dynamically
    global_field = next((f for f in ("global", "global_") if f in rule_model._fields), None)
    rule_fields = [f for f in ("name", "domain_force", global_field) if f]
    for row in rule_model.search([("model_id", "=", model_id)]).read(rule_fields):
        print("  RULE %s" % (row,))

head("SIG-09 — worked_hours COMPUTATION")
if "hr.attendance" in env:
    fg = env["hr.attendance"].fields_get(["worked_hours", "check_in", "check_out"])
    for name, meta in fg.items():
        print("%-14s type=%-10s store=%s readonly=%s" % (name, meta.get("type"), meta.get("store"), meta.get("readonly")))

head("SIG-12 — SECRET CHANNEL PROBE (§6.7)")
print("env FLEXSYS_HR_PEPPER set        : %s" % bool(os.environ.get("FLEXSYS_HR_PEPPER")))
print("env FLEXSYS_HR_PEPPER_FILE set   : %s" % bool(os.environ.get("FLEXSYS_HR_PEPPER_FILE")))
print("env ODOO_STAGE                   : %s" % os.environ.get("ODOO_STAGE", "(unset)"))
try:
    from odoo.tools import config as odoo_config
    print("data_dir                         : %s" % odoo_config.get("data_dir"))
    print("config file                      : %s" % odoo_config.rcfile)
    print("custom key flexsys_hr_pepper_file: %s" % odoo_config.get("flexsys_hr_pepper_file", "(absent)"))
    print("config.misc sections             : %s" % list(getattr(odoo_config, "misc", {}).keys()))
except Exception as exc:
    print("config probe failed: %s" % exc)
print("NOTE: values are never printed, only presence flags.")

head("DONE — paste this raw output into phase1/introspection_report.md")
