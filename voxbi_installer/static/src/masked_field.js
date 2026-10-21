/** @odoo-module **/
// Copyright 2026 VOXBI S.A.
// License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import { Component, signal, t, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Read-only char field that stays masked until the user clicks the eye icon.
// Used for the token / integration identifiers so they aren't shown by default.
export class MaskedTextField extends Component {
    static template = "voxbi_installer.MaskedTextField";
    props = useProps(standardFieldProps);

    revealed = signal(false);

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get displayValue() {
        if (!this.value) {
            return "";
        }
        // Fixed-length mask so the real length isn't leaked.
        return this.revealed() ? this.value : "••••••••••••";
    }

    toggle() {
        this.revealed.set(!this.revealed());
    }
}

export const maskedTextField = {
    component: MaskedTextField,
    displayName: "Masked Text",
    supportedTypes: ["char", "text"],
};

registry.category("fields").add("masked_text", maskedTextField);

// Editable char field rendered as a masked (password-style) input with an eye
// toggle. Used for the Cockpit token so it isn't shown in cleartext by default,
// while still being typeable/pasteable.
export class MaskedInputField extends Component {
    static template = "voxbi_installer.MaskedInputField";
    props = useProps({
        ...standardFieldProps,
        placeholder: t.string().optional(),
    });

    revealed = signal(false);

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    onInput(ev) {
        this.props.record.update({ [this.props.name]: ev.target.value });
    }

    toggle() {
        this.revealed.set(!this.revealed());
    }
}

export const maskedInputField = {
    component: MaskedInputField,
    displayName: "Masked Input",
    supportedTypes: ["char"],
    extractProps: ({ attrs }) => ({ placeholder: attrs.placeholder }),
};

registry.category("fields").add("masked_input", maskedInputField);
