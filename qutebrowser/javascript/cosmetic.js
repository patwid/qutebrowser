// SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
//
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Hide page elements matched by the cosmetic rules of the adblock lists.
 *
 * The rules are held by the adblock engine on the Python side, which we talk
 * to over a QWebChannel (see browser/webengine/cosmetic.py):
 *
 * - When the document is created, we ask for the rules applying to its URL,
 *   and add them to a stylesheet of our own.
 * - The lists also contain thousands of generic rules for a single class or
 *   ID. Rather than adding all of them to every page, we collect the classes
 *   and IDs showing up in the document, and ask which of them should be
 *   hidden.
 *
 * The channel is shared by all documents loaded in a tab, so when a document
 * gets replaced while it's waiting for an answer, the answer ends up at the
 * new document. Thus, every request carries a token of the document asking,
 * which is part of the answer. With an answer for another document, we ask
 * again.
 */

"use strict";

window._qutebrowser.cosmetic = (function() {
    const funcs = {};

    const hide_declaration = "{ display: none !important; }";
    // How long to collect classes and IDs before asking about them (ms).
    const batch_delay = 50;
    // How often to ask again after getting an answer for another document.
    const max_tries = 5;

    const token = `${Date.now()}-${Math.random()}`;

    let bridge = null;
    let sheet = null;
    let observer = null;
    let last_url = null;
    let batch_timer = null;
    let seen_classes = new Set();
    let seen_ids = new Set();
    let new_classes = [];
    let new_ids = [];

    function add_rules(rules) {
        if (!document.adoptedStyleSheets.includes(sheet)) {
            // Also done again when the page replaced the list.
            document.adoptedStyleSheets = [
                ...document.adoptedStyleSheets, sheet];
        }
        for (const rule of rules) {
            try {
                sheet.insertRule(rule, sheet.cssRules.length);
            } catch (err) {
                // A selector the engine doesn't support, skip it.
            }
        }
    }

    function ask_about(request, tries = max_tries) {
        bridge.generic_selectors(request, (json) => {
            const answer = JSON.parse(json);
            if (answer.token !== token) {
                if (tries > 1) {
                    ask_about(request, tries - 1);
                }
                return;
            }
            add_rules(answer.selectors.map(
                (selector) => `${selector} ${hide_declaration}`));
        });
    }

    function ask_about_new() {
        batch_timer = null;
        if (!new_classes.length && !new_ids.length) {
            return;
        }
        ask_about(JSON.stringify({
            token,
            "classes": new_classes,
            "ids": new_ids,
        }));
        new_classes = [];
        new_ids = [];
    }

    function collect_element(elem) {
        if (elem.nodeType !== Node.ELEMENT_NODE) {
            return;
        }
        for (const name of elem.classList) {
            if (!seen_classes.has(name)) {
                seen_classes.add(name);
                new_classes.push(name);
            }
        }
        // SVG elements have an ID which isn't a string
        if (typeof elem.id === "string" && elem.id &&
                !seen_ids.has(elem.id)) {
            seen_ids.add(elem.id);
            new_ids.push(elem.id);
        }
    }

    function collect_tree(root) {
        if (root.nodeType !== Node.ELEMENT_NODE) {
            return;
        }
        collect_element(root);
        for (const elem of root.querySelectorAll("[class], [id]")) {
            collect_element(elem);
        }
    }

    function on_mutations(mutations) {
        for (const mutation of mutations) {
            if (mutation.type === "attributes") {
                collect_element(mutation.target);
            } else {
                for (const node of mutation.addedNodes) {
                    collect_tree(node);
                }
            }
        }
        if (batch_timer === null && (new_classes.length || new_ids.length)) {
            batch_timer = setTimeout(ask_about_new, batch_delay);
        }
    }

    function stop_observing() {
        if (observer !== null) {
            observer.disconnect();
            observer = null;
        }
    }

    function apply(rules) {
        stop_observing();
        if (sheet === null) {
            sheet = new CSSStyleSheet();
        } else {
            sheet.replaceSync("");
        }
        seen_classes = new Set();
        seen_ids = new Set();
        new_classes = [];
        new_ids = [];

        if (!rules.enabled) {
            return;
        }

        const css = rules.hide.map(
            (selector) => `${selector} ${hide_declaration}`);
        for (const [selector, declarations] of Object.entries(rules.style)) {
            css.push(`${selector} { ${declarations.join("; ")} }`);
        }
        add_rules(css);

        if (rules.generic) {
            observer = new MutationObserver(on_mutations);
            observer.observe(document, {
                "subtree": true,
                "childList": true,
                "attributes": true,
                "attributeFilter": ["class", "id"],
            });
            if (document.documentElement) {
                collect_tree(document.documentElement);
                ask_about_new();
            }
        }
    }

    function load_rules(tries = max_tries) {
        const url = window.location.href;
        last_url = url;
        bridge.rules(token, url, (json) => {
            const answer = JSON.parse(json);
            if (answer.token !== token) {
                if (tries > 1) {
                    load_rules(tries - 1);
                }
            } else if (url === last_url) {
                apply(answer);
            }
        });
    }

    // Called when the URL changed without a new document being created.
    funcs.refresh = () => {
        if (bridge !== null && window.location.href !== last_url) {
            load_rules();
        }
    };

    // The transport is only available in the main frame.
    if (window.qt && window.qt.webChannelTransport) {
        // eslint-disable-next-line no-undef
        const web_channel = new QWebChannel(
            window.qt.webChannelTransport, (channel) => {
                bridge = channel.objects.cosmetic;
                load_rules();
            });
        // An answer for a request of the previous document, which we didn't
        // make. QWebChannel would fail on that.
        const handle_response = web_channel.handleResponse;
        web_channel.handleResponse = (message) => {
            if (web_channel.execCallbacks[message.id]) {
                handle_response(message);
            }
        };
    }

    return funcs;
})();
