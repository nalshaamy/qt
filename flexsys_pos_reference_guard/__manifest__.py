{
    "name": "FlexSys POS Reference Guard",
    "summary": "Prevents duplicate POS receipt references and preserves an audit trail",
    "version": "19.0.1.3.0",
    "category": "Point of Sale",
    "author": "FlexSys",
    "website": "https://flexsyssa.com",
    "support": "info@flexsyssa.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/pos_reference_guard_log_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "flexsys_pos_reference_guard/static/src/app/overrides/device_identifier_sequence_guard.js",
            "flexsys_pos_reference_guard/static/src/app/overrides/persistent_sequence_backup.js",
            "flexsys_pos_reference_guard/static/src/app/overrides/preserve_reload_sequence.js",
            "flexsys_pos_reference_guard/static/src/app/overrides/sequence_repair_sync.js",
        ],
    },
    "installable": True,
    "application": False,
}
