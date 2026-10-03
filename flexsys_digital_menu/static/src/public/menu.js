(() => {
    "use strict";

    const body = document.body;
    const slug = body.dataset.menuSlug;
    const defaultLanguage = body.dataset.defaultLanguage || "ar";
    const dataUrl = body.dataset.dataUrl || `/menu/${encodeURIComponent(slug)}/data`;
    if (!slug) return;

    const el = (id) => document.getElementById(id);
    const state = {
        language: localStorage.getItem(`fsm:${slug}:lang`) || defaultLanguage,
        branch: localStorage.getItem(`fsm:${slug}:branch`) || "",
        query: "",
        data: null,
    };

    const strings = {
        ar: {
            search: "ابحث في المنيو",
            all: "الكل",
            featured: "الأكثر تميزًا",
            unavailable: "المنيو غير متاح حاليًا",
            noResults: "لا توجد منتجات مطابقة لبحثك",
            soldOut: "غير متوفر حاليًا",
            calories: "السعرات",
            allergens: "الحساسية",
            ingredients: "المكونات",
            variants: "الخيارات",
            from: "يبدأ من",
            branch: "الفرع",
            vegetarian: "نباتي",
            vegan: "نباتي بالكامل",
            spicy: "حار",
            description: "الوصف",
            recommended: "قد يعجبك أيضًا",
            readMore: "اقرأ عني أكثر",
        },
        en: {
            search: "Search the menu",
            all: "All",
            featured: "Featured",
            unavailable: "This menu is currently unavailable",
            noResults: "No products match your search",
            soldOut: "Sold out",
            calories: "Calories",
            allergens: "Allergens",
            ingredients: "Ingredients",
            variants: "Options",
            from: "From",
            branch: "Branch",
            vegetarian: "Vegetarian",
            vegan: "Vegan",
            spicy: "Spicy",
            description: "Description",
            recommended: "You may also like",
            readMore: "Read more about me",
        },
    };

    function t(key) {
        return (strings[state.language] || strings.en)[key] || key;
    }

    function node(tag, className, text) {
        const item = document.createElement(tag);
        if (className) item.className = className;
        if (text !== undefined && text !== null) item.textContent = text;
        return item;
    }

    function formatPrice(amount) {
        const currency = state.data?.currency?.code || "SAR";
        const locale = state.language === "ar" ? "ar-SA" : "en-US";
        try {
            return new Intl.NumberFormat(locale, {
                style: "currency",
                currency,
                minimumFractionDigits: state.data?.currency?.decimal_places ?? 2,
                maximumFractionDigits: state.data?.currency?.decimal_places ?? 2,
            }).format(Number(amount || 0));
        } catch (_) {
            return `${Number(amount || 0).toFixed(2)} ${state.data?.currency?.symbol || currency}`;
        }
    }

    async function loadData() {
        const params = new URLSearchParams({ lang: state.language });
        if (state.branch) params.set("branch", state.branch);
        const separator = dataUrl.includes("?") ? "&" : "?";
        const response = await fetch(`${dataUrl}${separator}${params.toString()}`, {
            headers: { Accept: "application/json" },
            credentials: "same-origin",
        });
        if (!response.ok) throw new Error("Unable to load menu");
        state.data = await response.json();
        if (state.data.menu.branch?.key) state.branch = state.data.menu.branch.key;
        render();
    }

    function renderHeader() {
        const data = state.data.menu;
        document.documentElement.lang = state.language;
        document.documentElement.dir = state.language === "ar" ? "rtl" : "ltr";
        el("fsm-menu-title").textContent = data.name || "";
        el("fsm-menu-tagline").textContent = data.tagline || "";
        el("fsm-footer-name").textContent = data.name || "";
        el("fsm-search").placeholder = t("search");
        el("fsm-language-toggle").textContent = state.language === "ar" ? "EN" : "ع";
        const hero = el("fsm-hero-media");
        hero.style.backgroundImage = data.hero_url ? `url("${data.hero_url}")` : "none";

        const select = el("fsm-branch-select");
        select.textContent = "";
        if (data.branches.length > 1) {
            const placeholder = node("option", "", t("branch"));
            placeholder.value = "";
            select.appendChild(placeholder);
            data.branches.forEach((branch) => {
                const option = node("option", "", branch.name);
                option.value = branch.key;
                option.selected = branch.key === state.branch;
                select.appendChild(option);
            });
            select.hidden = false;
        } else {
            select.hidden = true;
        }
        el("fsm-language-toggle").hidden = data.languages.length < 2;
    }

    function productMatches(product) {
        if (!state.query) return true;
        const q = state.query.toLocaleLowerCase();
        return (product.search_text || "").toLocaleLowerCase().includes(q);
    }

    function makeBadge(text, muted = false) {
        return node("span", `fsm-badge${muted ? " muted" : ""}`, text);
    }

    function productCard(product) {
        const card = node("article", "fsm-card");
        card.tabIndex = 0;
        card.dataset.productKey = product.key;

        const imageWrap = node("div", "fsm-card-image-wrap");
        if (product.image_url) {
            const img = node("img", "fsm-card-image");
            img.src = product.image_url;
            img.loading = "lazy";
            img.alt = product.name;
            imageWrap.appendChild(img);
        } else {
            imageWrap.appendChild(node("div", "fsm-card-placeholder", "✦"));
        }
        card.appendChild(imageWrap);

        if (product.availability === "sold_out") {
            card.appendChild(node("span", "fsm-sold-out", t("soldOut")));
        }

        const content = node("div", "fsm-card-content");
        const top = node("div", "fsm-card-top");
        top.appendChild(node("h3", "fsm-card-name", product.name));
        if (state.data.display?.prices !== false) top.appendChild(node("span", "fsm-price", `${product.price_from ? `${t("from")} ` : ""}${formatPrice(product.price)}`));
        content.appendChild(top);
        if (product.description) {
            const descriptionPreview = node("div", "fsm-description-preview");
            descriptionPreview.appendChild(node("p", "fsm-description", product.description));
            const readMore = node("button", "fsm-read-more", t("readMore"));
            readMore.type = "button";
            readMore.addEventListener("click", (event) => {
                event.stopPropagation();
                openProduct(product);
            });
            descriptionPreview.appendChild(readMore);
            content.appendChild(descriptionPreview);
        }

        const meta = node("div", "fsm-meta");
        if (product.badge) meta.appendChild(makeBadge(product.badge));
        if (product.calories) meta.appendChild(makeBadge(`${product.calories} kcal`, true));
        if (product.vegetarian) meta.appendChild(makeBadge(t("vegetarian"), true));
        if (product.vegan) meta.appendChild(makeBadge(t("vegan"), true));
        if (product.spicy_level && product.spicy_level !== "none") meta.appendChild(makeBadge(t("spicy"), true));
        if (meta.childNodes.length) content.appendChild(meta);
        card.appendChild(content);

        card.addEventListener("click", () => openProduct(product));
        card.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") openProduct(product);
        });
        return card;
    }

    function section(title, products, key, slabBackground = "", categoryImage = "") {
        const wrapper = node("section", "fsm-section");
        wrapper.id = `category-${key}`;
        if (slabBackground) wrapper.style.background = slabBackground;
        const inner = node("div", "fsm-section-inner");
        const header = node("div", "fsm-section-header");
        const titleWrap = node("div", "fsm-section-title-wrap");
        if (categoryImage) { const image = node("img", "fsm-section-icon"); image.src = categoryImage; image.alt = ""; image.loading = "lazy"; titleWrap.appendChild(image); }
        titleWrap.appendChild(node("h2", "fsm-section-title", title));
        header.appendChild(titleWrap);
        inner.appendChild(header);
        const grid = node("div", "fsm-grid");
        products.forEach((product) => grid.appendChild(productCard(product)));
        inner.appendChild(grid);
        wrapper.appendChild(inner);
        return wrapper;
    }

    function renderCategories(filteredProducts) {
        const nav = el("fsm-category-nav");
        nav.textContent = "";
        const allButton = node("button", "fsm-category-chip is-active", t("all"));
        allButton.type = "button";
        allButton.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
        nav.appendChild(allButton);
        state.data.categories.forEach((category) => {
            if (!filteredProducts.some((product) => product.category_key === category.key)) return;
            const button = node("button", "fsm-category-chip", `${category.icon ? `${category.icon} ` : ""}${category.name}`);
            button.type = "button";
            button.addEventListener("click", () => {
                document.querySelector(`#category-${CSS.escape(category.key)}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
            });
            nav.appendChild(button);
        });
    }

    function renderProducts() {
        const status = el("fsm-status");
        const featured = el("fsm-featured");
        const sections = el("fsm-sections");
        sections.textContent = "";
        featured.textContent = "";
        featured.hidden = true;
        status.hidden = true;

        if (!state.data.menu.active_now) {
            status.textContent = t("unavailable");
            status.hidden = false;
            renderCategories([]);
            return;
        }

        const filtered = state.data.products.filter(productMatches);
        renderCategories(filtered);
        if (!filtered.length) {
            status.textContent = t("noResults");
            status.hidden = false;
            return;
        }

        const featuredProducts = filtered.filter((product) => product.featured).sort((a, b) => (a.featured_sequence || 10) - (b.featured_sequence || 10));
        if (featuredProducts.length) {
            featured.appendChild(section(t("featured"), featuredProducts, "featured"));
            featured.hidden = false;
        }

        state.data.categories.forEach((category) => {
            const products = filtered.filter((product) => product.category_key === category.key);
            if (products.length) sections.appendChild(section(category.name, products, category.key, category.slab_background, category.image_url));
        });
    }

    function detailRow(label, value) {
        const row = node("div", "fsm-detail-row");
        row.appendChild(node("span", "fsm-detail-label", label));
        row.appendChild(node("div", "", value));
        return row;
    }

    function recommendedProduct(product) {
        const candidates = (state.data?.products || []).filter((item) => (
            item.key !== product.key && item.availability === "available"
        ));
        if (!candidates.length) return null;

        const sameCategory = candidates
            .filter((item) => item.category_key === product.category_key)
            .sort((a, b) => (a.sequence || 10) - (b.sequence || 10));
        if (sameCategory.length) return sameCategory[0];

        const featured = candidates
            .filter((item) => item.featured)
            .sort((a, b) => (a.featured_sequence || 10) - (b.featured_sequence || 10));
        if (featured.length) return featured[0];

        return candidates.sort((a, b) => (a.sequence || 10) - (b.sequence || 10))[0];
    }

    function recommendationCard(product) {
        const card = node("button", "fsm-recommendation-card");
        card.type = "button";
        if (product.image_url) {
            const image = node("img", "fsm-recommendation-image");
            image.src = product.image_url;
            image.alt = product.name;
            image.loading = "lazy";
            card.appendChild(image);
        } else {
            card.appendChild(node("div", "fsm-recommendation-placeholder", "✦"));
        }
        const copy = node("div", "fsm-recommendation-copy");
        copy.appendChild(node("strong", "fsm-recommendation-name", product.name));
        if (state.data.display?.prices !== false) {
            copy.appendChild(node("span", "fsm-recommendation-price", `${product.price_from ? `${t("from")} ` : ""}${formatPrice(product.price)}`));
        }
        card.appendChild(copy);
        card.appendChild(node("span", "fsm-recommendation-arrow", document.documentElement.dir === "rtl" ? "‹" : "›"));
        card.addEventListener("click", () => openProduct(product));
        return card;
    }

    function openProduct(product) {
        const content = el("fsm-sheet-content");
        content.textContent = "";
        if (product.image_url) {
            const image = node("img", "fsm-sheet-image");
            image.src = product.image_url;
            image.alt = product.name;
            content.appendChild(image);
        }
        const bodyContent = node("div", "fsm-sheet-body");
        bodyContent.appendChild(node("h2", "", product.name));
        if (state.data.display?.prices !== false) bodyContent.appendChild(node("div", "fsm-sheet-price", `${product.price_from ? `${t("from")} ` : ""}${formatPrice(product.price)}`));

        if (product.description) {
            const descriptionBox = node("section", "fsm-description-box");
            descriptionBox.appendChild(node("span", "fsm-description-box-label", t("description")));
            descriptionBox.appendChild(node("p", "fsm-description-full", product.description));
            bodyContent.appendChild(descriptionBox);
        }

        const details = node("div", "fsm-detail-list");
        if (product.calories) details.appendChild(detailRow(t("calories"), `${product.calories} kcal`));
        if (product.ingredients) details.appendChild(detailRow(t("ingredients"), product.ingredients));
        if (product.allergens) details.appendChild(detailRow(t("allergens"), product.allergens));
        if (details.childNodes.length) bodyContent.appendChild(details);
        if (product.variants?.length > 1) {
            bodyContent.appendChild(node("h3", "", t("variants")));
            const list = node("div", "fsm-variant-list");
            product.variants.forEach((variant) => {
                const row = node("div", "fsm-variant");
                row.appendChild(node("span", "", variant.name));
                if (state.data.display?.prices !== false) row.appendChild(node("strong", "", formatPrice(variant.price)));
                list.appendChild(row);
            });
            bodyContent.appendChild(list);
        }

        const recommended = recommendedProduct(product);
        if (recommended) {
            const recommendation = node("section", "fsm-recommendation");
            recommendation.appendChild(node("h3", "fsm-recommendation-title", t("recommended")));
            recommendation.appendChild(recommendationCard(recommended));
            bodyContent.appendChild(recommendation);
        }

        content.appendChild(bodyContent);
        el("fsm-sheet-backdrop").hidden = false;
        el("fsm-product-sheet").hidden = false;
        document.body.style.overflow = "hidden";
        history.replaceState(null, "", `#product=${encodeURIComponent(product.key)}`);
        el("fsm-product-sheet").scrollTop = 0;
    }

    function closeProduct() {
        el("fsm-sheet-backdrop").hidden = true;
        el("fsm-product-sheet").hidden = true;
        document.body.style.overflow = "";
        history.replaceState(null, "", window.location.pathname + window.location.search);
    }

    function render() {
        renderHeader();
        renderProducts();
        const hash = new URLSearchParams(location.hash.replace(/^#/, ""));
        const productKey = hash.get("product");
        if (productKey) {
            const product = state.data.products.find((item) => item.key === productKey);
            if (product) openProduct(product);
        }
    }

    el("fsm-search").addEventListener("input", (event) => {
        state.query = event.target.value.trim();
        renderProducts();
    });
    el("fsm-language-toggle").addEventListener("click", async () => {
        state.language = state.language === "ar" ? "en" : "ar";
        localStorage.setItem(`fsm:${slug}:lang`, state.language);
        await loadData();
    });
    el("fsm-branch-select").addEventListener("change", async (event) => {
        state.branch = event.target.value;
        localStorage.setItem(`fsm:${slug}:branch`, state.branch);
        await loadData();
    });
    el("fsm-sheet-close").addEventListener("click", closeProduct);
    el("fsm-sheet-backdrop").addEventListener("click", closeProduct);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !el("fsm-product-sheet").hidden) closeProduct();
    });

    loadData().catch(() => {
        const status = el("fsm-status");
        status.textContent = state.language === "ar" ? "تعذر تحميل المنيو." : "Unable to load the menu.";
        status.hidden = false;
    });
})();
