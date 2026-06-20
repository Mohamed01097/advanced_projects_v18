/** @odoo-module **/

console.log("DYNAMIC RESTRICTION JS LOADED - ODOO 18");

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched, onWillStart, useState } from "@odoo/owl";

const EMPTY_RESTRICTIONS = Object.freeze({
    hide_restricted_buttons: false,
    prevent_create: false,
    prevent_edit: false,
    prevent_delete: false,
    prevent_duplicate: false,
    prevent_export: false,
    prevent_archive: false,
    prevent_import: false,
});

const RESTRICTION_FIELDS = Object.keys(EMPTY_RESTRICTIONS);

const MENU_LABEL_FIELDS = new Map([
    ["delete", "prevent_delete"],
    ["duplicate", "prevent_duplicate"],
    ["archive", "prevent_archive"],
    ["unarchive", "prevent_archive"],
    ["export", "prevent_export"],
    ["export all", "prevent_export"],
    ["import", "prevent_import"],
    ["import records", "prevent_import"],
]);

const CREATE_LABELS = ["new", "create", "جديد", "إنشاء"];

const FORM_CREATE_SELECTORS = [".o_form_button_create", ".o_control_panel .btn-primary"];
const LIST_CREATE_SELECTORS = [".o_list_button_add", ".o_control_panel .btn-primary"];
const MENU_ITEM_SELECTORS = [
    ".dropdown-menu .dropdown-item",
    ".o-dropdown--menu .dropdown-item",
    ".dropdown-menu .o-dropdown-item",
    ".o-dropdown--menu .o-dropdown-item",
    "[role=\"menuitem\"]",
].join(",");

const restrictionsByModel = new Map();
let activeModelName = false;
let observerStarted = false;
let observerTimer = false;

function normalizeRestrictions(restrictions) {
    const normalized = { ...EMPTY_RESTRICTIONS, ...(restrictions || {}) };
    for (const fieldName of RESTRICTION_FIELDS) {
        normalized[fieldName] = Boolean(normalized[fieldName]);
    }
    return normalized;
}

function isPrevented(restrictions, fieldName) {
    return Boolean(normalizeRestrictions(restrictions)[fieldName]);
}

function normalizeText(value) {
    return String(value || "")
        .replace(/\s+/g, " ")
        .trim()
        .toLowerCase();
}

function getElementText(element) {
    return normalizeText(element && (element.innerText || element.textContent));
}

function hasButtonLabel(element, labels) {
    const text = getElementText(element);
    return labels.some((label) => text.includes(normalizeText(label)));
}

function getControllerModelName(controller) {
    const props = controller.props || {};
    const root = controller.model && controller.model.root;
    return props.resModel || (root && root.resModel) || false;
}

function getControllerResId(controller) {
    const props = controller.props || {};
    const root = controller.model && controller.model.root;
    return (root && root.resId) || props.resId || false;
}

function isExistingFormRecord(controller) {
    const root = controller.model && controller.model.root;
    if (root) {
        return !root.isNew;
    }
    return Boolean(controller.props && controller.props.resId);
}

function setDynamicHidden(element, hidden) {
    if (!element) {
        return;
    }
    if (hidden) {
        element.classList.add("d-none");
        element.setAttribute("aria-hidden", "true");
        element.dataset.dynamicRestrictionHidden = "1";
    } else if (element.dataset.dynamicRestrictionHidden === "1") {
        element.classList.remove("d-none");
        element.removeAttribute("aria-hidden");
        delete element.dataset.dynamicRestrictionHidden;
    }
}

function forEachElement(root, selectors, callback) {
    const target = root || (typeof document !== "undefined" ? document : false);
    if (!target || !target.querySelectorAll) {
        return;
    }
    for (const selector of selectors) {
        try {
            target.querySelectorAll(selector).forEach(callback);
        } catch (error) {
            console.warn("dynamic_restriction: ignored invalid selector", selector, error);
        }
    }
}

function hideCreateButtons(root, restrictions, selectors) {
    const preventCreate = isPrevented(restrictions, "prevent_create");
    forEachElement(root, selectors, (button) => {
        const selectorNeedsTextGuard = button.matches(".o_control_panel .btn-primary");
        if (selectorNeedsTextGuard && !hasButtonLabel(button, CREATE_LABELS)) {
            return;
        }
        setDynamicHidden(button, preventCreate);
    });
}

function hideFormEditControls(root, restrictions, hideStatusIndicator) {
    const preventEdit = isPrevented(restrictions, "prevent_edit");
    forEachElement(root, [".o_form_button_edit"], (button) =>
        setDynamicHidden(button, preventEdit)
    );
    forEachElement(root, [".o_form_status_indicator"], (button) =>
        setDynamicHidden(button, preventEdit && hideStatusIndicator)
    );
}

function hideDropdownItemsByText(restrictions) {
    const target = typeof document !== "undefined" ? document : false;
    if (!target || !target.querySelectorAll) {
        return;
    }
    const normalized = normalizeRestrictions(restrictions);
    try {
        target.querySelectorAll(MENU_ITEM_SELECTORS).forEach((item) => {
            const fieldName = MENU_LABEL_FIELDS.get(getElementText(item));
            if (!fieldName) {
                return;
            }
            setDynamicHidden(item, normalized[fieldName]);
        });
    } catch (error) {
        console.warn("dynamic_restriction: failed to hide restricted menu items", error);
    }
}

function applyFormDomFallbacks(controller) {
    const rootEl = controller.rootRef && controller.rootRef.el;
    if (rootEl) {
        hideCreateButtons(rootEl, controller.uiRestrictions, FORM_CREATE_SELECTORS);
        hideFormEditControls(rootEl, controller.uiRestrictions, isExistingFormRecord(controller));
    }
    hideDropdownItemsByText(controller.uiRestrictions);
}

function applyListDomFallbacks(controller) {
    const rootEl = controller.rootRef && controller.rootRef.el;
    if (rootEl) {
        hideCreateButtons(rootEl, controller.uiRestrictions, LIST_CREATE_SELECTORS);
    }
    hideDropdownItemsByText(controller.uiRestrictions);
}

function scheduleDomFallbacks(callback) {
    if (typeof window === "undefined") {
        callback();
        return;
    }
    for (const delay of [0, 75, 250, 500]) {
        window.setTimeout(callback, delay);
    }
}

function setupDomFallbacks(controller, callback) {
    const runFallbacks = () => scheduleDomFallbacks(callback);
    onMounted(() => {
        const rootEl = controller.rootRef && controller.rootRef.el;
        if (rootEl && rootEl.addEventListener) {
            rootEl.addEventListener("click", runFallbacks, true);
        }
        runFallbacks();
    });
    onPatched(runFallbacks);
}

function setControllerRestrictions(controller, restrictions) {
    const normalized = normalizeRestrictions(restrictions);
    controller.uiRestrictions = normalized;
    const modelName = getControllerModelName(controller);
    if (modelName) {
        activeModelName = modelName;
        restrictionsByModel.set(modelName, normalized);
    }
    if (controller.dynamicRestrictionState) {
        controller.dynamicRestrictionState.restrictions = normalized;
    }
    return normalized;
}

function getActiveRestrictions() {
    return normalizeRestrictions(restrictionsByModel.get(activeModelName));
}

function cleanupGlobalDom() {
    try {
        const restrictions = getActiveRestrictions();
        if (typeof document === "undefined" || !document.body) {
            return;
        }
        hideCreateButtons(document.body, restrictions, FORM_CREATE_SELECTORS);
        hideCreateButtons(document.body, restrictions, LIST_CREATE_SELECTORS);
        hideFormEditControls(document.body, restrictions, true);
        hideDropdownItemsByText(restrictions);
    } catch (error) {
        console.warn("dynamic_restriction: failed global DOM cleanup", error);
    }
}

function scheduleGlobalDomCleanup() {
    if (typeof window === "undefined") {
        cleanupGlobalDom();
        return;
    }
    window.clearTimeout(observerTimer);
    observerTimer = window.setTimeout(cleanupGlobalDom, 50);
}

function ensureGlobalObserver() {
    if (observerStarted || typeof window === "undefined" || typeof MutationObserver === "undefined") {
        return;
    }
    observerStarted = true;
    try {
        const observer = new MutationObserver(scheduleGlobalDomCleanup);
        const startObserver = () => {
            if (!document.body) {
                return;
            }
            observer.observe(document.body, {
                childList: true,
                subtree: true,
            });
            scheduleGlobalDomCleanup();
        };
        if (document.body) {
            startObserver();
        } else {
            window.setTimeout(startObserver, 0);
        }
    } catch (error) {
        console.warn("dynamic_restriction: failed to start global observer", error);
    }
}

async function loadUiRestrictions(controller) {
    const modelName = getControllerModelName(controller);
    if (!modelName || !controller.orm || !controller.orm.call) {
        return setControllerRestrictions(controller, EMPTY_RESTRICTIONS);
    }

    try {
        const restrictions = await controller.orm.call("user.restrict", "get_ui_restrictions", [
            modelName,
            getControllerResId(controller),
        ]);
        const normalized = setControllerRestrictions(controller, restrictions);
        console.log("[Dynamic Restriction UI Odoo18]", modelName, normalized);
        ensureGlobalObserver();
        scheduleGlobalDomCleanup();
        return normalized;
    } catch (error) {
        console.warn("dynamic_restriction: failed to load UI restrictions", error);
        return setControllerRestrictions(controller, EMPTY_RESTRICTIONS);
    }
}

function filterStaticActionItems(items, restrictions) {
    const normalized = normalizeRestrictions(restrictions);
    const restrictedItems = { ...(items || {}) };
    for (const [actionName, fieldName] of [
        ["archive", "prevent_archive"],
        ["unarchive", "prevent_archive"],
        ["duplicate", "prevent_duplicate"],
        ["delete", "prevent_delete"],
        ["export", "prevent_export"],
    ]) {
        if (!restrictedItems[actionName]) {
            continue;
        }
        const originalIsAvailable = restrictedItems[actionName].isAvailable;
        restrictedItems[actionName] = {
            ...restrictedItems[actionName],
            isAvailable: () =>
                !normalized[fieldName] &&
                (originalIsAvailable === undefined || originalIsAvailable()),
        };
    }
    return restrictedItems;
}

function forceFormReadonly(controller) {
    if (!isPrevented(controller.uiRestrictions, "prevent_edit")) {
        return;
    }
    const root = controller.model && controller.model.root;
    if (!root || !root.switchMode || !isExistingFormRecord(controller) || !root.isInEdition) {
        return;
    }
    try {
        const result = root.switchMode("readonly");
        if (result && result.catch) {
            result.catch((error) =>
                console.warn("dynamic_restriction: failed to switch form to readonly", error)
            );
        }
    } catch (error) {
        console.warn("dynamic_restriction: failed to switch form to readonly", error);
    }
}

patch(FormController.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.uiRestrictions = normalizeRestrictions();
        this.dynamicRestrictionState = useState({ restrictions: this.uiRestrictions });
        this.baseCanCreate = this.canCreate;
        this.baseCanEdit = this.canEdit;

        onWillStart(async () => {
            await this.loadDynamicUiRestrictions(false);
        });

        setupDomFallbacks(this, () => {
            this.applyDynamicUiState();
            this.applyDynamicUiFallbacks();
        });
    },

    async loadDynamicUiRestrictions(shouldRender) {
        await loadUiRestrictions(this);
        this.applyDynamicUiState();
        this.applyDynamicUiFallbacks();
        if (shouldRender) {
            this.render();
        }
    },

    applyDynamicUiState() {
        this.canCreate = this.baseCanCreate && !isPrevented(this.uiRestrictions, "prevent_create");
        this.canEdit =
            this.baseCanEdit &&
            (!isPrevented(this.uiRestrictions, "prevent_edit") || !isExistingFormRecord(this));
        forceFormReadonly(this);
    },

    applyDynamicUiFallbacks() {
        applyFormDomFallbacks(this);
    },

    getStaticActionMenuItems() {
        return filterStaticActionItems(super.getStaticActionMenuItems(), this.uiRestrictions);
    },

    async shouldExecuteAction(item) {
        const label = getElementText({ textContent: item && (item.description || item.name) });
        const fieldName = MENU_LABEL_FIELDS.get(label);
        if (fieldName && isPrevented(this.uiRestrictions, fieldName)) {
            return false;
        }
        return super.shouldExecuteAction(item);
    },

    async create(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_create")) {
            return;
        }
        return super.create(...args);
    },

    async duplicateRecord(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_duplicate")) {
            return;
        }
        return super.duplicateRecord(...args);
    },

    async deleteRecord(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_delete")) {
            return;
        }
        return super.deleteRecord(...args);
    },
});

patch(ListController.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.uiRestrictions = normalizeRestrictions();
        this.dynamicRestrictionState = useState({ restrictions: this.uiRestrictions });
        this.baseActiveActions = { ...(this.activeActions || {}) };
        this.baseEditable = this.editable;

        onWillStart(async () => {
            await this.loadDynamicUiRestrictions(false);
        });

        setupDomFallbacks(this, () => {
            this.applyDynamicUiState();
            this.applyDynamicUiFallbacks();
        });
    },

    async loadDynamicUiRestrictions(shouldRender) {
        await loadUiRestrictions(this);
        this.applyDynamicUiState();
        this.applyDynamicUiFallbacks();
        if (shouldRender) {
            this.render();
        }
    },

    applyDynamicUiState() {
        this.activeActions = {
            ...this.baseActiveActions,
            create:
                this.baseActiveActions.create &&
                !isPrevented(this.uiRestrictions, "prevent_create"),
            edit:
                this.baseActiveActions.edit &&
                !isPrevented(this.uiRestrictions, "prevent_edit"),
            delete:
                this.baseActiveActions.delete &&
                !isPrevented(this.uiRestrictions, "prevent_delete"),
            duplicate:
                this.baseActiveActions.duplicate &&
                !isPrevented(this.uiRestrictions, "prevent_duplicate"),
        };
        this.editable = isPrevented(this.uiRestrictions, "prevent_edit")
            ? false
            : this.baseEditable;
    },

    applyDynamicUiFallbacks() {
        applyListDomFallbacks(this);
    },

    getStaticActionMenuItems() {
        return filterStaticActionItems(super.getStaticActionMenuItems(), this.uiRestrictions);
    },

    async onClickCreate(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_create")) {
            return;
        }
        return super.onClickCreate(...args);
    },

    async createRecord(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_create")) {
            return;
        }
        return super.createRecord(...args);
    },

    async onExportData(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_export")) {
            return;
        }
        return super.onExportData(...args);
    },

    async onDirectExportData(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_export")) {
            return;
        }
        return super.onDirectExportData(...args);
    },

    async toggleArchiveState(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_archive")) {
            return;
        }
        return super.toggleArchiveState(...args);
    },

    async duplicateRecords(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_duplicate")) {
            return;
        }
        return super.duplicateRecords(...args);
    },

    async onDeleteSelectedRecords(...args) {
        if (isPrevented(this.uiRestrictions, "prevent_delete")) {
            return;
        }
        return super.onDeleteSelectedRecords(...args);
    },
});
