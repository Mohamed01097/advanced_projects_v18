import { Component, onWillDestroy, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { patch } from "@web/core/utils/patch";
import { X2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";

const SUPPORTED_TYPES = new Set([
    "char",
    "text",
    "html",
    "integer",
    "float",
    "monetary",
    "many2one",
    "selection",
    "boolean",
    "date",
    "datetime",
]);

const INTERNAL_FIELDS = new Set(["id", "display_name", "__last_update"]);

const OPERATOR_GROUPS = {
    text: [
        { value: "contains", label: _t("contains") },
        { value: "not_contains", label: _t("not contains") },
        { value: "=", label: "=" },
        { value: "!=", label: "!=" },
        { value: "starts_with", label: _t("starts with") },
        { value: "ends_with", label: _t("ends with") },
    ],
    number: [
        { value: "=", label: "=" },
        { value: "!=", label: "!=" },
        { value: ">", label: ">" },
        { value: "<", label: "<" },
        { value: ">=", label: ">=" },
        { value: "<=", label: "<=" },
    ],
    date: [
        { value: "=", label: "=" },
        { value: "!=", label: "!=" },
        { value: ">", label: ">" },
        { value: "<", label: "<" },
        { value: ">=", label: ">=" },
        { value: "<=", label: "<=" },
    ],
    boolean: [
        { value: "is_true", label: _t("is true") },
        { value: "is_false", label: _t("is false") },
    ],
    selection: [
        { value: "=", label: "=" },
        { value: "!=", label: "!=" },
        { value: "contains", label: _t("contains") },
    ],
};

const FILTERS_BY_LIST = new WeakMap();
const DEFAULT_DISPLAY_MODE = "hide";
const DISPLAY_MODES = new Set([DEFAULT_DISPLAY_MODE, "highlight", "dim"]);
const SEARCH_DEBOUNCE_MS = 275;
const O2MAF_DEBUG = false;
const O2MAF_RENDERER_PROP = "o2mafFilterState";
const O2MAF_RENDERER_PROP_OPTIONAL = "o2mafFilterState?";
const QUICK_CHIP_IDS = new Set(["notes", "sections", "products", "qty_positive"]);
const QUANTITY_FIELD_NAMES = ["quantity", "product_uom_qty", "product_qty", "qty"];
const PRODUCT_FIELD_NAMES = ["product_id", "product_template_id", "product_tmpl_id"];

// Odoo 18 can define component props either as an array or as an object depending on
// the exact web client build. Keep this defensive so the module does not break the
// ListRenderer props validator during form loading.
if (Array.isArray(ListRenderer.props)) {
    if (!ListRenderer.props.includes(O2MAF_RENDERER_PROP_OPTIONAL)) {
        ListRenderer.props = [...ListRenderer.props, O2MAF_RENDERER_PROP_OPTIONAL];
    }
} else if (ListRenderer.props && typeof ListRenderer.props === "object") {
    ListRenderer.props = {
        ...ListRenderer.props,
        [O2MAF_RENDERER_PROP]: { type: Object, optional: true },
    };
}

function normalizeDisplayMode(displayMode) {
    return DISPLAY_MODES.has(displayMode) ? displayMode : DEFAULT_DISPLAY_MODE;
}

function debugFilter(...args) {
    if (O2MAF_DEBUG) {
        console.debug("[o2maf]", ...args);
    }
}

function getRecordKey(record) {
    const key =
        record?.id ??
        record?.resId ??
        record?._virtualId ??
        record?.localId ??
        record?.__bm_handle__;
    return key === undefined || key === null ? "" : String(key);
}

function sortFields(fields) {
    return [...fields].sort((left, right) => {
        const leftPriority = getFieldPriority(left);
        const rightPriority = getFieldPriority(right);
        if (leftPriority !== rightPriority) {
            return leftPriority - rightPriority;
        }
        return String(left.label || left.name).localeCompare(String(right.label || right.name));
    });
}

function getFieldPriority(field) {
    const key = `${field.name || ""} ${field.label || ""}`.toLocaleLowerCase();
    const groups = [
        ["product", "product_id", "product template"],
        ["description", "name", "label"],
        ["quantity", "qty", "product_uom_qty", "product_qty"],
        ["price", "amount", "subtotal", "total"],
        ["account"],
        ["tax", "taxes"],
        ["analytic"],
        ["date"],
    ];
    const index = groups.findIndex((keywords) => keywords.some((keyword) => key.includes(keyword)));
    return index >= 0 ? index : groups.length;
}

function getFieldGroup(type) {
    if (["integer", "float", "monetary"].includes(type)) {
        return "number";
    }
    if (["date", "datetime"].includes(type)) {
        return "date";
    }
    if (type === "boolean") {
        return "boolean";
    }
    if (type === "selection") {
        return "selection";
    }
    return "text";
}

function getCommonGroup(fields) {
    const groups = new Set(fields.map((field) => getFieldGroup(field.type)));
    return groups.size === 1 ? fields.length && groups.values().next().value : "text";
}

function normalizeText(value) {
    return String(value === false || value === null || value === undefined ? "" : value)
        .trim()
        .toLocaleLowerCase();
}

function stripHtml(value) {
    return String(value || "").replace(/<[^>]*>/g, " ");
}

function normalizeSelection(selection) {
    if (!selection) {
        return [];
    }
    if (Array.isArray(selection)) {
        return selection.map((item) => {
            if (Array.isArray(item)) {
                return { value: item[0], label: item[1] };
            }
            return { value: item, label: item };
        });
    }
    if (typeof selection === "object") {
        return Object.entries(selection).map(([value, label]) => ({ value, label }));
    }
    return [];
}

function getRawValueKey(value, type) {
    if (value === false || value === null || value === undefined) {
        return "";
    }
    if (type === "many2one") {
        if (Array.isArray(value)) {
            return `${value[0] || ""}|${value[1] || ""}`;
        }
        if (typeof value === "object") {
            return `${value.id || ""}|${value.display_name || value.name || ""}`;
        }
    }
    if (value instanceof Date) {
        return value.toISOString();
    }
    if (typeof value?.toISO === "function") {
        return value.toISO();
    }
    return String(value);
}

function getDisplayText(value, field) {
    if (value === false || value === null || value === undefined) {
        return "";
    }
    if (field.type === "many2one") {
        if (Array.isArray(value)) {
            return value[1] || value[0] || "";
        }
        if (typeof value === "object") {
            return value.display_name || value.name || value.id || "";
        }
    }
    if (field.type === "selection") {
        const option = field.selection.find((item) => item.value === value);
        return `${value || ""} ${option?.label || ""}`;
    }
    if (field.type === "html") {
        return stripHtml(value);
    }
    if (typeof value?.toISO === "function") {
        return value.toISO();
    }
    return value;
}

function getSelectionLabel(value, field) {
    return field.selection.find((item) => item.value === value)?.label || "";
}

function parseNumber(value) {
    if (typeof value === "number") {
        return value;
    }
    if (value === false || value === null || value === undefined || value === "") {
        return NaN;
    }
    return Number(String(value).replace(/[,\s]/g, ""));
}

function parseDateValue(value, type) {
    if (value === false || value === null || value === undefined || value === "") {
        return { key: "", time: NaN };
    }
    if (typeof value?.toISODate === "function" && type === "date") {
        const key = value.toISODate();
        return { key, time: Date.parse(`${key}T00:00:00`) };
    }
    if (typeof value?.toISO === "function") {
        const iso = value.toISO();
        return {
            key: type === "date" ? iso.slice(0, 10) : iso.slice(0, 16),
            time: typeof value.toMillis === "function" ? value.toMillis() : Date.parse(iso),
        };
    }
    if (value instanceof Date) {
        const iso = value.toISOString();
        return { key: type === "date" ? iso.slice(0, 10) : iso.slice(0, 16), time: value.getTime() };
    }
    const text = String(value).replace(" ", "T");
    const key = type === "date" ? text.slice(0, 10) : text.slice(0, 16);
    return { key, time: Date.parse(text) };
}

function compareOrdered(left, operator, right) {
    switch (operator) {
        case "=":
            return left === right;
        case "!=":
            return left !== right;
        case ">":
            return left > right;
        case "<":
            return left < right;
        case ">=":
            return left >= right;
        case "<=":
            return left <= right;
    }
    return false;
}

function getActiveFilter(list) {
    const filter = FILTERS_BY_LIST.get(list);
    return filter?.active ? filter : null;
}

export class One2ManyAdvancedFilterPanel extends Component {
    static template = "custom_one2many_advanced_filter.Panel";
    static props = {
        fields: Array,
        active: Boolean,
        activeCount: Number,
        activeChipIds: Array,
        displayMode: String,
        quickChips: Array,
        searchTerm: String,
        visibleCount: Number,
        matchCount: Number,
        totalCount: Number,
        onApply: Function,
        onDisplayModeChange: Function,
        onReset: Function,
    };

    setup() {
        this.nextConditionId = 1;
        this.searchDebounceTimer = null;
        this.state = useState({
            expanded: false,
            searchTerm: this.props.searchTerm || "",
            logic: "AND",
            displayMode: normalizeDisplayMode(this.props.displayMode),
            activeChipIds: [...(this.props.activeChipIds || [])],
            conditions: [this.makeCondition()],
        });
        onWillDestroy(() => this.clearSearchDebounce());
    }

    makeCondition() {
        const fieldNames = [];
        return {
            id: this.nextConditionId++,
            fieldNames,
            fieldQuery: "",
            fieldDropdownOpen: false,
            highlightedFieldIndex: 0,
            operator: this.getOperatorOptions(fieldNames)[0]?.value || "contains",
            value: "",
        };
    }

    getField(name) {
        return this.props.fields.find((field) => field.name === name);
    }

    getSelectedFields(conditionOrNames) {
        const fieldNames = Array.isArray(conditionOrNames)
            ? conditionOrNames
            : conditionOrNames.fieldNames;
        return fieldNames.map((name) => this.getField(name)).filter(Boolean);
    }

    getConditionGroup(conditionOrNames) {
        const fields = this.getSelectedFields(conditionOrNames);
        return getCommonGroup(fields) || "text";
    }

    getOperatorOptions(conditionOrNames) {
        return OPERATOR_GROUPS[this.getConditionGroup(conditionOrNames)] || OPERATOR_GROUPS.text;
    }

    getFieldOptions(condition) {
        const searchTerm = normalizeText(condition.fieldQuery);
        if (!searchTerm) {
            return this.props.fields;
        }
        const selectedNames = new Set(condition.fieldNames);
        return this.props.fields.filter(
            (field) =>
                selectedNames.has(field.name) ||
                normalizeText(`${field.label || ""} ${field.name || ""}`).includes(searchTerm)
        );
    }

    getSelectedFieldLabel(condition) {
        return this.getSelectedFields(condition)[0]?.label || "";
    }

    getFieldInputValue(condition) {
        return condition.fieldDropdownOpen ? condition.fieldQuery : this.getSelectedFieldLabel(condition);
    }

    openFieldDropdown(condition, ev) {
        condition.fieldDropdownOpen = true;
        condition.fieldQuery = this.getSelectedFieldLabel(condition);
        condition.highlightedFieldIndex = 0;
        ev.target.select();
    }

    getSelectionOptions(condition) {
        return this.getSelectedFields(condition).find((field) => field.type === "selection")
            ?.selection || [];
    }

    getValueInputType(condition) {
        const fields = this.getSelectedFields(condition);
        const group = this.getConditionGroup(condition);
        if (group === "number") {
            return "number";
        }
        if (group === "date") {
            return fields.some((field) => field.type === "datetime") ? "datetime-local" : "date";
        }
        return "text";
    }

    getValuePlaceholder(condition) {
        const fields = this.getSelectedFields(condition);
        const field = fields[0];
        const group = this.getConditionGroup(condition);
        if (group === "number") {
            return _t("Enter number...");
        }
        if (group === "date") {
            return _t("Select date...");
        }
        if (!field) {
            return _t("Search value...");
        }
        return `Search ${String(field.label || _t("value")).toLocaleLowerCase()}...`;
    }

    getActiveSummary() {
        const totalCount = this.props.totalCount || 0;
        if (!this.props.active) {
            return _t("Showing %s of %s lines", totalCount, totalCount);
        }
        const displayModeLabel = this.getDisplayModeLabel(this.props.displayMode);
        if (normalizeDisplayMode(this.props.displayMode) === DEFAULT_DISPLAY_MODE) {
            return _t(
                "Showing %s of %s lines - %s",
                this.props.visibleCount,
                this.props.totalCount,
                displayModeLabel
            );
        }
        return _t(
            "Showing %s of %s lines - %s",
            this.props.matchCount,
            this.props.totalCount,
            displayModeLabel
        );
    }

    getDisplayModeLabel(displayMode) {
        switch (normalizeDisplayMode(displayMode)) {
            case "highlight":
                return _t("Highlight matching lines");
            case "dim":
                return _t("Dim non-matching lines");
            default:
                return _t("Hide non-matching lines");
        }
    }

    isChipActive(chip) {
        return this.state.activeChipIds.includes(chip.id);
    }

    conditionUsesValue(condition) {
        return !["is_true", "is_false"].includes(condition.operator);
    }

    useBooleanValueSelect(condition) {
        return this.getConditionGroup(condition) === "boolean";
    }

    getBooleanValue(condition) {
        return condition.operator === "is_false" ? "false" : "true";
    }

    useSelectionDropdown(condition) {
        return (
            this.getConditionGroup(condition) === "selection" &&
            condition.operator !== "contains" &&
            this.getSelectionOptions(condition).length
        );
    }

    ensureOperator(condition) {
        const operators = this.getOperatorOptions(condition);
        if (!operators.some((operator) => operator.value === condition.operator)) {
            condition.operator = operators[0]?.value || "contains";
            condition.value = "";
        }
        if (!this.conditionUsesValue(condition)) {
            condition.value = "";
        }
    }

    addCondition() {
        this.state.conditions.push(this.makeCondition());
    }

    removeCondition(condition) {
        if (this.state.conditions.length === 1) {
            this.state.conditions.splice(0, 1);
            return;
        }
        const index = this.state.conditions.findIndex((item) => item.id === condition.id);
        if (index >= 0) {
            this.state.conditions.splice(index, 1);
        }
    }

    selectField(condition, field) {
        condition.fieldNames = field ? [field.name] : [];
        condition.fieldQuery = "";
        condition.fieldDropdownOpen = false;
        condition.highlightedFieldIndex = 0;
        this.ensureOperator(condition);
    }

    onOperatorChange(condition, ev) {
        condition.operator = ev.target.value;
        this.ensureOperator(condition);
    }

    onBooleanValueChange(condition, ev) {
        condition.operator = ev.target.value === "false" ? "is_false" : "is_true";
        condition.value = "";
    }

    onValueInput(condition, ev) {
        condition.value = ev.target.value;
    }

    onFieldInput(condition, ev) {
        condition.fieldDropdownOpen = true;
        condition.fieldQuery = ev.target.value;
        condition.highlightedFieldIndex = 0;
    }

    onDisplayModeChange(ev) {
        const displayMode = normalizeDisplayMode(ev.target.value);
        this.state.displayMode = displayMode;
        this.props.onDisplayModeChange(displayMode);
    }

    onSearchInput(ev) {
        this.state.searchTerm = ev.target.value;
        this.scheduleApply();
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.apply();
        } else if (ev.key === "Escape" && this.state.searchTerm) {
            ev.preventDefault();
            this.state.searchTerm = "";
            this.apply();
        }
    }

    onValueKeydown(condition, ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.apply();
        } else if (ev.key === "Escape" && condition.value) {
            ev.preventDefault();
            condition.value = "";
        }
    }

    onFieldKeydown(condition, ev) {
        const options = this.getFieldOptions(condition);
        if (ev.key === "ArrowDown") {
            ev.preventDefault();
            condition.fieldDropdownOpen = true;
            condition.highlightedFieldIndex = options.length
                ? Math.min(options.length - 1, condition.highlightedFieldIndex + 1)
                : 0;
        } else if (ev.key === "ArrowUp") {
            ev.preventDefault();
            condition.fieldDropdownOpen = true;
            condition.highlightedFieldIndex = options.length
                ? Math.max(0, condition.highlightedFieldIndex - 1)
                : 0;
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            if (options.length) {
                this.selectField(condition, options[condition.highlightedFieldIndex] || options[0]);
            }
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            condition.fieldDropdownOpen = false;
            condition.fieldQuery = "";
        }
    }

    onFieldBlur(condition) {
        condition.fieldDropdownOpen = false;
        condition.fieldQuery = "";
    }

    toggleChip(chip) {
        const activeChipIds = this.state.activeChipIds.filter((id) => id !== chip.id);
        if (activeChipIds.length === this.state.activeChipIds.length) {
            activeChipIds.push(chip.id);
        }
        this.state.activeChipIds = activeChipIds;
        this.apply();
    }

    clearSearchDebounce() {
        if (this.searchDebounceTimer) {
            clearTimeout(this.searchDebounceTimer);
            this.searchDebounceTimer = null;
        }
    }

    scheduleApply() {
        this.clearSearchDebounce();
        this.searchDebounceTimer = setTimeout(() => {
            this.searchDebounceTimer = null;
            this.apply();
        }, SEARCH_DEBOUNCE_MS);
    }

    getPayload() {
        const conditions = this.state.conditions
            .map((condition) => ({
                fieldNames: [...condition.fieldNames],
                operator: condition.operator,
                value: condition.value,
            }))
            .filter(
                (condition) =>
                    condition.fieldNames.length &&
                    (!this.conditionUsesValue(condition) || condition.value !== "")
            );
        return {
            searchTerm: this.state.searchTerm.trim(),
            logic: this.state.logic === "OR" ? "OR" : "AND",
            displayMode: normalizeDisplayMode(this.state.displayMode),
            activeChipIds: [...this.state.activeChipIds],
            conditions,
        };
    }

    apply() {
        this.clearSearchDebounce();
        this.props.onApply(this.getPayload());
    }

    reset() {
        this.clearSearchDebounce();
        this.state.searchTerm = "";
        this.state.logic = "AND";
        this.state.displayMode = DEFAULT_DISPLAY_MODE;
        this.state.activeChipIds = [];
        this.state.conditions.splice(0, this.state.conditions.length, this.makeCondition());
        this.props.onReset();
    }
}

patch(X2ManyField.prototype, {
    setup() {
        super.setup(...arguments);
        this.o2mafCurrentList = null;
        this.o2mafCurrentFilterState = null;
        this.o2mafSkipNextSync = false;
        this.o2mafValueCache = new WeakMap();
        this.o2mafSearchValueCache = new WeakMap();
        this.o2mafState = useState({
            active: false,
            conditions: [],
            searchTerm: "",
            activeChipIds: [],
            logic: "AND",
            displayMode: DEFAULT_DISPLAY_MODE,
            visibleCount: 0,
            matchCount: 0,
            totalCount: 0,
            matchedRowKeys: new Set(),
            visibleRowKeys: new Set(),
            firstRowKeys: [],
        });
        onWillDestroy(() => {
            if (this.o2mafCurrentList) {
                FILTERS_BY_LIST.delete(this.o2mafCurrentList);
            }
            this.o2mafValueCache = new WeakMap();
            this.o2mafSearchValueCache = new WeakMap();
        });
    },

    get rendererProps() {
        const props = { ...super.rendererProps };
        if (this.o2mafSkipNextSync) {
            this.o2mafSkipNextSync = false;
        } else {
            this.o2mafSyncStore(false);
        }
        if (this.o2mafCanDisplay) {
            props.o2mafFilterState = this.o2mafCurrentFilterState || this.o2mafRendererFilterState;
        }
        return props;
    },

    get o2mafPanelComponent() {
        return One2ManyAdvancedFilterPanel;
    },

    get o2mafCanDisplay() {
        return Boolean(
            this.props.viewMode === "list" &&
            !this.isMany2Many &&
            this.list &&
            !this.list.isGrouped
        );
    },

    get o2mafPanelProps() {
        const totalCount = this.list?.records?.length || 0;
        return {
            fields: this.o2mafAvailableFields,
            active: this.o2mafState.active,
            activeCount: this.o2mafState.conditions.length,
            activeChipIds: this.o2mafState.activeChipIds,
            displayMode: this.o2mafState.displayMode,
            quickChips: this.o2mafQuickChips,
            searchTerm: this.o2mafState.searchTerm,
            visibleCount: this.o2mafState.visibleCount,
            matchCount: this.o2mafState.matchCount,
            totalCount: this.o2mafState.totalCount || totalCount,
            onApply: this.o2mafApplyFilter.bind(this),
            onDisplayModeChange: this.o2mafChangeDisplayMode.bind(this),
            onReset: this.o2mafResetFilter.bind(this),
        };
    },

    get o2mafRendererFilterState() {
        return {
            active: this.o2mafState.active,
            displayMode: this.o2mafState.displayMode,
            searchTerm: this.o2mafState.searchTerm,
            activeChipIds: this.o2mafState.activeChipIds,
            matchedRowKeys: this.o2mafState.matchedRowKeys,
            visibleRowKeys: this.o2mafState.visibleRowKeys,
            visibleCount: this.o2mafState.visibleCount,
            matchCount: this.o2mafState.matchCount,
            totalCount: this.o2mafState.totalCount,
            firstRowKeys: this.o2mafState.firstRowKeys,
            debug: O2MAF_DEBUG,
        };
    },

    get o2mafAvailableFields() {
        if (!this.o2mafCanDisplay) {
            return [];
        }
        const fields = this.list.fields || {};
        const result = [];
        const seen = new Set();
        for (const column of this.archInfo?.columns || []) {
            const name = column.name;
            const field = fields[name];
            if (
                column.type !== "field" ||
                !name ||
                seen.has(name) ||
                INTERNAL_FIELDS.has(name) ||
                name.startsWith("__") ||
                column.widget === "handle" ||
                !field ||
                !SUPPORTED_TYPES.has(field.type) ||
                this.o2mafIsColumnInvisible(column)
            ) {
                continue;
            }
            seen.add(name);
            result.push({
                name,
                label: column.label || field.string || name,
                type: field.type,
                selection: normalizeSelection(field.selection),
            });
        }
        return sortFields(result);
    },

    get o2mafQuickChips() {
        const fields = this.list?.fields || {};
        const chips = [];
        if (fields.display_type) {
            chips.push({ id: "notes", label: _t("Notes Only") });
            chips.push({ id: "sections", label: _t("Sections Only") });
        }
        if (fields.display_type || PRODUCT_FIELD_NAMES.some((name) => fields[name])) {
            chips.push({ id: "products", label: _t("Products Only") });
        }
        if (QUANTITY_FIELD_NAMES.some((name) => fields[name])) {
            chips.push({ id: "qty_positive", label: _t("Quantity > 0") });
        }
        return chips;
    },

    o2mafIsColumnInvisible(column) {
        if (!column.column_invisible) {
            return false;
        }
        try {
            const evalContext = this.list?.evalContext || this.props?.record?.evalContext || {};
            return evaluateBooleanExpr(column.column_invisible, evalContext);
        } catch {
            return false;
        }
    },

    o2mafApplyFilter(payload) {
        const conditions = this.o2mafSanitizeConditions(payload.conditions || []);
        const searchTerm = String(payload.searchTerm || "").trim();
        const activeChipIds = this.o2mafSanitizeChipIds(payload.activeChipIds || []);
        this.o2mafState.logic = payload.logic === "OR" ? "OR" : "AND";
        this.o2mafState.displayMode = normalizeDisplayMode(payload.displayMode);
        this.o2mafState.conditions = conditions;
        this.o2mafState.searchTerm = searchTerm;
        this.o2mafState.activeChipIds = activeChipIds;
        this.o2mafState.active = Boolean(conditions.length || searchTerm || activeChipIds.length);
        this.o2mafSyncStore(true);
        this.render();
    },

    o2mafChangeDisplayMode(displayMode) {
        this.o2mafState.displayMode = normalizeDisplayMode(displayMode);
        if (this.o2mafState.active) {
            this.o2mafSkipNextSync = true;
            this.o2mafPublishFilterState();
            this.render();
        }
    },

    o2mafResetFilter() {
        this.o2mafState.active = false;
        this.o2mafState.conditions = [];
        this.o2mafState.searchTerm = "";
        this.o2mafState.activeChipIds = [];
        this.o2mafState.logic = "AND";
        this.o2mafState.displayMode = DEFAULT_DISPLAY_MODE;
        this.o2mafState.visibleCount = 0;
        this.o2mafState.matchCount = 0;
        this.o2mafState.totalCount = this.list?.records?.length || 0;
        this.o2mafState.matchedRowKeys = new Set();
        this.o2mafState.visibleRowKeys = new Set();
        this.o2mafState.firstRowKeys = [];
        this.o2mafCurrentFilterState = null;
        if (this.o2mafCurrentList) {
            FILTERS_BY_LIST.delete(this.o2mafCurrentList);
        }
        this.render();
    },

    o2mafSanitizeConditions(conditions) {
        const fieldsByName = new Map(this.o2mafAvailableFields.map((field) => [field.name, field]));
        return conditions.flatMap((condition) => {
            const fields = [...new Set(condition.fieldNames || [])]
                .map((name) => fieldsByName.get(name))
                .filter(Boolean);
            if (!fields.length) {
                return [];
            }
            const group = getCommonGroup(fields) || "text";
            const operators = OPERATOR_GROUPS[group] || OPERATOR_GROUPS.text;
            const operator = operators.some((item) => item.value === condition.operator)
                ? condition.operator
                : operators[0].value;
            if (!["is_true", "is_false"].includes(operator) && condition.value === "") {
                return [];
            }
            return [
                {
                    fields,
                    group,
                    operator,
                    value: condition.value,
                },
            ];
        });
    },

    o2mafSanitizeChipIds(chipIds) {
        const availableChipIds = new Set(this.o2mafQuickChips.map((chip) => chip.id));
        return [...new Set(chipIds)].filter(
            (chipId) => QUICK_CHIP_IDS.has(chipId) && availableChipIds.has(chipId)
        );
    },

    o2mafSyncStore(updateState) {
        const list = this.list;
        if (this.o2mafCurrentList && this.o2mafCurrentList !== list) {
            FILTERS_BY_LIST.delete(this.o2mafCurrentList);
        }
        this.o2mafCurrentList = list;
        if (!this.o2mafCanDisplay || !this.o2mafState.active) {
            if (list) {
                FILTERS_BY_LIST.delete(list);
            }
            if (updateState) {
                const totalCount = list?.records?.length || 0;
                this.o2mafState.visibleCount = totalCount;
                this.o2mafState.matchCount = 0;
                this.o2mafState.totalCount = totalCount;
                this.o2mafState.matchedRowKeys = new Set();
                this.o2mafState.visibleRowKeys = new Set();
                this.o2mafState.firstRowKeys = [];
            }
            this.o2mafCurrentFilterState = null;
            return;
        }
        const records = list.records || [];
        const { visibleRowKeys, matchedRowKeys, firstRowKeys } = this.o2mafComputeVisibleRecords(records);
        const filterState = {
            active: true,
            displayMode: this.o2mafState.displayMode,
            matchedRowKeys,
            visibleRowKeys,
            visibleCount: visibleRowKeys.size,
            matchCount: matchedRowKeys.size,
            totalCount: records.length,
            firstRowKeys,
            debug: O2MAF_DEBUG,
        };
        if (updateState) {
            this.o2mafState.visibleRowKeys = visibleRowKeys;
            this.o2mafState.matchedRowKeys = matchedRowKeys;
            this.o2mafState.firstRowKeys = firstRowKeys;
            this.o2mafState.visibleCount = visibleRowKeys.size;
            this.o2mafState.matchCount = matchedRowKeys.size;
            this.o2mafState.totalCount = records.length;
        }
        this.o2mafPublishFilterState(filterState);
    },

    o2mafPublishFilterState(filterState = this.o2mafRendererFilterState) {
        const list = this.o2mafCurrentList || this.list;
        if (!list || !filterState.active) {
            return;
        }
        this.o2mafCurrentFilterState = filterState;
        FILTERS_BY_LIST.set(list, filterState);
        debugFilter("publish", {
            displayMode: filterState.displayMode,
            filtersActive: filterState.active,
            totalRows: filterState.totalCount,
            matchedRows: filterState.matchCount,
            firstRowKeys: filterState.firstRowKeys,
        });
    },

    o2mafComputeVisibleRecords(records) {
        const visibleRowKeys = new Set();
        const matchedRowKeys = new Set();
        const displayRecords = new Set();
        const sectionParents = new Map();
        const preserveSectionParents = !this.o2mafState.activeChipIds.some((chipId) =>
            ["notes", "sections", "products"].includes(chipId)
        );
        let currentSection = null;
        let currentSubsection = null;
        const firstRowKeys = records.slice(0, 5).map((record) => getRecordKey(record));

        for (const record of records) {
            const displayType = record.data?.display_type;
            if (displayType === "line_section") {
                currentSection = record;
                currentSubsection = null;
            } else if (displayType === "line_subsection") {
                currentSubsection = record;
            }
            sectionParents.set(
                record,
                [currentSection, currentSubsection].filter((section) => section && section !== record)
            );
            const matches = !record.isNew && !record.isInEdition && this.o2mafRecordMatches(record);
            if (matches) {
                matchedRowKeys.add(getRecordKey(record));
            }
            if (record.isNew || record.isInEdition || matches) {
                displayRecords.add(record);
            }
        }

        for (const record of records) {
            if (!displayRecords.has(record)) {
                continue;
            }
            visibleRowKeys.add(getRecordKey(record));
            if (preserveSectionParents) {
                for (const parent of sectionParents.get(record) || []) {
                    visibleRowKeys.add(getRecordKey(parent));
                }
            }
        }
        debugFilter("compute", {
            displayMode: this.o2mafState.displayMode,
            filtersActive: this.o2mafState.active,
            totalRows: records.length,
            matchedRows: matchedRowKeys.size,
            firstRowKeys,
        });
        return { visibleRowKeys, matchedRowKeys, firstRowKeys };
    },

    o2mafRecordMatches(record) {
        const { conditions, logic } = this.o2mafState;
        let conditionsMatch = true;
        if (conditions.length) {
            conditionsMatch =
                logic === "OR"
                    ? conditions.some((condition) => this.o2mafConditionMatches(record, condition))
                    : conditions.every((condition) => this.o2mafConditionMatches(record, condition));
        }
        return (
            conditionsMatch &&
            this.o2mafSearchMatches(record) &&
            this.o2mafQuickChipsMatch(record)
        );
    },

    o2mafSearchMatches(record) {
        const searchTerm = normalizeText(this.o2mafState.searchTerm);
        if (!searchTerm) {
            return true;
        }
        return this.o2mafGetSearchText(record).includes(searchTerm);
    },

    o2mafGetSearchText(record) {
        let recordCache = this.o2mafSearchValueCache.get(record);
        const fields = this.o2mafAvailableFields;
        const key = fields
            .map((field) => `${field.name}:${getRawValueKey(record.data?.[field.name], field.type)}`)
            .join("|");
        if (recordCache?.key === key) {
            return recordCache.value;
        }
        const value = fields
            .map((field) => this.o2mafGetComparable(record, field).text)
            .filter(Boolean)
            .join(" ");
        recordCache = { key, value };
        this.o2mafSearchValueCache.set(record, recordCache);
        return value;
    },

    o2mafQuickChipsMatch(record) {
        return this.o2mafState.activeChipIds.every((chipId) => {
            switch (chipId) {
                case "notes":
                    return record.data?.display_type === "line_note";
                case "sections":
                    return record.data?.display_type === "line_section";
                case "products":
                    return this.o2mafIsProductLine(record);
                case "qty_positive":
                    return this.o2mafQuantityValue(record) > 0;
            }
            return true;
        });
    },

    o2mafIsProductLine(record) {
        if (Object.prototype.hasOwnProperty.call(record.data || {}, "display_type")) {
            return !record.data.display_type;
        }
        const productField = PRODUCT_FIELD_NAMES.find((name) =>
            Object.prototype.hasOwnProperty.call(record.data || {}, name)
        );
        if (!productField) {
            return false;
        }
        const value = record.data[productField];
        if (Array.isArray(value)) {
            return Boolean(value[0] || value[1]);
        }
        return Boolean(value);
    },

    o2mafQuantityValue(record) {
        const quantityField = QUANTITY_FIELD_NAMES.find((name) =>
            Object.prototype.hasOwnProperty.call(record.data || {}, name)
        );
        return quantityField ? parseNumber(record.data[quantityField]) : NaN;
    },

    o2mafConditionMatches(record, condition) {
        return condition.fields.some((field) => {
            if (!record.data || !Object.prototype.hasOwnProperty.call(record.data, field.name)) {
                return false;
            }
            const comparable = this.o2mafGetComparable(record, field);
            if (condition.group === "number") {
                const target = parseNumber(condition.value);
                return (
                    Number.isFinite(comparable.number) &&
                    Number.isFinite(target) &&
                    compareOrdered(comparable.number, condition.operator, target)
                );
            }
            if (condition.group === "date") {
                const target = parseDateValue(condition.value, field.type);
                if (!comparable.date.key || !target.key) {
                    return false;
                }
                if (["=", "!="].includes(condition.operator)) {
                    return compareOrdered(comparable.date.key, condition.operator, target.key);
                }
                return (
                    Number.isFinite(comparable.date.time) &&
                    Number.isFinite(target.time) &&
                    compareOrdered(comparable.date.time, condition.operator, target.time)
                );
            }
            if (condition.group === "boolean") {
                return condition.operator === "is_true" ? comparable.boolean : !comparable.boolean;
            }
            if (condition.group === "selection") {
                const target = normalizeText(condition.value);
                if (condition.operator === "contains") {
                    return comparable.text.includes(target);
                }
                const exactMatch = comparable.exactTexts.includes(target);
                return condition.operator === "=" ? exactMatch : !exactMatch;
            }
            return this.o2mafCompareText(comparable.text, condition.operator, condition.value);
        });
    },

    o2mafCompareText(text, operator, value) {
        const target = normalizeText(value);
        switch (operator) {
            case "contains":
                return text.includes(target);
            case "not_contains":
                return !text.includes(target);
            case "=":
                return text === target;
            case "!=":
                return text !== target;
            case "starts_with":
                return text.startsWith(target);
            case "ends_with":
                return text.endsWith(target);
        }
        return false;
    },

    o2mafGetComparable(record, field) {
        let recordCache = this.o2mafValueCache.get(record);
        if (!recordCache) {
            recordCache = new Map();
            this.o2mafValueCache.set(record, recordCache);
        }
        const value = record.data[field.name];
        const key = getRawValueKey(value, field.type);
        const cached = recordCache.get(field.name);
        if (cached?.key === key) {
            return cached.value;
        }
        const displayText = getDisplayText(value, field);
        const exactTexts = [
            normalizeText(value),
            normalizeText(displayText),
            normalizeText(field.type === "selection" ? getSelectionLabel(value, field) : ""),
        ];
        const comparable = {
            text: normalizeText(displayText),
            exactTexts,
            number: parseNumber(value),
            date: parseDateValue(value, field.type),
            boolean: value === true || value === 1 || value === "true",
        };
        recordCache.set(field.name, { key, value: comparable });
        return comparable;
    },
});

patch(ListRenderer.prototype, {
    getRowClass(record) {
        const className = super.getRowClass(...arguments);
        const filter = this.props.o2mafFilterState?.active
            ? this.props.o2mafFilterState
            : getActiveFilter(this.props.list);
        if (!filter) {
            return className;
        }
        const rowKey = getRecordKey(record);
        const isMatched = filter.matchedRowKeys.has(rowKey);
        const isVisible = filter.visibleRowKeys.has(rowKey);
        debugFilter("row", {
            rowKey,
            displayMode: filter.displayMode,
            filtersActive: filter.active,
            matched: isMatched,
            visible: isVisible,
        });
        if (filter.displayMode === "highlight") {
            return isMatched ? `${className} o_o2m_filter_match` : className;
        }
        if (filter.displayMode === "dim") {
            return isMatched || record.isNew || record.isInEdition
                ? className
                : `${className} o_o2m_filter_dim`;
        }
        if (!isVisible) {
            return `${className} d-none o_o2maf_filtered_out`;
        }
        return className;
    },

    get getEmptyRowIds() {
        const filter = this.props.o2mafFilterState?.active
            ? this.props.o2mafFilterState
            : getActiveFilter(this.props.list);
        if (!filter || filter.displayMode !== DEFAULT_DISPLAY_MODE) {
            return super.getEmptyRowIds;
        }
        let nbEmptyRow = Math.max(0, 4 - filter.visibleCount);
        if (nbEmptyRow > 0 && this.displayRowCreates) {
            nbEmptyRow -= 1;
        }
        return Array.from(Array(nbEmptyRow).keys());
    },
});
