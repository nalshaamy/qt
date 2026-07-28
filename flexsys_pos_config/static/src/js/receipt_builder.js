/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const BLOCK_LIBRARY = [
    { type: "logo", title: "Logo", icon: "fa-image" },
    { type: "company", title: "Company Information", icon: "fa-building" },
    { type: "queue", title: "Queue Number", icon: "fa-ticket" },
    { type: "order_info", title: "Order Information", icon: "fa-info-circle" },
    { type: "customer", title: "Customer Information", icon: "fa-user" },
    { type: "items", title: "Items", icon: "fa-list" },
    { type: "totals", title: "Totals", icon: "fa-calculator" },
    { type: "payments", title: "Payments", icon: "fa-credit-card" },
    { type: "qr", title: "QR Code", icon: "fa-qrcode" },
    { type: "message", title: "Custom Message", icon: "fa-comment" },
    { type: "divider", title: "Divider", icon: "fa-minus" },
    { type: "spacer", title: "Spacer", icon: "fa-arrows-v" },
    { type: "footer", title: "Footer", icon: "fa-align-center" },
];

const BLOCK_ICONS = Object.fromEntries(BLOCK_LIBRARY.map((item) => [item.type, item.icon]));
BLOCK_ICONS.header = "fa-building";

export class FlexsysReceiptBuilder extends Component {
    static template = "flexsys_pos_config.ReceiptBuilder";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            saving: false,
            adding: false,
            templates: [],
            selectedTemplateId: null,
            selectedTemplate: null,
            blocks: [],
            selectedBlockId: null,
            dirtyBlockIds: [],
        });
        this.blockLibrary = BLOCK_LIBRARY;
        onWillStart(() => this.loadTemplates());
    }

    get selectedBlock() {
        return this.state.blocks.find((block) => block.id === this.state.selectedBlockId) || null;
    }

    get enabledBlocks() {
        return [...this.state.blocks]
            .filter((block) => block.enabled)
            .sort((a, b) => a.sequence - b.sequence || a.id - b.id);
    }

    get selectedBlockIcon() {
        return this.getBlockIcon(this.selectedBlock?.block_type);
    }

    get posDisplayName() {
        const value = this.state.selectedTemplate?.pos_config_id;
        return Array.isArray(value) ? value[1] : "Point of Sale";
    }

    getBlockIcon(blockType) {
        return BLOCK_ICONS[blockType] || "fa-square";
    }

    getBlockClass(block) {
        const alignment = block.alignment || "center";
        const size = block.font_size || "normal";
        return `o_flexsys_live_block o_flexsys_live_${block.block_type} text-${alignment} fs-${size}${block.bold ? " fw-bold" : ""}${block.id === this.state.selectedBlockId ? " selected" : ""}`;
    }

    async loadTemplates() {
        this.state.loading = true;
        try {
            const templates = await this.orm.searchRead(
                "flexsys.pos.receipt.template",
                [["active", "=", true]],
                ["name", "pos_config_id", "is_default", "description"],
                { order: "is_default desc, name asc" }
            );
            this.state.templates = templates;
            if (templates.length) {
                await this.selectTemplate(templates[0].id);
            }
        } finally {
            this.state.loading = false;
        }
    }

    async selectTemplate(templateId) {
        const parsedId = Number(templateId);
        this.state.selectedTemplateId = parsedId;
        this.state.selectedTemplate = this.state.templates.find((item) => item.id === parsedId) || null;
        const blocks = await this.orm.searchRead(
            "flexsys.pos.receipt.block",
            [["template_id", "=", parsedId]],
            ["sequence", "enabled", "block_type", "title", "show_title", "content", "alignment", "font_size", "bold"],
            { order: "sequence asc, id asc" }
        );
        this.state.blocks = blocks;
        this.state.selectedBlockId = blocks[0]?.id || null;
        this.state.dirtyBlockIds = [];
    }

    onTemplateChange(ev) {
        this.selectTemplate(ev.target.value);
    }

    selectBlock(blockId) {
        this.state.selectedBlockId = blockId;
    }

    markDirty(blockId) {
        if (!this.state.dirtyBlockIds.includes(blockId)) {
            this.state.dirtyBlockIds.push(blockId);
        }
    }

    updateBlockField(field, value) {
        const block = this.selectedBlock;
        if (!block) return;
        block[field] = value;
        this.markDirty(block.id);
    }

    onTitleInput(ev) { this.updateBlockField("title", ev.target.value); }
    onContentInput(ev) { this.updateBlockField("content", ev.target.value); }
    onEnabledChange(ev) { this.updateBlockField("enabled", ev.target.checked); }
    onShowTitleChange(ev) { this.updateBlockField("show_title", ev.target.checked); }
    onAlignmentChange(ev) { this.updateBlockField("alignment", ev.target.value); }
    onFontSizeChange(ev) { this.updateBlockField("font_size", ev.target.value); }
    onBoldChange(ev) { this.updateBlockField("bold", ev.target.checked); }

    moveBlock(direction) {
        const index = this.state.blocks.findIndex((block) => block.id === this.state.selectedBlockId);
        const targetIndex = index + direction;
        if (index < 0 || targetIndex < 0 || targetIndex >= this.state.blocks.length) return;
        const current = this.state.blocks[index];
        const target = this.state.blocks[targetIndex];
        [current.sequence, target.sequence] = [target.sequence, current.sequence];
        this.state.blocks.splice(index, 1);
        this.state.blocks.splice(targetIndex, 0, current);
        this.markDirty(current.id);
        this.markDirty(target.id);
    }

    async addBlock(type, title) {
        if (!this.state.selectedTemplateId || this.state.adding) return;
        this.state.adding = true;
        try {
            const lastSequence = Math.max(0, ...this.state.blocks.map((block) => block.sequence || 0));
            const ids = await this.orm.create("flexsys.pos.receipt.block", [{
                template_id: this.state.selectedTemplateId,
                sequence: lastSequence + 10,
                block_type: type,
                title,
                alignment: ["items", "totals", "payments", "order_info", "customer"].includes(type) ? "left" : "center",
            }]);
            await this.selectTemplate(this.state.selectedTemplateId);
            this.state.selectedBlockId = ids[0];
            this.notification.add(`${title} added.`, { type: "success" });
        } finally {
            this.state.adding = false;
        }
    }

    async duplicateBlock() {
        const block = this.selectedBlock;
        if (!block) return;
        const ids = await this.orm.create("flexsys.pos.receipt.block", [{
            template_id: this.state.selectedTemplateId,
            sequence: block.sequence + 1,
            enabled: block.enabled,
            block_type: block.block_type,
            title: `${block.title} Copy`,
            show_title: block.show_title,
            content: block.content || false,
            alignment: block.alignment,
            font_size: block.font_size,
            bold: block.bold,
        }]);
        await this.selectTemplate(this.state.selectedTemplateId);
        this.state.selectedBlockId = ids[0];
        this.notification.add("Block duplicated.", { type: "success" });
    }

    async deleteBlock() {
        const block = this.selectedBlock;
        if (!block) return;
        await this.orm.unlink("flexsys.pos.receipt.block", [block.id]);
        await this.selectTemplate(this.state.selectedTemplateId);
        this.notification.add("Block removed.", { type: "success" });
    }

    async save() {
        if (!this.state.dirtyBlockIds.length) {
            this.notification.add("No changes to save.", { type: "info" });
            return;
        }
        this.state.saving = true;
        try {
            const dirtyIds = new Set(this.state.dirtyBlockIds);
            for (const block of this.state.blocks.filter((item) => dirtyIds.has(item.id))) {
                await this.orm.write("flexsys.pos.receipt.block", [block.id], {
                    sequence: block.sequence,
                    enabled: block.enabled,
                    title: block.title,
                    show_title: block.show_title,
                    content: block.content || false,
                    alignment: block.alignment,
                    font_size: block.font_size,
                    bold: block.bold,
                });
            }
            this.state.dirtyBlockIds = [];
            this.notification.add("Receipt template saved.", { type: "success" });
        } catch (error) {
            this.notification.add("The receipt template could not be saved.", { type: "danger" });
            throw error;
        } finally {
            this.state.saving = false;
        }
    }

    async openTemplates() {
        await this.action.doAction("flexsys_pos_config.action_flexsys_receipt_templates");
    }

    async openPreview() {
        if (!this.state.selectedTemplateId) return;
        if (this.state.dirtyBlockIds.length) await this.save();
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "Receipt Preview",
            res_model: "flexsys.pos.receipt.preview",
            views: [[false, "form"]],
            target: "new",
            context: { default_template_id: this.state.selectedTemplateId },
        });
    }
}

registry.category("actions").add("flexsys_pos_config.receipt_builder", FlexsysReceiptBuilder);
