# Troubleshooting

## FLPOS settings are not visible

- Confirm that the module is installed.
- Confirm that Point of Sale is installed.
- Upgrade FLPOS after replacing module files.
- Clear the browser cache and reopen Settings.

## Custom logo does not appear

- Confirm **Enable Custom Receipt Logo** is active.
- Confirm a logo was uploaded for the same POS currently open.
- Save the settings.
- Close and reopen or fully reload the POS.
- Test with a PNG or JPEG image.

## Default logo still appears

- Confirm **Hide Default Receipt Logo** is enabled for the correct POS.
- Reload the POS after saving.
- Clear POS frontend assets if an older asset bundle is cached.

## “Powered by Odoo” still appears

- Confirm the setting is enabled for the correct POS.
- Reload the POS.
- Upgrade the module to rebuild assets after deployment.

## Closing report is not listed

- Open a `pos.session` record, not a POS order.
- Confirm the module was upgraded successfully.
- Check that `report/pos_session_report.xml` was loaded.
- Restart Odoo and upgrade FLPOS.

## PDF layout is incorrect

- Confirm `wkhtmltopdf` is supported by the Odoo deployment.
- Test with the standard Odoo PDF engine.
- Avoid overriding the FLPOS report stylesheet from another custom module.
