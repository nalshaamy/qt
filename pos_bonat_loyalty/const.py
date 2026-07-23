product_fields = ['price_extra', 'lst_price', 'default_code', 'code', 'partner_ref', 'product_tmpl_id', 'barcode', 'product_template_variant_value_ids', 'standard_price', 'volume', 'weight', 'image_1920', 'image_variant_1920', 'write_date', 'id', 'display_name', 'create_uid', 'create_date', 'write_uid', 'tax_string', 'qty_available', 'virtual_available', 'free_qty', 'incoming_qty', 'outgoing_qty', 'reordering_min_qty', 'reordering_max_qty', 'avg_cost', 'total_value', 'cost_method', 'name', 'sequence', 'description', 'description_purchase', 'description_sale', 'type', 'categ_id', 'currency_id', 'cost_currency_id', 'list_price', 'volume_uom_name', 'weight_uom_name', 'sale_ok', 'purchase_ok', 'uom_id', 'uom_name', 'company_id', 'product_tag_ids', 'taxes_id', 'supplier_taxes_id', 'available_in_pos', 'to_weight', 'pos_categ_ids']
product_m2o_fields = {
    'categ_id': ['name', 'parent_id']
}
product_m2m_fields = {
    'product_template_variant_value_ids': ['attribute_id', 'name'],
    'product_tag_ids': ['name'],
    'taxes_id': ['name', 'amount_type', 'type_tax_use', 'amount', 'price_include'],
    'supplier_taxes_id': ['name', 'amount_type', 'type_tax_use', 'amount', 'price_include'],
    'pos_categ_ids': ['name', 'parent_id', 'sequence']
}

pos_categ_fields = ['name', 'parent_id', 'sequence', 'image_128']

pos_config_fields = ['name', 'currency_id', 'uuid', 'session_ids', 'current_session_id', 'current_session_state', 'number_of_rescue_session', 'last_session_closing_cash', 'last_session_closing_date', 'pos_session_username', 'pos_session_state', 'pos_session_duration', 'pricelist_id', 'available_pricelist_ids', 'company_id', 'tip_product_id', 'payment_method_ids', 'current_user_id', 'cash_rounding', 'only_round_cash_method', 'has_active_session', 'manual_discount', 'warehouse_id', 'display_name']
pos_config_m2m_fields = {
    'payment_method_ids': ['name', 'is_online_payment', 'type', 'sequence']
}

pos_session_fields = ["company_id", "config_id", "name", "access_token", "user_id", "currency_id", "start_at", "stop_at", "state", "opening_notes", "closing_notes", "cash_control", "cash_journal_id", "cash_register_balance_end_real", "cash_register_balance_start", "cash_register_balance_end", "cash_register_difference", "cash_real_transaction", "order_ids", "order_count", "statement_line_ids", "payment_method_ids", "total_payments_amount", "is_in_company_currency", "update_stock_at_closing", "bank_payment_ids", "display_name", "create_uid", "create_date", "write_uid", "write_date"]

pos_order_fields = ['name', 'date_order', 'user_id', 'amount_tax', 'amount_total', 'amount_paid', 'amount_return', 'margin', 'margin_percent', 'lines', 'company_id', 'country_code', 'pricelist_id', 'partner_id', 'sequence_number', 'session_id', 'config_id', 'currency_id', 'currency_rate', 'state', 'general_customer_note', 'pos_reference', 'payment_ids', 'is_tipped', 'tip_amount', 'refund_orders_count', 'is_refund', 'refunded_order_id', 'has_refundable_lines', 'ticket_code', 'tracking_number', 'display_name', 'create_uid', 'create_date', 'write_uid', 'write_date']
pos_order_m2o_fields = {
    'partner_id': ['name', 'company_type', 'is_company', 'company_name', 'street', 'street2', 'city', 'zip', 'state_id', 'country_id', 'vat', 'phone', 'email', 'website']
}
pos_order_o2m_fields = {
    'lines': ['attribute_value_ids', 'combo_line_ids', 'combo_parent_id', 'company_id', 'create_date', 'create_uid', 'currency_id', 'custom_attribute_value_ids', 'customer_note', 'discount', 'display_name', 'full_product_name', 'is_total_cost_computed', 'margin', 'margin_percent', 'name', 'notice', 'price_extra', 'price_subtotal', 'price_subtotal_incl', 'price_unit', 'product_id', 'product_uom_id', 'qty', 'refund_orderline_ids', 'refunded_orderline_id', 'refunded_qty', 'tax_ids', 'tax_ids_after_fiscal_position', 'total_cost', 'uuid', 'write_date', 'write_uid'],
    'payment_ids': ['account_move_id', 'amount', 'card_type', 'cardholder_name', 'company_id', 'create_date', 'create_uid', 'currency_id', 'currency_rate', 'display_name', 'is_change', 'name', 'online_account_payment_id', 'partner_id', 'payment_date', 'payment_method_id', 'payment_status', 'pos_order_id', 'session_id', 'ticket', 'transaction_id', 'write_date', 'write_uid']
}
