/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";

const isRTL = document.documentElement.dir === "rtl";
const UI = isRTL ? {
    active_orders: "الطلبات النشطة", open_tasks: "المهام المفتوحة", delayed_tasks: "المهام المتأخرة", available_stations: "المحطات المتاحة",
    view_details: "عرض التفاصيل", excellent: "ممتاز", stable: "مستقر", warning: "يحتاج متابعة", critical: "حالة حرجة",
    waiting: "انتظار", executing: "تنفيذ", no_stations: "لم تتم إضافة محطات تنفيذ بعد.", no_events: "لا توجد أحداث تشغيلية بعد.",
    event_order_created: "تم إنشاء طلب", event_order_state: "تغيرت حالة طلب", event_line_state: "تغيرت حالة صنف", event_task_created: "تم إنشاء مهمة تنفيذ",
    total_orders: "إجمالي الطلبات", completed_sales: "المبيعات المنفذة", average_order: "متوسط الطلب", registered_customers: "العملاء المسجلون",
    new: "جديد", preparing: "قيد التحضير", completed: "منفذ", cancelled: "ملغي", no_data: "لا توجد بيانات.", order_unit: "طلب", currency: "ر.س",
    highest_sales: "أعلى مبيعات", lowest_sales: "أقل مبيعات", highest_orders: "الأكثر طلبًا", lowest_orders: "الأقل طلبًا",
    no_customers: "لا توجد بيانات عملاء منفذة ضمن الفترة.", customer: "عميل", no_mobile: "بدون جوال", last_order: "آخر طلب", visit: "زيارة", average: "متوسط",
    no_orders: "لا توجد طلبات.", order_not_found: "تعذر العثور على بيانات الطلب.", order_details: "تفاصيل الطلب",
    table: "الطاولة", car_details: "بيانات السيارة", delivery_distance: "مسافة التوصيل", km: "كم", delivery_location: "موقع التوصيل", open_map: "فتح الخريطة",
    product: "المنتج", quantity: "الكمية", unit_price: "سعر الوحدة", subtotal: "الإجمالي الفرعي", note: "الملاحظة",
    system: "النظام", status: "الحالة", pos: "نقطة البيع", date: "التاريخ", customer_type: "نوع العميل", customer_name: "اسم العميل", mobile: "رقم الجوال", order_type: "نوع الطلب", payment_method: "طريقة الدفع", order_notes: "ملاحظات الطلب", no_notes: "لا توجد ملاحظات.", price: "السعر", total: "الإجمالي", no_products: "لا توجد منتجات.", order_total: "إجمالي الطلب",
    store_open: "المتجر مفتوح", store_closed: "المتجر مغلق", orders_available: "الطلبات متاحة للعملاء الآن.", close_store: "إغلاق المتجر", open_store: "فتح المتجر", no_branches: "لا توجد فروع مرتبطة.", no_address: "العنوان غير مضاف", open: "مفتوح", closed: "مغلق", delivery_range: "نطاق التوصيل (كم)",
    update_branch_failed: t("update_branch_failed"), update_setting_failed: t("update_setting_failed"), update_distance_failed: t("update_distance_failed"), choose_pos_products: "اختر نقطة البيع من القائمة أعلاه لعرض وتعديل توفر المنتجات.", no_items: "لا توجد أصناف.", uncategorized: "بدون تصنيف", available: "متوفر", unavailable: "نفذت الكمية", update_product_failed: t("update_product_failed"), no_tables: "لم تتم إضافة طاولات بعد.", delete: "حذف", delete_table_confirm: "حذف الطاولة؟", delete_table_failed: t("delete_table_failed"), all_pos: "كل نقاط البيع", select_pos: "اختر نقطة البيع", select_branch: "اختر الفرع", dashboard_load_failed: t("dashboard_load_failed"), settings_update_failed: t("settings_update_failed"), add_table_failed: t("add_table_failed"), products_load_failed: t("products_load_failed")
} : {
    active_orders: "Active orders", open_tasks: "Open tasks", delayed_tasks: "Delayed tasks", available_stations: "Available stations",
    view_details: "View details", excellent: "Excellent", stable: "Stable", warning: "Needs attention", critical: "Critical",
    waiting: "Waiting", executing: "Executing", no_stations: "No execution stations have been added yet.", no_events: "No operational events yet.",
    event_order_created: "Order created", event_order_state: "Order status changed", event_line_state: "Order line status changed", event_task_created: "Execution task created",
    total_orders: "Total orders", completed_sales: "Completed sales", average_order: "Average order", registered_customers: "Registered customers",
    new: "New", preparing: "Preparing", completed: "Completed", cancelled: "Cancelled", no_data: "No data available.", order_unit: "orders", currency: "SAR",
    highest_sales: "Highest sales", lowest_sales: "Lowest sales", highest_orders: "Most orders", lowest_orders: "Fewest orders",
    no_customers: "No completed customer data is available for this period.", customer: "Customer", no_mobile: "No mobile", last_order: "Last order", visit: "visits", average: "Average",
    no_orders: "No orders found.", order_not_found: "Order data could not be found.", order_details: "Order details",
    table: "Table", car_details: "Car details", delivery_distance: "Delivery distance", km: "km", delivery_location: "Delivery location", open_map: "Open map",
    product: "Product", quantity: "Quantity", unit_price: "Unit price", subtotal: "Subtotal", note: "Note",
    system: "System", status: "Status", pos: "Point of sale", date: "Date", customer_type: "Customer type", customer_name: "Customer name", mobile: "Mobile", order_type: "Order type", payment_method: "Payment method", order_notes: "Order notes", no_notes: "No notes.", price: "Price", total: "Total", no_products: "No products.", order_total: "Order total",
    store_open: "Store open", store_closed: "Store closed", orders_available: "Orders are available to customers now.", close_store: "Close store", open_store: "Open store", no_branches: "No linked branches.", no_address: "No address", open: "Open", closed: "Closed", delivery_range: "Delivery range (km)",
    update_branch_failed: "Could not update branch", update_setting_failed: "Could not update setting", update_distance_failed: "Could not update delivery range", choose_pos_products: "Select a point of sale above to manage product availability.", no_items: "No items found.", uncategorized: "Uncategorized", available: "Available", unavailable: "Unavailable", update_product_failed: "Could not update product", no_tables: "No tables have been added yet.", delete: "Delete", delete_table_confirm: "Delete table?", delete_table_failed: "Could not delete table", all_pos: "All points of sale", select_pos: "Select point of sale", select_branch: "Select branch", dashboard_load_failed: "Could not load dashboard", settings_update_failed: "Could not update settings", add_table_failed: "Could not add table", products_load_failed: "Could not load point-of-sale products"
};
const t = (key, fallback) => UI[key] || fallback;

const stateLabels = isRTL
    ? {scheduled:"مجدول", new:"جديد", accepted:"تم الاعتماد", preparing:"قيد التحضير", partially_ready:"جاهز جزئيًا", ready:"جاهز", completed:"مكتمل", rejected:"مرفوض", cancelled:"ملغي"}
    : {scheduled:"Scheduled", new:"New", accepted:"Accepted", preparing:"Preparing", partially_ready:"Partially ready", ready:"Ready", completed:"Completed", rejected:"Rejected", cancelled:"Cancelled"};
const typeLabels = isRTL
    ? {dine_in:"محلي", takeaway:"سفري", car:"طلب سيارة", delivery:"توصيل"}
    : {dine_in:"Dine in", takeaway:"Takeaway", car:"Car order", delivery:"Delivery"};
const paymentLabels = isRTL
    ? {cash:"نقدًا", card:"بطاقة", wallet:"محفظة إلكترونية"}
    : {cash:"Cash", card:"Card", wallet:"Electronic wallet"};

function money(value) { return Number(value || 0).toFixed(2); }
function formatDateTime(value) { return value ? String(value).replace("T", " ").slice(0, 16) : "-"; }

function activateDashboardTab(tabName) {
    document.querySelectorAll(".fs-manager-tab").forEach((button) => button.classList.toggle("active", button.dataset.dashboardTab === tabName));
    document.querySelectorAll(".fs-dashboard-page").forEach((page) => page.classList.toggle("active", page.dataset.dashboardPage === tabName));
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

function renderMissionControl(data) {
    const health = Number(data?.overall_health || 0);
    const healthBox = document.querySelector("#mission-overall-health");
    const healthLabel = document.querySelector("#mission-health-label");
    if (healthBox) healthBox.textContent = `${health}%`;
    if (healthLabel) {
        healthLabel.textContent = health >= 90 ? t("excellent") : health >= 70 ? t("stable") : health >= 50 ? t("warning") : t("critical");
        healthLabel.dataset.health = health >= 90 ? "excellent" : health >= 70 ? "stable" : health >= 50 ? "warning" : "critical";
    }

    const kpis = [
        [t("active_orders", "Active orders"), data?.active_orders || 0, "orders"],
        [t("open_tasks", "Open tasks"), data?.open_tasks || 0, "tasks"],
        [t("delayed_tasks", "Delayed tasks"), data?.delayed_tasks || 0, "delayed"],
        [t("available_stations", "Available stations"), `${data?.active_stations || 0}/${data?.total_stations || 0}`, "stations"],
    ];
    const kpiBox = document.querySelector("#mission-control-kpis");
    if (kpiBox) kpiBox.innerHTML = kpis.map(([label,value,css]) => `
        <article class="fs-mission-kpi fs-mission-kpi-${css}"><span>${label}</span><strong>${value}</strong></article>`).join("");

    const stationBox = document.querySelector("#mission-stations");
    const stations = data?.stations || [];
    if (stationBox) stationBox.innerHTML = stations.length ? stations.map((station) => {
        const load = Number(station.active_tasks || 0) + Number(station.waiting_tasks || 0);
        const capacityText = Number(station.capacity || 0) > 0 ? `${load}/${station.capacity}` : `${load}`;
        return `<div class="fs-station-health-row">
            <span class="fs-station-dot is-${station.status}"></span>
            <div><strong>${station.name}</strong><small>${station.waiting_tasks || 0} ${t("waiting")} · ${station.active_tasks || 0} ${t("executing")}</small></div>
            <b>${capacityText}</b>
        </div>`;
    }).join("") : `<div class="fs-manager-empty">${t("no_stations")}</div>`;

    const eventLabels = {
        "order.created": t("event_order_created"),
        "order.state_changed": t("event_order_state"),
        "order_line.state_changed": t("event_line_state"),
        "task.created": t("event_task_created"),
    };
    const eventBox = document.querySelector("#mission-events");
    const events = data?.events || [];
    if (eventBox) eventBox.innerHTML = events.length ? events.map((event) => `
        <div class="fs-mission-event">
            <span class="fs-event-pulse"></span>
            <div><strong>${eventLabels[event.type] || event.type}</strong><small>${event.reference || "-"} · ${event.actor || t("system")}</small></div>
            <time>${formatDateTime(event.occurred_at)}</time>
        </div>`).join("") : `<div class="fs-manager-empty">${t("no_events")}</div>`;
}

function renderKpis(summary) {
    const cards = [
        [t("total_orders"), summary.total_orders, "orders", "◫"],
        [t("completed_sales"), `${money(summary.total_sales)} ${t("currency")}`, "sales", "↗"],
        [t("average_order"), `${money(summary.average_order)} ${t("currency")}`, "average", "≈"],
        [t("registered_customers"), summary.registered_customers, "customers", "★"],
        [t("new"), summary.new, "new", "●"],
        [t("preparing"), summary.preparing, "preparing", "◷"],
        [t("completed"), summary.ready, "ready", "✓"],
        [t("cancelled"), summary.cancelled, "cancelled", "×"],
    ];
    const box = document.querySelector("#dashboard-kpis");
    box.innerHTML = cards.map(([label,value,css,icon]) => `
        <article class="fs-kpi-card fs-kpi-${css}">
            <div class="fs-kpi-icon">${icon}</div><span>${label}</span><strong>${value}</strong>
        </article>`).join("");
}

function renderTopProducts(products) {
    const box = document.querySelector("#top-products");
    if (!products.length) { box.innerHTML = `<div class="fs-manager-empty">${t("no_data")}</div>`; return; }
    const maxQty = Math.max(...products.map((item) => Number(item.qty || 0)), 1);
    box.innerHTML = products.map((item,index) => `
        <div class="fs-product-rank">
            <div class="fs-product-rank-head"><span>${index+1}. ${item.name}</span><strong>${Number(item.qty||0).toFixed(0)} ${t("order_unit")}</strong></div>
            <div class="fs-product-bar"><span style="width:${(Number(item.qty||0)/maxQty)*100}%"></span></div>
            <small>${money(item.sales)} ${t("currency")}</small>
        </div>`).join("");
}

function renderBreakdown(selector, values, labels) {
    const box = document.querySelector(selector);
    const entries = Object.entries(values || {});
    const total = entries.reduce((sum,[,value]) => sum + Number(value || 0), 0) || 1;
    box.innerHTML = entries.map(([key,value]) => `
        <div class="fs-breakdown-row">
            <div><span>${labels[key] || key}</span><strong>${value}</strong></div>
            <div class="fs-breakdown-bar"><span style="width:${Number(value||0)/total*100}%"></span></div>
        </div>`).join("");
}


function renderDailyComparison(highlights) {
    const box = document.querySelector("#daily-comparison");
    const items = [
        [t("highest_sales"), highlights?.highest_sales_day, "sales-high"],
        [t("lowest_sales"), highlights?.lowest_sales_day, "sales-low"],
        [t("highest_orders"), highlights?.highest_orders_day, "orders-high"],
        [t("lowest_orders"), highlights?.lowest_orders_day, "orders-low"],
    ];
    box.innerHTML = items.map(([label,item,css]) => `
        <article class="fs-day-compare-card ${css}">
            <span>${label}</span>
            <strong>${item?.date || "-"}</strong>
            <small>${css.includes("sales") ? `${money(item?.sales || 0)} ${t("currency")}` : `${item?.orders || 0} ${t("order_unit")}`}</small>
        </article>
    `).join("");
}

function renderTopCustomers(customers) {
    const box = document.querySelector("#top-customers");
    if (!customers.length) { box.innerHTML = `<div class="fs-manager-empty">${t("no_customers")}</div>`; return; }
    box.innerHTML = customers.map((customer,index) => `
        <article class="fs-vip-customer-card ${index < 3 ? `top-${index+1}` : ""}">
            <div class="fs-vip-rank">${index+1}</div>
            <div class="fs-vip-avatar">${(customer.name || (isRTL ? "ع" : "C")).trim().charAt(0)}</div>
            <div class="fs-vip-info"><strong>${customer.name || t("customer")}</strong><span>${customer.mobile || t("no_mobile")}</span><small>${t("last_order")}: ${formatDateTime(customer.last_order)}</small></div>
            <div class="fs-vip-stats"><span><b>${customer.orders}</b> ${t("visit")}</span><span><b>${money(customer.spent)}</b> ${t("currency")}</span><span>${t("average")} ${money(customer.average_order)} ${t("currency")}</span></div>
        </article>`).join("");
    const best = document.querySelector("#best-customer-card");
    const customer = customers[0];
    best.innerHTML = `<div class="fs-best-customer"><div class="fs-vip-avatar">${(customer.name||(isRTL?"ع":"C")).charAt(0)}</div><strong>${customer.name}</strong><span>${customer.orders} ${t("visit")}</span><b>${money(customer.spent)} ${t("currency")}</b></div>`;
}

function renderOrders(orders) {
    const body = document.querySelector("#recent-orders-body");
    if (!orders.length) {
        body.innerHTML = `<tr><td colspan="9" class="fs-manager-empty">${t("no_orders")}</td></tr>`;
        return;
    }

    body.innerHTML = orders.map((order) => `
        <tr class="fs-clickable-order-row" data-order-id="${order.id}" tabindex="0">
            <td><strong>${order.name || "-"}</strong></td>
            <td>${order.customer_name || "-"}</td>
            <td><span class="fs-order-chip">${order.order_type_label || typeLabels[order.order_type] || "-"}</span></td>
            <td>${order.payment_method_label || paymentLabels[order.payment_method] || "-"}</td>
            <td><span class="fs-manager-status fs-manager-status-${order.state}">${order.state_label || stateLabels[order.state] || order.state}</span></td>
            <td>${order.pos_name || "-"}</td>
            <td>${money(order.amount_total)} ${t("currency")}</td>
            <td>${formatDateTime(order.create_date)}</td>
            <td><button type="button" class="fs-view-order-details" data-order-id="${order.id}">${t("view_details", "View details")}</button></td>
        </tr>`).join("");

    const orderMap = new Map(orders.map((order) => [Number(order.id), order]));

    const showOrder = (orderId) => {
        const order = orderMap.get(Number(orderId));
        if (!order) {
            alert(t("order_not_found"));
            return;
        }
        renderOrderDetails(order);
        activateDashboardTab("order-details");
    };

    body.querySelectorAll(".fs-view-order-details").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            showOrder(button.dataset.orderId);
        });
    });

    body.querySelectorAll(".fs-clickable-order-row").forEach((row) => {
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
    title.textContent = order.name || t("order_details");

    const extraDetails = [];
    if (order.table_name) extraDetails.push(`<div><span>${t("table")}</span><strong>${order.table_name}</strong></div>`);
    if (order.car_details) extraDetails.push(`<div><span>${t("car_details")}</span><strong>${order.car_details}</strong></div>`);
    if (order.delivery_distance_km) extraDetails.push(`<div><span>${t("delivery_distance")}</span><strong>${Number(order.delivery_distance_km).toFixed(2)} ${t("km")}</strong></div>`);
    if (order.delivery_google_maps_url) extraDetails.push(`<div><span>${t("delivery_location")}</span><strong><a href="${order.delivery_google_maps_url}" target="_blank" rel="noopener">${t("open_map")}</a></strong></div>`);

    const lines = (order.lines || []).map((line) => `
        <tr>
            <td>${line.product || "-"}</td>
            <td>${Number(line.qty || 0)}</td>
            <td>${money(line.price_unit)} ${t("currency")}</td>
            <td>${money(line.subtotal)} ${t("currency")}</td>
            <td>${line.note || "-"}</td>
        </tr>`).join("");

    box.innerHTML = `
        <div class="fs-order-details-summary">
            <div><span>${t("status")}</span><strong class="fs-manager-status fs-manager-status-${order.state}">${order.state_label || stateLabels[order.state] || order.state}</strong></div>
            <div><span>${t("pos")}</span><strong>${order.pos_name || "-"}</strong></div>
            <div><span>${t("date")}</span><strong>${formatDateTime(order.create_date)}</strong></div>
            <div><span>${t("customer_type")}</span><strong>${order.customer_type || "-"}</strong></div>
            <div><span>${t("customer_name")}</span><strong>${order.customer_name || "-"}</strong></div>
            <div><span>${t("mobile")}</span><strong>${order.customer_mobile || "-"}</strong></div>
            <div><span>${t("order_type")}</span><strong>${order.order_type_label || typeLabels[order.order_type] || "-"}</strong></div>
            <div><span>${t("payment_method")}</span><strong>${order.payment_method_label || paymentLabels[order.payment_method] || "-"}</strong></div>
            ${extraDetails.join("")}
        </div>
        <div class="fs-order-details-note">
            <span>${t("order_notes")}</span>
            <p>${order.note || t("no_notes")}</p>
        </div>
        <div class="fs-table-wrap fs-order-lines-table">
            <table>
                <thead><tr><th>${t("product")}</th><th>${t("quantity")}</th><th>${t("price")}</th><th>${t("total")}</th><th>${t("note")}</th></tr></thead>
                <tbody>${lines || `<tr><td colspan="5" class="fs-manager-empty">${t("no_products")}</td></tr>`}</tbody>
                <tfoot><tr><td colspan="3">${t("order_total")}</td><td colspan="2"><strong>${money(order.amount_total)} ${t("currency")}</strong></td></tr></tfoot>
            </table>
        </div>`;
}

function renderStore(store) {
    const title = document.querySelector("#store-status-title");
    const message = document.querySelector("#store-status-message");
    const toggle = document.querySelector("#toggle-store");
    title.textContent = store.is_open ? t("store_open") : t("store_closed");
    message.textContent = store.is_open ? t("orders_available") : (store.closed_message || t("store_closed"));
    toggle.textContent = store.is_open ? t("close_store") : t("open_store");
    toggle.dataset.open = store.is_open ? "1" : "0";
    toggle.classList.toggle("is-open", store.is_open);
    toggle.classList.toggle("is-closed", !store.is_open);
    document.querySelector("#closed-message").value = store.closed_message || "";
    document.querySelector("#allow-browse-closed").checked = Boolean(store.allow_browse_when_closed);
    document.querySelector("#reopen-at").value = store.reopen_at ? store.reopen_at.replace(" ", "T").slice(0,16) : "";
}

function renderBranches(branches) {
    const box = document.querySelector("#manager-branches");
    if (!branches.length) { box.innerHTML = `<div class="fs-manager-empty">${t("no_branches")}</div>`; return; }
    box.innerHTML = branches.map((branch) => `
        <article class="fs-manager-branch-card ${branch.is_open ? "" : "is-closed"}">
            <div class="fs-manager-branch-head">
                <div><strong>${branch.name}</strong><span>${branch.address || t("no_address")}</span></div>
                <button class="fs-branch-open-toggle ${branch.is_open ? "is-open":"is-closed"}" data-branch-id="${branch.id}" data-open="${branch.is_open ? "1":"0"}">${branch.is_open ? t("open"):t("closed")}</button>
            </div>
            <div class="fs-manager-branch-meta">
                <label>${t("delivery_range")}<input class="fs-branch-distance-input" type="number" min="0" step="0.5" value="${branch.max_distance_km || 0}" data-branch-id="${branch.id}"/></label>
            </div>
            <div class="fs-branch-settings-grid">
                ${[
                    ["enable_dine_in","محلي",branch.enabled_order_types?.dine_in],
                    ["enable_takeaway","سفري",branch.enabled_order_types?.takeaway],
                    ["enable_car_order","طلب سيارة",branch.enabled_order_types?.car],
                    ["enable_delivery","توصيل",branch.enabled_order_types?.delivery],
                    ["enable_cash","نقدًا",branch.enabled_payment_methods?.cash],
                    ["enable_card","بطاقة",branch.enabled_payment_methods?.card],
                    ["enable_wallet","محفظة إلكترونية",branch.enabled_payment_methods?.wallet],
                ].map(([key,label,enabled]) => `
                    <label class="fs-setting-toggle">
                        <input type="checkbox" data-branch-id="${branch.id}" data-setting="${key}" ${enabled ? "checked" : ""}/>
                        <span>${label}</span>
                    </label>
                `).join("")}
            </div>
        </article>`).join("");

    box.querySelectorAll(".fs-branch-open-toggle").forEach((button) => button.addEventListener("click", async () => {
        button.disabled = true;
        try {
            const result = await rpc("/operations/api/branches/update", {branch_id:Number(button.dataset.branchId), is_open:button.dataset.open !== "1"});
            if (!result?.success) throw new Error(result?.error || t("update_branch_failed"));
            await loadDashboard();
        } catch (error) { alert(error.message); } finally { button.disabled = false; }
    }));

    box.querySelectorAll(".fs-setting-toggle input").forEach((input) => input.addEventListener("change", async () => {
        const payload = {branch_id:Number(input.dataset.branchId)};
        payload[input.dataset.setting] = input.checked;
        const result = await rpc("/operations/api/branches/update", payload);
        if (!result?.success) {
            input.checked = !input.checked;
            alert(result?.error || t("update_setting_failed"));
        }
    }));

    box.querySelectorAll(".fs-branch-distance-input").forEach((input) => input.addEventListener("change", async () => {
        const result = await rpc("/operations/api/branches/update", {
            branch_id:Number(input.dataset.branchId),
            max_distance_km:Number(input.value || 0),
        });
        if (!result?.success) alert(result?.error || t("update_distance_failed"));
    }));
}

function renderMenuProducts(products, selectedPosConfigId) {
    const box = document.querySelector("#manager-menu-products");
    if (!selectedPosConfigId) {
        box.innerHTML = `<div class="fs-manager-empty">${t("choose_pos_products")}</div>`;
        return;
    }
    if (!products.length) { box.innerHTML = `<div class="fs-manager-empty">${t("no_items")}</div>`; return; }
    box.innerHTML = products.map((product) => `
        <article class="fs-manager-product-card ${product.available ? "" : "is-sold-out"}">
            <img src="${product.image_url}" alt="${product.name}"/><div class="fs-manager-product-info"><strong>${product.name}</strong><span>${product.category || t("uncategorized")}</span><small>${money(product.price)} ${t("currency")}</small></div>
            <button class="fs-product-availability-btn ${product.available ? "is-available":"is-unavailable"}" data-product-id="${product.id}" data-available="${product.available ? "1":"0"}">${product.available ? t("available"):t("unavailable")}</button>
        </article>`).join("");
    box.querySelectorAll(".fs-product-availability-btn").forEach((button) => button.addEventListener("click", async () => {
        button.disabled = true;
        try {
            const result = await rpc("/operations/api/products/availability", {product_template_id:Number(button.dataset.productId), pos_config_id:Number(selectedPosConfigId), available:button.dataset.available !== "1"});
            if (!result?.success) throw new Error(result?.error || t("update_product_failed"));
            await loadMenuProducts();
        } catch (error) { alert(error.message); } finally { button.disabled = false; }
    }));
}

function renderTables(tables) {
    const box = document.querySelector("#manager-tables");
    if (!tables.length) { box.innerHTML = `<div class="fs-manager-empty">${t("no_tables")}</div>`; return; }
    box.innerHTML = tables.map((table) => `
        <article class="fs-table-admin-card"><div><strong>${table.name}</strong><span>${table.branch_name}</span></div>
        <button class="fs-delete-table" data-table-id="${table.id}">${t("delete")}</button></article>`).join("");
    box.querySelectorAll(".fs-delete-table").forEach((button) => button.addEventListener("click", async () => {
        if (!confirm(t("delete_table_confirm"))) return;
        const result = await rpc("/operations/api/tables/delete", {table_id:Number(button.dataset.tableId)});
        if (!result?.success) alert(result?.error || t("delete_table_failed")); else await loadDashboard();
    }));
}

async function loadMenuProducts() {
    const productFilter = document.querySelector("#product-pos-filter");
    const selectedPosConfigId = productFilter?.value || false;
    if (!selectedPosConfigId) {
        renderMenuProducts([], false);
        return;
    }

    const result = await rpc("/operations/api/products", {
        pos_config_id: Number(selectedPosConfigId),
    });
    if (!result?.success) {
        throw new Error(result?.error || t("products_load_failed"));
    }
    renderMenuProducts(result.menu_products || [], result.selected_pos_config_id);
}

function populatePosOptions(posConfigs) {
    const options = posConfigs.map((pos) => `<option value="${pos.id}">${pos.name}</option>`).join("");
    const filter = document.querySelector("#filter-pos");
    const current = filter.value;
    filter.innerHTML = `<option value="">${t("all_pos")}</option>` + options;
    filter.value = current;

    const productFilter = document.querySelector("#product-pos-filter");
    const productCurrent = productFilter.value;
    productFilter.innerHTML = `<option value="">${t("select_pos")}</option>` + options;
    productFilter.value = productCurrent;

    const tableBranch = document.querySelector("#new-table-branch");
    tableBranch.innerHTML = `<option value="">${t("select_branch")}</option>` + options;
}

async function loadDashboard() {
    const result = await rpc("/operations/api/dashboard", getFilters());
    if (!result?.success) throw new Error(result?.error || t("dashboard_load_failed"));
    renderMissionControl(result.mission_control || {});
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
    const result = await rpc("/operations/api/store/update", values);
    if (!result?.success) throw new Error(result?.error || t("settings_update_failed"));
    renderStore(result.store);
}

document.addEventListener("DOMContentLoaded", async () => {
    document.querySelectorAll(".fs-manager-tab").forEach((button) => button.addEventListener("click", () => activateDashboardTab(button.dataset.dashboardTab)));
    document.querySelectorAll("[data-open-tab]").forEach((item) => item.addEventListener("click", () => activateDashboardTab(item.dataset.openTab)));
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
        const result = await rpc("/operations/api/tables/save", {name:document.querySelector("#new-table-name").value, pos_config_id:document.querySelector("#new-table-branch").value, active:true});
        if (!result?.success) alert(result?.error || t("add_table_failed")); else { document.querySelector("#new-table-name").value = ""; await loadDashboard(); }
    });
    try { await loadDashboard(); } catch (error) { console.error(error); alert(error.message || t("dashboard_load_failed")); }
});
