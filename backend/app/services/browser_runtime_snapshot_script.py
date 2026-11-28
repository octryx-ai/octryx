"""The page script of the browser worker's snapshot action."""

SNAPSHOT_ELEMENTS_SCRIPT = """(limit, previewChars) => {
                const selectors = [
                    "a",
                    "button",
                    "input",
                    "textarea",
                    "select",
                    "[role='button']",
                    "[role='link']",
                    "[contenteditable='true']",
                ];
                const seen = new Set();
                let index = 1;
                const rows = [];
                const candidates = document.querySelectorAll(selectors.join(","));
                for (const el of candidates) {
                    if (rows.length >= limit) break;
                    if (seen.has(el)) continue;
                    seen.add(el);
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (!rect.width || !rect.height) continue;
                    if (style.visibility === "hidden" || style.display === "none") continue;
                    const ref = `e${index++}`;
                    el.setAttribute("data-octryx-ref", ref);
                    rows.push({
                        ref,
                        tag: el.tagName.toLowerCase(),
                        text: (el.innerText || el.textContent || "").trim().slice(0, previewChars),
                        type: el.getAttribute("type") || "",
                        placeholder: el.getAttribute("placeholder") || "",
                        aria_label: el.getAttribute("aria-label") || "",
                        href: el.getAttribute("href") || "",
                    });
                }
                return rows;
            }"""
