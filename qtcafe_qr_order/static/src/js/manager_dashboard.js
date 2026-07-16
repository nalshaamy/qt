/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";

const stateLabels = {new:"جديد", accepted:"تم الاعتماد", preparing:"قيد التحضير", ready:"منفذ", cancelled:"ملغي"};
const typeLabels = {dine_in:"محلي", takeaway:"سفري", car:"طلب سيارة", delivery:"توصيل"};
const paymentLabels = {cash:"نقدًا", card:"بطاقة", wallet:"محفظة إلكترونية"};

function money(value) { return Number(value || 0).toFixed(2); }
function formatDateTime(value) { return value ? String(value).replace("T", " ").slice(0, 16) : "-"; }

function activateDashboardTab(tabName) {
    document.querySelectorAll(".qt-manager-tab").forEach((button) => button.classList.toggle("active", button.dataset.dashboardTab === tabName));
    document.querySelectorAll(".qt-dashboard-page").forEach((page) => page.classList.toggle("active", page.dataset.dashboardPage === tabName));
    window.scrollTo({top: 0, behavior: "smooth"});
}

function getFilters() {
    return {
        date_from: document.querySelector("#filter-date-from")?.value || false,
        date_to: document.querySelector("#filter-date-to")?.value || false,
        state: document.querySelector("#filter-state")?.value || false,
        pos_config_id: document.querySelector("#filter-pos")?.value || false,
        customer_type: document.querySelector("#filter-customer-type")?.value || false,
    };
}

function renderKpis(summary) {
    const cards = [
        ["إجمالي الطلبات", summary.total_orders, "orders", "◫"],
        ["المبيعات المنفذة", `${money(summary.total_sales)} ر.س`, "sales", "↗"],
        ["متوسط الطلب", `${money(summary.average_order)} ر.س`, "average", "≈"],
        ["العملاء المسجلون", summary.registered_customers, "customers", "★"],
        ["جديد", summary.new, "new", "●"],
        ["قيد التحضير", summary.preparing, "preparing", "◷"],
        ["منفذ", summary.ready, "ready", "✓"],
        ["ملغي", summary.cancelled, "cancelled", "×"],
    ];
    const box = document.querySelector("#dashboard-kpis");
    box.innerHTML = cards.map(([label,value,css,icon]) => `
        <article class="qt-kpi-card qt-kpi-${css}">
            <div class="qt-kpi-icon">${icon}</div><span>${label}</span><strong>${value}</strong>
        </article>`).join("");
}

function renderTopProducts(products) {
    const box = document.querySelector("#top-products");
    if (!products.length) { box.innerHTML = '<div class="qt-manager-empty">لا توجد بيانات.</div>'; return; }
    const maxQty = Math.max(...products.map((item) => Number(item.qty || 0)), 1);
    box.innerHTML = products.map((item,index) => `
        <div class="qt-product-rank">
            <div class="qt-product-rank-head"><span>${index+1}. ${item.name}</span><strong>${Number(item.qty||0).toFixed(0)} طلب</strong></div>
            <div class="qt-product-bar"><span style="width:${(Number(item.qty||0)/maxQty)*100}%"></span></div>
            <small>${money(item.sales)} ر.س</small>
        </div>`).join("");
}

function renderBreakdown(selector, values, labels) {
    const box = document.querySelector(selector);
    const entries = Object.entries(values || {});
    const total = entries.reduce((sum,[,value]) => sum + Number(value || 0), 0) || 1;
    box.innerHTML = entries.map(([key,value]) => `
        <div class="qt-breakdown-row">
            <div><span>${labels[key] || key}</span><strong>${value}</strong></div>
            <div class="qt-breakdown-bar"><span style="width:${Number(value||0)/total*100}%"></span></div>
        </div>`).join("");
}


function renderDailyComparison(highlights) {
    const box = document.querySelector("#daily-comparison");
    const items = [
        ["أعلى مبيعات", highlights?.highest_sales_day, "sales-high"],
        ["أقل مبيعات", highlights?.lowest_sales_day, "sales-low"],
        ["الأكثر طلبًا", highlights?.highest_orders_day, "orders-high"],
        ["الأقل طلبًا", highlights?.lowest_orders_day, "orders-low"],
    ];
    box.innerHTML = items.map(([label,item,css]) => `
        <article class="qt-day-compare-card ${css}">
            <span>${label}</span>
            <strong>${item?.date || "-"}</strong>
            <small>${css.includes("sales") ? `${money(item?.sales || 0)} ر.س` : `${item?.orders || 0} طلب`}</small>
        </article>
    `).join("");
}

function renderTopCustomers(customers) {
    const box = document.querySelector("#top-customers");
    if (!customers.length) { box.innerHTML = '<div class="qt-manager-empty">لا توجد بيانات عملاء منفذة ضمن الفترة.</div>'; return; }
    box.innerHTML = customers.map((customer,index) => `
        <article class="qt-vip-customer-card ${index < 3 ? `top-${index+1}` : ""}">
            <div class="qt-vip-rank">${index+1}</div>
            <div class="qt-vip-avatar">${(customer.name || "ع").trim().charAt(0)}</div>
            <div class="qt-vip-info"><strong>${customer.name || "عميل"}</strong><span>${customer.mobile || "بدون جوال"}</span><small>آخر طلب: ${formatDateTime(customer.last_order)}</small></div>
            <div class="qt-vip-stats"><span><b>${customer.orders}</b> زيارة</span><span><b>${money(customer.spent)}</b> ر.س</span><span>متوسط ${money(customer.average_order)} ر.س</span></div>
        </article>`).join("");
    const best = document.querySelector("#best-customer-card");
    const customer = customers[0];
    best.innerHTML = `<div class="qt-best-customer"><div class="qt-vip-avatar">${(customer.name||"ع").charAt(0)}</div><strong>${customer.name}</strong><span>${customer.orders} زيارة</span><b>${money(customer.spent)} ر.س</b></div>`;
}

function renderOrders(orders) {
    const body = document.querySelector("#recent-orders-body");
    if (!orders.length) {
        body.innerHTML = '<tr><td colspan="9" class="qt-manager-empty">لا توجد طلبات.</td></tr>';
        return;
    }

    body.innerHTML = orders.map((order) => `
        <tr class="qt-clickable-order-row" data-order-id="${order.id}" tabindex="0">
            <td><strong>${order.name || "-"}</strong></td>
            <td>${order.customer_name || "-"}</td>
            <td><span class="qt-order-chip">${order.order_type_label || typeLabels[order.order_type] || "-"}</span></td>
            <td>${order.payment_method_label || paymentLabels[order.payment_method] || "-"}</td>
            <td><span class="qt-manager-status qt-manager-status-${order.state}">${order.state_label || stateLabels[order.state] || order.state}</span></td>
            <td>${order.pos_name || "-"}</td>
            <td>${money(order.amount_total)} ر.س</td>
            <td>${formatDateTime(order.create_date)}</td>
            <td><button type="button" class="qt-view-order-details" data-order-id="${order.id}">عرض التفاصيل</button></td>
        </tr>`).join("");

    const orderMap = new Map(orders.map((order) => [Number(order.id), order]));

    const showOrder = (orderId) => {
        const order = orderMap.get(Number(orderId));
        if (!order) {
            alert("تعذر العثور على بيانات الطلب.");
            return;
        }
        renderOrderDetails(order);
        activateDashboardTab("order-details");
    };

    body.querySelectorAll(".qt-view-order-details").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            showOrder(button.dataset.orderId);
        });
    });

    body.querySelectorAll(".qt-clickable-order-row").forEach((row) => {
        row.addEventListener("click", () => showOrder(row.dataset.orderId));
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                showOrder(row.dataset.orderId);
            }
        });
    });
}

function renderOrderDetails(order) {
    const title = document.querySelector("#order-details-title");
    const box = document.querySelector("#order-details-content");
    title.textContent = order.name || "تفاصيل الطلب";

    const extraDetails = [];
    if (order.table_name) extraDetails.push(`<div><span>الطاولة</span><strong>${order.table_name}</strong></div>`);
    if (order.car_details) extraDetails.push(`<div><span>بيانات السيارة</span><strong>${order.car_details}</strong></div>`);
    if (order.delivery_distance_km) extraDetails.push(`<div><span>مسافة التوصيل</span><strong>${Number(order.delivery_distance_km).toFixed(2)} كم</strong></div>`);
    if (order.delivery_google_maps_url) extraDetails.push(`<div><span>موقع التوصيل</span><strong><a href="${order.delivery_google_maps_url}" target="_blank" rel="noopener">فتح الخريطة</a></strong></div>`);

    const lines = (order.lines || []).map((line) => `
        <tr>
            <td>${line.product || "-"}</td>
            <td>${Number(line.qty || 0)}</td>
            <td>${money(line.price_unit)} ر.س</td>
            <td>${money(line.subtotal)} ر.س</td>
            <td>${line.note || "-"}</td>
        </tr>`).join("");

    box.innerHTML = `
        <div class="qt-order-details-summary">
            <div><span>الحالة</span><strong class="qt-manager-status qt-manager-status-${order.state}">${order.state_label || stateLabels[order.state] || order.state}</strong></div>
            <div><span>نقطة البيع</span><strong>${order.pos_name || "-"}</strong></div>
            <div><span>التاريخ</span><strong>${formatDateTime(order.create_date)}</strong></div>
            <div><span>نوع العميل</span><strong>${order.customer_type || "-"}</strong></div>
            <div><span>اسم العميل</span><strong>${order.customer_name || "-"}</strong></div>
            <div><span>رقم الجوال</span><strong>${order.customer_mobile || "-"}</strong></div>
            <div><span>نوع الطلب</span><strong>${order.order_type_label || typeLabels[order.order_type] || "-"}</strong></div>
            <div><span>طريقة الدفع</span><strong>${order.payment_method_label || paymentLabels[order.payment_method] || "-"}</strong></div>
            ${extraDetails.join("")}
        </div>
        <div class="qt-order-details-note">
            <span>ملاحظات الطلب</span>
            <p>${order.note || "لا توجد ملاحظات."}</p>
        </div>
        <div class="qt-table-wrap qt-order-lines-table">
            <table>
                <thead><tr><th>المنتج</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th>ملاحظة</th></tr></thead>
                <tbody>${lines || '<tr><td colspan="5" class="qt-manager-empty">لا توجد منتجات.</td></tr>'}</tbody>
                <tfoot><tr><td colspan="3">إجمالي الطلب</td><td colspan="2"><strong>${money(order.amount_total)} ر.س</strong></td></tr></tfoot>
            </table>
        </div>`;
}

function renderStore(store) {
    const title = document.querySelector("#store-status-title");
    const message = document.querySelector("#store-status-message");
    const toggle = document.querySelector("#toggle-store");
    title.textContent = store.is_open ? "المتجر مفتوح" : "المتجر مغلق";
    message.textContent = store.is_open ? "الطلبات متاحة للعملاء الآن." : (store.closed_message || "المتجر مغلق.");
    toggle.textContent = store.is_open ? "إغلاق المتجر" : "فتح المتجر";
    toggle.dataset.open = store.is_open ? "1" : "0";
    toggle.classList.toggle("is-open", store.is_open);
    toggle.classList.toggle("is-closed", !store.is_open);
    document.querySelector("#closed-message").value = store.closed_message || "";
    document.querySelector("#allow-browse-closed").checked = Boolean(store.allow_browse_when_closed);
    document.querySelector("#reopen-at").value = store.reopen_at ? store.reopen_at.replace(" ", "T").slice(0,16) : "";
}

function renderBranches(branches) {
    const box = document.querySelector("#manager-branches");
    if (!branches.length) { box.innerHTML = '<div class="qt-manager-empty">لا توجد فروع مرتبطة.</div>'; return; }
    box.innerHTML = branches.map((branch) => `
        <article class="qt-manager-branch-card ${branch.is_open ? "" : "is-closed"}">
            <div class="qt-manager-branch-head">
                <div><strong>${branch.name}</strong><span>${branch.address || "العنوان غير مضاف"}</span></div>
                <button class="qt-branch-open-toggle ${branch.is_open ? "is-open":"is-closed"}" data-branch-id="${branch.id}" data-open="${branch.is_open ? "1":"0"}">${branch.is_open ? "مفتوح":"مغلق"}</button>
            </div>
            <div class="qt-manager-branch-meta">
                <label>نطاق التوصيل (كم)<input class="qt-branch-distance-input" type="number" min="0" step="0.5" value="${branch.max_distance_km || 0}" data-branch-id="${branch.id}"/></label>
            </div>
            <div class="qt-branch-settings-grid">
                ${[
                    ["enable_dine_in","محلي",branch.enabled_order_types?.dine_in],
                    ["enable_takeaway","سفري",branch.enabled_order_types?.takeaway],
                    ["enable_car_order","طلب سيارة",branch.enabled_order_types?.car],
                    ["enable_delivery","توصيل",branch.enabled_order_types?.delivery],
                    ["enable_cash","نقدًا",branch.enabled_payment_methods?.cash],
                    ["enable_card","بطاقة",branch.enabled_payment_methods?.card],
                    ["enable_wallet","محفظة إلكترونية",branch.enabled_payment_methods?.wallet],
                ].map(([key,label,enabled]) => `
                    <label class="qt-setting-toggle">
                        <input type="checkbox" data-branch-id="${branch.id}" data-setting="${key}" ${enabled ? "checked" : ""}/>
                        <span>${label}</span>
                    </label>
                `).join("")}
            </div>
        </article>`).join("");

    box.querySelectorAll(".qt-branch-open-toggle").forEach((button) => button.addEventListener("click", async () => {
        button.disabled = true;
        try {
            const result = await rpc("/qtcafe/manager/branch/update", {branch_id:Number(button.dataset.branchId), is_open:button.dataset.open !== "1"});
            if (!result?.success) throw new Error(result?.error || "تعذر تحديث الفرع");
            await loadDashboard();
        } catch (error) { alert(error.message); } finally { button.disabled = false; }
    }));

    box.querySelectorAll(".qt-setting-toggle input").forEach((input) => input.addEventListener("change", async () => {
        const payload = {branch_id:Number(input.dataset.branchId)};
        payload[input.dataset.setting] = input.checked;
        const result = await rpc("/qtcafe/manager/branch/update", payload);
        if (!result?.success) {
            input.checked = !input.checked;
            alert(result?.error || "تعذر تحديث الإعداد");
        }
    }));

    box.querySelectorAll(".qt-branch-distance-input").forEach((input) => input.addEventListener("change", async () => {
        const result = await rpc("/qtcafe/manager/branch/update", {
            branch_id:Number(input.dataset.branchId),
            max_distance_km:Number(input.value || 0),
        });
        if (!result?.success) alert(result?.error || "تعذر تحديث نطاق التوصيل");
    }));
}

function renderMenuProducts(products, selectedPosConfigId) {
    const box = document.querySelector("#manager-menu-products");
    if (!selectedPosConfigId) {
        box.innerHTML = '<div class="qt-manager-empty">اختر نقطة البيع من القائمة أعلاه لعرض وتعديل توفر المنتجات.</div>';
        return;
    }
    if (!products.length) { box.innerHTML = '<div class="qt-manager-empty">لا توجد أصناف.</div>'; return; }
    box.innerHTML = products.map((product) => `
        <article class="qt-manager-product-card ${product.available ? "" : "is-sold-out"}">
            <img src="${product.image_url}" alt="${product.name}"/><div class="qt-manager-product-info"><strong>${product.name}</strong><span>${product.category || "بدون تصنيف"}</span><small>${money(product.price)} ر.س</small></div>
            <button class="qt-product-availability-btn ${product.available ? "is-available":"is-unavailable"}" data-product-id="${product.id}" data-available="${product.available ? "1":"0"}">${product.available ? "متوفر":"نفذت الكمية"}</button>
        </article>`).join("");
    box.querySelectorAll(".qt-product-availability-btn").forEach((button) => button.addEventListener("click", async () => {
        button.disabled = true;
        try {
            const result = await rpc("/qtcafe/manager/product/availability", {product_template_id:Number(button.dataset.productId), pos_config_id:Number(selectedPosConfigId), available:button.dataset.available !== "1"});
            if (!result?.success) throw new Error(result?.error || "تعذر تحديث الصنف");
            await loadMenuProducts();
        } catch (error) { alert(error.message); } finally { button.disabled = false; }
    }));
}

function renderTables(tables) {
    const box = document.querySelector("#manager-tables");
    if (!tables.length) { box.innerHTML = '<div class="qt-manager-empty">لم تتم إضافة طاولات بعد.</div>'; return; }
    box.innerHTML = tables.map((table) => `
        <article class="qt-table-admin-card"><div><strong>${table.name}</strong><span>${table.branch_name}</span></div>
        <button class="qt-delete-table" data-table-id="${table.id}">حذف</button></article>`).join("");
    box.querySelectorAll(".qt-delete-table").forEach((button) => button.addEventListener("click", async () => {
        if (!confirm("حذف الطاولة؟")) return;
        const result = await rpc("/qtcafe/manager/table/delete", {table_id:Number(button.dataset.tableId)});
        if (!result?.success) alert(result?.error || "تعذر حذف الطاولة"); else await loadDashboard();
    }));
}

async function loadMenuProducts() {
    const productFilter = document.querySelector("#product-pos-filter");
    const selectedPosConfigId = productFilter?.value || false;
    if (!selectedPosConfigId) {
        renderMenuProducts([], false);
        return;
    }

    const result = await rpc("/qtcafe/manager/products/data", {
        pos_config_id: Number(selectedPosConfigId),
    });
    if (!result?.success) {
        throw new Error(result?.error || "تعذر تحميل منتجات نقطة البيع");
    }
    renderMenuProducts(result.menu_products || [], result.selected_pos_config_id);
}

function populatePosOptions(posConfigs) {
    const options = posConfigs.map((pos) => `<option value="${pos.id}">${pos.name}</option>`).join("");
    const filter = document.querySelector("#filter-pos");
    const current = filter.value;
    filter.innerHTML = '<option value="">كل نقاط البيع</option>' + options;
    filter.value = current;

    const productFilter = document.querySelector("#product-pos-filter");
    const productCurrent = productFilter.value;
    productFilter.innerHTML = '<option value="">اختر نقطة البيع</option>' + options;
    productFilter.value = productCurrent;

    const tableBranch = document.querySelector("#new-table-branch");
    tableBranch.innerHTML = '<option value="">اختر الفرع</option>' + options;
}

async function loadDashboard() {
    const result = await rpc("/qtcafe/manager/dashboard/data", getFilters());
    if (!result?.success) throw new Error(result?.error || "تعذر تحميل لوحة التحكم");
    renderKpis(result.summary); renderTopProducts(result.top_products || []);
    renderDailyComparison(result.daily_highlights || {});
    renderBreakdown("#order-type-breakdown", result.order_type_counts, typeLabels);
    renderBreakdown("#payment-breakdown", result.payment_counts, paymentLabels);
    renderTopCustomers(result.top_customers || []); renderOrders(result.recent_orders || []);
    renderStore(result.store || {}); renderBranches(result.branches || []);
    renderTables(result.tables || []);
    populatePosOptions(result.pos_configs || []);
}

async function updateStore(values) {
    const result = await rpc("/qtcafe/manager/store/update", values);
    if (!result?.success) throw new Error(result?.error || "تعذر تحديث الإعدادات");
    renderStore(result.store);
}

document.addEventListener("DOMContentLoaded", async () => {
    document.querySelectorAll(".qt-manager-tab").forEach((button) => button.addEventListener("click", () => activateDashboardTab(button.dataset.dashboardTab)));
    document.querySelector("#back-to-orders").addEventListener("click", () => activateDashboardTab("orders"));
    const today = new Date(), prior = new Date(); prior.setDate(today.getDate()-6);
    document.querySelector("#filter-date-from").value = prior.toISOString().slice(0,10);
    document.querySelector("#filter-date-to").value = today.toISOString().slice(0,10);
    document.querySelector("#apply-dashboard-filters").addEventListener("click", loadDashboard);
    document.querySelector("#product-pos-filter").addEventListener("change", async () => {
        try {
            await loadMenuProducts();
        } catch (error) {
            alert(error.message);
        }
    });
    document.querySelector("#toggle-store").addEventListener("click", async (event) => { await updateStore({is_open:event.currentTarget.dataset.open !== "1"}); await loadDashboard(); });
    document.querySelector("#save-store-settings").addEventListener("click", async () => {
        await updateStore({closed_message:document.querySelector("#closed-message").value, reopen_at:document.querySelector("#reopen-at").value || false, allow_browse_when_closed:document.querySelector("#allow-browse-closed").checked});
        await loadDashboard();
    });
    document.querySelector("#add-table").addEventListener("click", async () => {
        const result = await rpc("/qtcafe/manager/table/save", {name:document.querySelector("#new-table-name").value, pos_config_id:document.querySelector("#new-table-branch").value, active:true});
        if (!result?.success) alert(result?.error || "تعذر إضافة الطاولة"); else { document.querySelector("#new-table-name").value = ""; await loadDashboard(); }
    });
    try { await loadDashboard(); } catch (error) { console.error(error); alert(error.message || "تعذر تحميل لوحة التحكم"); }
});
