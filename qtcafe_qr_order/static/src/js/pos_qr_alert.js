/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";

/** QT Cafe QR Order - POS new order alert
 * Reads the active POS config directly from the POS application, while preserving
 * URL lookup as a fallback. It polls the backend for new QR orders and shows
 * a floating alert with sound.
 */

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        const configId = this.pos?.config?.id;
        if (configId) {
            window.__qtCafeActivePosConfigId = Number(configId);
        }
    },
});

(function () {
    "use strict";

    if (window.__qtCafeQrPosAlertLoaded) {
        return;
    }
    window.__qtCafeQrPosAlertLoaded = true;

    const POLL_MS = 7000;
    let lastKnownIds = new Set();
    let initialized = false;
    let audioUnlocked = false;

    function isPosPage() {
        return window.location.pathname.includes('/pos') || document.body.classList.contains('pos');
    }

    function unlockAudio() {
        audioUnlocked = true;
        document.removeEventListener('click', unlockAudio);
        document.removeEventListener('touchstart', unlockAudio);
    }
    document.addEventListener('click', unlockAudio);
    document.addEventListener('touchstart', unlockAudio);

    function beep() {
        if (!audioUnlocked) {
            return;
        }
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = ctx.createOscillator();
            const gain = ctx.createGain();
            oscillator.type = 'sine';
            oscillator.frequency.value = 880;
            gain.gain.value = 0.12;
            oscillator.connect(gain);
            gain.connect(ctx.destination);
            oscillator.start();
            setTimeout(() => {
                oscillator.stop();
                ctx.close();
            }, 260);
        } catch (e) {
            // Silent fail: browser may block audio.
        }
    }

    function ensureStyles() {
        if (document.getElementById('qtcafe-pos-alert-style')) return;
        const style = document.createElement('style');
        style.id = 'qtcafe-pos-alert-style';
        style.textContent = `
            #qtcafe-pos-alert {
                position: fixed;
                top: 18px;
                right: 18px;
                z-index: 999999;
                width: min(420px, calc(100vw - 36px));
                background: #ffffff;
                color: #1f2937;
                border-radius: 22px;
                box-shadow: 0 20px 70px rgba(0,0,0,.30);
                border: 3px solid #1e5a78;
                direction: rtl;
                font-family: inherit;
                overflow: hidden;
                display: none;
            }
            #qtcafe-pos-alert.qtcafe-show { display: block; animation: qtcafePulse .8s ease-in-out 0s 3; }
            .qtcafe-pos-alert-head { background: #1e5a78; color: white; padding: 16px 18px; font-size: 22px; font-weight: 800; }
            .qtcafe-pos-alert-body { padding: 16px 18px; font-size: 16px; }
            .qtcafe-pos-alert-count { font-size: 42px; font-weight: 900; color: #1e5a78; line-height: 1; margin: 6px 0 10px; }
            .qtcafe-pos-alert-actions { display: flex; gap: 10px; padding: 0 18px 18px; }
            .qtcafe-pos-alert-actions button, .qtcafe-pos-alert-actions a {
                border: 0; border-radius: 14px; padding: 12px 14px; cursor: pointer;
                font-weight: 800; text-decoration: none; text-align: center; flex: 1;
            }
            .qtcafe-pos-alert-open { background: #1e5a78; color: #fff; }
            .qtcafe-pos-alert-close { background: #e5e7eb; color: #111827; }
            #qtcafe-pos-badge {
                position: fixed; top: 18px; left: 18px; z-index: 999998;
                background: #1e5a78; color: white; border-radius: 999px;
                padding: 10px 16px; font-weight: 900; direction: rtl; display: none;
                box-shadow: 0 10px 30px rgba(0,0,0,.22);
            }
            @keyframes qtcafePulse { 0%{transform:scale(1)} 50%{transform:scale(1.035)} 100%{transform:scale(1)} }
        `;
        document.head.appendChild(style);
    }

    function ensureElements() {
        ensureStyles();
        if (!document.getElementById('qtcafe-pos-alert')) {
            const alert = document.createElement('div');
            alert.id = 'qtcafe-pos-alert';
            alert.innerHTML = `
                <div class="qtcafe-pos-alert-head">طلب QR جديد</div>
                <div class="qtcafe-pos-alert-body">
                    <div>وصل طلب جديد من صفحة العميل.</div>
                    <div class="qtcafe-pos-alert-count" id="qtcafe-pos-alert-count">1</div>
                    <div>افتح شاشة الطلبات لقبول الطلب ومتابعته.</div>
                </div>
                <div class="qtcafe-pos-alert-actions">
                    <a class="qtcafe-pos-alert-open" href="/qtcafe/cashier" target="_blank">عرض الطلبات</a>
                    <button class="qtcafe-pos-alert-close" type="button">إخفاء</button>
                </div>
            `;
            document.body.appendChild(alert);
            alert.querySelector('.qtcafe-pos-alert-close').addEventListener('click', () => alert.classList.remove('qtcafe-show'));
        }
        if (!document.getElementById('qtcafe-pos-badge')) {
            const badge = document.createElement('div');
            badge.id = 'qtcafe-pos-badge';
            badge.textContent = 'QR Orders: 0';
            badge.addEventListener('click', () => window.open('/qtcafe/cashier', '_blank'));
            document.body.appendChild(badge);
        }
    }

    function currentPosConfigId() {
        const activeConfigId = Number(window.__qtCafeActivePosConfigId || 0);
        if (activeConfigId > 0) {
            return String(activeConfigId);
        }

        const params = new URLSearchParams(window.location.search);
        const direct = params.get('config_id') || params.get('pos_config_id');
        if (direct && /^\d+$/.test(direct)) {
            return direct;
        }

        const hashParams = new URLSearchParams((window.location.hash.split('?')[1] || ''));
        const fromHash = hashParams.get('config_id') || hashParams.get('pos_config_id');
        return fromHash && /^\d+$/.test(fromHash) ? fromHash : '';
    }

    async function poll() {
        if (!isPosPage()) return;
        ensureElements();
        try {
            const configId = currentPosConfigId();
            if (!configId) return;
            const response = await fetch(`/qtcafe/orders/pending_count?pos_config_id=${encodeURIComponent(configId)}`, { credentials: 'same-origin' });
            if (!response.ok) return;
            const data = await response.json();
            const ids = new Set(data.ids || []);
            const count = data.count || 0;
            const badge = document.getElementById('qtcafe-pos-badge');
            if (badge) {
                badge.style.display = count ? 'block' : 'none';
                badge.textContent = `QR Orders: ${count}`;
            }
            let hasNew = false;
            if (initialized) {
                for (const id of ids) {
                    if (!lastKnownIds.has(id)) {
                        hasNew = true;
                        break;
                    }
                }
            }
            lastKnownIds = ids;
            initialized = true;
            if (hasNew || (count > 0 && !document.getElementById('qtcafe-pos-alert')?.classList.contains('qtcafe-show'))) {
                const alert = document.getElementById('qtcafe-pos-alert');
                const countEl = document.getElementById('qtcafe-pos-alert-count');
                if (countEl) countEl.textContent = String(count);
                if (alert) alert.classList.add('qtcafe-show');
                beep();
                setTimeout(beep, 420);
            }
        } catch (e) {
            // avoid breaking POS if network request fails
        }
    }

    setTimeout(poll, 2500);
    setInterval(poll, POLL_MS);
})();
