# FLPOS User Guide

## 1. Overview

FLPOS improves customer receipt branding and provides a detailed A4 closing report for POS sessions. Settings are stored separately for each Point of Sale configuration.

## 2. Receipt settings

Open:

**Point of Sale → Configuration → Settings**

Select the required Point of Sale before changing its options.

### Enable Custom Receipt Logo

Activates a dedicated logo used only on customer receipts for the selected POS.

### Receipt Logo

Uploads the dedicated receipt image. A compact, high-contrast logo is recommended for thermal printers.

### Hide Default Receipt Logo

Hides Odoo’s standard company logo from the printed customer receipt.

### Hide “Powered by Odoo”

Removes the standard Odoo branding line from the receipt footer.

> Settings affect newly loaded POS sessions. Reload an already-open POS after changing receipt options.

## 3. A4 closing report

Open:

**Point of Sale → Orders → Sessions**

Open a POS session and use:

**Print → Enhanced Session Closing**

The report includes:

- POS and company information.
- Opening and closing timestamps.
- Session duration.
- Total orders and average order value.
- Gross sales, taxes, discounts, and refunds.
- Payment method totals.
- Opening, expected, actual, and difference cash values.
- Product and variant sales details.

## 4. Multiple Points of Sale

Each Point of Sale stores its own FLPOS receipt configuration. Changing the logo or receipt options for one POS does not change another POS.

## 5. Recommended logo preparation

- Use PNG or JPEG.
- Prefer a transparent or white background.
- Avoid very small text.
- Use a horizontal or compact square layout.
- Test on the actual printer before production rollout.

## 6. Permissions

Users need standard Odoo access to Point of Sale settings and sessions. FLPOS does not create a separate security role.
