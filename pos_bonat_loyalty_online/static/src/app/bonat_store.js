/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { BonatApi } from "@pos_bonat_loyalty_online/app/bonat_api";
import { bonatRuntime } from "@pos_bonat_loyalty_online/app/bonat_runtime";
import {
    BONAT_API_URL_DEFAULT,
    BONAT_API_URL_STAGING_DEFAULT,
    BONAT_BACKUP_FIELDS,
    BONAT_BACKUP_PARAM,
    PARAM_API_URL,
    PARAM_API_URL_STAGING,
} from "@pos_bonat_loyalty_online/app/bonat_const";

/*
 * POS startup wiring.
 *
 * Replaces two Python hooks that cannot exist in an importable module:
 *
 *  1. res.company._load_pos_data_fields(), which appended
 *     enable_bonat_integration / bonat_api_key / bonat_merchant_id /
 *     bonat_merchant_name / bonat_demo_mode to the preloaded POS payload.
 *
 *     Manual x_ fields are NOT preloaded: this was measured on a real Odoo
 *     Online database, where `pos.config.x_bonat_spike_token` came back
 *     undefined from the payload while an ORM read of the same field succeeded.
 *     So the values are fetched here with one explicit read at startup.
 *
 *  2. product_template._load_pos_data_domain(), which force-included the Bonat
 *     discount product in the POS load even though it is available_in_pos=False.
 *     Replaced by pos.data.loadProductFromPos(), the standard client-side entry
 *     point for pulling a product into the registry on demand.
 *
 * Everything is defensive: a failure here must degrade Bonat to "disabled" and
 * must never stop the POS from opening.
 */
/**
 * Stable fingerprint of a menu payload, so an unchanged catalogue costs zero
 * network traffic on POS open. Only the fields Bonat's mapper consumes take part,
 * sorted by id, so record ordering and irrelevant field churn don't force pushes.
 */
async function bonatCatalogueHash(payload) {
    const stable = JSON.stringify({
        c: payload.categories.map((c) => [c.id, c.name]).sort((a, b) => a[0] - b[0]),
        p: payload.products
            .map((p) => [p.id, p.name, p.lst_price, p.pos_categ_ids[0]?.id || 0])
            .sort((a, b) => a[0] - b[0]),
    });
    if (window.crypto?.subtle) {
        const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(stable));
        return (
            "sha256-" +
            Array.from(new Uint8Array(digest))
                .map((b) => b.toString(16).padStart(2, "0"))
                .join("")
        );
    }
    // crypto.subtle exists only in secure contexts; a POS served over plain http
    // falls back to djb2. Collisions just cost one redundant (idempotent) push.
    let h = 5381;
    for (let i = 0; i < stable.length; i++) {
        h = ((h << 5) + h + stable.charCodeAt(i)) | 0;
    }
    return "djb2-" + (h >>> 0).toString(16) + "-" + stable.length;
}

patch(PosStore.prototype, {
    async afterProcessServerData() {
        await super.afterProcessServerData(...arguments);

        // Neutral default, so every consumer can read pos.bonat unconditionally.
        this.bonat = {
            enabled: false,
            apiKey: "",
            merchantId: "",
            merchantName: "",
            demoMode: false,
            // ADR 0003 on main (docs/adr/0003-odoo19-menu-sync-mode-toggle.md — this
            // branch's own docs/adr/0003-*.md is a different decision, see
            // docs/adr/README.md): neutral default matches res.company's own
            // no-guaranteed-value column (see data/bonat_company_fields.xml) —
            // anything other than the literal "template" reads as variant-level.
            menuSyncMode: "variant",
            apiUrl: BONAT_API_URL_DEFAULT,
            apiUrlStaging: BONAT_API_URL_STAGING_DEFAULT,
            discountProduct: null,
            voucherPaymentMethodId: null,
            loadError: null,
        };
        this.bonatApi = new BonatApi(() => this.bonat, this);

        // Publish services the model layer cannot reach: PosOrderline records have
        // no `pos` or `env` back-reference on this series. See bonat_runtime.js.
        bonatRuntime.notification = this.notification;
        bonatRuntime.pos = this;

        try {
            await this.loadBonatConfig();
        } catch (error) {
            console.error("[bonat] configuration load failed, integration disabled:", error);
            this.bonat.loadError = String(error?.message || error);
        }

        // Settings survival across module re-imports (see BONAT_BACKUP_PARAM):
        // a configured POS refreshes the backup; an unconfigured one attempts a
        // restore. Both are best-effort — cashiers lack the needed rights and
        // fail silently; a manager or admin opening the POS does the real work.
        if (this.bonat.enabled || this.bonat.apiKey || this.bonat.merchantId) {
            this.mirrorBonatConfig().catch(() => {});
        } else if (!this.bonat.loadError) {
            try {
                await this.healBonatConfigFromBackup();
            } catch {
                // Expected for non-admin users; the settings page has its own heal.
            }
        }

        if (this.bonat.enabled) {
            // Fire-and-forget: menu sync must never delay or block POS opening.
            this.syncBonatMenu().catch((error) =>
                console.error("[bonat] menu sync failed:", error)
            );
        }
    },

    /**
     * Copy the company's Bonat configuration into the runtime-created backup
     * parameter, so the next field wipe (module re-import, platform registry
     * churn) is recoverable. Skips the write when the backup already matches.
     */
    async mirrorBonatConfig() {
        const values = {
            x_bonat_enabled: this.bonat.enabled,
            x_bonat_api_key: this.bonat.apiKey,
            x_bonat_merchant_id: this.bonat.merchantId,
            x_bonat_merchant_name: this.bonat.merchantName,
            x_bonat_demo_mode: this.bonat.demoMode,
        };
        const serialized = JSON.stringify(values);
        const current = await this.data.call("ir.config_parameter", "get_param", [
            BONAT_BACKUP_PARAM,
            "",
        ]);
        if (current === serialized) {
            return;
        }
        await this.data.call("ir.config_parameter", "set_param", [
            BONAT_BACKUP_PARAM,
            serialized,
        ]);
        console.log("[bonat] configuration backup refreshed");
    },

    /**
     * Restore the company's Bonat fields from the backup parameter after a
     * wipe, then reload the configuration so this session comes up configured.
     */
    async healBonatConfigFromBackup() {
        const raw = await this.data.call("ir.config_parameter", "get_param", [
            BONAT_BACKUP_PARAM,
            "",
        ]);
        let backup = null;
        try {
            backup = raw ? JSON.parse(raw) : null;
        } catch {
            backup = null;
        }
        if (!backup || typeof backup !== "object") {
            return;
        }
        const values = {};
        for (const field of BONAT_BACKUP_FIELDS) {
            if (field in backup) {
                values[field] = backup[field];
            }
        }
        if (!Object.keys(values).length) {
            return;
        }
        const companyId = this.config?.company_id?.id ?? this.company?.id;
        await this.data.call("res.company", "write", [[companyId], values]);
        console.warn(
            "[bonat] configuration was empty and has been restored from backup" +
                " (a module update most likely reset it)"
        );
        await this.loadBonatConfig();
    },

    /**
     * Push the catalogue this POS just loaded to Bonat, replacing the
     * webhook-triggered pull that the on-premise module serves through its
     * Python /api/pos/* controllers (impossible on Odoo Online).
     *
     * Runs on every POS open, but a fingerprint check makes the unchanged case
     * free: the hash of the last payload Bonat accepted is kept in localStorage
     * and nothing is sent while it matches. On failure the old hash is kept, so
     * the next POS open retries automatically — no queues, no timers.
     */
    async syncBonatMenu() {
        if (!this.bonat.enabled || !this.bonat.apiKey || !this.bonat.merchantId) {
            return;
        }
        const payload = this.buildBonatMenuPayload();
        if (!payload.products.length) {
            // Bonat's endpoint rejects empty snapshots by design (a broken client
            // must not wipe a merchant's menu), so don't bother sending one.
            console.log("[bonat] no POS products loaded, menu sync skipped");
            return;
        }

        const hash = await bonatCatalogueHash(payload);
        const storageKey = `bonat_menu_hash_${this.bonat.merchantId}_${this.config?.id ?? 0}`;
        let lastHash = null;
        try {
            lastHash = window.localStorage.getItem(storageKey);
        } catch {
            // Storage can be unavailable (private mode); worst case is one
            // redundant idempotent push per POS open.
        }
        if (lastHash === hash) {
            console.log("[bonat] menu unchanged since last push, sync skipped");
            return;
        }

        const result = await this.bonatApi.menuSync({ ...payload, catalogue_hash: hash });
        if (result.success) {
            try {
                window.localStorage.setItem(storageKey, hash);
            } catch {
                // Same storage caveat as above.
            }
            console.log(
                `[bonat] menu sync pushed ${payload.products.length} products and ` +
                    `${payload.categories.length} categories` +
                    (this.bonat.demoMode ? " (Demo Mode, staging)" : "")
            );
        } else {
            // Old hash kept on purpose: the next POS open retries.
            console.error("[bonat] menu sync rejected:", result.error);
        }
    },

    /**
     * Snapshot of the catalogue in the shape Bonat's odooPartnerMenuMapper and
     * odooPartnerCategoryMapper consume. Everything here is already in the POS
     * registry — no extra reads. The Bonat discount line product is excluded:
     * it is plugin plumbing, not a menu item.
     */
    buildBonatMenuPayload() {
        // ADR 0003 on main (docs/adr/0003-odoo19-menu-sync-mode-toggle.md — see the
        // note in data/bonat_company_fields.xml about this branch's own, different
        // ADR 0003): 'template' pushes product.template rows so redemption's
        // allowed_products IDs resolve against templates; 'variant' (default) is
        // today's unchanged product.product behavior.
        const isTemplateMode = this.bonat.menuSyncMode === "template";
        const productModelName = isTemplateMode ? "product.template" : "product.product";
        // this.bonat.discountProduct is always a product.product record (loaded by
        // loadBonatDiscountProduct). In template mode the iterated ids are template
        // ids, a separate sequence (ADR 0003 on main, Decision 4) — compare against
        // the discount product's own template id instead, or the exclusion below
        // would silently compare unrelated id spaces. available_in_pos usually
        // excludes it too, but NOT always: README's "Can this build run on a
        // self-hosted 19.0 instance?" documents setting available_in_pos=True on the
        // discount product as the workaround for the missing
        // pos.data.loadProductFromPos() there — in that configuration this ID check
        // is the ONLY guard excluding the discount product from the synced catalog,
        // not defense in depth on top of available_in_pos.
        const discountProductId = isTemplateMode
            ? this.bonat.discountProduct?.product_tmpl_id?.id
            : this.bonat.discountProduct?.id;
        const products = (this.models[productModelName]?.getAll?.() || [])
            .filter(
                (product) =>
                    product.available_in_pos !== false && product.id !== discountProductId
            )
            .map((product) => ({
                id: product.id,
                name: product.display_name || product.name || "",
                // product.template has no lst_price field (Challenge F2 on the
                // classic build's BON-2420): its list_price already is the
                // effective price (no variant price_extra to add), so mirror it
                // under the key Bonat's odooPartnerMenuMapper actually reads.
                lst_price: isTemplateMode
                    ? product.list_price || 0
                    : typeof product.lst_price === "number"
                      ? product.lst_price
                      : product.list_price || 0,
                available_in_pos: true,
                pos_categ_ids: (product.pos_categ_ids || []).map((categ) => ({ id: categ.id })),
            }))
            // Local-only records carry non-numeric ids; Bonat can't key on those.
            .filter((product) => Number.isInteger(product.id) && product.name);

        const categories = (this.models["pos.category"]?.getAll?.() || [])
            .map((categ) => ({ id: categ.id, name: categ.name || "" }))
            .filter((categ) => Number.isInteger(categ.id) && categ.name);

        return {
            merchant_id: this.bonat.merchantId,
            source: "odoo_online_pos",
            demo: this.bonat.demoMode,
            categories,
            products,
        };
    },

    /** Read the Bonat configuration off res.company and pos.config. */
    async loadBonatConfig() {
        const companyId = this.config?.company_id?.id ?? this.company?.id;
        if (!companyId) {
            console.warn("[bonat] no company id available, integration disabled");
            return;
        }

        const rows = await this.data.read(
            "res.company",
            [companyId],
            [
                "x_bonat_enabled",
                "x_bonat_api_key",
                "x_bonat_merchant_id",
                "x_bonat_merchant_name",
                "x_bonat_demo_mode",
                "x_bonat_menu_sync_mode",
                "x_bonat_api_url",
                "x_bonat_api_url_staging",
            ]
        );
        const row = Array.isArray(rows) ? rows[0] : rows;
        if (!row) {
            console.warn("[bonat] company read returned nothing, integration disabled");
            return;
        }

        // Odoo returns false for empty char fields; normalize to "".
        const str = (value) => (typeof value === "string" ? value : "");

        Object.assign(this.bonat, {
            enabled: !!row.x_bonat_enabled,
            apiKey: str(row.x_bonat_api_key),
            merchantId: str(row.x_bonat_merchant_id),
            merchantName: str(row.x_bonat_merchant_name),
            demoMode: !!row.x_bonat_demo_mode,
            // No DB-level default is possible on this manual column (see the
            // comment in data/bonat_company_fields.xml) — anything but the
            // literal "template" is treated as variant-level, so an unset
            // (NULL) column reads exactly like an explicit "variant".
            menuSyncMode: row.x_bonat_menu_sync_mode === "template" ? "template" : "variant",
        });

        const params = await this.loadBonatUrlParameters();
        this.bonat.apiUrl =
            params[PARAM_API_URL] || str(row.x_bonat_api_url) || BONAT_API_URL_DEFAULT;
        this.bonat.apiUrlStaging =
            params[PARAM_API_URL_STAGING] ||
            str(row.x_bonat_api_url_staging) ||
            BONAT_API_URL_STAGING_DEFAULT;

        if (this.bonat.demoMode) {
            // INFO, not warn: this is a normal operating mode and the POS already
            // shows a banner. Grep "[bonat] Demo Mode" to audit a session.
            console.log(
                "[bonat] Demo Mode is ON, outbound calls go to the staging environment." +
                    " No real loyalty transactions will be recorded."
            );
        }

        if (this.bonat.enabled) {
            await this.loadBonatDiscountProduct();
            await this.loadBonatVoucherPaymentMethod();
        }
    },

    /**
     * Best-effort read of the two ir.config_parameter overrides.
     *
     * On-premise these are authoritative, read with sudo() inside
     * res.company._get_bonat_api_base_url(). Here the POS client runs as the
     * cashier, who normally cannot read ir.config_parameter, so an AccessError is
     * the expected outcome rather than a fault. Returns {} in that case and the
     * caller falls back to the company field.
     */
    async loadBonatUrlParameters() {
        try {
            const rows = await this.data.searchRead(
                "ir.config_parameter",
                [["key", "in", [PARAM_API_URL, PARAM_API_URL_STAGING]]],
                ["key", "value"]
            );
            return Object.fromEntries(
                (rows || [])
                    .filter((r) => typeof r.value === "string" && r.value)
                    .map((r) => [r.key, r.value])
            );
        } catch {
            // Expected for a non-admin cashier. Not logged at error level.
            return {};
        }
    },

    /**
     * Resolve pos.config.x_bonat_discount_product_id and make sure the product
     * exists in the POS registry, so promo_code_button.js can hand a real
     * product.product record to addLineToOrder() for type=1 codes.
     */
    async loadBonatDiscountProduct() {
        let configRow;
        try {
            const rows = await this.data.read(
                "pos.config",
                [this.config.id],
                ["x_bonat_discount_product_id"]
            );
            configRow = Array.isArray(rows) ? rows[0] : rows;
        } catch (error) {
            console.error("[bonat] could not read the discount product setting:", error);
            return;
        }

        const raw = configRow?.x_bonat_discount_product_id;
        // A many2one read comes back as [id, display_name], or false when unset.
        const productId = Array.isArray(raw) ? raw[0] : raw || null;
        if (!productId) {
            // Not an error: only type=1 codes need it, and the POS shows a clear
            // dialog if one arrives while this is unset.
            console.log("[bonat] no discount product configured on this POS config");
            return;
        }

        // Already in the registry, e.g. because it is available_in_pos anyway.
        let product = this.models["product.product"].get(productId);
        if (product) {
            this.bonat.discountProduct = product;
            return;
        }

        try {
            const detail = await this.data.read("product.product", [productId], [
                "product_tmpl_id",
            ]);
            const tmplRaw = (Array.isArray(detail) ? detail[0] : detail)?.product_tmpl_id;
            const tmplId = Array.isArray(tmplRaw) ? tmplRaw[0] : tmplRaw;
            if (!tmplId) {
                console.error("[bonat] discount product", productId, "has no template");
                return;
            }
            /*
             * loadProductFromPos() is the standard entry point on saas~19.4, but it
             * does NOT exist on the 19.0 series: verified against
             * odoo19.bonat.io (19.0-20260630), whose data service offers read,
             * searchRead, call, silentCall and callRelated only.
             *
             * Rather than guess at a replacement, fail loudly with the fix. On 19.0
             * the workaround is to tick "Available in POS" on the Bonat discount
             * product: it is then part of the normal POS load and the fast path
             * above resolves it without needing this branch at all. The only cost
             * is that the product becomes visible in the cashier's grid.
             */
            if (typeof this.data.loadProductFromPos !== "function") {
                console.error(
                    "[bonat] this Odoo build has no data.loadProductFromPos, so the discount" +
                        " product cannot be pulled into the POS on demand. Set 'Available in POS'" +
                        " on the Bonat discount product to make whole-order (type 1) codes work."
                );
                return;
            }
            // Loads the template, its variants and their relations into the registry.
            await this.data.loadProductFromPos([tmplId]);
            product = this.models["product.product"].get(productId);
        } catch (error) {
            console.error("[bonat] failed to load the discount product into the POS:", error);
            return;
        }

        if (!product) {
            console.error(
                "[bonat] discount product",
                productId,
                "could not be resolved after loading; type=1 codes will be refused"
            );
            return;
        }
        this.bonat.discountProduct = product;
    },

    /**
     * Resolve pos.config.x_bonat_voucher_payment_method_id and cache its id.
     *
     * Unlike the discount product, payment methods are always part of the
     * standard POS payload (this.config.payment_method_ids), so no on-demand
     * load into the registry is needed here — just remember which one the
     * merchant picked, the same way loadBonatDiscountProduct resolves its
     * own x_ field.
     */
    async loadBonatVoucherPaymentMethod() {
        let configRow;
        try {
            const rows = await this.data.read(
                "pos.config",
                [this.config.id],
                ["x_bonat_voucher_payment_method_id"]
            );
            configRow = Array.isArray(rows) ? rows[0] : rows;
        } catch (error) {
            console.error("[bonat] could not read the voucher payment method setting:", error);
            return;
        }

        const raw = configRow?.x_bonat_voucher_payment_method_id;
        // A many2one read comes back as [id, display_name], or false when unset.
        const methodId = Array.isArray(raw) ? raw[0] : raw || null;
        if (!methodId) {
            // Not an error: voucher payment-line enforcement is optional. Unset
            // means the voucher stays a banner only, same as before this ticket.
            console.log("[bonat] no voucher payment method configured on this POS config");
            return;
        }

        // Must be linked to THIS config's payment_method_ids, not just exist
        // company-wide — otherwise addPaymentline() would attach a line for a
        // method this session's POS was never configured to accept.
        if (!(this.config.payment_method_ids || []).some((pm) => pm.id === methodId)) {
            console.warn(
                "[bonat] configured voucher payment method",
                methodId,
                "is not linked to this POS config; voucher payment-line enforcement disabled"
            );
            return;
        }
        this.bonat.voucherPaymentMethodId = methodId;
    },
});
