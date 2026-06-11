/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
import { onPatched, onWillStart, useEffect } from "@odoo/owl";

const EMPTY_RESTRICTIONS = Object.freeze({
    prevent_create: false,
    prevent_edit: false,
    prevent_delete: false,
    prevent_duplicate: false,
    prevent_export: false,
    prevent_archive: false,
    prevent_import: false,
    prevent_mass_edit: false,
    prevent_mass_delete: false,
    prevent_mass_archive: false,
});

const ACTION_FIELDS = Object.keys(EMPTY_RESTRICTIONS);

const STATIC_ACTIONS = {
    archive: "prevent_archive",
    unarchive: "prevent_archive",
    duplicate: "prevent_duplicate",
    delete: "prevent_delete",
    export: "prevent_export",
};

const COG_COMPONENT_FIELDS = {
    ExportAll: "prevent_export",
    ImportRecords: "prevent_import",
};

const cogMenuRegistry = registry.category("cogMenu");
const restrictionsByModel = new Map();

function normalizeRestrictions(restrictions) {
    const normalized = { ...EMPTY_RESTRICTIONS, ...(restrictions || {}) };
    for (const fieldName of ACTION_FIELDS) {
        normalized[fieldName] = Boolean(normalized[fieldName]);
    }
    return normalized;
}

function setModelRestrictions(modelName, restrictions) {
    const normalized = normalizeRestrictions(restrictions);
    if (modelName) {
        restrictionsByModel.set(modelName, normalized);
    }
    return normalized;
}

function getModelRestrictions(modelName) {
    return normalizeRestrictions(restrictionsByModel.get(modelName));
}

function isPrevented(restrictions, fieldName) {
    const normalized = normalizeRestrictions(restrictions);
    return Boolean(fieldName && normalized[fieldName]);
}

function getControllerModelName(controller) {
    const props = controller.props || {};
    const model = controller.model || {};
    return props.resModel || (model.root && model.root.resModel) || false;
}

function getControllerRecordIds(controller) {
    const root = controller.model && controller.model.root;
    if (!root) {
        return [];
    }
    if (root.resId) {
        return [root.resId];
    }
    if (Array.isArray(root.selection)) {
        return root.selection.map((record) => record.resId).filter(Boolean);
    }
    return [];
}

function getEnvModelName(env) {
    return (
        (env.searchModel && env.searchModel.resModel) ||
        (env.model && env.model.root && env.model.root.resModel) ||
        (env.config && env.config.resModel) ||
        false
    );
}

function getCogModelName(cogMenu) {
    const props = cogMenu.props || {};
    return props.resModel || getEnvModelName(cogMenu.env || {});
}

async function loadUiRestrictions(controller) {
    const modelName = getControllerModelName(controller);
    if (!modelName) {
        return setModelRestrictions(modelName, EMPTY_RESTRICTIONS);
    }

    const orm = controller.dynamicRestrictionOrm || controller.orm;
    if (!orm) {
        return setModelRestrictions(modelName, EMPTY_RESTRICTIONS);
    }

    try {
        const recordIds = getControllerRecordIds(controller);
        const args = recordIds.length ? [modelName, recordIds] : [modelName];
        const restrictions = await orm.call("user.restrict", "get_ui_restrictions", args);
        return setModelRestrictions(modelName, restrictions);
    } catch (error) {
        console.warn("dynamic_restriction: failed to load UI restrictions", error);
        return setModelRestrictions(modelName, EMPTY_RESTRICTIONS);
    }
}

function restrictStaticActionItems(items, restrictions, extraActionFields = {}) {
    const normalized = normalizeRestrictions(restrictions);
    const restrictedItems = { ...items };
    for (const [actionName, fieldName] of Object.entries(STATIC_ACTIONS)) {
        if (!restrictedItems[actionName]) {
            continue;
        }
        const massFieldName = extraActionFields[actionName];
        const originalIsAvailable = restrictedItems[actionName].isAvailable;
        restrictedItems[actionName] = {
            ...restrictedItems[actionName],
            isAvailable: () =>
                !normalized[fieldName] &&
                !normalized[massFieldName] &&
                (originalIsAvailable === undefined || originalIsAvailable()),
        };
    }
    return restrictedItems;
}

function isActionItemPrevented(item, restrictions, extraActionFields = {}) {
    const actionKey = item && item.key;
    const fieldName = STATIC_ACTIONS[actionKey];
    const massFieldName = extraActionFields[actionKey];
    return isPrevented(restrictions, fieldName) || isPrevented(restrictions, massFieldName);
}

function patchCogMenuRegistryItem(registryKey, fieldName) {
    if (!cogMenuRegistry.contains(registryKey)) {
        return;
    }
    const originalItem = cogMenuRegistry.get(registryKey);
    const originalIsDisplayed = originalItem.isDisplayed;
    cogMenuRegistry.add(
        registryKey,
        {
            ...originalItem,
            isDisplayed: async (env) => {
                const displayed = originalIsDisplayed ? await originalIsDisplayed(env) : true;
                if (!displayed) {
                    return false;
                }
                return !isPrevented(getModelRestrictions(getEnvModelName(env)), fieldName);
            },
        },
        { force: true }
    );
}

// Odoo 18 exposes Export All and Import through the cogMenu registry. Keep the
// getter filter below as a fallback for already-computed registry items.
patchCogMenuRegistryItem("export-all-menu", "prevent_export");
patchCogMenuRegistryItem("import-menu", "prevent_import");

patch(CogMenu.prototype, {
    get cogItems() {
        const restrictions = getModelRestrictions(getCogModelName(this));
        return super.cogItems.filter((item) => {
            const componentName = item.key || (item.Component && item.Component.name);
            const fieldName = COG_COMPONENT_FIELDS[componentName];
            return !isPrevented(restrictions, fieldName);
        });
    },
});

patch(FormController.prototype, {
    setup() {
        super.setup();
        this.dynamicRestrictionOrm = useService("orm");
        this.uiRestrictions = setModelRestrictions(this.props.resModel, EMPTY_RESTRICTIONS);
        this.baseCanCreate = this.canCreate;
        this.baseCanEdit = this.canEdit;

        onWillStart(async () => {
            await this.loadDynamicUiRestrictions(false);
        });

        useEffect(
            () => {
                this.loadDynamicUiRestrictions(true);
            },
            () => [(this.model.root && this.model.root.resId) || false]
        );

        onPatched(() => this.applyDynamicUiFallbacks());
    },

    async loadDynamicUiRestrictions(shouldRender) {
        this.uiRestrictions = await loadUiRestrictions(this);
        this.applyDynamicUiState();
        if (shouldRender) {
            this.render();
        }
    },

    applyDynamicUiState() {
        this.canCreate = this.baseCanCreate && !isPrevented(this.uiRestrictions, "prevent_create");
        this.canEdit = this.baseCanEdit && !isPrevented(this.uiRestrictions, "prevent_edit");

        const root = this.model && this.model.root;
        if (
            root &&
            root.switchMode &&
            !root.isNew &&
            root.isInEdition &&
            isPrevented(this.uiRestrictions, "prevent_edit")
        ) {
            root.switchMode("readonly");
        }
    },

    applyDynamicUiFallbacks() {
        const rootEl = this.rootRef && this.rootRef.el;
        if (!rootEl) {
            return;
        }
        const root = this.model && this.model.root;
        const preventExistingRecordEdit =
            isPrevented(this.uiRestrictions, "prevent_edit") && !(root && root.isNew);
        rootEl
            .querySelectorAll(".o_form_button_create")
            .forEach((button) =>
                button.classList.toggle(
                    "d-none",
                    isPrevented(this.uiRestrictions, "prevent_create")
                )
            );
        rootEl
            .querySelectorAll(".o_form_status_indicator")
            .forEach((button) => button.classList.toggle("d-none", preventExistingRecordEdit));
    },

    getStaticActionMenuItems() {
        return restrictStaticActionItems(
            super.getStaticActionMenuItems(),
            this.uiRestrictions
        );
    },

    async shouldExecuteAction(item) {
        if (isActionItemPrevented(item, this.uiRestrictions)) {
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
        this.dynamicRestrictionOrm = useService("orm");
        this.uiRestrictions = setModelRestrictions(getControllerModelName(this), EMPTY_RESTRICTIONS);
        this.baseActiveActions = { ...this.activeActions };
        this.baseEditable = this.editable;
        this.baseModelMultiEdit = Boolean(this.model && this.model.multiEdit);

        onWillStart(async () => {
            await this.loadDynamicUiRestrictions(false);
        });

        useEffect(
            () => {
                this.loadDynamicUiRestrictions(true);
            },
            () => [this.props.resModel]
        );

        onPatched(() => this.applyDynamicUiFallbacks());
    },

    async loadDynamicUiRestrictions(shouldRender) {
        this.uiRestrictions = await loadUiRestrictions(this);
        this.applyDynamicUiState();
        if (shouldRender) {
            this.render();
        }
    },

    getSelectedCount() {
        const root = this.model && this.model.root;
        if (!root) {
            return 0;
        }
        if (root.isDomainSelected) {
            return 2;
        }
        return Array.isArray(root.selection) ? root.selection.length : 0;
    },

    getListMassActionFields() {
        if (this.getSelectedCount() <= 1) {
            return {};
        }
        return {
            archive: "prevent_mass_archive",
            unarchive: "prevent_mass_archive",
            delete: "prevent_mass_delete",
        };
    },

    isAnyMassActionPrevented() {
        return (
            this.getSelectedCount() > 1 &&
            (isPrevented(this.uiRestrictions, "prevent_mass_edit") ||
                isPrevented(this.uiRestrictions, "prevent_mass_delete") ||
                isPrevented(this.uiRestrictions, "prevent_mass_archive"))
        );
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
        if (this.model) {
            this.model.multiEdit =
                this.baseModelMultiEdit && !isPrevented(this.uiRestrictions, "prevent_mass_edit");
        }
    },

    applyDynamicUiFallbacks() {
        const rootEl = this.rootRef && this.rootRef.el;
        if (!rootEl) {
            return;
        }
        rootEl
            .querySelectorAll(".o_list_button_add")
            .forEach((button) =>
                button.classList.toggle(
                    "d-none",
                    isPrevented(this.uiRestrictions, "prevent_create")
                )
            );
    },

    get actionMenuProps() {
        return {
            ...super.actionMenuProps,
            shouldExecuteAction: this.shouldExecuteAction.bind(this),
        };
    },

    getStaticActionMenuItems() {
        return restrictStaticActionItems(
            super.getStaticActionMenuItems(),
            this.uiRestrictions,
            this.getListMassActionFields()
        );
    },

    async shouldExecuteAction(item) {
        if (isActionItemPrevented(item, this.uiRestrictions, this.getListMassActionFields())) {
            return false;
        }
        if (item && item.action && this.isAnyMassActionPrevented()) {
            return false;
        }
        return true;
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
        if (
            isPrevented(this.uiRestrictions, "prevent_archive") ||
            (this.getSelectedCount() > 1 && isPrevented(this.uiRestrictions, "prevent_mass_archive"))
        ) {
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
        if (
            isPrevented(this.uiRestrictions, "prevent_delete") ||
            (this.getSelectedCount() > 1 && isPrevented(this.uiRestrictions, "prevent_mass_delete"))
        ) {
            return;
        }
        return super.onDeleteSelectedRecords(...args);
    },

    async beforeExecuteActionButton(clickParams) {
        if (this.isAnyMassActionPrevented()) {
            return false;
        }
        return super.beforeExecuteActionButton(clickParams);
    },

    onWillSaveMulti(editedRecord, changes, validSelectedRecords) {
        if (
            validSelectedRecords.length > 1 &&
            isPrevented(this.uiRestrictions, "prevent_mass_edit")
        ) {
            return false;
        }
        return super.onWillSaveMulti(editedRecord, changes, validSelectedRecords);
    },
});
