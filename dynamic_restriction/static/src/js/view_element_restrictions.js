/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onPatched, onWillStart, onWillUnmount } from "@odoo/owl";

const EMPTY_VIEW_ELEMENT_RESTRICTIONS = Object.freeze({
    buttons: Object.freeze([]),
    tabs: Object.freeze([]),
    button_labels: Object.freeze({}),
    tab_labels: Object.freeze({}),
});

const TAB_NAV_SELECTORS = [
    ".nav-link",
    ".o_notebook .nav-link",
    "button[role=\"tab\"]",
    "a[role=\"tab\"]",
    ".o_notebook_headers a",
    ".o_notebook_headers button",
];
const TAB_NAV_SELECTOR = TAB_NAV_SELECTORS.join(",");

function normalizeRestrictions(result) {
    const restrictions = result || {};
    const buttonLabels = restrictions.button_labels || {};
    const tabLabels = restrictions.tab_labels || {};
    return {
        buttons: Array.isArray(restrictions.buttons)
            ? restrictions.buttons
                  .filter(Boolean)
                  .map((button) => {
                      if (typeof button === "string") {
                          return {
                              name: button,
                              label: buttonLabels[button] || button,
                          };
                      }
                      return {
                          name: button.name || "",
                          label: button.label || button.name || "",
                      };
                  })
                  .filter((button) => button.name)
            : [],
        tabs: Array.isArray(restrictions.tabs)
            ? restrictions.tabs.filter(Boolean).map((tab) => {
                  if (typeof tab === "string") {
                      return {
                          name: tab,
                          label: tabLabels[tab] || tab,
                      };
                  }
                  return {
                      name: tab.name || "",
                      label: tab.label || tab.name || "",
                  };
              }).filter((tab) => tab.name || tab.label)
            : [],
        button_labels: buttonLabels,
        tab_labels: tabLabels,
    };
}

function normalizeText(value) {
    return String(value || "")
        .replace(/\s+/g, " ")
        .trim();
}

function escapeAttributeValue(value) {
    return String(value || "")
        .replace(/\\/g, "\\\\")
        .replace(/"/g, '\\"');
}

function attrSelector(attributeName, value) {
    return `[${attributeName}="${escapeAttributeValue(value)}"]`;
}

function attrContainsSelector(attributeName, value) {
    return `[${attributeName}*="${escapeAttributeValue(value)}"]`;
}

function escapeCssIdentifier(value) {
    if (typeof CSS !== "undefined" && CSS.escape) {
        return CSS.escape(value);
    }
    return String(value || "").replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function matchesSelector(element, selector) {
    try {
        return Boolean(element && element.matches && element.matches(selector));
    } catch {
        return false;
    }
}

function closestSelector(element, selector) {
    try {
        return element && element.closest ? element.closest(selector) : false;
    } catch {
        return false;
    }
}

function setHidden(element, hidden) {
    if (!element) {
        return;
    }
    if (hidden) {
        element.classList.add("d-none");
        element.setAttribute("aria-hidden", "true");
        element.dataset.dynamicViewElementRestrictionHidden = "1";
    } else if (element.dataset.dynamicViewElementRestrictionHidden === "1") {
        element.classList.remove("d-none");
        element.removeAttribute("aria-hidden");
        delete element.dataset.dynamicViewElementRestrictionHidden;
    }
}

function setTabHidden(element, hidden) {
    const wasHiddenByRestriction =
        element && element.dataset.dynamicViewElementRestrictionHidden === "1";
    setHidden(element, hidden);
    if (!element || !element.style) {
        return;
    }
    if (hidden) {
        element.style.display = "none";
    } else if (wasHiddenByRestriction) {
        element.style.removeProperty("display");
    }
}

function safeQueryAll(root, selectors, callback) {
    if (!root || !root.querySelectorAll) {
        return;
    }
    for (const selector of selectors) {
        try {
            root.querySelectorAll(selector).forEach(callback);
        } catch (error) {
            console.warn("[Dynamic View Element Restrictions Odoo18] invalid selector", error);
        }
    }
}

function getTabNavigationElement(element) {
    if (!element) {
        return false;
    }
    if (matchesSelector(element, TAB_NAV_SELECTOR)) {
        return element;
    }
    const navElement = closestSelector(element, TAB_NAV_SELECTOR);
    if (navElement) {
        return navElement;
    }
    if (closestSelector(element, ".o_notebook_headers")) {
        return closestSelector(element, "a, button, .nav-link, [role=\"tab\"]") || element;
    }
    return false;
}

function getTabHideTarget(element) {
    const navElement = getTabNavigationElement(element) || element;
    return (
        closestSelector(navElement, "li.nav-item") ||
        closestSelector(navElement, ".nav-item") ||
        navElement
    );
}

function isHidden(element) {
    return (
        !element ||
        element.classList.contains("d-none") ||
        element.hidden ||
        (element.style && element.style.display === "none")
    );
}

function applyButtonRestrictions(root, restrictions) {
    for (const button of restrictions.buttons) {
        const buttonName = typeof button === "string" ? button : button.name;
        if (!buttonName) {
            continue;
        }
        const nameSelector = attrSelector("name", buttonName);
        safeQueryAll(root, [`button${nameSelector}`, `.btn${nameSelector}`], (button) => {
            setHidden(button, true);
        });
    }
}

function getTargetId(value) {
    const target = String(value || "").trim();
    if (!target || target === "#") {
        return false;
    }
    const hashIndex = target.indexOf("#");
    if (hashIndex >= 0) {
        return target.slice(hashIndex + 1) || false;
    }
    return target;
}

function findElementById(root, targetId) {
    if (!targetId) {
        return false;
    }
    const selector = `#${escapeCssIdentifier(targetId)}`;
    try {
        return (
            (root && root.querySelector && root.querySelector(selector)) ||
            (typeof document !== "undefined" && document.querySelector(selector)) ||
            false
        );
    } catch {
        return false;
    }
}

function getControlledPane(root, element) {
    if (!element || !element.getAttribute) {
        return false;
    }
    const targetValues = [
        element.getAttribute("aria-controls"),
        element.getAttribute("data-bs-target"),
        element.getAttribute("data-target"),
        element.getAttribute("href"),
    ];
    for (const targetValue of targetValues) {
        const pane = findElementById(root, getTargetId(targetValue));
        if (pane) {
            return pane;
        }
    }
    return false;
}

function hideTabElement(root, element) {
    const tabNav = getTabNavigationElement(element);
    const pane = getControlledPane(root, tabNav || element);
    if (tabNav) {
        const tabNavItem = getTabHideTarget(tabNav);
        setTabHidden(tabNav, true);
        if (tabNavItem !== tabNav) {
            setTabHidden(tabNavItem, true);
        }
    } else {
        setTabHidden(element, true);
    }
    setTabHidden(pane, true);
}

function hideTabByName(root, tabName) {
    if (!tabName) {
        return;
    }
    const selectors = [
        attrSelector("name", tabName),
        attrSelector("data-name", tabName),
        attrSelector("data-tab", tabName),
        attrContainsSelector("aria-controls", tabName),
        attrContainsSelector("href", tabName),
    ];
    safeQueryAll(root, selectors, (element) => {
        hideTabElement(root, element);
    });
}

function hideTabByLabel(root, tabLabel) {
    const expectedLabel = normalizeText(tabLabel);
    if (!expectedLabel) {
        return;
    }
    safeQueryAll(root, TAB_NAV_SELECTORS, (link) => {
        if (normalizeText(link.textContent) === expectedLabel) {
            hideTabElement(root, link);
        }
    });
}

function keepNotebookOnVisibleTab(notebook) {
    const tabLinks = Array.from(notebook.querySelectorAll(TAB_NAV_SELECTOR));
    const activeLink = tabLinks.find(
        (link) => link.classList.contains("active") || link.getAttribute("aria-selected") === "true"
    );
    const activeTabItem = activeLink && getTabHideTarget(activeLink);
    const content = notebook.querySelector(".o_notebook_content");
    if (!activeLink || !isHidden(activeTabItem)) {
        setHidden(content, false);
        return;
    }

    const visibleLink = tabLinks.find((link) => {
        const tabItem = getTabHideTarget(link);
        return (
            !isHidden(tabItem) &&
            !link.classList.contains("disabled") &&
            link.getAttribute("aria-disabled") !== "true"
        );
    });
    if (visibleLink) {
        visibleLink.click();
        setTabHidden(content, false);
        return;
    }
    setTabHidden(content, true);
}

function applyTabRestrictions(root, restrictions) {
    for (const tab of restrictions.tabs) {
        hideTabByName(root, tab.name);
        hideTabByLabel(root, tab.label);
    }
    safeQueryAll(root, [".o_notebook"], keepNotebookOnVisibleTab);
}

function applyViewElementRestrictions(controller) {
    try {
        const root = controller.rootRef && controller.rootRef.el;
        if (!root) {
            return;
        }
        const restrictions = controller.dynamicViewElementRestrictions || EMPTY_VIEW_ELEMENT_RESTRICTIONS;
        applyButtonRestrictions(root, restrictions);
        applyTabRestrictions(root, restrictions);
    } catch (error) {
        console.warn("[Dynamic View Element Restrictions Odoo18] apply failed", error);
    }
}

function getControllerModelName(controller) {
    const props = controller.props || {};
    const root = controller.model && controller.model.root;
    return props.resModel || (root && root.resModel) || false;
}

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this.dynamicViewElementOrm = useService("orm");
        this.dynamicViewElementRestrictions = EMPTY_VIEW_ELEMENT_RESTRICTIONS;
        this.dynamicViewElementObserver = false;
        this.dynamicViewElementTimer = false;

        onWillStart(async () => {
            await this.loadDynamicViewElementRestrictions();
        });

        onMounted(() => {
            this.startDynamicViewElementObserver();
            this.scheduleDynamicViewElementApply();
        });

        onPatched(() => {
            this.scheduleDynamicViewElementApply();
        });

        onWillUnmount(() => {
            this.stopDynamicViewElementObserver();
        });
    },

    async loadDynamicViewElementRestrictions() {
        const modelName = getControllerModelName(this);
        if (!modelName) {
            this.dynamicViewElementRestrictions = EMPTY_VIEW_ELEMENT_RESTRICTIONS;
            return;
        }
        try {
            const result = await this.dynamicViewElementOrm.call(
                "user.restrict",
                "get_view_ui_restrictions",
                [modelName]
            );
            this.dynamicViewElementRestrictions = normalizeRestrictions(result);
        } catch (error) {
            this.dynamicViewElementRestrictions = EMPTY_VIEW_ELEMENT_RESTRICTIONS;
            console.warn("[Dynamic View Element Restrictions Odoo18] load failed", error);
        }
    },

    scheduleDynamicViewElementApply() {
        if (typeof window === "undefined") {
            applyViewElementRestrictions(this);
            return;
        }
        window.clearTimeout(this.dynamicViewElementTimer);
        this.dynamicViewElementTimer = window.setTimeout(() => {
            applyViewElementRestrictions(this);
        }, 300);
    },

    startDynamicViewElementObserver() {
        if (typeof MutationObserver === "undefined") {
            return;
        }
        const target = typeof document !== "undefined" && document.body;
        if (!target || this.dynamicViewElementObserver) {
            return;
        }
        try {
            this.dynamicViewElementObserver = new MutationObserver(() => {
                this.scheduleDynamicViewElementApply();
            });
            this.dynamicViewElementObserver.observe(target, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: [
                    "class",
                    "name",
                    "data-name",
                    "data-tab",
                    "href",
                    "aria-controls",
                    "aria-selected",
                    "data-bs-target",
                    "data-target",
                ],
            });
        } catch (error) {
            this.dynamicViewElementObserver = false;
            console.warn("[Dynamic View Element Restrictions Odoo18] observer failed", error);
        }
    },

    stopDynamicViewElementObserver() {
        if (typeof window !== "undefined") {
            window.clearTimeout(this.dynamicViewElementTimer);
        }
        if (this.dynamicViewElementObserver) {
            this.dynamicViewElementObserver.disconnect();
            this.dynamicViewElementObserver = false;
        }
    },
});
