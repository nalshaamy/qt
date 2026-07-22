# Installation

## Prerequisites

- Odoo 19 instance.
- Point of Sale installed.
- Access to the custom addons directory.
- Administrator access to update and install applications.

## Install from a custom addons path

1. Copy the `flexsys_pos_config` directory into your custom addons path.
2. Restart the Odoo service.
3. Enable developer mode.
4. Open **Apps** and select **Update Apps List**.
5. Search for **FLPOS**.
6. Select **Install**.

## Upgrade an existing installation

1. Replace the previous `flexsys_pos_config` directory with the new version.
2. Restart Odoo.
3. Open **Apps**.
4. Search for **FLPOS**.
5. Select **Upgrade**.

## Odoo.sh

1. Add the module directory to the Git repository.
2. Commit and push the change to the required branch.
3. Wait for the Odoo.sh build to finish.
4. Open the database and upgrade **FLPOS** from Apps.

## Verification

After installation, open:

**Point of Sale → Configuration → Settings**

The following FLPOS sections should appear:

- Receipt
- Closing Reports
