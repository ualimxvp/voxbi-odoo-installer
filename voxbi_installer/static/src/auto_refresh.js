/** @odoo-module **/
// Copyright 2026 Mixvoip SA
// License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import { Component, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

// While an install is in progress we poll cockpit so the Status section and
// the log console update on their own — the user never has to click Refresh.
const POLL_INTERVAL_MS = 3000;

export class VoxbiAutoRefresh extends Component {
    static template = "voxbi_installer.AutoRefresh";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.timer = null;

        // Start/stop polling whenever the record's state (or id) changes. The
        // cleanup tears the timer down when we leave the "installing" state or
        // the widget unmounts.
        useEffect(
            (state, resId) => {
                if (state === "installing" && resId) {
                    this.timer = setInterval(() => this._refresh(resId), POLL_INTERVAL_MS);
                    return () => {
                        clearInterval(this.timer);
                        this.timer = null;
                    };
                }
            },
            () => [this.props.record.data.state, this.props.record.resId]
        );
    }

    async _refresh(resId) {
        try {
            await this.orm.call("voxbi.installer.setup", "action_refresh", [[resId]]);
            // Re-read the record from the server so the Status fields and the
            // Output log reflect the latest cockpit response.
            await this.props.record.load();
        } catch {
            // On any error (network, server) stop auto-polling; the manual
            // "Refresh status" button stays available as a fallback.
            if (this.timer) {
                clearInterval(this.timer);
                this.timer = null;
            }
        }
    }
}

// Odoo 16 registers the widget Component class directly in "view_widgets" and
// reads extractProps as a static on the class, unlike the Odoo 17+ object form
// ({ component: ... }).
registry.category("view_widgets").add("voxbi_auto_refresh", VoxbiAutoRefresh);
