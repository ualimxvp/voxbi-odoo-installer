/** @odoo-module **/
// Copyright 2026 Mixvoip SA
// License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

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

// Odoo 16 registers the Component class directly and reads the descriptor keys
// as static members (displayName / supportedTypes / extractProps), unlike the
// Odoo 17+ object-descriptor form ({ component, ... }).
MaskedTextField.displayName = "Masked Text";
MaskedTextField.supportedTypes = ["char", "text"];

registry.category("fields").add("masked_text", MaskedTextField);

// Editable char field rendered as a masked (password-style) input with an eye
// toggle. Used for the Cockpit token so it isn't shown in cleartext by default,
// while still being typeable/pasteable.
export class MaskedInputField extends Component {
    static template = "voxbi_installer.MaskedInputField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.state = useState({ revealed: false });
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    onInput(ev) {
        this.props.record.update({ [this.props.name]: ev.target.value });
    }

    toggle() {
        this.state.revealed = !this.state.revealed;
    }
}

MaskedInputField.displayName = "Masked Input";
MaskedInputField.supportedTypes = ["char"];
MaskedInputField.extractProps = ({ attrs }) => ({ placeholder: attrs.placeholder });

registry.category("fields").add("masked_input", MaskedInputField);
