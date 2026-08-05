/** @odoo-module **/

const SELECTORS = {
    open: "[data-fs-command-open]",
    backdrop: "[data-fs-command-backdrop]",
    input: "[data-fs-command-input]",
    results: "[data-fs-command-results]",
};

class FlexSysCommandPalette {
    constructor(root) {
        this.root = root;
        this.backdrop = root.querySelector(SELECTORS.backdrop);
        this.input = root.querySelector(SELECTORS.input);
        this.results = root.querySelector(SELECTORS.results);
        this.activeIndex = 0;
        this.items = [];
        this.requestId = 0;
        this.bind();
    }

    bind() {
        this.root.querySelector(SELECTORS.open)?.addEventListener("click", () => this.open());
        this.backdrop?.addEventListener("click", (event) => {
            if (event.target === this.backdrop) this.close();
        });
        this.input?.addEventListener("input", () => this.load(this.input.value));
        this.input?.addEventListener("keydown", (event) => this.onInputKeydown(event));
    }

    async open() {
        this.backdrop.hidden = false;
        document.documentElement.classList.add("fs-command-open");
        this.input.value = "";
        this.input.focus();
        await this.load("");
    }

    close() {
        this.backdrop.hidden = true;
        document.documentElement.classList.remove("fs-command-open");
    }

    async load(query) {
        const currentRequest = ++this.requestId;
        this.results.innerHTML = '<div class="fs-command-state"><span class="fa fa-spinner fa-spin"/> Loading…</div>';
        try {
            const response = await fetch(`/flexsys/command?q=${encodeURIComponent(query || "")}`, {
                headers: {Accept: "application/json"},
                credentials: "same-origin",
            });
            if (response.status === 401) {
                window.location.assign("/flexsys/login");
                return;
            }
            const payload = await response.json();
            if (currentRequest !== this.requestId) return;
            this.items = Array.isArray(payload.items) ? payload.items : [];
            this.activeIndex = 0;
            this.render();
        } catch (_error) {
            if (currentRequest !== this.requestId) return;
            this.items = [];
            this.results.innerHTML = '<div class="fs-command-state">Unable to load commands.</div>';
        }
    }

    render() {
        this.results.replaceChildren();
        if (!this.items.length) {
            const empty = document.createElement("div");
            empty.className = "fs-command-state";
            empty.textContent = "No matching commands.";
            this.results.appendChild(empty);
            return;
        }
        this.items.forEach((item, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `fs-command-item${index === this.activeIndex ? " is-active" : ""}`;
            button.setAttribute("role", "option");
            button.setAttribute("aria-selected", index === this.activeIndex ? "true" : "false");

            const icon = document.createElement("span");
            icon.className = `fs-command-item-icon fa ${item.icon || "fa-file"}`;
            const content = document.createElement("span");
            content.className = "fs-command-item-content";
            const title = document.createElement("strong");
            title.textContent = item.title || "Untitled";
            const subtitle = document.createElement("small");
            subtitle.textContent = [item.application, item.subtitle].filter(Boolean).join(" · ");
            const arrow = document.createElement("span");
            arrow.className = "fa fa-arrow-right fs-command-item-arrow";
            content.append(title, subtitle);
            button.append(icon, content, arrow);
            button.addEventListener("mouseenter", () => { this.activeIndex = index; this.syncActive(); });
            button.addEventListener("click", () => this.activate(index));
            this.results.appendChild(button);
        });
    }

    syncActive() {
        [...this.results.querySelectorAll(".fs-command-item")].forEach((node, index) => {
            const active = index === this.activeIndex;
            node.classList.toggle("is-active", active);
            node.setAttribute("aria-selected", active ? "true" : "false");
            if (active) node.scrollIntoView({block: "nearest"});
        });
    }

    onInputKeydown(event) {
        if (event.key === "Escape") { event.preventDefault(); this.close(); return; }
        if (!this.items.length) return;
        if (event.key === "ArrowDown") {
            event.preventDefault();
            this.activeIndex = (this.activeIndex + 1) % this.items.length;
            this.syncActive();
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            this.activeIndex = (this.activeIndex - 1 + this.items.length) % this.items.length;
            this.syncActive();
        } else if (event.key === "Enter") {
            event.preventDefault();
            this.activate(this.activeIndex);
        }
    }

    activate(index) {
        const item = this.items[index];
        if (item?.url?.startsWith("/") && !item.url.startsWith("//")) {
            window.location.assign(item.url);
        }
    }
}

function initialize() {
    document.querySelectorAll(".fs-platform-page").forEach((page) => {
        if (page.querySelector(SELECTORS.backdrop)) new FlexSysCommandPalette(page);
    });
    document.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
            const trigger = document.querySelector(SELECTORS.open);
            if (trigger) { event.preventDefault(); trigger.click(); }
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
} else {
    initialize();
}
