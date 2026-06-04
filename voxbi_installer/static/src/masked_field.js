/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Read-only char field that stays masked until the user clicks the eye icon.
// Used for the token / integration identifiers so they aren't shown by default.
export class MaskedTextField extends Component {
    static template = "voxbi_installer.MaskedTextField";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ revealed: false });
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get displayValue() {
        if (!this.value) {
            return "";
        }
        // Fixed-length mask so the real length isn't leaked.
        return this.state.revealed ? this.value : "••••••••••••";
    }

    toggle() {
        this.state.revealed = !this.state.revealed;
    }
}

export const maskedTextField = {
    component: MaskedTextField,
    displayName: "Masked Text",
    supportedTypes: ["char", "text"],
};

registry.category("fields").add("masked_text", maskedTextField);
