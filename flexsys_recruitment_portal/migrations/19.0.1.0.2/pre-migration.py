"""Prepare existing RC2 website-bound configs for company-bound storage.

Never delete or automatically merge employer branding or CV-related settings.
"""


def migrate(cr, version):
    cr.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'flexsys_career_config'
              AND column_name = 'website_id'
        )
    """)
    if cr.fetchone()[0]:
        # Column may remain as an obsolete SQL column after the ORM field is
        # removed. Explicitly drop its NOT NULL restriction so fresh company
        # configurations can be created after upgrading this module.
        cr.execute('ALTER TABLE flexsys_career_config ALTER COLUMN website_id DROP NOT NULL')

    # New V1 config is unique per company, unlike RC2 per-website config.
    # Preserve rather than silently merge/destroy different logo palettes.
    cr.execute("""
        SELECT company_id, COUNT(*)
        FROM flexsys_career_config
        GROUP BY company_id HAVING COUNT(*) > 1
        LIMIT 1
    """)
    duplicate = cr.fetchone()
    if duplicate:
        raise RuntimeError(
            'FlexSys Careers RC3 upgrade: company %s has %s website-based '
            'configurations. Consolidate the configurations with a DBA on '
            'a backup/Staging copy before upgrading. No data was deleted.'
            % duplicate
        )
