# Features

## Receipt Engine

### Dedicated receipt logo

A separate image can be configured for each POS without replacing the company logo stored on the company record.

### Default logo visibility

The standard receipt logo can be hidden per POS through CSS scoped to the receipt root.

### Odoo footer visibility

The “Powered by Odoo” footer can be shown or hidden independently.

### Safe POS architecture

The receipt implementation uses QWeb inheritance and standard POS model data. It does not patch the POS Store, ReceiptHeader component, or POS loader.

## Closing Report

### A4 PDF report

A printable A4 report is available from POS session records.

### Sales summary

Includes order count, gross sales, untaxed sales, taxes, discounts, refunds, sold quantity, and average order value.

### Payment summary

Groups transactions by payment method and displays transaction count and amount.

### Cash reconciliation

Displays opening cash, cash received, expected cash, actual cash, and cash difference when the session provides those values.

### Product analysis

Groups POS lines by product variant and displays quantity, refunds, attributes, category, barcode, discount, and net amount.

## Configuration

All functional options are stored per `pos.config` and exposed through standard Point of Sale settings.
