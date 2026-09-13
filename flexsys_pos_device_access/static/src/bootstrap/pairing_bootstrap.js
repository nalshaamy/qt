/** @odoo-module **/

// The first request of a paired-device link intentionally targets /web/login.
// Odoo's server-wide login controller selects ?db=<database> for a fresh
// browser. Once the database is selected, this module is available in the
// database-specific frontend asset bundle and forwards the one-time secret
// from the URL fragment to the real FlexSys pairing controller.
//
// The pairing secret stays in the fragment until this point, so it is not sent
// to /web/login and does not appear in the login request's server access log.

const PREFIX = "#flexsys_pair=";
const TOKEN_RE = /^[A-Za-z0-9_-]{32,160}$/;

const hash = window.location.hash || "";
if (hash.startsWith(PREFIX)) {
    let token = "";
    try {
        token = decodeURIComponent(hash.slice(PREFIX.length));
    } catch {
        token = "";
    }

    if (TOKEN_RE.test(token)) {
        // replace() avoids retaining the bootstrap URL as a separate browser
        // history entry. The target is now safe to resolve because Odoo has
        // already selected the database in the current session.
        window.location.replace(`/flexsys/pos/pair/${encodeURIComponent(token)}`);
    }
}
