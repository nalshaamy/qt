# Odoo Apps Publishing Checklist

Before publishing this commercial package:

- [ ] Confirm the selling price and currency in `__manifest__.py`.
- [ ] Add a real support email to the manifest when the support mailbox is ready.
- [ ] Confirm website and author metadata.
- [ ] Keep `static/description/index.html` and all listing images in English.
- [ ] Validate the module on a clean Odoo 19 database.
- [ ] Validate upgrade from the previous released version.
- [ ] Run the Device Pairing acceptance matrix on at least two browsers/devices.
- [ ] Verify no secrets, customer names, domains, or test credentials are included in the ZIP.
- [ ] Verify no `__pycache__`, `.pyc`, editor, or OS metadata files are included.
- [ ] Confirm the intended license before publication. This packaging pass intentionally leaves it unchanged.
