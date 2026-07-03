# ReceiptAI access control

ReceiptAI uses backend-enforced role-based access control (RBAC) plus customer and receipt scopes. The mobile UI may hide unavailable actions, but it is never the security boundary.

The separate operations console is served at `/ops/` on the backend deployment. Regular `customer_user` accounts continue using the mobile app; only platform admins, master users, customer owners, support agents, receipt editors, and auditors can enter the console.

## Roles

| Role | Scope | Intended access |
|---|---|---|
| `platform_admin` | Global | Users, roles, settings, every customer, audit, and all receipt operations |
| `master_user` | Global | All customer receipts, reports, analytics, support approval, and audit; cannot grant platform-admin privileges |
| `customer_owner` | One customer | Customer members, receipts, analytics, corrections, deletion, support approval, and audit |
| `customer_user` | Personal ownership | Upload and manage only receipts they own |
| `support_agent` | Approved grant only | No customer data by default; time-limited case access after approval |
| `receipt_editor` | Customer or receipt assignment | Read/update/correct assigned data; no deletion or user administration |
| `auditor` | Customer or receipt assignment | Read-only receipt and audit access |
| `service_account` | Explicit customer | Scan/reprocess operations for trusted backend jobs |

All cross-user receipt access requires one of: a global data role, a customer-scoped role, an unexpired support grant, or an unexpired receipt assignment. A missing or unknown receipt returns the same `404` response to avoid disclosing another customer's data.

## Deployment

1. Run [`backend/supabase_rbac.sql`](../backend/supabase_rbac.sql) once in the Supabase SQL editor using an administrator/service-role session.
2. Bootstrap the first administrator using the commented SQL at the bottom of that file, or set `RBAC_BOOTSTRAP_ADMIN_USER_IDS` to the administrator's Supabase user UUID for the first deployment.
3. Deploy the backend. During a rolling deployment where the migration is not yet present, the API deliberately falls back to existing owner-only access; it never grants cross-user access.
4. Confirm `SUPABASE_SERVICE_KEY` or `SUPABASE_SERVICE_ROLE_KEY` is configured only on the backend. Never ship it in the app.
5. Verify `GET /rbac/me`, then create organization customers and role assignments through the audited `/rbac` endpoints.

## Support workflow

A support agent has zero receipt visibility by default. A customer owner, master user, or platform administrator creates a grant with a case ID, reason, limited receipt permissions, scope (customer or receipt), and expiration. Self-approval is rejected. Revocation takes effect after the authorization cache's maximum 30-second lifetime and is logged.

## Operations console

- **Overview:** authorized receipt totals, assignments, support grants, roles, and recent activity.
- **Receipts:** scoped receipt search, header correction, and line-item correction.
- **Assignments:** route one receipt, selected receipts, a date range, a month, a year, or all authorized receipts to correction operators; assignments can be revoked.
- **Support access:** create and revoke receipt- or customer-scoped access windows.
- **Users:** create operator accounts, assign roles, and activate/deactivate accounts.
- **Customers:** create and inspect isolated organization workspaces.
- **Roles:** inspect permissions; platform admins may customize non-admin roles.
- **Audit:** review security-sensitive activity within the authorized scope.

## Operational rules

- Use short support expirations and the smallest necessary permission set.
- Assign `receipt_editor`, not `customer_owner`, to correction staff.
- Do not use `master_user` for routine support.
- Review `/rbac/audit` regularly and retain logs according to the privacy policy.
- Receipt images remain private evidence and require `receipts.view_image` when an evidence endpoint is added.
- The AI agent remains personal/owner-scoped. Cross-customer analytics use deterministic report APIs, preventing one customer's receipt facts from entering another customer's conversation.

## Launch verification

- Customer A cannot list, correct, delete, or infer Customer B's receipt.
- Support sees nothing before approval, only the approved scope during the window, and nothing after revocation/expiry.
- Receipt editors cannot delete receipts or manage users.
- Customer owners cannot create platform admins or master users.
- Master users cannot grant platform-admin privileges.
- Every role, support, correction, assignment, customer, and deletion mutation writes an audit event.
- Guest session ownership behavior is unchanged.
