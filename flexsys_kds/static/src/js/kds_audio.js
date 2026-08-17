/** @odoo-module **/

/**
 * Generates a short beep tone entirely in-code (Web Audio API oscillator),
 * rather than bundling an external sound file - keeps working even if
 * some static asset fails to load, and avoids adding a binary asset to
 * the module for one short tone.
 *
 * Browsers block audio playback until a user gesture happens on the page
 * at least once (autoplay policy). `resumeAudioOnFirstInteraction()` is
 * wired to the first click/touch anywhere on the page to resume the
 * AudioContext as soon as possible - but the very first order of a shift
 * may not audibly beep if nobody has tapped the screen yet. That's a
 * browser platform limitation, not something fixable from application
 * code.
 */
let audioCtx = null;

function getAudioContext() {
    if (!audioCtx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (Ctx) {
            audioCtx = new Ctx();
        }
    }
    return audioCtx;
}

export function resumeAudioOnFirstInteraction() {
    const ctx = getAudioContext();
    if (ctx && ctx.state === "suspended") {
        ctx.resume().catch(() => {});
    }
}

document.addEventListener("click", resumeAudioOnFirstInteraction, { once: true });
document.addEventListener("touchstart", resumeAudioOnFirstInteraction, { once: true });

export function playBeep() {
    const ctx = getAudioContext();
    if (!ctx) return;
    try {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = "sine";
        osc.frequency.value = 880;
        const now = ctx.currentTime;
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(0.35, now + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);
        osc.start(now);
        osc.stop(now + 0.36);
    } catch (e) {
        // Audio unavailable/blocked - fail silently, never break the
        // screen over a missed beep.
    }
}

/**
 * CANCELLATION VISIBILITY (dev request, point 5: "use a clearly
 * distinguishable cancellation notification/sound so kitchen staff
 * notice it quickly"): a lower-pitched double-tone, deliberately the
 * opposite shape of playBeep() above (one bright rising tone) - two
 * short, low, descending pulses read as "stop/attention" rather than
 * "something arrived", so staff can tell the two apart without looking
 * at the screen first. Identical implementation to the public kiosk's
 * own playCancelAlert() in controllers/kds_kiosk.py - kept in sync
 * manually, same as this file's playBeep() already is with the kiosk's
 * own copy.
 */
export function playCancelAlert() {
    const ctx = getAudioContext();
    if (!ctx) return;
    try {
        const now = ctx.currentTime;
        [[420, 0], [330, 0.16]].forEach(([freq, delay]) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = "square";
            osc.frequency.value = freq;
            const start = now + delay;
            gain.gain.setValueAtTime(0.0001, start);
            gain.gain.exponentialRampToValueAtTime(0.28, start + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.15);
            osc.start(start);
            osc.stop(start + 0.16);
        });
    } catch (e) {
        // Audio unavailable/blocked - fail silently, never break the
        // screen over a missed alert.
    }
}
