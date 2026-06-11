# Dynamic Access Manager

Dynamic Access Manager is a professional security and access-control framework for Odoo. It helps administrators configure advanced user restrictions, group restrictions, company policies, approval workflows, audit logs, UI button hiding, and operational controls without writing custom security code.

This package version: Odoo 18

Supported product line: Odoo 17, Odoo 18, Odoo 19

Author: BSMA Developers

Website: https://www.bsmadevelopers.com

License: OPL-1

## Overview

Standard Odoo access rights and record rules are powerful, but many organizations need more practical control over business actions such as create, edit, delete, duplicate, archive, import, export, and mass actions. Dynamic Access Manager adds a configurable security layer that can be managed directly from the Odoo backend.

The module is designed for consultants, implementation partners, and business administrators who need strong governance without custom code for every model or workflow.

## Features

- Dynamic action restrictions for create, edit, delete, duplicate, archive, import, export, and mass operations.
- User-specific restrictions for individual employees or selected users.
- Group restrictions for sales, accounting, warehouse, HR, and management teams.
- Company restrictions for multi-company databases.
- Domain and state restrictions for conditional policies such as confirmed orders or posted invoices.
- Own Documents Only mode using a configurable owner field.
- Approval workflow for edit, delete, duplicate, and archive actions.
- Audit logs for blocked actions and approval execution.
- UI button hiding for restricted actions in the Odoo backend.
- Readonly field protection for sensitive fields.
- Time restrictions by weekday and allowed hours.
- IP restrictions by address or CIDR range.
- Import and export protection for sensitive data.
- Mass action protection for bulk edit, delete, and archive operations.
- Restriction templates for reusable business policies.

## Business Use Cases

- Prevent editing confirmed Sales Orders.
- Prevent deleting posted Invoices.
- Restrict salespersons to their own Leads.
- Require approval before deleting CRM Opportunities.
- Restrict access by company in a multi-company environment.
- Restrict sensitive actions by office IP address.
- Prevent users from exporting customer or financial data.
- Block mass delete operations from list views.
- Protect price, discount, payment term, and responsible user fields.
- Allow managers to approve sensitive actions instead of blocking them permanently.

## Real Business Scenarios

### Prevent editing confirmed Sales Orders

Create a restriction on `sale.order`, enable Prevent Edit, and add a domain condition for confirmed orders. Users can work normally on quotations but cannot modify confirmed orders unless allowed by policy.

### Prevent deleting posted Invoices

Create a restriction on `account.move`, enable Prevent Delete, and apply it to posted invoices. This protects accounting integrity and supports compliance requirements.

### Restrict salespersons to their own Leads

Enable Own Documents Only on `crm.lead` and select the responsible salesperson field. Sales users only access records assigned to them.

### Require approval before deleting CRM Opportunities

Enable Require Approval and select Delete in Approval Actions. When a user attempts to delete an opportunity, an approval request is created and the original record remains untouched until approved.

### Restrict access by company

Select one or more companies on a restriction to apply policies only to those legal entities. This is useful when different subsidiaries have different security rules.

### Restrict actions by office IP

Enable IP restrictions and define trusted office IP addresses or CIDR ranges. Sensitive actions are blocked outside approved networks.

## Installation

1. Copy the `dynamic_restriction` module into your Odoo addons path.
2. Restart the Odoo service.
3. Update the Apps list.
4. Install `Dynamic Access Manager`.
5. Confirm that the module dependencies are available: `base` and `web`.

Example update command:

```bash
./odoo-bin -d DB_NAME -u dynamic_restriction
```

Replace `DB_NAME` with your actual Odoo database name.

## Configuration

1. Go to the Dynamic Access Manager menu.
2. Open Restrictions.
3. Create a new restriction.
4. Select the target model.
5. Select users, groups, companies, or ownership rules.
6. Choose blocked actions such as Prevent Create, Prevent Edit, Prevent Delete, Prevent Export, or Prevent Archive.
7. Optionally enable Hide Restricted Buttons for improved user experience.
8. Optionally configure domains, approval workflow, readonly fields, time restrictions, IP restrictions, or templates.
9. Save and test with a non-admin user.

## Examples

### Block delete on CRM Leads

- Model: `crm.lead`
- Users: selected sales user
- Prevent Delete: enabled
- Hide Restricted Buttons: optional

Result: the user cannot delete CRM leads. If UI hiding is enabled, the Delete action is also hidden where possible.

### Approval before deleting opportunities

- Model: `crm.lead`
- Require Approval: enabled
- Approval Actions: Delete
- Prevent Delete: disabled

Result: delete attempts create approval requests. The opportunity is not deleted until an administrator approves the request.

### Protect confirmed Sales Orders

- Model: `sale.order`
- Prevent Edit: enabled
- Domain: `[('state', '=', 'sale')]`

Result: users can edit quotations but cannot edit confirmed Sales Orders.

### Restrict export by IP

- Model: `res.partner`
- Prevent Export: enabled
- Use IP Restriction: enabled
- Allowed IP Ranges: office IP or CIDR range

Result: exports are allowed only from trusted network locations.

## Supported Versions

- Odoo 17
- Odoo 18
- Odoo 19

Separate release branches may be maintained per Odoo version according to Odoo Apps Store packaging requirements.

## Security Architecture

Dynamic Access Manager uses backend validation as the primary enforcement layer. UI button hiding is an experience improvement, not the only security mechanism.

Key architecture principles:

- Backend methods validate restricted actions before executing create, write, delete, duplicate, archive, import, export, and mass actions.
- Approval requests are created before blocked actions are executed.
- Approved actions run with explicit bypass context to avoid being blocked again by the same restriction.
- Audit logs provide traceability for blocked and approved operations.
- Domain, company, group, user, owner, time, and IP conditions are evaluated server-side.
- UI hiding helps users avoid unavailable actions but does not replace backend security.

## Odoo Apps SEO Keywords

Dynamic Access Manager is relevant for Odoo Security, Odoo Access Rights, Odoo Permissions, Odoo Record Rules Alternative, Odoo Approval Workflow, Odoo User Restrictions, Odoo Group Restrictions, Odoo Company Restrictions, Odoo Audit Logs, Odoo UI Button Hiding, Odoo Import Protection, and Odoo Export Protection.

## FAQ

### Does this replace standard Odoo access rights?

No. It complements Odoo access rights and record rules by adding configurable action-level restrictions and approval workflows.

### Is UI hiding enough for security?

No. UI hiding improves user experience, but backend validation remains the source of truth.

### Can approval be used without prevent flags?

Yes. Approval workflow can be configured as an alternative to direct blocking for supported actions.

### Can restrictions be applied by group?

Yes. Restrictions can target users, groups, companies, and ownership rules.

### Can I restrict actions only for specific states?

Yes. Domain restrictions can apply rules only when records match a state or other domain condition.

### Are audit logs available?

Yes. The module records blocked actions and approval-related activity for review.

### Does it support multi-company environments?

Yes. Restrictions can be applied globally or to selected companies.

## Support

For installation support, customization, migration, or implementation assistance, contact BSMA Developers.

Website: https://www.bsmadevelopers.com

Email: support@bsmadevelopers.com

## Author

BSMA Developers

## License

OPL-1
