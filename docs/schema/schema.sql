-- FBOS database schema (MySQL 8 dialect), generated from SQLAlchemy models in src/v1/*/models
-- One database per service. Cross-service references are logical only (no FK constraints).

-- ======================================================================
-- 01_identity  (Identity service, port 8001)  — 21 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_identity;
USE fbos_identity;

CREATE TABLE object_types (
	code VARCHAR(200) NOT NULL, 
	owning_service VARCHAR(100) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	access_endpoint VARCHAR(512), 
	PRIMARY KEY (code)
);

CREATE INDEX ix_object_types_owning_service ON object_types (owning_service);
CREATE TABLE organizations (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	code VARCHAR(100), 
	base_currency VARCHAR(10) NOT NULL, 
	fiscal_year_start VARCHAR(5) NOT NULL, 
	timezone VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_organizations_code ON organizations (code);
CREATE TABLE permissions (
	code VARCHAR(200) NOT NULL, 
	service VARCHAR(100) NOT NULL, 
	description TEXT, 
	PRIMARY KEY (code)
);

CREATE INDEX ix_permissions_service ON permissions (service);
CREATE TABLE security_audit_logs (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36), 
	user_id VARCHAR(36), 
	category VARCHAR(50) NOT NULL, 
	event_type VARCHAR(100) NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	ip_address VARCHAR(100), 
	user_agent VARCHAR(512), 
	status VARCHAR(50) NOT NULL, 
	details JSON, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_security_audit_logs_category ON security_audit_logs (category);
CREATE INDEX ix_security_audit_logs_event_type ON security_audit_logs (event_type);
CREATE INDEX ix_security_audit_logs_organization_id ON security_audit_logs (organization_id);
CREATE INDEX ix_security_audit_logs_user_id ON security_audit_logs (user_id);
CREATE TABLE verticals (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_verticals_code ON verticals (code);
CREATE TABLE api_clients (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(100) NOT NULL, 
	client_secret_hash VARCHAR(255), 
	name VARCHAR(255) NOT NULL, 
	allowed_owner_hash VARCHAR(255), 
	allowed_scopes TEXT, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_api_clients_client_id ON api_clients (client_id);
CREATE INDEX ix_api_clients_organization_id ON api_clients (organization_id);
CREATE TABLE calendars (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	timezone VARCHAR(100) NOT NULL, 
	weekly_hours JSON, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX ix_calendars_organization_id ON calendars (organization_id);
CREATE TABLE field_definitions (
	id VARCHAR(36) NOT NULL, 
	vertical_id VARCHAR(36), 
	organization_id VARCHAR(36) NOT NULL, 
	object_type VARCHAR(200) NOT NULL, 
	version_no INTEGER NOT NULL, 
	json_schema JSON, 
	ui_schema JSON, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vertical_id) REFERENCES verticals (id) ON DELETE CASCADE, 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(object_type) REFERENCES object_types (code) ON DELETE RESTRICT
);

CREATE INDEX ix_field_definitions_organization_id ON field_definitions (organization_id);
CREATE INDEX ix_field_definitions_vertical_id ON field_definitions (vertical_id);
CREATE TABLE roles (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	is_system BOOL NOT NULL, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_role_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX ix_roles_code ON roles (code);
CREATE INDEX ix_roles_organization_id ON roles (organization_id);
CREATE TABLE vertical_packs (
	id VARCHAR(36) NOT NULL, 
	vertical_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	pack_code VARCHAR(100) NOT NULL, 
	version_no INTEGER NOT NULL, 
	manifest JSON, 
	status VARCHAR(50) NOT NULL, 
	import_results JSON, 
	activated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vertical_id) REFERENCES verticals (id) ON DELETE CASCADE, 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX ix_vertical_packs_organization_id ON vertical_packs (organization_id);
CREATE INDEX ix_vertical_packs_vertical_id ON vertical_packs (vertical_id);
CREATE TABLE calendar_holidays (
	id VARCHAR(36) NOT NULL, 
	calendar_id VARCHAR(36) NOT NULL, 
	holiday_date DATE NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	is_half_day BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(calendar_id) REFERENCES calendars (id) ON DELETE CASCADE
);

CREATE INDEX ix_calendar_holidays_calendar_id ON calendar_holidays (calendar_id);
CREATE TABLE org_units (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	unit_type VARCHAR(50), 
	parent_id VARCHAR(36), 
	path VARCHAR(2048) NOT NULL, 
	head_user_id VARCHAR(36), 
	calendar_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	version INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_org_unit_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(parent_id) REFERENCES org_units (id) ON DELETE RESTRICT, 
	FOREIGN KEY(calendar_id) REFERENCES calendars (id) ON DELETE SET NULL
);

CREATE INDEX ix_org_units_code ON org_units (code);
CREATE INDEX ix_org_units_organization_id ON org_units (organization_id);
CREATE INDEX ix_org_units_parent_id ON org_units (parent_id);
CREATE INDEX ix_org_units_path ON org_units (path);
CREATE TABLE role_permissions (
	role_id VARCHAR(36) NOT NULL, 
	permission_code VARCHAR(200) NOT NULL, 
	PRIMARY KEY (role_id, permission_code), 
	FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	FOREIGN KEY(permission_code) REFERENCES permissions (code) ON DELETE CASCADE
);

CREATE TABLE legal_entities (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	mg_unit_id VARCHAR(36), 
	legal_name VARCHAR(512) NOT NULL, 
	pan VARCHAR(20), 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(mg_unit_id) REFERENCES org_units (id) ON DELETE SET NULL
);

CREATE INDEX ix_legal_entities_organization_id ON legal_entities (organization_id);
CREATE INDEX ix_legal_entities_pan ON legal_entities (pan);
CREATE TABLE org_unit_verticals (
	id VARCHAR(36) NOT NULL, 
	org_unit_id VARCHAR(36) NOT NULL, 
	vertical_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_org_unit_vertical UNIQUE (org_unit_id, vertical_id), 
	FOREIGN KEY(org_unit_id) REFERENCES org_units (id) ON DELETE CASCADE, 
	FOREIGN KEY(vertical_id) REFERENCES verticals (id) ON DELETE CASCADE
);

CREATE INDEX ix_org_unit_verticals_org_unit_id ON org_unit_verticals (org_unit_id);
CREATE INDEX ix_org_unit_verticals_vertical_id ON org_unit_verticals (vertical_id);
CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	manager_user_id VARCHAR(36), 
	home_unit_id VARCHAR(36), 
	employee_code VARCHAR(100), 
	email VARCHAR(255) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	phone VARCHAR(50), 
	user_type VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	last_login_at DATETIME, 
	created_at DATETIME NOT NULL, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(manager_user_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(home_unit_id) REFERENCES org_units (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_users_employee_code ON users (employee_code);
CREATE INDEX ix_users_home_unit_id ON users (home_unit_id);
CREATE INDEX ix_users_organization_id ON users (organization_id);
CREATE INDEX ix_users_status ON users (status);
CREATE TABLE refresh_tokens (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	family_id VARCHAR(36) NOT NULL, 
	issued_at DATETIME NOT NULL, 
	revoked_at DATETIME, 
	user_agent VARCHAR(512), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
CREATE TABLE role_assignments (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	role_id VARCHAR(36) NOT NULL, 
	scope_unit_id VARCHAR(36), 
	scope_vertical_id VARCHAR(36), 
	scope_path VARCHAR(2048), 
	self_only BOOL NOT NULL, 
	valid_from DATETIME NOT NULL, 
	valid_to DATETIME, 
	granted_by_id VARCHAR(36), 
	reason VARCHAR(500), 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	FOREIGN KEY(scope_unit_id) REFERENCES org_units (id) ON DELETE CASCADE, 
	FOREIGN KEY(scope_vertical_id) REFERENCES verticals (id) ON DELETE CASCADE, 
	FOREIGN KEY(granted_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_role_assignments_organization_id ON role_assignments (organization_id);
CREATE INDEX ix_role_assignments_role_id ON role_assignments (role_id);
CREATE INDEX ix_role_assignments_scope_path ON role_assignments (scope_path);
CREATE INDEX ix_role_assignments_scope_unit_id ON role_assignments (scope_unit_id);
CREATE INDEX ix_role_assignments_scope_vertical_id ON role_assignments (scope_vertical_id);
CREATE INDEX ix_role_assignments_user_id ON role_assignments (user_id);
CREATE TABLE tax_registrations (
	id VARCHAR(36) NOT NULL, 
	legal_entity_id VARCHAR(36) NOT NULL, 
	branch_unit_id VARCHAR(36), 
	pin VARCHAR(50) NOT NULL, 
	regime_code VARCHAR(50) NOT NULL, 
	registered_address TEXT, 
	valid_from DATE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(legal_entity_id) REFERENCES legal_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(branch_unit_id) REFERENCES org_units (id) ON DELETE SET NULL
);

CREATE INDEX ix_tax_registrations_legal_entity_id ON tax_registrations (legal_entity_id);
CREATE INDEX ix_tax_registrations_pin ON tax_registrations (pin);
CREATE TABLE unit_memberships (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	unit_id VARCHAR(36) NOT NULL, 
	member_role VARCHAR(100), 
	valid_to DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(unit_id) REFERENCES org_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_unit_memberships_unit_id ON unit_memberships (unit_id);
CREATE INDEX ix_unit_memberships_user_id ON unit_memberships (user_id);
CREATE TABLE user_credentials (
	user_id VARCHAR(36) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	otp_secret_enc TEXT, 
	otp_enabled BOOL NOT NULL, 
	recovery_codes TEXT, 
	failed_attempts INTEGER NOT NULL, 
	locked_until DATETIME, 
	password_changed_at DATETIME, 
	reset_token VARCHAR(255), 
	reset_token_expires_at DATETIME, 
	invitation_token VARCHAR(255), 
	invitation_token_expires_at DATETIME, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_credentials_invitation_token ON user_credentials (invitation_token);
CREATE INDEX ix_user_credentials_reset_token ON user_credentials (reset_token);
ALTER TABLE org_units ADD CONSTRAINT fk_org_units_head_user_id FOREIGN KEY(head_user_id) REFERENCES users (id) ON DELETE SET NULL;

-- ======================================================================
-- 02_revenue  (Revenue service, port 8002)  — 27 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_revenue;
USE fbos_revenue;

CREATE TABLE accounting_exports (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	entity_type VARCHAR(100) NOT NULL, 
	entity_id VARCHAR(36) NOT NULL, 
	target_system VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	exported_at DATETIME, 
	error TEXT, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_accounting_exports_entity_id ON accounting_exports (entity_id);
CREATE INDEX ix_accounting_exports_organization_id ON accounting_exports (organization_id);
CREATE INDEX ix_accounting_exports_status ON accounting_exports (status);
CREATE TABLE activities (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	activity_type VARCHAR(100) NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	occurred_at DATETIME NOT NULL, 
	outcome_at DATETIME, 
	summary TEXT, 
	outcome VARCHAR(255), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_activities_activity_type ON activities (activity_type);
CREATE INDEX ix_activities_organization_id ON activities (organization_id);
CREATE INDEX ix_activities_owner_user_id ON activities (owner_user_id);
CREATE INDEX ix_activities_subject_id ON activities (subject_id);
CREATE TABLE billing_schedules (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	context_id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(36) NOT NULL, 
	currency VARCHAR(10) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_billing_schedules_client_id ON billing_schedules (client_id);
CREATE INDEX ix_billing_schedules_context_id ON billing_schedules (context_id);
CREATE INDEX ix_billing_schedules_organization_id ON billing_schedules (organization_id);
CREATE INDEX ix_billing_schedules_status ON billing_schedules (status);
CREATE TABLE clients (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	legal_name VARCHAR(512), 
	client_type VARCHAR(50) NOT NULL, 
	pan VARCHAR(20), 
	gstin VARCHAR(20), 
	status VARCHAR(50) NOT NULL, 
	billing_address TEXT, 
	owner_user_id VARCHAR(36) NOT NULL, 
	source VARCHAR(100), 
	closed_at DATETIME, 
	attributes JSON, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_clients_code ON clients (code);
CREATE INDEX ix_clients_organization_id ON clients (organization_id);
CREATE INDEX ix_clients_owner_user_id ON clients (owner_user_id);
CREATE INDEX ix_clients_pan ON clients (pan);
CREATE TABLE collection_cases (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(36) NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	dunning_level INTEGER NOT NULL, 
	total_overdue NUMERIC(15, 2) NOT NULL, 
	initiated_at DATETIME NOT NULL DEFAULT now(), 
	promised_date DATE, 
	promised_amount NUMERIC(15, 2), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_collection_cases_client_id ON collection_cases (client_id);
CREATE INDEX ix_collection_cases_organization_id ON collection_cases (organization_id);
CREATE INDEX ix_collection_cases_owner_user_id ON collection_cases (owner_user_id);
CREATE INDEX ix_collection_cases_status ON collection_cases (status);
CREATE TABLE deals (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	closed_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_deals_organization_id ON deals (organization_id);
CREATE INDEX ix_deals_owner_user_id ON deals (owner_user_id);
CREATE INDEX ix_deals_status ON deals (status);
CREATE TABLE invoice_series (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	fin_registration_id VARCHAR(36) NOT NULL, 
	doc_type VARCHAR(50) NOT NULL, 
	prefix VARCHAR(20) NOT NULL, 
	fiscal_year VARCHAR(10) NOT NULL, 
	next_number INTEGER NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_invoice_series_fin_registration_id ON invoice_series (fin_registration_id);
CREATE INDEX ix_invoice_series_organization_id ON invoice_series (organization_id);
CREATE TABLE offerings (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	vertical_id VARCHAR(36), 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	sac_code VARCHAR(20), 
	gst_code VARCHAR(20), 
	unit VARCHAR(50), 
	billing_model VARCHAR(50) NOT NULL, 
	list_price NUMERIC(15, 2), 
	default_work_template_code VARCHAR(100), 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_offerings_code ON offerings (code);
CREATE INDEX ix_offerings_organization_id ON offerings (organization_id);
CREATE INDEX ix_offerings_vertical_id ON offerings (vertical_id);
CREATE TABLE payments (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(36) NOT NULL, 
	receipt_no VARCHAR(100) NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	currency VARCHAR(10) NOT NULL, 
	method VARCHAR(50) NOT NULL, 
	gateway VARCHAR(50), 
	gateway_payment_id VARCHAR(255), 
	bank_reference VARCHAR(255), 
	charges NUMERIC(15, 2) NOT NULL, 
	unapplied_amount NUMERIC(15, 2) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	recorded_by VARCHAR(36) NOT NULL, 
	received_at DATETIME NOT NULL DEFAULT now(), 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_payments_org_receipt_no UNIQUE (organization_id, receipt_no)
);

CREATE INDEX ix_payments_client_id ON payments (client_id);
CREATE INDEX ix_payments_gateway_payment_id ON payments (gateway_payment_id);
CREATE INDEX ix_payments_organization_id ON payments (organization_id);
CREATE INDEX ix_payments_receipt_no ON payments (receipt_no);
CREATE INDEX ix_payments_status ON payments (status);
CREATE TABLE webhook_inbox (
	id VARCHAR(36) NOT NULL, 
	provider VARCHAR(100) NOT NULL, 
	provider_event_id VARCHAR(255) NOT NULL, 
	payload JSON, 
	received_at DATETIME NOT NULL DEFAULT now(), 
	processed_at DATETIME, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_webhook_inbox_provider ON webhook_inbox (provider);
CREATE UNIQUE INDEX ix_webhook_inbox_provider_event_id ON webhook_inbox (provider_event_id);
CREATE INDEX ix_webhook_inbox_status ON webhook_inbox (status);
CREATE TABLE client_contacts (
	id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	designation VARCHAR(255), 
	email VARCHAR(255), 
	phone VARCHAR(50), 
	is_primary BOOL NOT NULL, 
	contact_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE CASCADE
);

CREATE INDEX ix_client_contacts_client_id ON client_contacts (client_id);
CREATE INDEX ix_client_contacts_email ON client_contacts (email);
CREATE TABLE collection_followups (
	id VARCHAR(36) NOT NULL, 
	case_id VARCHAR(36) NOT NULL, 
	channel VARCHAR(50) NOT NULL, 
	by_user_id VARCHAR(36) NOT NULL, 
	notes TEXT, 
	outcome VARCHAR(255), 
	followed_up_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(case_id) REFERENCES collection_cases (id) ON DELETE CASCADE
);

CREATE INDEX ix_collection_followups_case_id ON collection_followups (case_id);
CREATE TABLE invoices (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	series_id VARCHAR(36), 
	original_invoice_id VARCHAR(36), 
	invoice_no VARCHAR(100), 
	doc_type VARCHAR(50) NOT NULL, 
	context_id VARCHAR(36), 
	contract_id VARCHAR(36), 
	work_unit_id VARCHAR(36), 
	client_id VARCHAR(36) NOT NULL, 
	issue_date DATE, 
	due_date DATE, 
	supplier_gstin VARCHAR(20) NOT NULL, 
	recipient_gstin VARCHAR(20), 
	place_of_supply VARCHAR(100) NOT NULL, 
	reverse_charge BOOL NOT NULL, 
	currency VARCHAR(10) NOT NULL, 
	exchange_rate NUMERIC(12, 6) NOT NULL, 
	taxable_total NUMERIC(15, 2) NOT NULL, 
	igst_total NUMERIC(15, 2) NOT NULL, 
	cgst_total NUMERIC(15, 2) NOT NULL, 
	sgst_total NUMERIC(15, 2) NOT NULL, 
	grand_total NUMERIC(15, 2) NOT NULL, 
	amount_settled NUMERIC(15, 2) NOT NULL, 
	balance_due NUMERIC(15, 2) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	irn VARCHAR(100), 
	ack_no VARCHAR(50), 
	signed_at DATETIME, 
	pdf_document_id VARCHAR(36), 
	issued_by VARCHAR(36), 
	client_snapshot JSON, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_invoices_org_invoice_no UNIQUE (organization_id, invoice_no), 
	FOREIGN KEY(series_id) REFERENCES invoice_series (id) ON DELETE RESTRICT, 
	FOREIGN KEY(original_invoice_id) REFERENCES invoices (id) ON DELETE SET NULL, 
	UNIQUE (irn)
);

CREATE INDEX ix_invoices_client_id ON invoices (client_id);
CREATE INDEX ix_invoices_context_id ON invoices (context_id);
CREATE INDEX ix_invoices_contract_id ON invoices (contract_id);
CREATE INDEX ix_invoices_doc_type ON invoices (doc_type);
CREATE INDEX ix_invoices_invoice_no ON invoices (invoice_no);
CREATE INDEX ix_invoices_organization_id ON invoices (organization_id);
CREATE INDEX ix_invoices_status ON invoices (status);
CREATE TABLE leads (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	vertical_id VARCHAR(36), 
	client_id VARCHAR(36), 
	name VARCHAR(255) NOT NULL, 
	contact_name VARCHAR(255), 
	contact_email VARCHAR(255), 
	contact_phone VARCHAR(50), 
	company_name VARCHAR(255), 
	company_ref VARCHAR(255), 
	source VARCHAR(100), 
	owner_user_id VARCHAR(36) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	loss_reason VARCHAR(512), 
	scope_path VARCHAR(2048), 
	attributes JSON, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE SET NULL
);

CREATE INDEX ix_leads_client_id ON leads (client_id);
CREATE INDEX ix_leads_organization_id ON leads (organization_id);
CREATE INDEX ix_leads_owner_user_id ON leads (owner_user_id);
CREATE INDEX ix_leads_scope_path ON leads (scope_path);
CREATE INDEX ix_leads_status ON leads (status);
CREATE INDEX ix_leads_vertical_id ON leads (vertical_id);
CREATE TABLE refunds (
	id VARCHAR(36) NOT NULL, 
	payment_id VARCHAR(36) NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	reason TEXT, 
	gateway_refund_id VARCHAR(255), 
	status VARCHAR(50) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(payment_id) REFERENCES payments (id) ON DELETE RESTRICT
);

CREATE INDEX ix_refunds_gateway_refund_id ON refunds (gateway_refund_id);
CREATE INDEX ix_refunds_payment_id ON refunds (payment_id);
CREATE INDEX ix_refunds_status ON refunds (status);
CREATE TABLE billing_schedule_lines (
	id VARCHAR(36) NOT NULL, 
	schedule_id VARCHAR(36) NOT NULL, 
	invoice_id VARCHAR(36), 
	seq INTEGER NOT NULL, 
	milestone_type VARCHAR(50) NOT NULL, 
	milestone_code VARCHAR(100), 
	due_date DATE, 
	amount NUMERIC(15, 2) NOT NULL, 
	description TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(schedule_id) REFERENCES billing_schedules (id) ON DELETE CASCADE, 
	FOREIGN KEY(invoice_id) REFERENCES invoices (id) ON DELETE SET NULL
);

CREATE INDEX ix_billing_schedule_lines_schedule_id ON billing_schedule_lines (schedule_id);
CREATE TABLE collection_case_invoices (
	case_id VARCHAR(36) NOT NULL, 
	invoice_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (case_id, invoice_id), 
	FOREIGN KEY(case_id) REFERENCES collection_cases (id) ON DELETE CASCADE, 
	FOREIGN KEY(invoice_id) REFERENCES invoices (id) ON DELETE CASCADE
);

CREATE TABLE opportunities (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(36) NOT NULL, 
	deal_id VARCHAR(36), 
	lead_id VARCHAR(36), 
	name VARCHAR(255) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	probability INTEGER, 
	expected_value NUMERIC(15, 2), 
	currency VARCHAR(10) NOT NULL, 
	expected_close_date DATE, 
	owner_user_id VARCHAR(36) NOT NULL, 
	loss_reason VARCHAR(512), 
	scope_path VARCHAR(2048), 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE RESTRICT, 
	FOREIGN KEY(deal_id) REFERENCES deals (id) ON DELETE SET NULL, 
	FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE SET NULL
);

CREATE INDEX ix_opportunities_client_id ON opportunities (client_id);
CREATE INDEX ix_opportunities_deal_id ON opportunities (deal_id);
CREATE INDEX ix_opportunities_lead_id ON opportunities (lead_id);
CREATE INDEX ix_opportunities_organization_id ON opportunities (organization_id);
CREATE INDEX ix_opportunities_owner_user_id ON opportunities (owner_user_id);
CREATE INDEX ix_opportunities_scope_path ON opportunities (scope_path);
CREATE INDEX ix_opportunities_status ON opportunities (status);
CREATE TABLE payment_allocations (
	id VARCHAR(36) NOT NULL, 
	payment_id VARCHAR(36) NOT NULL, 
	invoice_id VARCHAR(36) NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	allocated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(payment_id) REFERENCES payments (id) ON DELETE CASCADE, 
	FOREIGN KEY(invoice_id) REFERENCES invoices (id) ON DELETE RESTRICT
);

CREATE INDEX ix_payment_allocations_invoice_id ON payment_allocations (invoice_id);
CREATE INDEX ix_payment_allocations_payment_id ON payment_allocations (payment_id);
CREATE TABLE invoice_lines (
	id VARCHAR(36) NOT NULL, 
	invoice_id VARCHAR(36) NOT NULL, 
	schedule_line_id VARCHAR(36), 
	offering_id VARCHAR(36), 
	line_no INTEGER NOT NULL, 
	description TEXT NOT NULL, 
	hsn_code VARCHAR(20), 
	quantity NUMERIC(15, 4) NOT NULL, 
	unit_price NUMERIC(15, 2) NOT NULL, 
	discount NUMERIC(15, 2) NOT NULL, 
	taxable_value NUMERIC(15, 2) NOT NULL, 
	igst_amount NUMERIC(15, 2) NOT NULL, 
	cgst_amount NUMERIC(15, 2) NOT NULL, 
	sgst_amount NUMERIC(15, 2) NOT NULL, 
	line_total NUMERIC(15, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(invoice_id) REFERENCES invoices (id) ON DELETE CASCADE, 
	FOREIGN KEY(schedule_line_id) REFERENCES billing_schedule_lines (id) ON DELETE SET NULL
);

CREATE INDEX ix_invoice_lines_invoice_id ON invoice_lines (invoice_id);
CREATE TABLE quotations (
	id VARCHAR(36) NOT NULL, 
	opportunity_id VARCHAR(36), 
	client_id VARCHAR(36) NOT NULL, 
	previous_revision_id VARCHAR(36), 
	quote_no VARCHAR(100) NOT NULL, 
	revision_no INTEGER NOT NULL, 
	currency VARCHAR(10) NOT NULL, 
	summary TEXT, 
	place_of_supply VARCHAR(255), 
	subtotal NUMERIC(15, 2) NOT NULL, 
	discount_total NUMERIC(15, 2) NOT NULL, 
	tax_total NUMERIC(15, 2) NOT NULL, 
	grand_total NUMERIC(15, 2) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	approved_request_id VARCHAR(36), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	completed_at DATETIME, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE SET NULL, 
	FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE RESTRICT, 
	FOREIGN KEY(previous_revision_id) REFERENCES quotations (id) ON DELETE SET NULL
);

CREATE INDEX ix_quotations_client_id ON quotations (client_id);
CREATE INDEX ix_quotations_opportunity_id ON quotations (opportunity_id);
CREATE INDEX ix_quotations_quote_no ON quotations (quote_no);
CREATE INDEX ix_quotations_status ON quotations (status);
CREATE TABLE contracts (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(36) NOT NULL, 
	accepted_quotation_id VARCHAR(36), 
	opportunity_id VARCHAR(36), 
	deal_id VARCHAR(36), 
	parent_contract_id VARCHAR(36), 
	contract_no VARCHAR(100) NOT NULL, 
	contract_type VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	sla_tier VARCHAR(50), 
	start_date DATE NOT NULL, 
	end_date DATE, 
	total_value NUMERIC(15, 2) NOT NULL, 
	currency VARCHAR(10) NOT NULL, 
	payment_terms_days INTEGER, 
	sla_fee NUMERIC(15, 2), 
	coverage TEXT, 
	gst_fee NUMERIC(15, 2), 
	signed_at DATETIME, 
	signed_document_id VARCHAR(36), 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_contracts_org_contract_no UNIQUE (organization_id, contract_no), 
	FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE RESTRICT, 
	FOREIGN KEY(accepted_quotation_id) REFERENCES quotations (id) ON DELETE SET NULL, 
	FOREIGN KEY(opportunity_id) REFERENCES opportunities (id) ON DELETE SET NULL, 
	FOREIGN KEY(deal_id) REFERENCES deals (id) ON DELETE SET NULL, 
	FOREIGN KEY(parent_contract_id) REFERENCES contracts (id) ON DELETE SET NULL
);

CREATE INDEX ix_contracts_client_id ON contracts (client_id);
CREATE INDEX ix_contracts_contract_no ON contracts (contract_no);
CREATE INDEX ix_contracts_deal_id ON contracts (deal_id);
CREATE INDEX ix_contracts_opportunity_id ON contracts (opportunity_id);
CREATE INDEX ix_contracts_organization_id ON contracts (organization_id);
CREATE INDEX ix_contracts_status ON contracts (status);
CREATE TABLE negotiation_notes (
	id VARCHAR(36) NOT NULL, 
	quotation_id VARCHAR(36) NOT NULL, 
	resulting_revision_id VARCHAR(36), 
	round_no INTEGER NOT NULL, 
	issued_by VARCHAR(255), 
	summary TEXT, 
	requested_changes TEXT, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(quotation_id) REFERENCES quotations (id) ON DELETE CASCADE, 
	FOREIGN KEY(resulting_revision_id) REFERENCES quotations (id) ON DELETE SET NULL
);

CREATE INDEX ix_negotiation_notes_quotation_id ON negotiation_notes (quotation_id);
CREATE TABLE quotation_items (
	id VARCHAR(36) NOT NULL, 
	quotation_id VARCHAR(36) NOT NULL, 
	offering_id VARCHAR(36) NOT NULL, 
	line_no INTEGER NOT NULL, 
	description TEXT, 
	quantity NUMERIC(15, 4) NOT NULL, 
	unit VARCHAR(50), 
	unit_price NUMERIC(15, 2) NOT NULL, 
	discount_pct NUMERIC(8, 4) NOT NULL, 
	gst_rate NUMERIC(8, 4) NOT NULL, 
	net_price NUMERIC(15, 2) NOT NULL, 
	billing_model VARCHAR(50) NOT NULL, 
	line_total NUMERIC(15, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(quotation_id) REFERENCES quotations (id) ON DELETE CASCADE, 
	FOREIGN KEY(offering_id) REFERENCES offerings (id) ON DELETE RESTRICT
);

CREATE INDEX ix_quotation_items_quotation_id ON quotation_items (quotation_id);
CREATE TABLE contract_payment_terms (
	id VARCHAR(36) NOT NULL, 
	contract_id VARCHAR(36) NOT NULL, 
	seq INTEGER NOT NULL, 
	trigger_type VARCHAR(50) NOT NULL, 
	milestone_code VARCHAR(100), 
	amount NUMERIC(15, 2), 
	percent NUMERIC(8, 4), 
	end_date DATE, 
	due_offset_days INTEGER, 
	description TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(contract_id) REFERENCES contracts (id) ON DELETE CASCADE
);

CREATE INDEX ix_contract_payment_terms_contract_id ON contract_payment_terms (contract_id);
CREATE TABLE contract_terms (
	id VARCHAR(36) NOT NULL, 
	contract_id VARCHAR(36) NOT NULL, 
	offering_id VARCHAR(36) NOT NULL, 
	description TEXT, 
	quantity NUMERIC(15, 4) NOT NULL, 
	unit_price NUMERIC(15, 2) NOT NULL, 
	billing_model VARCHAR(50) NOT NULL, 
	billing_frequency VARCHAR(50), 
	PRIMARY KEY (id), 
	FOREIGN KEY(contract_id) REFERENCES contracts (id) ON DELETE CASCADE, 
	FOREIGN KEY(offering_id) REFERENCES offerings (id) ON DELETE RESTRICT
);

CREATE INDEX ix_contract_terms_contract_id ON contract_terms (contract_id);
CREATE TABLE renewals (
	id VARCHAR(36) NOT NULL, 
	contract_id VARCHAR(36) NOT NULL, 
	new_opportunity_id VARCHAR(36), 
	date DATE, 
	status VARCHAR(50) NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	outcome_reason TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(contract_id) REFERENCES contracts (id) ON DELETE RESTRICT, 
	FOREIGN KEY(new_opportunity_id) REFERENCES opportunities (id) ON DELETE SET NULL
);

CREATE INDEX ix_renewals_contract_id ON renewals (contract_id);
CREATE INDEX ix_renewals_owner_user_id ON renewals (owner_user_id);
CREATE INDEX ix_renewals_status ON renewals (status);

-- ======================================================================
-- 03_delivery  (Delivery service, port 8003)  — 44 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_delivery;
USE fbos_delivery;

CREATE TABLE handovers (
	id VARCHAR(36) NOT NULL, 
	parent_handover_id VARCHAR(36), 
	organization_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	from_unit_id VARCHAR(36) NOT NULL, 
	to_unit_id VARCHAR(36) NOT NULL, 
	requested_by VARCHAR(36) NOT NULL, 
	reason VARCHAR(255) NOT NULL, 
	notes TEXT, 
	status VARCHAR(50) NOT NULL, 
	responded_by VARCHAR(36), 
	responded_at DATETIME, 
	rejection_reason TEXT, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(parent_handover_id) REFERENCES handovers (id) ON DELETE SET NULL
);

CREATE INDEX ix_handovers_from_unit_id ON handovers (from_unit_id);
CREATE INDEX ix_handovers_organization_id ON handovers (organization_id);
CREATE INDEX ix_handovers_parent_handover_id ON handovers (parent_handover_id);
CREATE INDEX ix_handovers_status ON handovers (status);
CREATE INDEX ix_handovers_subject_id ON handovers (subject_id);
CREATE INDEX ix_handovers_subject_type ON handovers (subject_type);
CREATE INDEX ix_handovers_to_unit_id ON handovers (to_unit_id);
CREATE TABLE task_types (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	category VARCHAR(100) NOT NULL, 
	requires_review BOOL NOT NULL, 
	default_estimate_minutes INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_task_types_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_task_types_code ON task_types (code);
CREATE INDEX ix_task_types_organization_id ON task_types (organization_id);
CREATE TABLE work_dependencies (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	predecessor_type VARCHAR(50) NOT NULL, 
	predecessor_id VARCHAR(36) NOT NULL, 
	successor_type VARCHAR(50) NOT NULL, 
	successor_id VARCHAR(36) NOT NULL, 
	dependency_type VARCHAR(20) NOT NULL, 
	lag_days INTEGER NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_work_dependencies_organization_id ON work_dependencies (organization_id);
CREATE INDEX ix_work_dependencies_predecessor_id ON work_dependencies (predecessor_id);
CREATE INDEX ix_work_dependencies_successor_id ON work_dependencies (successor_id);
CREATE TABLE work_unit_types (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	category VARCHAR(100) NOT NULL, 
	requires_client BOOL NOT NULL, 
	default_template_code VARCHAR(100), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_work_unit_types_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_work_unit_types_code ON work_unit_types (code);
CREATE INDEX ix_work_unit_types_organization_id ON work_unit_types (organization_id);
CREATE TABLE workflow_definitions (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	vertical_id VARCHAR(36), 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	current_version_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_definitions_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_workflow_definitions_code ON workflow_definitions (code);
CREATE INDEX ix_workflow_definitions_current_version_id ON workflow_definitions (current_version_id);
CREATE INDEX ix_workflow_definitions_organization_id ON workflow_definitions (organization_id);
CREATE INDEX ix_workflow_definitions_status ON workflow_definitions (status);
CREATE INDEX ix_workflow_definitions_subject_type ON workflow_definitions (subject_type);
CREATE INDEX ix_workflow_definitions_vertical_id ON workflow_definitions (vertical_id);
CREATE TABLE task_templates (
	id VARCHAR(36) NOT NULL, 
	task_type_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	title_template VARCHAR(255) NOT NULL, 
	description TEXT, 
	checklist JSON, 
	estimate_minutes INTEGER, 
	default_priority VARCHAR(50) NOT NULL, 
	version_no INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_task_templates_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(task_type_id) REFERENCES task_types (id) ON DELETE RESTRICT
);

CREATE INDEX ix_task_templates_code ON task_templates (code);
CREATE INDEX ix_task_templates_organization_id ON task_templates (organization_id);
CREATE INDEX ix_task_templates_task_type_id ON task_templates (task_type_id);
CREATE TABLE work_templates (
	id VARCHAR(36) NOT NULL, 
	work_unit_type_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	vertical_id VARCHAR(36), 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_work_templates_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(work_unit_type_id) REFERENCES work_unit_types (id) ON DELETE RESTRICT
);

CREATE INDEX ix_work_templates_code ON work_templates (code);
CREATE INDEX ix_work_templates_organization_id ON work_templates (organization_id);
CREATE INDEX ix_work_templates_status ON work_templates (status);
CREATE INDEX ix_work_templates_vertical_id ON work_templates (vertical_id);
CREATE INDEX ix_work_templates_work_unit_type_id ON work_templates (work_unit_type_id);
CREATE TABLE workflow_versions (
	id VARCHAR(36) NOT NULL, 
	definition_id VARCHAR(36) NOT NULL, 
	version_no INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	checksum VARCHAR(64), 
	published_at DATETIME, 
	published_by VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(definition_id) REFERENCES workflow_definitions (id) ON DELETE CASCADE
);

CREATE INDEX ix_workflow_versions_definition_id ON workflow_versions (definition_id);
CREATE INDEX ix_workflow_versions_status ON workflow_versions (status);
CREATE TABLE recurring_task_rules (
	id VARCHAR(36) NOT NULL, 
	template_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100), 
	subject_id VARCHAR(36), 
	owning_unit_id VARCHAR(36), 
	rrule VARCHAR(255) NOT NULL, 
	timezone VARCHAR(100) NOT NULL, 
	next_run_at DATETIME NOT NULL, 
	ends_at DATETIME, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(template_id) REFERENCES task_templates (id) ON DELETE CASCADE
);

CREATE INDEX ix_recurring_task_rules_next_run_at ON recurring_task_rules (next_run_at);
CREATE INDEX ix_recurring_task_rules_organization_id ON recurring_task_rules (organization_id);
CREATE INDEX ix_recurring_task_rules_owning_unit_id ON recurring_task_rules (owning_unit_id);
CREATE INDEX ix_recurring_task_rules_status ON recurring_task_rules (status);
CREATE INDEX ix_recurring_task_rules_subject_id ON recurring_task_rules (subject_id);
CREATE INDEX ix_recurring_task_rules_subject_type ON recurring_task_rules (subject_type);
CREATE INDEX ix_recurring_task_rules_template_id ON recurring_task_rules (template_id);
CREATE TABLE stages (
	id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	seq INTEGER NOT NULL, 
	stage_type VARCHAR(50) NOT NULL, 
	owner_unit_selector JSON, 
	sla_policy_code VARCHAR(100), 
	exit_criteria JSON, 
	allow_parallel BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(version_id) REFERENCES workflow_versions (id) ON DELETE CASCADE
);

CREATE INDEX ix_stages_code ON stages (code);
CREATE INDEX ix_stages_version_id ON stages (version_id);
CREATE TABLE tasks (
	id VARCHAR(36) NOT NULL, 
	parent_task_id VARCHAR(36), 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	subject_type VARCHAR(100), 
	subject_id VARCHAR(36), 
	work_unit_id VARCHAR(36), 
	workflow_instance_id VARCHAR(36), 
	stage_run_id VARCHAR(36), 
	source VARCHAR(50) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	description TEXT, 
	owning_unit_id VARCHAR(36), 
	scope_path VARCHAR(255), 
	assignee_user_id VARCHAR(36), 
	reviewer_user_id VARCHAR(36), 
	task_type_id VARCHAR(36) NOT NULL, 
	priority VARCHAR(50) NOT NULL, 
	template_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	review_round INTEGER NOT NULL, 
	start_at DATETIME, 
	due_at DATETIME, 
	completed_at DATETIME, 
	estimate_minutes INTEGER, 
	logged_minutes INTEGER NOT NULL, 
	progress_pct INTEGER NOT NULL, 
	attributes JSON, 
	created_by VARCHAR(36), 
	version INTEGER NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tasks_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(parent_task_id) REFERENCES tasks (id) ON DELETE SET NULL, 
	FOREIGN KEY(task_type_id) REFERENCES task_types (id) ON DELETE RESTRICT, 
	FOREIGN KEY(template_id) REFERENCES task_templates (id) ON DELETE SET NULL
);

CREATE INDEX ix_tasks_assignee_user_id ON tasks (assignee_user_id);
CREATE INDEX ix_tasks_code ON tasks (code);
CREATE INDEX ix_tasks_organization_id ON tasks (organization_id);
CREATE INDEX ix_tasks_owning_unit_id ON tasks (owning_unit_id);
CREATE INDEX ix_tasks_parent_task_id ON tasks (parent_task_id);
CREATE INDEX ix_tasks_reviewer_user_id ON tasks (reviewer_user_id);
CREATE INDEX ix_tasks_scope_path ON tasks (scope_path);
CREATE INDEX ix_tasks_stage_run_id ON tasks (stage_run_id);
CREATE INDEX ix_tasks_status ON tasks (status);
CREATE INDEX ix_tasks_subject_id ON tasks (subject_id);
CREATE INDEX ix_tasks_subject_type ON tasks (subject_type);
CREATE INDEX ix_tasks_task_type_id ON tasks (task_type_id);
CREATE INDEX ix_tasks_template_id ON tasks (template_id);
CREATE INDEX ix_tasks_work_unit_id ON tasks (work_unit_id);
CREATE INDEX ix_tasks_workflow_instance_id ON tasks (workflow_instance_id);
CREATE TABLE work_template_versions (
	id VARCHAR(36) NOT NULL, 
	template_id VARCHAR(36) NOT NULL, 
	version_no INTEGER NOT NULL, 
	structure JSON, 
	workflow_definition_code VARCHAR(100), 
	status VARCHAR(50) NOT NULL, 
	published_at DATETIME, 
	published_by VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(template_id) REFERENCES work_templates (id) ON DELETE CASCADE
);

CREATE INDEX ix_work_template_versions_template_id ON work_template_versions (template_id);
CREATE TABLE workflow_instances (
	id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	scope_path VARCHAR(255), 
	status VARCHAR(50) NOT NULL, 
	context JSON, 
	started_by VARCHAR(36), 
	started_at DATETIME NOT NULL DEFAULT now(), 
	completed_at DATETIME, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(version_id) REFERENCES workflow_versions (id) ON DELETE RESTRICT
);

CREATE INDEX ix_workflow_instances_organization_id ON workflow_instances (organization_id);
CREATE INDEX ix_workflow_instances_scope_path ON workflow_instances (scope_path);
CREATE INDEX ix_workflow_instances_status ON workflow_instances (status);
CREATE INDEX ix_workflow_instances_subject_id ON workflow_instances (subject_id);
CREATE INDEX ix_workflow_instances_subject_type ON workflow_instances (subject_type);
CREATE INDEX ix_workflow_instances_version_id ON workflow_instances (version_id);
CREATE TABLE automation_rules (
	id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36) NOT NULL, 
	stage_id VARCHAR(36), 
	`trigger` VARCHAR(100) NOT NULL, 
	`condition` JSON, 
	actions JSON NOT NULL, 
	priority INTEGER NOT NULL, 
	enabled BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(version_id) REFERENCES workflow_versions (id) ON DELETE CASCADE, 
	FOREIGN KEY(stage_id) REFERENCES stages (id) ON DELETE CASCADE
);

CREATE INDEX ix_automation_rules_stage_id ON automation_rules (stage_id);
CREATE INDEX ix_automation_rules_version_id ON automation_rules (version_id);
CREATE TABLE checklist_items (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	seq INTEGER NOT NULL, 
	text VARCHAR(500) NOT NULL, 
	mandatory BOOL NOT NULL, 
	done_by VARCHAR(36), 
	done_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_checklist_items_task_id ON checklist_items (task_id);
CREATE TABLE stage_task_templates (
	id VARCHAR(36) NOT NULL, 
	stage_id VARCHAR(36) NOT NULL, 
	task_template_code VARCHAR(100) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	required BOOL NOT NULL, 
	assignee_selector JSON, 
	due_offset_minutes INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(stage_id) REFERENCES stages (id) ON DELETE CASCADE
);

CREATE INDEX ix_stage_task_templates_stage_id ON stage_task_templates (stage_id);
CREATE INDEX ix_stage_task_templates_task_template_code ON stage_task_templates (task_template_code);
CREATE TABLE task_assignments (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	unit_id VARCHAR(36), 
	user_id VARCHAR(36), 
	assignment_role VARCHAR(100) NOT NULL, 
	assigned_by VARCHAR(36), 
	assigned_at DATETIME NOT NULL DEFAULT now(), 
	accepted_at DATETIME, 
	ended_at DATETIME, 
	end_reason VARCHAR(255), 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_task_assignments_task_id ON task_assignments (task_id);
CREATE INDEX ix_task_assignments_unit_id ON task_assignments (unit_id);
CREATE INDEX ix_task_assignments_user_id ON task_assignments (user_id);
CREATE TABLE task_comments (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	author_id VARCHAR(36) NOT NULL, 
	body TEXT NOT NULL, 
	mentions VARCHAR(36), 
	edited_at DATETIME, 
	deleted_at DATETIME, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_task_comments_author_id ON task_comments (author_id);
CREATE INDEX ix_task_comments_task_id ON task_comments (task_id);
CREATE TABLE task_dependencies (
	task_id VARCHAR(36) NOT NULL, 
	depends_on_task_id VARCHAR(36) NOT NULL, 
	dependency_type VARCHAR(20) NOT NULL, 
	PRIMARY KEY (task_id, depends_on_task_id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE, 
	FOREIGN KEY(depends_on_task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE TABLE task_reviews (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	round INTEGER NOT NULL, 
	reviewer_id VARCHAR(36) NOT NULL, 
	result VARCHAR(50) NOT NULL, 
	rating INTEGER, 
	feedback TEXT, 
	reviewed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_task_reviews_reviewer_id ON task_reviews (reviewer_id);
CREATE INDEX ix_task_reviews_task_id ON task_reviews (task_id);
CREATE TABLE task_status_history (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	from_status VARCHAR(50), 
	to_status VARCHAR(50) NOT NULL, 
	changed_by VARCHAR(36), 
	reason TEXT, 
	changed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_task_status_history_task_id ON task_status_history (task_id);
CREATE TABLE task_watchers (
	task_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (task_id, user_id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE TABLE time_entries (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	work_date DATE NOT NULL, 
	started_at DATETIME, 
	ended_at DATETIME, 
	minutes INTEGER NOT NULL, 
	billable BOOL NOT NULL, 
	source VARCHAR(50) NOT NULL, 
	note TEXT, 
	approved_by VARCHAR(36), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE
);

CREATE INDEX ix_time_entries_organization_id ON time_entries (organization_id);
CREATE INDEX ix_time_entries_task_id ON time_entries (task_id);
CREATE INDEX ix_time_entries_user_id ON time_entries (user_id);
CREATE TABLE transitions (
	id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	trigger_type VARCHAR(50) NOT NULL, 
	from_stage_id VARCHAR(36) NOT NULL, 
	to_stage_id VARCHAR(36) NOT NULL, 
	`condition` JSON, 
	approval_policy_code VARCHAR(100), 
	allowed_permission VARCHAR(100), 
	priority INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(version_id) REFERENCES workflow_versions (id) ON DELETE CASCADE, 
	FOREIGN KEY(from_stage_id) REFERENCES stages (id) ON DELETE CASCADE, 
	FOREIGN KEY(to_stage_id) REFERENCES stages (id) ON DELETE CASCADE
);

CREATE INDEX ix_transitions_code ON transitions (code);
CREATE INDEX ix_transitions_from_stage_id ON transitions (from_stage_id);
CREATE INDEX ix_transitions_to_stage_id ON transitions (to_stage_id);
CREATE INDEX ix_transitions_version_id ON transitions (version_id);
CREATE TABLE work_units (
	id VARCHAR(36) NOT NULL, 
	parent_work_unit_id VARCHAR(36), 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	objective TEXT, 
	work_unit_type_id VARCHAR(36) NOT NULL, 
	template_version_id VARCHAR(36), 
	vertical_id VARCHAR(36), 
	owning_unit_id VARCHAR(36), 
	scope_path VARCHAR(255), 
	client_id VARCHAR(36), 
	contract_id VARCHAR(36), 
	deal_id VARCHAR(36), 
	manager_user_id VARCHAR(36), 
	planned_start DATE, 
	planned_end DATE, 
	actual_start DATE, 
	actual_end DATE, 
	status VARCHAR(50) NOT NULL, 
	priority VARCHAR(50) NOT NULL, 
	billable BOOL NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	progress_pct NUMERIC(5, 2) NOT NULL, 
	health VARCHAR(50) NOT NULL, 
	attributes JSON, 
	version INTEGER NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_work_units_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(parent_work_unit_id) REFERENCES work_units (id) ON DELETE SET NULL, 
	FOREIGN KEY(work_unit_type_id) REFERENCES work_unit_types (id) ON DELETE RESTRICT, 
	FOREIGN KEY(template_version_id) REFERENCES work_template_versions (id) ON DELETE SET NULL
);

CREATE INDEX ix_work_units_client_id ON work_units (client_id);
CREATE INDEX ix_work_units_code ON work_units (code);
CREATE INDEX ix_work_units_contract_id ON work_units (contract_id);
CREATE INDEX ix_work_units_deal_id ON work_units (deal_id);
CREATE INDEX ix_work_units_manager_user_id ON work_units (manager_user_id);
CREATE INDEX ix_work_units_organization_id ON work_units (organization_id);
CREATE INDEX ix_work_units_owning_unit_id ON work_units (owning_unit_id);
CREATE INDEX ix_work_units_parent_work_unit_id ON work_units (parent_work_unit_id);
CREATE INDEX ix_work_units_scope_path ON work_units (scope_path);
CREATE INDEX ix_work_units_status ON work_units (status);
CREATE INDEX ix_work_units_template_version_id ON work_units (template_version_id);
CREATE INDEX ix_work_units_vertical_id ON work_units (vertical_id);
CREATE INDEX ix_work_units_work_unit_type_id ON work_units (work_unit_type_id);
CREATE TABLE baselines (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	baseline_no INTEGER NOT NULL, 
	snapshot JSON NOT NULL, 
	approved_by VARCHAR(36), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_baselines_work_unit_id ON baselines (work_unit_id);
CREATE TABLE change_requests (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	cr_no VARCHAR(100) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	reason TEXT, 
	scope_impact TEXT, 
	schedule_impact_days INTEGER NOT NULL, 
	cost_impact NUMERIC(15, 2) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	approval_request_id VARCHAR(36), 
	amends_contract BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_change_requests_cr_no ON change_requests (cr_no);
CREATE INDEX ix_change_requests_status ON change_requests (status);
CREATE INDEX ix_change_requests_work_unit_id ON change_requests (work_unit_id);
CREATE TABLE closures (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	summary TEXT, 
	lessons_learned TEXT, 
	client_signoff_document_id VARCHAR(36), 
	closed_by VARCHAR(36), 
	closed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_closures_work_unit_id ON closures (work_unit_id);
CREATE TABLE cost_entries (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	category VARCHAR(100) NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	occurred_on DATE NOT NULL, 
	source_type VARCHAR(50) NOT NULL, 
	source_ref VARCHAR(255), 
	source_event_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_cost_entries_work_unit_id ON cost_entries (work_unit_id);
CREATE TABLE issues (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	severity VARCHAR(50) NOT NULL, 
	owner_user_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	resolution TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_issues_status ON issues (status);
CREATE INDEX ix_issues_work_unit_id ON issues (work_unit_id);
CREATE TABLE pending_signals (
	id VARCHAR(36) NOT NULL, 
	instance_id VARCHAR(36) NOT NULL, 
	transition_id VARCHAR(36), 
	awaited_event_type VARCHAR(100) NOT NULL, 
	correlation_key VARCHAR(255) NOT NULL, 
	expires_at DATETIME, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(instance_id) REFERENCES workflow_instances (id) ON DELETE CASCADE, 
	FOREIGN KEY(transition_id) REFERENCES transitions (id) ON DELETE SET NULL
);

CREATE INDEX ix_pending_signals_awaited_event_type ON pending_signals (awaited_event_type);
CREATE INDEX ix_pending_signals_correlation_key ON pending_signals (correlation_key);
CREATE INDEX ix_pending_signals_instance_id ON pending_signals (instance_id);
CREATE INDEX ix_pending_signals_status ON pending_signals (status);
CREATE INDEX ix_pending_signals_transition_id ON pending_signals (transition_id);
CREATE TABLE phases (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	seq INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	planned_start DATE, 
	planned_end DATE, 
	actual_start DATE, 
	actual_end DATE, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_phases_status ON phases (status);
CREATE INDEX ix_phases_work_unit_id ON phases (work_unit_id);
CREATE TABLE progress_snapshots (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	as_of DATE NOT NULL, 
	planned_pct NUMERIC(5, 2) NOT NULL, 
	actual_pct NUMERIC(5, 2) NOT NULL, 
	spi NUMERIC(6, 3), 
	cpi NUMERIC(6, 3), 
	health_overall VARCHAR(50) NOT NULL, 
	health_schedule VARCHAR(50) NOT NULL, 
	health_cost VARCHAR(50) NOT NULL, 
	health_resource VARCHAR(50) NOT NULL, 
	health_risk VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_progress_snapshots_work_unit_id ON progress_snapshots (work_unit_id);
CREATE TABLE risks (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	probability INTEGER NOT NULL, 
	impact INTEGER NOT NULL, 
	score INTEGER NOT NULL, 
	mitigation TEXT, 
	owner_user_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_risks_status ON risks (status);
CREATE INDEX ix_risks_work_unit_id ON risks (work_unit_id);
CREATE TABLE stage_runs (
	id VARCHAR(36) NOT NULL, 
	instance_id VARCHAR(36) NOT NULL, 
	stage_id VARCHAR(36) NOT NULL, 
	iteration INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	owner_unit_id VARCHAR(36), 
	entered_at DATETIME NOT NULL DEFAULT now(), 
	exited_at DATETIME, 
	entered_via_transition_id VARCHAR(36), 
	exited_via_transition_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(instance_id) REFERENCES workflow_instances (id) ON DELETE CASCADE, 
	FOREIGN KEY(stage_id) REFERENCES stages (id) ON DELETE RESTRICT, 
	FOREIGN KEY(entered_via_transition_id) REFERENCES transitions (id) ON DELETE SET NULL, 
	FOREIGN KEY(exited_via_transition_id) REFERENCES transitions (id) ON DELETE SET NULL
);

CREATE INDEX ix_stage_runs_instance_id ON stage_runs (instance_id);
CREATE INDEX ix_stage_runs_stage_id ON stage_runs (stage_id);
CREATE INDEX ix_stage_runs_status ON stage_runs (status);
CREATE TABLE status_history (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	from_status VARCHAR(50), 
	to_status VARCHAR(50) NOT NULL, 
	changed_by VARCHAR(36), 
	reason TEXT, 
	changed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_status_history_work_unit_id ON status_history (work_unit_id);
CREATE TABLE work_budgets (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	planned_amount NUMERIC(15, 2) NOT NULL, 
	approved_amount NUMERIC(15, 2) NOT NULL, 
	version_no INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_work_budgets_work_unit_id ON work_budgets (work_unit_id);
CREATE TABLE work_unit_members (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	member_role VARCHAR(100) NOT NULL, 
	allocation_pct NUMERIC(5, 2) NOT NULL, 
	valid_from DATE NOT NULL, 
	valid_to DATE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_work_unit_members_user_id ON work_unit_members (user_id);
CREATE INDEX ix_work_unit_members_work_unit_id ON work_unit_members (work_unit_id);
CREATE TABLE work_unit_services (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	offering_id VARCHAR(36) NOT NULL, 
	contract_item_id VARCHAR(36), 
	is_primary BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE
);

CREATE INDEX ix_work_unit_services_offering_id ON work_unit_services (offering_id);
CREATE INDEX ix_work_unit_services_work_unit_id ON work_unit_services (work_unit_id);
CREATE TABLE action_executions (
	id VARCHAR(36) NOT NULL, 
	instance_id VARCHAR(36) NOT NULL, 
	rule_id VARCHAR(36) NOT NULL, 
	stage_run_id VARCHAR(36), 
	action_type VARCHAR(100) NOT NULL, 
	idempotency_key VARCHAR(255) NOT NULL, 
	input JSON, 
	status VARCHAR(50) NOT NULL, 
	attempts INTEGER NOT NULL, 
	last_error TEXT, 
	executed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(instance_id) REFERENCES workflow_instances (id) ON DELETE CASCADE, 
	FOREIGN KEY(rule_id) REFERENCES automation_rules (id) ON DELETE RESTRICT, 
	FOREIGN KEY(stage_run_id) REFERENCES stage_runs (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_action_executions_idempotency_key ON action_executions (idempotency_key);
CREATE INDEX ix_action_executions_instance_id ON action_executions (instance_id);
CREATE INDEX ix_action_executions_rule_id ON action_executions (rule_id);
CREATE INDEX ix_action_executions_stage_run_id ON action_executions (stage_run_id);
CREATE INDEX ix_action_executions_status ON action_executions (status);
CREATE TABLE milestones (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	phase_id VARCHAR(36), 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	seq INTEGER NOT NULL, 
	weight NUMERIC(5, 2) NOT NULL, 
	planned_date DATE NOT NULL, 
	forecast_date DATE, 
	actual_date DATE, 
	is_billing_milestone BOOL NOT NULL, 
	requires_client_acceptance BOOL NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE, 
	FOREIGN KEY(phase_id) REFERENCES phases (id) ON DELETE SET NULL
);

CREATE INDEX ix_milestones_code ON milestones (code);
CREATE INDEX ix_milestones_phase_id ON milestones (phase_id);
CREATE INDEX ix_milestones_status ON milestones (status);
CREATE INDEX ix_milestones_work_unit_id ON milestones (work_unit_id);
CREATE TABLE transition_log (
	id VARCHAR(36) NOT NULL, 
	instance_id VARCHAR(36) NOT NULL, 
	transition_id VARCHAR(36) NOT NULL, 
	from_stage_run_id VARCHAR(36), 
	to_stage_run_id VARCHAR(36), 
	performed_by VARCHAR(36), 
	performed_by_type VARCHAR(50) NOT NULL, 
	reason TEXT, 
	approval_request_id VARCHAR(36), 
	performed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(instance_id) REFERENCES workflow_instances (id) ON DELETE CASCADE, 
	FOREIGN KEY(transition_id) REFERENCES transitions (id) ON DELETE RESTRICT, 
	FOREIGN KEY(from_stage_run_id) REFERENCES stage_runs (id) ON DELETE SET NULL, 
	FOREIGN KEY(to_stage_run_id) REFERENCES stage_runs (id) ON DELETE SET NULL
);

CREATE INDEX ix_transition_log_from_stage_run_id ON transition_log (from_stage_run_id);
CREATE INDEX ix_transition_log_instance_id ON transition_log (instance_id);
CREATE INDEX ix_transition_log_to_stage_run_id ON transition_log (to_stage_run_id);
CREATE INDEX ix_transition_log_transition_id ON transition_log (transition_id);
CREATE TABLE work_packages (
	id VARCHAR(36) NOT NULL, 
	work_unit_id VARCHAR(36) NOT NULL, 
	phase_id VARCHAR(36), 
	name VARCHAR(255) NOT NULL, 
	owner_unit_id VARCHAR(36), 
	estimated_hours NUMERIC(10, 2) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(work_unit_id) REFERENCES work_units (id) ON DELETE CASCADE, 
	FOREIGN KEY(phase_id) REFERENCES phases (id) ON DELETE SET NULL
);

CREATE INDEX ix_work_packages_phase_id ON work_packages (phase_id);
CREATE INDEX ix_work_packages_status ON work_packages (status);
CREATE INDEX ix_work_packages_work_unit_id ON work_packages (work_unit_id);
CREATE TABLE deliverables (
	id VARCHAR(36) NOT NULL, 
	milestone_id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	document_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	accepted_by VARCHAR(255), 
	accepted_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(milestone_id) REFERENCES milestones (id) ON DELETE CASCADE
);

CREATE INDEX ix_deliverables_milestone_id ON deliverables (milestone_id);
CREATE INDEX ix_deliverables_status ON deliverables (status);

-- ======================================================================
-- 04_control  (Control service, port 8004)  — 11 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_control;
USE fbos_control;

CREATE TABLE approval_delegations (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	from_user_id VARCHAR(36) NOT NULL, 
	to_user_id VARCHAR(36) NOT NULL, 
	request_types VARCHAR(255) NOT NULL, 
	valid_from DATETIME NOT NULL, 
	valid_to DATETIME NOT NULL, 
	reason VARCHAR(255), 
	created_by VARCHAR(36), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_approval_delegations_from_user_id ON approval_delegations (from_user_id);
CREATE INDEX ix_approval_delegations_organization_id ON approval_delegations (organization_id);
CREATE INDEX ix_approval_delegations_to_user_id ON approval_delegations (to_user_id);
CREATE TABLE approval_policies (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	request_type VARCHAR(100) NOT NULL, 
	`condition` JSON, 
	priority INTEGER NOT NULL, 
	version_no INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_approval_policies_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_approval_policies_code ON approval_policies (code);
CREATE INDEX ix_approval_policies_organization_id ON approval_policies (organization_id);
CREATE INDEX ix_approval_policies_request_type ON approval_policies (request_type);
CREATE INDEX ix_approval_policies_status ON approval_policies (status);
CREATE INDEX ix_approval_policies_subject_type ON approval_policies (subject_type);
CREATE TABLE sla_policies (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	metric VARCHAR(50) NOT NULL, 
	`condition` JSON NOT NULL, 
	priority INTEGER NOT NULL, 
	target_minutes INTEGER NOT NULL, 
	calendar_mode VARCHAR(50) NOT NULL, 
	start_on VARCHAR(100) NOT NULL, 
	stop_on JSON NOT NULL, 
	pause_on JSON, 
	thresholds JSON NOT NULL, 
	escalation_levels JSON NOT NULL, 
	version_no INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_sla_policies_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_sla_policies_code ON sla_policies (code);
CREATE INDEX ix_sla_policies_organization_id ON sla_policies (organization_id);
CREATE INDEX ix_sla_policies_status ON sla_policies (status);
CREATE INDEX ix_sla_policies_subject_type ON sla_policies (subject_type);
CREATE TABLE approval_policy_steps (
	id VARCHAR(36) NOT NULL, 
	policy_id VARCHAR(36) NOT NULL, 
	seq INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	mode VARCHAR(50) NOT NULL, 
	approver_selector JSON NOT NULL, 
	quorum VARCHAR(50) NOT NULL, 
	min_approvals INTEGER NOT NULL, 
	skip_condition JSON, 
	allow_delegation BOOL NOT NULL, 
	sla_policy_code VARCHAR(100), 
	PRIMARY KEY (id), 
	FOREIGN KEY(policy_id) REFERENCES approval_policies (id) ON DELETE CASCADE
);

CREATE INDEX ix_approval_policy_steps_policy_id ON approval_policy_steps (policy_id);
CREATE TABLE approval_requests (
	id VARCHAR(36) NOT NULL, 
	policy_id VARCHAR(36) NOT NULL, 
	previous_request_id VARCHAR(36), 
	organization_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	subject_version VARCHAR(50), 
	request_type VARCHAR(100) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	context JSON, 
	requested_by VARCHAR(36) NOT NULL, 
	reason TEXT, 
	priority VARCHAR(50) NOT NULL, 
	policy_version INTEGER NOT NULL, 
	idempotency_key VARCHAR(255), 
	status VARCHAR(50) NOT NULL, 
	decided_at DATETIME, 
	scope_path VARCHAR(255), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_approval_requests_org_idempotency_key UNIQUE (organization_id, idempotency_key), 
	FOREIGN KEY(policy_id) REFERENCES approval_policies (id) ON DELETE RESTRICT, 
	FOREIGN KEY(previous_request_id) REFERENCES approval_requests (id) ON DELETE SET NULL
);

CREATE INDEX ix_approval_requests_idempotency_key ON approval_requests (idempotency_key);
CREATE INDEX ix_approval_requests_organization_id ON approval_requests (organization_id);
CREATE INDEX ix_approval_requests_policy_id ON approval_requests (policy_id);
CREATE INDEX ix_approval_requests_previous_request_id ON approval_requests (previous_request_id);
CREATE INDEX ix_approval_requests_request_type ON approval_requests (request_type);
CREATE INDEX ix_approval_requests_requested_by ON approval_requests (requested_by);
CREATE INDEX ix_approval_requests_scope_path ON approval_requests (scope_path);
CREATE INDEX ix_approval_requests_status ON approval_requests (status);
CREATE INDEX ix_approval_requests_subject_id ON approval_requests (subject_id);
CREATE INDEX ix_approval_requests_subject_type ON approval_requests (subject_type);
CREATE TABLE sla_instances (
	id VARCHAR(36) NOT NULL, 
	policy_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	metric VARCHAR(50) NOT NULL, 
	state VARCHAR(50) NOT NULL, 
	started_at DATETIME NOT NULL, 
	due_at DATETIME NOT NULL, 
	target_minutes INTEGER NOT NULL, 
	paused_minutes INTEGER NOT NULL, 
	consumed_pct NUMERIC(6, 2) NOT NULL, 
	elapsed_business_minutes INTEGER NOT NULL, 
	current_escalation_level INTEGER NOT NULL, 
	breached_at DATETIME, 
	met_at DATETIME, 
	pauses JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(policy_id) REFERENCES sla_policies (id) ON DELETE RESTRICT
);

CREATE INDEX ix_sla_instances_due_at ON sla_instances (due_at);
CREATE INDEX ix_sla_instances_organization_id ON sla_instances (organization_id);
CREATE INDEX ix_sla_instances_policy_id ON sla_instances (policy_id);
CREATE INDEX ix_sla_instances_state ON sla_instances (state);
CREATE INDEX ix_sla_instances_subject_id ON sla_instances (subject_id);
CREATE INDEX ix_sla_instances_subject_type ON sla_instances (subject_type);
CREATE TABLE approval_steps (
	id VARCHAR(36) NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	seq INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	mode VARCHAR(50) NOT NULL, 
	quorum VARCHAR(50) NOT NULL, 
	min_approvals INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	activated_at DATETIME, 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(request_id) REFERENCES approval_requests (id) ON DELETE CASCADE
);

CREATE INDEX ix_approval_steps_request_id ON approval_steps (request_id);
CREATE INDEX ix_approval_steps_status ON approval_steps (status);
CREATE TABLE sla_escalations (
	id VARCHAR(36) NOT NULL, 
	instance_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	level INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	target_user_id VARCHAR(36), 
	triggered_at DATETIME NOT NULL, 
	acknowledged_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(instance_id) REFERENCES sla_instances (id) ON DELETE CASCADE
);

CREATE INDEX ix_sla_escalations_instance_id ON sla_escalations (instance_id);
CREATE INDEX ix_sla_escalations_status ON sla_escalations (status);
CREATE INDEX ix_sla_escalations_subject_id ON sla_escalations (subject_id);
CREATE INDEX ix_sla_escalations_subject_type ON sla_escalations (subject_type);
CREATE INDEX ix_sla_escalations_target_user_id ON sla_escalations (target_user_id);
CREATE TABLE sla_exceptions (
	id VARCHAR(36) NOT NULL, 
	instance_id VARCHAR(36) NOT NULL, 
	reason_code VARCHAR(50) NOT NULL, 
	description TEXT NOT NULL, 
	effect VARCHAR(50) NOT NULL, 
	extend_minutes INTEGER, 
	evidence_document_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	approval_request_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(instance_id) REFERENCES sla_instances (id) ON DELETE CASCADE
);

CREATE INDEX ix_sla_exceptions_approval_request_id ON sla_exceptions (approval_request_id);
CREATE INDEX ix_sla_exceptions_instance_id ON sla_exceptions (instance_id);
CREATE INDEX ix_sla_exceptions_status ON sla_exceptions (status);
CREATE TABLE approval_step_assignees (
	id VARCHAR(36) NOT NULL, 
	step_id VARCHAR(36) NOT NULL, 
	approver_user_id VARCHAR(36) NOT NULL, 
	resolved_from VARCHAR(50) NOT NULL, 
	delegated_from_user_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	acted_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(step_id) REFERENCES approval_steps (id) ON DELETE CASCADE
);

CREATE INDEX ix_approval_step_assignees_approver_user_id ON approval_step_assignees (approver_user_id);
CREATE INDEX ix_approval_step_assignees_status ON approval_step_assignees (status);
CREATE INDEX ix_approval_step_assignees_step_id ON approval_step_assignees (step_id);
CREATE TABLE approval_decisions (
	id VARCHAR(36) NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	step_id VARCHAR(36) NOT NULL, 
	assignee_id VARCHAR(36), 
	actor_user_id VARCHAR(36) NOT NULL, 
	decision VARCHAR(50) NOT NULL, 
	comment TEXT, 
	ip VARCHAR(45), 
	acted_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(request_id) REFERENCES approval_requests (id) ON DELETE CASCADE, 
	FOREIGN KEY(step_id) REFERENCES approval_steps (id) ON DELETE CASCADE, 
	FOREIGN KEY(assignee_id) REFERENCES approval_step_assignees (id) ON DELETE SET NULL
);

CREATE INDEX ix_approval_decisions_actor_user_id ON approval_decisions (actor_user_id);
CREATE INDEX ix_approval_decisions_assignee_id ON approval_decisions (assignee_id);
CREATE INDEX ix_approval_decisions_request_id ON approval_decisions (request_id);
CREATE INDEX ix_approval_decisions_step_id ON approval_decisions (step_id);

-- ======================================================================
-- 05_documents  (Documents service, port 8005)  — 10 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_documents;
USE fbos_documents;

CREATE TABLE retention_policies (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	retain_days INTEGER NOT NULL, 
	`trigger` VARCHAR(50) NOT NULL, 
	final_action VARCHAR(50) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_retention_policies_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_retention_policies_code ON retention_policies (code);
CREATE INDEX ix_retention_policies_organization_id ON retention_policies (organization_id);
CREATE TABLE storage_objects (
	id VARCHAR(36) NOT NULL, 
	provider VARCHAR(50) NOT NULL, 
	bucket VARCHAR(255) NOT NULL, 
	object_key VARCHAR(500) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	mime_type VARCHAR(100) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	scan_status VARCHAR(50) NOT NULL, 
	encryption VARCHAR(50) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_storage_objects_object_key ON storage_objects (object_key);
CREATE TABLE upload_sessions (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36), 
	version_no INTEGER NOT NULL, 
	file_name VARCHAR(255) NOT NULL, 
	mime_type VARCHAR(100) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	category_code VARCHAR(100) NOT NULL, 
	title VARCHAR(255), 
	link_subject_type VARCHAR(100), 
	link_subject_id VARCHAR(36), 
	link_role VARCHAR(50), 
	upload_url VARCHAR(1024) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_upload_sessions_document_id ON upload_sessions (document_id);
CREATE INDEX ix_upload_sessions_organization_id ON upload_sessions (organization_id);
CREATE TABLE document_categories (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	default_classification VARCHAR(50) NOT NULL, 
	retention_policy_id VARCHAR(36), 
	allowed_mime_types VARCHAR(500), 
	max_file_size_bytes BIGINT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_document_categories_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(retention_policy_id) REFERENCES retention_policies (id) ON DELETE SET NULL
);

CREATE INDEX ix_document_categories_code ON document_categories (code);
CREATE INDEX ix_document_categories_organization_id ON document_categories (organization_id);
CREATE INDEX ix_document_categories_retention_policy_id ON document_categories (retention_policy_id);
CREATE TABLE documents (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	category_id VARCHAR(36) NOT NULL, 
	classification VARCHAR(50) NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	owner_user_name VARCHAR(255) NOT NULL, 
	owner_avatar_url VARCHAR(500), 
	current_version_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	locked BOOL NOT NULL, 
	legal_hold BOOL NOT NULL, 
	retain_until DATE, 
	scope_path VARCHAR(255), 
	version INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_documents_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(category_id) REFERENCES document_categories (id) ON DELETE RESTRICT
);

CREATE INDEX ix_documents_category_id ON documents (category_id);
CREATE INDEX ix_documents_code ON documents (code);
CREATE INDEX ix_documents_current_version_id ON documents (current_version_id);
CREATE INDEX ix_documents_organization_id ON documents (organization_id);
CREATE INDEX ix_documents_owner_user_id ON documents (owner_user_id);
CREATE INDEX ix_documents_scope_path ON documents (scope_path);
CREATE INDEX ix_documents_status ON documents (status);
CREATE TABLE document_grants (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	principal_type VARCHAR(50) NOT NULL, 
	principal_id VARCHAR(36) NOT NULL, 
	level VARCHAR(50) NOT NULL, 
	granted_by VARCHAR(36), 
	expires_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_document_grants_document_id ON document_grants (document_id);
CREATE INDEX ix_document_grants_principal_id ON document_grants (principal_id);
CREATE TABLE document_links (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	label VARCHAR(500), 
	link_role VARCHAR(50) NOT NULL, 
	linked_by VARCHAR(36), 
	linked_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_document_links_document_id ON document_links (document_id);
CREATE INDEX ix_document_links_subject_id ON document_links (subject_id);
CREATE INDEX ix_document_links_subject_type ON document_links (subject_type);
CREATE TABLE document_versions (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	version_no INTEGER NOT NULL, 
	storage_object_id VARCHAR(36) NOT NULL, 
	file_name VARCHAR(255) NOT NULL, 
	change_note TEXT, 
	status VARCHAR(50) NOT NULL, 
	uploaded_by VARCHAR(36), 
	uploaded_by_name VARCHAR(255) NOT NULL, 
	uploaded_by_avatar_url VARCHAR(500), 
	uploaded_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, 
	FOREIGN KEY(storage_object_id) REFERENCES storage_objects (id) ON DELETE RESTRICT
);

CREATE INDEX ix_document_versions_document_id ON document_versions (document_id);
CREATE INDEX ix_document_versions_storage_object_id ON document_versions (storage_object_id);
CREATE TABLE document_shares (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36), 
	token_hash VARCHAR(128) NOT NULL, 
	raw_token_preview VARCHAR(64), 
	password_hash VARCHAR(255), 
	expires_at DATETIME, 
	max_downloads INTEGER, 
	download_count INTEGER NOT NULL, 
	created_by VARCHAR(36), 
	revoked_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, 
	FOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE SET NULL
);

CREATE INDEX ix_document_shares_document_id ON document_shares (document_id);
CREATE UNIQUE INDEX ix_document_shares_token_hash ON document_shares (token_hash);
CREATE INDEX ix_document_shares_version_id ON document_shares (version_id);
CREATE TABLE document_access_logs (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36), 
	actor_user_id VARCHAR(36), 
	share_id VARCHAR(36), 
	action VARCHAR(50) NOT NULL, 
	ip VARCHAR(45), 
	occurred_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, 
	FOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE SET NULL, 
	FOREIGN KEY(share_id) REFERENCES document_shares (id) ON DELETE SET NULL
);

CREATE INDEX ix_document_access_logs_actor_user_id ON document_access_logs (actor_user_id);
CREATE INDEX ix_document_access_logs_document_id ON document_access_logs (document_id);
CREATE INDEX ix_document_access_logs_share_id ON document_access_logs (share_id);
CREATE INDEX ix_document_access_logs_version_id ON document_access_logs (version_id);

-- ======================================================================
-- 06_communication  (Communication service, port 8006)  — 11 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_communication;
USE fbos_communication;

CREATE TABLE device_tokens (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	platform VARCHAR(50) NOT NULL, 
	token VARCHAR(512) NOT NULL, 
	last_seen_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_device_tokens_organization_id ON device_tokens (organization_id);
CREATE UNIQUE INDEX ix_device_tokens_token ON device_tokens (token);
CREATE INDEX ix_device_tokens_user_id ON device_tokens (user_id);
CREATE TABLE notification_channels (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	channel_type VARCHAR(50) NOT NULL, 
	provider VARCHAR(50) NOT NULL, 
	sender_identity VARCHAR(255) NOT NULL, 
	credential_ref VARCHAR(255), 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_notification_channels_organization_id ON notification_channels (organization_id);
CREATE INDEX ix_notification_channels_status ON notification_channels (status);
CREATE TABLE notification_preferences (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	event_category VARCHAR(100) NOT NULL, 
	channel_type VARCHAR(50) NOT NULL, 
	enabled BOOL NOT NULL, 
	digest VARCHAR(50) NOT NULL, 
	quiet_hours JSON, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_notification_preferences_organization_id ON notification_preferences (organization_id);
CREATE INDEX ix_notification_preferences_user_id ON notification_preferences (user_id);
CREATE TABLE notification_rules (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	event_type VARCHAR(100) NOT NULL, 
	`condition` JSON, 
	template_code VARCHAR(100) NOT NULL, 
	recipient_selector JSON NOT NULL, 
	channel_types VARCHAR(100) NOT NULL, 
	urgency VARCHAR(50) NOT NULL, 
	digestible BOOL NOT NULL, 
	enabled BOOL NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_notification_rules_code ON notification_rules (code);
CREATE INDEX ix_notification_rules_event_type ON notification_rules (event_type);
CREATE INDEX ix_notification_rules_organization_id ON notification_rules (organization_id);
CREATE TABLE notification_templates (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	channel_type VARCHAR(50) NOT NULL, 
	locale VARCHAR(10) NOT NULL, 
	version_no INTEGER NOT NULL, 
	subject VARCHAR(255), 
	body TEXT NOT NULL, 
	provider_template_id VARCHAR(255), 
	variables_schema JSON, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_notification_templates_code ON notification_templates (code);
CREATE INDEX ix_notification_templates_organization_id ON notification_templates (organization_id);
CREATE INDEX ix_notification_templates_status ON notification_templates (status);
CREATE TABLE suppressions (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	channel_type VARCHAR(50) NOT NULL, 
	address VARCHAR(255) NOT NULL, 
	reason VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_suppressions_address ON suppressions (address);
CREATE INDEX ix_suppressions_organization_id ON suppressions (organization_id);
CREATE TABLE webhook_subscriptions (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	url VARCHAR(2048) NOT NULL, 
	event_types JSON NOT NULL, 
	description VARCHAR(255), 
	secret VARCHAR(255) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_webhook_subscriptions_organization_id ON webhook_subscriptions (organization_id);
CREATE INDEX ix_webhook_subscriptions_status ON webhook_subscriptions (status);
CREATE TABLE notifications (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	rule_id VARCHAR(36), 
	source_event_id VARCHAR(36), 
	event_type VARCHAR(100) NOT NULL, 
	subject_type VARCHAR(100), 
	subject_id VARCHAR(36), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(rule_id) REFERENCES notification_rules (id) ON DELETE SET NULL
);

CREATE INDEX ix_notifications_event_type ON notifications (event_type);
CREATE INDEX ix_notifications_organization_id ON notifications (organization_id);
CREATE INDEX ix_notifications_rule_id ON notifications (rule_id);
CREATE INDEX ix_notifications_source_event_id ON notifications (source_event_id);
CREATE INDEX ix_notifications_subject_id ON notifications (subject_id);
CREATE INDEX ix_notifications_subject_type ON notifications (subject_type);
CREATE TABLE deliveries (
	id VARCHAR(36) NOT NULL, 
	notification_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36), 
	address VARCHAR(255) NOT NULL, 
	channel_type VARCHAR(50) NOT NULL, 
	template_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	provider_message_id VARCHAR(255), 
	attempts INTEGER NOT NULL, 
	last_error TEXT, 
	scheduled_at DATETIME, 
	sent_at DATETIME, 
	delivered_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(notification_id) REFERENCES notifications (id) ON DELETE CASCADE, 
	FOREIGN KEY(template_id) REFERENCES notification_templates (id) ON DELETE SET NULL
);

CREATE INDEX ix_deliveries_notification_id ON deliveries (notification_id);
CREATE INDEX ix_deliveries_status ON deliveries (status);
CREATE INDEX ix_deliveries_user_id ON deliveries (user_id);
CREATE TABLE inbox_items (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	notification_id VARCHAR(36), 
	body TEXT NOT NULL, 
	action_url VARCHAR(512), 
	subject_type VARCHAR(100), 
	subject_id VARCHAR(36), 
	event_type VARCHAR(100), 
	urgency VARCHAR(50) NOT NULL, 
	read_at DATETIME, 
	archived_at DATETIME, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(notification_id) REFERENCES notifications (id) ON DELETE SET NULL
);

CREATE INDEX ix_inbox_items_event_type ON inbox_items (event_type);
CREATE INDEX ix_inbox_items_notification_id ON inbox_items (notification_id);
CREATE INDEX ix_inbox_items_subject_id ON inbox_items (subject_id);
CREATE INDEX ix_inbox_items_subject_type ON inbox_items (subject_type);
CREATE INDEX ix_inbox_items_user_id ON inbox_items (user_id);
CREATE TABLE delivery_attempts (
	id VARCHAR(36) NOT NULL, 
	delivery_id VARCHAR(36) NOT NULL, 
	attempt_no INTEGER NOT NULL, 
	attempted_at DATETIME NOT NULL DEFAULT now(), 
	success BOOL NOT NULL, 
	provider_response JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(delivery_id) REFERENCES deliveries (id) ON DELETE CASCADE
);

CREATE INDEX ix_delivery_attempts_delivery_id ON delivery_attempts (delivery_id);

-- ======================================================================
-- 07_management  (Management service, port 8007)  — 30 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_management;
USE fbos_management;

CREATE TABLE fiscal_years (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fiscal_years_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_fiscal_years_code ON fiscal_years (code);
CREATE INDEX ix_fiscal_years_organization_id ON fiscal_years (organization_id);
CREATE INDEX ix_fiscal_years_status ON fiscal_years (status);
CREATE TABLE kpi_definitions (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	unit VARCHAR(50) NOT NULL, 
	direction VARCHAR(50) NOT NULL, 
	aggregation VARCHAR(50) NOT NULL, 
	formula JSON, 
	frequency VARCHAR(50) NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	version_no INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_kpi_definitions_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_kpi_definitions_code ON kpi_definitions (code);
CREATE INDEX ix_kpi_definitions_organization_id ON kpi_definitions (organization_id);
CREATE INDEX ix_kpi_definitions_owner_user_id ON kpi_definitions (owner_user_id);
CREATE INDEX ix_kpi_definitions_status ON kpi_definitions (status);
CREATE TABLE resources (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	resource_type VARCHAR(50) NOT NULL, 
	user_id VARCHAR(36), 
	unit_id VARCHAR(36), 
	calendar_id VARCHAR(36), 
	employment_type VARCHAR(50) NOT NULL, 
	fte NUMERIC(5, 2) NOT NULL, 
	daily_capacity_minutes INTEGER NOT NULL, 
	internal_cost_rate NUMERIC(12, 2), 
	effective_from DATE NOT NULL, 
	effective_to DATE, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_resources_calendar_id ON resources (calendar_id);
CREATE INDEX ix_resources_organization_id ON resources (organization_id);
CREATE INDEX ix_resources_status ON resources (status);
CREATE INDEX ix_resources_unit_id ON resources (unit_id);
CREATE INDEX ix_resources_user_id ON resources (user_id);
CREATE TABLE skills (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	category VARCHAR(100) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_skills_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_skills_category ON skills (category);
CREATE INDEX ix_skills_code ON skills (code);
CREATE INDEX ix_skills_organization_id ON skills (organization_id);
CREATE TABLE availability_exceptions (
	id VARCHAR(36) NOT NULL, 
	resource_id VARCHAR(36) NOT NULL, 
	starts_at DATETIME NOT NULL, 
	ends_at DATETIME NOT NULL, 
	exception_type VARCHAR(50) NOT NULL, 
	minutes INTEGER NOT NULL, 
	source VARCHAR(100), 
	reason TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE
);

CREATE INDEX ix_availability_exceptions_resource_id ON availability_exceptions (resource_id);
CREATE INDEX ix_availability_exceptions_starts_at ON availability_exceptions (starts_at);
CREATE TABLE budgets (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	fiscal_year_id VARCHAR(36) NOT NULL, 
	scope_unit_id VARCHAR(36), 
	scope_vertical_id VARCHAR(36), 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	revision_no INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	approval_request_id VARCHAR(36), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_budgets_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(fiscal_year_id) REFERENCES fiscal_years (id) ON DELETE RESTRICT
);

CREATE INDEX ix_budgets_approval_request_id ON budgets (approval_request_id);
CREATE INDEX ix_budgets_code ON budgets (code);
CREATE INDEX ix_budgets_fiscal_year_id ON budgets (fiscal_year_id);
CREATE INDEX ix_budgets_organization_id ON budgets (organization_id);
CREATE INDEX ix_budgets_scope_unit_id ON budgets (scope_unit_id);
CREATE INDEX ix_budgets_scope_vertical_id ON budgets (scope_vertical_id);
CREATE INDEX ix_budgets_status ON budgets (status);
CREATE TABLE capacity_gaps (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	skill_id VARCHAR(36), 
	unit_id VARCHAR(36), 
	period_start DATE NOT NULL, 
	period_end DATE NOT NULL, 
	required_minutes INTEGER NOT NULL, 
	available_minutes INTEGER NOT NULL, 
	gap_minutes INTEGER NOT NULL, 
	severity VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(skill_id) REFERENCES skills (id) ON DELETE SET NULL
);

CREATE INDEX ix_capacity_gaps_organization_id ON capacity_gaps (organization_id);
CREATE INDEX ix_capacity_gaps_skill_id ON capacity_gaps (skill_id);
CREATE INDEX ix_capacity_gaps_status ON capacity_gaps (status);
CREATE INDEX ix_capacity_gaps_unit_id ON capacity_gaps (unit_id);
CREATE TABLE capacity_ledger (
	resource_id VARCHAR(36) NOT NULL, 
	day DATE NOT NULL, 
	capacity_minutes INTEGER NOT NULL, 
	allocated_minutes INTEGER NOT NULL, 
	actual_minutes INTEGER NOT NULL, 
	overload BOOL NOT NULL, 
	PRIMARY KEY (resource_id, day), 
	FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE
);

CREATE INDEX ix_capacity_ledger_day ON capacity_ledger (day);
CREATE TABLE kpi_measurements (
	id VARCHAR(36) NOT NULL, 
	kpi_definition_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	reverses_id VARCHAR(36), 
	measured_on DATE NOT NULL, 
	value NUMERIC(14, 4) NOT NULL, 
	unit_id VARCHAR(36), 
	vertical_id VARCHAR(36), 
	user_id VARCHAR(36), 
	client_id VARCHAR(36), 
	offering_id VARCHAR(36), 
	source_type VARCHAR(50) NOT NULL, 
	source_event_id VARCHAR(36), 
	entered_by VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(kpi_definition_id) REFERENCES kpi_definitions (id) ON DELETE CASCADE, 
	FOREIGN KEY(reverses_id) REFERENCES kpi_measurements (id) ON DELETE SET NULL
);

CREATE INDEX ix_kpi_measurements_client_id ON kpi_measurements (client_id);
CREATE INDEX ix_kpi_measurements_kpi_definition_id ON kpi_measurements (kpi_definition_id);
CREATE INDEX ix_kpi_measurements_measured_on ON kpi_measurements (measured_on);
CREATE INDEX ix_kpi_measurements_offering_id ON kpi_measurements (offering_id);
CREATE INDEX ix_kpi_measurements_organization_id ON kpi_measurements (organization_id);
CREATE INDEX ix_kpi_measurements_reverses_id ON kpi_measurements (reverses_id);
CREATE INDEX ix_kpi_measurements_source_event_id ON kpi_measurements (source_event_id);
CREATE INDEX ix_kpi_measurements_unit_id ON kpi_measurements (unit_id);
CREATE INDEX ix_kpi_measurements_user_id ON kpi_measurements (user_id);
CREATE INDEX ix_kpi_measurements_vertical_id ON kpi_measurements (vertical_id);
CREATE TABLE kpi_sources (
	id VARCHAR(36) NOT NULL, 
	kpi_definition_id VARCHAR(36) NOT NULL, 
	source_type VARCHAR(50) NOT NULL, 
	event_type VARCHAR(100), 
	value_path VARCHAR(255), 
	filter JSON, 
	dimension_map JSON, 
	enabled BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kpi_definition_id) REFERENCES kpi_definitions (id) ON DELETE CASCADE
);

CREATE INDEX ix_kpi_sources_kpi_definition_id ON kpi_sources (kpi_definition_id);
CREATE TABLE kpi_thresholds (
	id VARCHAR(36) NOT NULL, 
	kpi_definition_id VARCHAR(36) NOT NULL, 
	scope_unit_id VARCHAR(36), 
	green_from_pct NUMERIC(5, 2) NOT NULL, 
	amber_from_pct NUMERIC(5, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kpi_definition_id) REFERENCES kpi_definitions (id) ON DELETE CASCADE
);

CREATE INDEX ix_kpi_thresholds_kpi_definition_id ON kpi_thresholds (kpi_definition_id);
CREATE INDEX ix_kpi_thresholds_scope_unit_id ON kpi_thresholds (scope_unit_id);
CREATE TABLE planning_periods (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	fiscal_year_id VARCHAR(36) NOT NULL, 
	parent_period_id VARCHAR(36), 
	period_type VARCHAR(50) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(fiscal_year_id) REFERENCES fiscal_years (id) ON DELETE CASCADE, 
	FOREIGN KEY(parent_period_id) REFERENCES planning_periods (id) ON DELETE SET NULL
);

CREATE INDEX ix_planning_periods_fiscal_year_id ON planning_periods (fiscal_year_id);
CREATE INDEX ix_planning_periods_organization_id ON planning_periods (organization_id);
CREATE INDEX ix_planning_periods_parent_period_id ON planning_periods (parent_period_id);
CREATE INDEX ix_planning_periods_status ON planning_periods (status);
CREATE TABLE resource_requirements (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	skill_id VARCHAR(36), 
	min_level INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	required_minutes INTEGER NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	priority VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(skill_id) REFERENCES skills (id) ON DELETE SET NULL
);

CREATE INDEX ix_resource_requirements_organization_id ON resource_requirements (organization_id);
CREATE INDEX ix_resource_requirements_skill_id ON resource_requirements (skill_id);
CREATE INDEX ix_resource_requirements_status ON resource_requirements (status);
CREATE INDEX ix_resource_requirements_subject_id ON resource_requirements (subject_id);
CREATE INDEX ix_resource_requirements_subject_type ON resource_requirements (subject_type);
CREATE TABLE resource_skills (
	resource_id VARCHAR(36) NOT NULL, 
	skill_id VARCHAR(36) NOT NULL, 
	level INTEGER NOT NULL, 
	years_experience NUMERIC(4, 1), 
	verified_by VARCHAR(36), 
	valid_until DATE, 
	PRIMARY KEY (resource_id, skill_id), 
	FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE CASCADE, 
	FOREIGN KEY(skill_id) REFERENCES skills (id) ON DELETE CASCADE
);

CREATE TABLE allocations (
	id VARCHAR(36) NOT NULL, 
	resource_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	requirement_id VARCHAR(36), 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	minutes_per_day INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	override_reason TEXT, 
	approved_by VARCHAR(36), 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(resource_id) REFERENCES resources (id) ON DELETE RESTRICT, 
	FOREIGN KEY(requirement_id) REFERENCES resource_requirements (id) ON DELETE SET NULL
);

CREATE INDEX ix_allocations_end_date ON allocations (end_date);
CREATE INDEX ix_allocations_organization_id ON allocations (organization_id);
CREATE INDEX ix_allocations_requirement_id ON allocations (requirement_id);
CREATE INDEX ix_allocations_resource_id ON allocations (resource_id);
CREATE INDEX ix_allocations_start_date ON allocations (start_date);
CREATE INDEX ix_allocations_status ON allocations (status);
CREATE INDEX ix_allocations_subject_id ON allocations (subject_id);
CREATE INDEX ix_allocations_subject_type ON allocations (subject_type);
CREATE TABLE budget_lines (
	id VARCHAR(36) NOT NULL, 
	budget_id VARCHAR(36) NOT NULL, 
	category VARCHAR(100) NOT NULL, 
	description TEXT, 
	planned_amount NUMERIC(14, 2) NOT NULL, 
	approved_amount NUMERIC(14, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(budget_id) REFERENCES budgets (id) ON DELETE CASCADE
);

CREATE INDEX ix_budget_lines_budget_id ON budget_lines (budget_id);
CREATE INDEX ix_budget_lines_category ON budget_lines (category);
CREATE TABLE scenarios (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	base_period_id VARCHAR(36) NOT NULL, 
	assumption_type VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(base_period_id) REFERENCES planning_periods (id) ON DELETE CASCADE
);

CREATE INDEX ix_scenarios_base_period_id ON scenarios (base_period_id);
CREATE INDEX ix_scenarios_organization_id ON scenarios (organization_id);
CREATE INDEX ix_scenarios_status ON scenarios (status);
CREATE TABLE strategic_goals (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	period_id VARCHAR(36), 
	parent_goal_id VARCHAR(36), 
	scope_unit_id VARCHAR(36), 
	scope_vertical_id VARCHAR(36), 
	owner_user_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	priority VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_strategic_goals_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(period_id) REFERENCES planning_periods (id) ON DELETE SET NULL, 
	FOREIGN KEY(parent_goal_id) REFERENCES strategic_goals (id) ON DELETE SET NULL
);

CREATE INDEX ix_strategic_goals_code ON strategic_goals (code);
CREATE INDEX ix_strategic_goals_organization_id ON strategic_goals (organization_id);
CREATE INDEX ix_strategic_goals_owner_user_id ON strategic_goals (owner_user_id);
CREATE INDEX ix_strategic_goals_parent_goal_id ON strategic_goals (parent_goal_id);
CREATE INDEX ix_strategic_goals_period_id ON strategic_goals (period_id);
CREATE INDEX ix_strategic_goals_scope_unit_id ON strategic_goals (scope_unit_id);
CREATE INDEX ix_strategic_goals_scope_vertical_id ON strategic_goals (scope_vertical_id);
CREATE INDEX ix_strategic_goals_status ON strategic_goals (status);
CREATE TABLE allocation_history (
	id VARCHAR(36) NOT NULL, 
	allocation_id VARCHAR(36) NOT NULL, 
	change_type VARCHAR(50) NOT NULL, 
	`before` JSON, 
	after JSON, 
	changed_by VARCHAR(36), 
	changed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(allocation_id) REFERENCES allocations (id) ON DELETE CASCADE
);

CREATE INDEX ix_allocation_history_allocation_id ON allocation_history (allocation_id);
CREATE TABLE budget_actuals (
	id VARCHAR(36) NOT NULL, 
	budget_line_id VARCHAR(36) NOT NULL, 
	amount NUMERIC(14, 2) NOT NULL, 
	occurred_on DATE NOT NULL, 
	source_type VARCHAR(50) NOT NULL, 
	source_event_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(budget_line_id) REFERENCES budget_lines (id) ON DELETE CASCADE
);

CREATE INDEX ix_budget_actuals_budget_line_id ON budget_actuals (budget_line_id);
CREATE INDEX ix_budget_actuals_occurred_on ON budget_actuals (occurred_on);
CREATE INDEX ix_budget_actuals_source_event_id ON budget_actuals (source_event_id);
CREATE TABLE budget_allocations (
	id VARCHAR(36) NOT NULL, 
	budget_line_id VARCHAR(36) NOT NULL, 
	target_type VARCHAR(100) NOT NULL, 
	target_id VARCHAR(36) NOT NULL, 
	amount NUMERIC(14, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(budget_line_id) REFERENCES budget_lines (id) ON DELETE CASCADE
);

CREATE INDEX ix_budget_allocations_budget_line_id ON budget_allocations (budget_line_id);
CREATE INDEX ix_budget_allocations_target_id ON budget_allocations (target_id);
CREATE INDEX ix_budget_allocations_target_type ON budget_allocations (target_type);
CREATE TABLE goal_kpis (
	goal_id VARCHAR(36) NOT NULL, 
	kpi_definition_id VARCHAR(36) NOT NULL, 
	weight NUMERIC(5, 2) NOT NULL, 
	PRIMARY KEY (goal_id, kpi_definition_id), 
	FOREIGN KEY(goal_id) REFERENCES strategic_goals (id) ON DELETE CASCADE, 
	FOREIGN KEY(kpi_definition_id) REFERENCES kpi_definitions (id) ON DELETE CASCADE
);

CREATE TABLE initiatives (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	goal_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	linked_work_unit_id VARCHAR(36), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_initiatives_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(goal_id) REFERENCES strategic_goals (id) ON DELETE CASCADE
);

CREATE INDEX ix_initiatives_code ON initiatives (code);
CREATE INDEX ix_initiatives_goal_id ON initiatives (goal_id);
CREATE INDEX ix_initiatives_linked_work_unit_id ON initiatives (linked_work_unit_id);
CREATE INDEX ix_initiatives_organization_id ON initiatives (organization_id);
CREATE INDEX ix_initiatives_owner_user_id ON initiatives (owner_user_id);
CREATE INDEX ix_initiatives_status ON initiatives (status);
CREATE TABLE kpi_targets (
	id VARCHAR(36) NOT NULL, 
	goal_id VARCHAR(36), 
	kpi_definition_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	period_id VARCHAR(36) NOT NULL, 
	supersedes_id VARCHAR(36), 
	scope_unit_id VARCHAR(36), 
	scope_vertical_id VARCHAR(36), 
	scope_user_id VARCHAR(36), 
	target_value NUMERIC(14, 4) NOT NULL, 
	stretch_value NUMERIC(14, 4), 
	revision_no INTEGER NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	approval_request_id VARCHAR(36), 
	approved_at DATETIME, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(goal_id) REFERENCES strategic_goals (id) ON DELETE SET NULL, 
	FOREIGN KEY(kpi_definition_id) REFERENCES kpi_definitions (id) ON DELETE CASCADE, 
	FOREIGN KEY(period_id) REFERENCES planning_periods (id) ON DELETE CASCADE, 
	FOREIGN KEY(supersedes_id) REFERENCES kpi_targets (id) ON DELETE SET NULL
);

CREATE INDEX ix_kpi_targets_approval_request_id ON kpi_targets (approval_request_id);
CREATE INDEX ix_kpi_targets_goal_id ON kpi_targets (goal_id);
CREATE INDEX ix_kpi_targets_kpi_definition_id ON kpi_targets (kpi_definition_id);
CREATE INDEX ix_kpi_targets_organization_id ON kpi_targets (organization_id);
CREATE INDEX ix_kpi_targets_period_id ON kpi_targets (period_id);
CREATE INDEX ix_kpi_targets_scope_unit_id ON kpi_targets (scope_unit_id);
CREATE INDEX ix_kpi_targets_scope_user_id ON kpi_targets (scope_user_id);
CREATE INDEX ix_kpi_targets_scope_vertical_id ON kpi_targets (scope_vertical_id);
CREATE INDEX ix_kpi_targets_status ON kpi_targets (status);
CREATE INDEX ix_kpi_targets_supersedes_id ON kpi_targets (supersedes_id);
CREATE TABLE scenario_values (
	id VARCHAR(36) NOT NULL, 
	scenario_id VARCHAR(36) NOT NULL, 
	kpi_definition_id VARCHAR(36) NOT NULL, 
	period_id VARCHAR(36) NOT NULL, 
	baseline_value NUMERIC(14, 4) NOT NULL, 
	scenario_value NUMERIC(14, 4) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE, 
	FOREIGN KEY(kpi_definition_id) REFERENCES kpi_definitions (id) ON DELETE CASCADE, 
	FOREIGN KEY(period_id) REFERENCES planning_periods (id) ON DELETE CASCADE
);

CREATE INDEX ix_scenario_values_kpi_definition_id ON scenario_values (kpi_definition_id);
CREATE INDEX ix_scenario_values_period_id ON scenario_values (period_id);
CREATE INDEX ix_scenario_values_scenario_id ON scenario_values (scenario_id);
CREATE TABLE initiative_milestones (
	id VARCHAR(36) NOT NULL, 
	initiative_id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	due_date DATE NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	progress_pct NUMERIC(5, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(initiative_id) REFERENCES initiatives (id) ON DELETE CASCADE
);

CREATE INDEX ix_initiative_milestones_initiative_id ON initiative_milestones (initiative_id);
CREATE INDEX ix_initiative_milestones_status ON initiative_milestones (status);
CREATE TABLE kpi_results (
	id VARCHAR(36) NOT NULL, 
	target_id VARCHAR(36), 
	kpi_definition_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	period_id VARCHAR(36) NOT NULL, 
	scope_key VARCHAR(100) NOT NULL, 
	actual_value NUMERIC(14, 4) NOT NULL, 
	target_value NUMERIC(14, 4) NOT NULL, 
	achievement_pct NUMERIC(6, 2) NOT NULL, 
	variance_abs NUMERIC(14, 4) NOT NULL, 
	variance_pct NUMERIC(6, 2) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	trend VARCHAR(50) NOT NULL, 
	calc_version INTEGER NOT NULL, 
	inputs_hash VARCHAR(64) NOT NULL, 
	calculated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(target_id) REFERENCES kpi_targets (id) ON DELETE SET NULL, 
	FOREIGN KEY(kpi_definition_id) REFERENCES kpi_definitions (id) ON DELETE CASCADE, 
	FOREIGN KEY(period_id) REFERENCES planning_periods (id) ON DELETE CASCADE
);

CREATE INDEX ix_kpi_results_kpi_definition_id ON kpi_results (kpi_definition_id);
CREATE INDEX ix_kpi_results_organization_id ON kpi_results (organization_id);
CREATE INDEX ix_kpi_results_period_id ON kpi_results (period_id);
CREATE INDEX ix_kpi_results_scope_key ON kpi_results (scope_key);
CREATE INDEX ix_kpi_results_status ON kpi_results (status);
CREATE INDEX ix_kpi_results_target_id ON kpi_results (target_id);
CREATE TABLE roadmap_items (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	initiative_id VARCHAR(36), 
	roadmap_code VARCHAR(100) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	seq INTEGER NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(initiative_id) REFERENCES initiatives (id) ON DELETE SET NULL
);

CREATE INDEX ix_roadmap_items_initiative_id ON roadmap_items (initiative_id);
CREATE INDEX ix_roadmap_items_organization_id ON roadmap_items (organization_id);
CREATE INDEX ix_roadmap_items_roadmap_code ON roadmap_items (roadmap_code);
CREATE INDEX ix_roadmap_items_status ON roadmap_items (status);
CREATE TABLE corrective_actions (
	id VARCHAR(36) NOT NULL, 
	kpi_result_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	due_date DATE NOT NULL, 
	task_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	closure_note TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kpi_result_id) REFERENCES kpi_results (id) ON DELETE CASCADE
);

CREATE INDEX ix_corrective_actions_kpi_result_id ON corrective_actions (kpi_result_id);
CREATE INDEX ix_corrective_actions_organization_id ON corrective_actions (organization_id);
CREATE INDEX ix_corrective_actions_owner_user_id ON corrective_actions (owner_user_id);
CREATE INDEX ix_corrective_actions_status ON corrective_actions (status);
CREATE INDEX ix_corrective_actions_task_id ON corrective_actions (task_id);
CREATE TABLE kpi_period_snapshots (
	id VARCHAR(36) NOT NULL, 
	kpi_result_id VARCHAR(36) NOT NULL, 
	frozen_at DATETIME NOT NULL DEFAULT now(), 
	payload JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(kpi_result_id) REFERENCES kpi_results (id) ON DELETE CASCADE
);

CREATE INDEX ix_kpi_period_snapshots_kpi_result_id ON kpi_period_snapshots (kpi_result_id);

-- ======================================================================
-- 08_insight  (Insight service, port 8008)  — 15 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_insight;
USE fbos_insight;

CREATE TABLE alert_rules (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	metric_code VARCHAR(100) NOT NULL, 
	`condition` JSON NOT NULL, 
	severity VARCHAR(50) NOT NULL, 
	recipients_selector JSON NOT NULL, 
	enabled BOOL NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_alert_rules_metric_code ON alert_rules (metric_code);
CREATE INDEX ix_alert_rules_organization_id ON alert_rules (organization_id);
CREATE TABLE audit_anchors (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	anchor_date DATE NOT NULL, 
	event_count BIGINT NOT NULL, 
	merkle_root VARCHAR(64) NOT NULL, 
	archive_object_key VARCHAR(1024), 
	anchored_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_audit_anchors_anchor_date ON audit_anchors (anchor_date);
CREATE INDEX ix_audit_anchors_organization_id ON audit_anchors (organization_id);
CREATE TABLE audit_events (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	occurred_at DATETIME NOT NULL, 
	recorded_at DATETIME NOT NULL DEFAULT now(), 
	category VARCHAR(100) NOT NULL, 
	source_service VARCHAR(100) NOT NULL, 
	event_type VARCHAR(100) NOT NULL, 
	actor_type VARCHAR(50) NOT NULL, 
	actor_id VARCHAR(36), 
	subject_type VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(36), 
	action VARCHAR(50) NOT NULL, 
	changes JSON, 
	context JSON, 
	severity VARCHAR(50) NOT NULL, 
	row_hash VARCHAR(64), 
	PRIMARY KEY (id)
);

CREATE INDEX ix_audit_events_actor_id ON audit_events (actor_id);
CREATE INDEX ix_audit_events_category ON audit_events (category);
CREATE INDEX ix_audit_events_event_type ON audit_events (event_type);
CREATE INDEX ix_audit_events_occurred_at ON audit_events (occurred_at);
CREATE INDEX ix_audit_events_organization_id ON audit_events (organization_id);
CREATE INDEX ix_audit_events_source_service ON audit_events (source_service);
CREATE INDEX ix_audit_events_subject_id ON audit_events (subject_id);
CREATE INDEX ix_audit_events_subject_type ON audit_events (subject_type);
CREATE TABLE compliance_requirements (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	framework VARCHAR(50) NOT NULL, 
	requirement TEXT NOT NULL, 
	owner_user_id VARCHAR(36) NOT NULL, 
	frequency VARCHAR(50) NOT NULL, 
	next_due DATE, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_compliance_requirements_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_compliance_requirements_code ON compliance_requirements (code);
CREATE INDEX ix_compliance_requirements_framework ON compliance_requirements (framework);
CREATE INDEX ix_compliance_requirements_organization_id ON compliance_requirements (organization_id);
CREATE INDEX ix_compliance_requirements_owner_user_id ON compliance_requirements (owner_user_id);
CREATE INDEX ix_compliance_requirements_status ON compliance_requirements (status);
CREATE TABLE dashboards (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	audience VARCHAR(50) NOT NULL, 
	layout JSON NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_dashboards_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_dashboards_code ON dashboards (code);
CREATE INDEX ix_dashboards_organization_id ON dashboards (organization_id);
CREATE TABLE dim_date (
	day DATE NOT NULL, 
	fiscal_year VARCHAR(50) NOT NULL, 
	fiscal_quarter VARCHAR(50) NOT NULL, 
	month VARCHAR(50) NOT NULL, 
	is_working_day BOOL NOT NULL, 
	PRIMARY KEY (day)
);

CREATE INDEX ix_dim_date_fiscal_year ON dim_date (fiscal_year);
CREATE TABLE dim_org_unit (
	unit_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	unit_type VARCHAR(50) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	path VARCHAR(255), 
	PRIMARY KEY (unit_id)
);

CREATE INDEX ix_dim_org_unit_organization_id ON dim_org_unit (organization_id);
CREATE INDEX ix_dim_org_unit_path ON dim_org_unit (path);
CREATE TABLE governance_policies (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	version_no INTEGER NOT NULL, 
	document_id VARCHAR(36), 
	effective_from DATE, 
	review_by DATE, 
	owner_user_id VARCHAR(36) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_governance_policies_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_governance_policies_code ON governance_policies (code);
CREATE INDEX ix_governance_policies_document_id ON governance_policies (document_id);
CREATE INDEX ix_governance_policies_organization_id ON governance_policies (organization_id);
CREATE INDEX ix_governance_policies_owner_user_id ON governance_policies (owner_user_id);
CREATE INDEX ix_governance_policies_status ON governance_policies (status);
CREATE TABLE metric_daily (
	day DATE NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	metric_code VARCHAR(100) NOT NULL, 
	dimension_key VARCHAR(100) NOT NULL, 
	value NUMERIC(14, 4) NOT NULL, 
	PRIMARY KEY (day, organization_id, metric_code, dimension_key)
);

CREATE TABLE report_definitions (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	dataset VARCHAR(100) NOT NULL, 
	parameters_schema JSON, 
	schedule_rule VARCHAR(100), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_report_definitions_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_report_definitions_code ON report_definitions (code);
CREATE INDEX ix_report_definitions_organization_id ON report_definitions (organization_id);
CREATE TABLE compliance_evidence (
	id VARCHAR(36) NOT NULL, 
	requirement_id VARCHAR(36) NOT NULL, 
	period VARCHAR(50) NOT NULL, 
	document_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	reviewed_by VARCHAR(36), 
	reviewed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(requirement_id) REFERENCES compliance_requirements (id) ON DELETE CASCADE
);

CREATE INDEX ix_compliance_evidence_document_id ON compliance_evidence (document_id);
CREATE INDEX ix_compliance_evidence_requirement_id ON compliance_evidence (requirement_id);
CREATE INDEX ix_compliance_evidence_status ON compliance_evidence (status);
CREATE TABLE fact_revenue (
	invoice_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(36) NOT NULL, 
	vertical_id VARCHAR(36), 
	issue_day DATE NOT NULL, 
	taxable_amount NUMERIC(14, 2) NOT NULL, 
	settled_amount NUMERIC(14, 2) NOT NULL, 
	days_to_pay INTEGER, 
	PRIMARY KEY (invoice_id), 
	FOREIGN KEY(issue_day) REFERENCES dim_date (day) ON DELETE RESTRICT
);

CREATE INDEX ix_fact_revenue_client_id ON fact_revenue (client_id);
CREATE INDEX ix_fact_revenue_issue_day ON fact_revenue (issue_day);
CREATE INDEX ix_fact_revenue_organization_id ON fact_revenue (organization_id);
CREATE INDEX ix_fact_revenue_vertical_id ON fact_revenue (vertical_id);
CREATE TABLE fact_tasks (
	task_id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	unit_id VARCHAR(36), 
	vertical_id VARCHAR(36), 
	assignee_user_id VARCHAR(36), 
	created_day DATE, 
	due_day DATE, 
	on_time BOOL, 
	rework_rounds INTEGER NOT NULL, 
	logged_minutes INTEGER NOT NULL, 
	sla_breached BOOL NOT NULL, 
	completed_day DATE, 
	PRIMARY KEY (task_id), 
	FOREIGN KEY(unit_id) REFERENCES dim_org_unit (unit_id) ON DELETE SET NULL, 
	FOREIGN KEY(created_day) REFERENCES dim_date (day) ON DELETE RESTRICT, 
	FOREIGN KEY(due_day) REFERENCES dim_date (day) ON DELETE RESTRICT, 
	FOREIGN KEY(completed_day) REFERENCES dim_date (day) ON DELETE RESTRICT
);

CREATE INDEX ix_fact_tasks_assignee_user_id ON fact_tasks (assignee_user_id);
CREATE INDEX ix_fact_tasks_completed_day ON fact_tasks (completed_day);
CREATE INDEX ix_fact_tasks_created_day ON fact_tasks (created_day);
CREATE INDEX ix_fact_tasks_due_day ON fact_tasks (due_day);
CREATE INDEX ix_fact_tasks_organization_id ON fact_tasks (organization_id);
CREATE INDEX ix_fact_tasks_unit_id ON fact_tasks (unit_id);
CREATE INDEX ix_fact_tasks_vertical_id ON fact_tasks (vertical_id);
CREATE TABLE policy_acknowledgements (
	id VARCHAR(36) NOT NULL, 
	policy_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	policy_version INTEGER NOT NULL, 
	acknowledged_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(policy_id) REFERENCES governance_policies (id) ON DELETE CASCADE
);

CREATE INDEX ix_policy_acknowledgements_policy_id ON policy_acknowledgements (policy_id);
CREATE INDEX ix_policy_acknowledgements_user_id ON policy_acknowledgements (user_id);
CREATE TABLE report_runs (
	id VARCHAR(36) NOT NULL, 
	report_id VARCHAR(36) NOT NULL, 
	requested_by VARCHAR(36), 
	parameters JSON, 
	status VARCHAR(50) NOT NULL, 
	output_document_id VARCHAR(36), 
	started_at DATETIME, 
	finished_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(report_id) REFERENCES report_definitions (id) ON DELETE CASCADE
);

CREATE INDEX ix_report_runs_output_document_id ON report_runs (output_document_id);
CREATE INDEX ix_report_runs_report_id ON report_runs (report_id);
CREATE INDEX ix_report_runs_requested_by ON report_runs (requested_by);
CREATE INDEX ix_report_runs_status ON report_runs (status);

-- ======================================================================
-- 09_assets  (Assets service, port 8009)  — 21 tables
-- ======================================================================
CREATE DATABASE IF NOT EXISTS fbos_assets;
USE fbos_assets;

CREATE TABLE asset_categories (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	parent_id VARCHAR(36), 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_asset_categories_org_code UNIQUE (organization_id, code), 
	FOREIGN KEY(parent_id) REFERENCES asset_categories (id) ON DELETE SET NULL
);

CREATE INDEX ix_asset_categories_code ON asset_categories (code);
CREATE INDEX ix_asset_categories_organization_id ON asset_categories (organization_id);
CREATE INDEX ix_asset_categories_parent_id ON asset_categories (parent_id);
CREATE TABLE code_sequences (
	organization_id VARCHAR(36) NOT NULL, 
	sequence_key VARCHAR(100) NOT NULL, 
	period_key VARCHAR(50) NOT NULL, 
	prefix VARCHAR(50) NOT NULL, 
	next_value BIGINT NOT NULL, 
	PRIMARY KEY (organization_id, sequence_key, period_key)
);

CREATE TABLE idempotency_keys (
	organization_id VARCHAR(36) NOT NULL, 
	`key` VARCHAR(255) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	response_status INTEGER NOT NULL, 
	response_body JSON, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (organization_id, `key`)
);

CREATE INDEX ix_idempotency_keys_expires_at ON idempotency_keys (expires_at);
CREATE TABLE outbox (
	id VARCHAR(36) NOT NULL, 
	aggregate_type VARCHAR(100) NOT NULL, 
	aggregate_id VARCHAR(36) NOT NULL, 
	event_type VARCHAR(100) NOT NULL, 
	payload JSON NOT NULL, 
	headers JSON, 
	occurred_at DATETIME NOT NULL DEFAULT now(), 
	published_at DATETIME, 
	attempts INTEGER NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_outbox_aggregate_id ON outbox (aggregate_id);
CREATE INDEX ix_outbox_aggregate_type ON outbox (aggregate_type);
CREATE INDEX ix_outbox_event_type ON outbox (event_type);
CREATE INDEX ix_outbox_published_at ON outbox (published_at);
CREATE TABLE processed_events (
	consumer VARCHAR(100) NOT NULL, 
	event_id VARCHAR(36) NOT NULL, 
	processed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (consumer, event_id)
);

CREATE TABLE vendors (
	id VARCHAR(36) NOT NULL, 
	organization_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	vendor_type VARCHAR(50) NOT NULL, 
	gstin VARCHAR(50), 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vendors_org_code UNIQUE (organization_id, code)
);

CREATE INDEX ix_vendors_code ON vendors (code);
CREATE INDEX ix_vendors_organization_id ON vendors (organization_id);
CREATE INDEX ix_vendors_status ON vendors (status);
CREATE TABLE asset_types (
	id VARCHAR(36) NOT NULL, 
	category_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	family VARCHAR(50) NOT NULL, 
	attribute_schema JSON, 
	tracks_expiry BOOL NOT NULL, 
	single_custodian BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(category_id) REFERENCES asset_categories (id) ON DELETE RESTRICT
);

CREATE INDEX ix_asset_types_category_id ON asset_types (category_id);
CREATE UNIQUE INDEX ix_asset_types_code ON asset_types (code);
CREATE TABLE vendor_accounts (
	id VARCHAR(36) NOT NULL, 
	vendor_id VARCHAR(36) NOT NULL, 
	account_identifier VARCHAR(255) NOT NULL, 
	owner_user_id VARCHAR(36), 
	billing_email VARCHAR(255), 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE
);

CREATE INDEX ix_vendor_accounts_owner_user_id ON vendor_accounts (owner_user_id);
CREATE INDEX ix_vendor_accounts_status ON vendor_accounts (status);
CREATE INDEX ix_vendor_accounts_vendor_id ON vendor_accounts (vendor_id);
CREATE TABLE assets (
	id VARCHAR(36) NOT NULL, 
	parent_asset_id VARCHAR(36), 
	organization_id VARCHAR(36) NOT NULL, 
	asset_tag VARCHAR(100) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	asset_type_id VARCHAR(36) NOT NULL, 
	owner_unit_id VARCHAR(36), 
	scope_path VARCHAR(255), 
	custodian_user_id VARCHAR(36), 
	status VARCHAR(50) NOT NULL, 
	criticality VARCHAR(50) NOT NULL, 
	serial_no VARCHAR(100), 
	acquired_on DATE, 
	acquisition_cost NUMERIC(14, 2), 
	currency VARCHAR(3) NOT NULL, 
	expires_at DATE, 
	renewal_due_on DATE, 
	auto_renew BOOL NOT NULL, 
	attributes JSON, 
	version INTEGER NOT NULL, 
	vendor_account_id VARCHAR(36), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_assets_org_asset_tag UNIQUE (organization_id, asset_tag), 
	FOREIGN KEY(parent_asset_id) REFERENCES assets (id) ON DELETE SET NULL, 
	FOREIGN KEY(asset_type_id) REFERENCES asset_types (id) ON DELETE RESTRICT, 
	FOREIGN KEY(vendor_account_id) REFERENCES vendor_accounts (id) ON DELETE SET NULL
);

CREATE INDEX ix_assets_asset_tag ON assets (asset_tag);
CREATE INDEX ix_assets_asset_type_id ON assets (asset_type_id);
CREATE INDEX ix_assets_custodian_user_id ON assets (custodian_user_id);
CREATE INDEX ix_assets_organization_id ON assets (organization_id);
CREATE INDEX ix_assets_owner_unit_id ON assets (owner_unit_id);
CREATE INDEX ix_assets_parent_asset_id ON assets (parent_asset_id);
CREATE INDEX ix_assets_scope_path ON assets (scope_path);
CREATE INDEX ix_assets_serial_no ON assets (serial_no);
CREATE INDEX ix_assets_status ON assets (status);
CREATE INDEX ix_assets_vendor_account_id ON assets (vendor_account_id);
CREATE TABLE asset_assignments (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	assignee_type VARCHAR(50) NOT NULL, 
	assignee_id VARCHAR(36) NOT NULL, 
	assigned_at DATETIME NOT NULL, 
	returned_at DATETIME, 
	condition_out VARCHAR(100), 
	condition_in VARCHAR(100), 
	assigned_by VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX ix_asset_assignments_asset_id ON asset_assignments (asset_id);
CREATE INDEX ix_asset_assignments_assigned_at ON asset_assignments (assigned_at);
CREATE INDEX ix_asset_assignments_assignee_id ON asset_assignments (assignee_id);
CREATE TABLE asset_costs (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	cost_type VARCHAR(50) NOT NULL, 
	amount NUMERIC(14, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	period_start DATE, 
	period_end DATE, 
	vendor_invoice_ref VARCHAR(100), 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX ix_asset_costs_asset_id ON asset_costs (asset_id);
CREATE TABLE asset_disposals (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	method VARCHAR(50) NOT NULL, 
	disposed_on DATE NOT NULL, 
	value_realised NUMERIC(14, 2), 
	data_wiped BOOL NOT NULL, 
	certificate_document_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX ix_asset_disposals_asset_id ON asset_disposals (asset_id);
CREATE INDEX ix_asset_disposals_certificate_document_id ON asset_disposals (certificate_document_id);
CREATE TABLE asset_relationships (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	relation_type VARCHAR(50) NOT NULL, 
	related_asset_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE, 
	FOREIGN KEY(related_asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX ix_asset_relationships_asset_id ON asset_relationships (asset_id);
CREATE INDEX ix_asset_relationships_related_asset_id ON asset_relationships (related_asset_id);
CREATE TABLE asset_renewals (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	due_on DATE NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	approval_request_id VARCHAR(36), 
	decided_by VARCHAR(36), 
	new_expires_at DATE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX ix_asset_renewals_approval_request_id ON asset_renewals (approval_request_id);
CREATE INDEX ix_asset_renewals_asset_id ON asset_renewals (asset_id);
CREATE INDEX ix_asset_renewals_status ON asset_renewals (status);
CREATE TABLE credentials (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36), 
	organization_id VARCHAR(36) NOT NULL, 
	vendor_account_id VARCHAR(36), 
	name VARCHAR(255) NOT NULL, 
	kind VARCHAR(50) NOT NULL, 
	secret_ref VARCHAR(255) NOT NULL, 
	rotation_days INTEGER, 
	last_rotated_at DATETIME, 
	expires_at DATETIME, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE SET NULL, 
	FOREIGN KEY(vendor_account_id) REFERENCES vendor_accounts (id) ON DELETE SET NULL
);

CREATE INDEX ix_credentials_asset_id ON credentials (asset_id);
CREATE INDEX ix_credentials_organization_id ON credentials (organization_id);
CREATE INDEX ix_credentials_status ON credentials (status);
CREATE INDEX ix_credentials_vendor_account_id ON credentials (vendor_account_id);
CREATE TABLE licenses (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	license_type VARCHAR(50) NOT NULL, 
	seats_total INTEGER NOT NULL, 
	expires_at DATE, 
	key_secret_ref VARCHAR(255), 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX ix_licenses_asset_id ON licenses (asset_id);
CREATE TABLE maintenance_records (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	maintenance_type VARCHAR(50) NOT NULL, 
	vendor_id VARCHAR(36), 
	scheduled_on DATE NOT NULL, 
	completed_on DATE, 
	cost NUMERIC(14, 2), 
	task_id VARCHAR(36), 
	notes TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE, 
	FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE SET NULL
);

CREATE INDEX ix_maintenance_records_asset_id ON maintenance_records (asset_id);
CREATE INDEX ix_maintenance_records_task_id ON maintenance_records (task_id);
CREATE INDEX ix_maintenance_records_vendor_id ON maintenance_records (vendor_id);
CREATE TABLE subscriptions (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36) NOT NULL, 
	plan_name VARCHAR(255) NOT NULL, 
	billing_cycle VARCHAR(50) NOT NULL, 
	amount NUMERIC(14, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	seats INTEGER, 
	current_period_end DATE NOT NULL, 
	auto_renew BOOL NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX ix_subscriptions_asset_id ON subscriptions (asset_id);
CREATE INDEX ix_subscriptions_status ON subscriptions (status);
CREATE TABLE vendor_contracts (
	id VARCHAR(36) NOT NULL, 
	asset_id VARCHAR(36), 
	vendor_id VARCHAR(36) NOT NULL, 
	contract_type VARCHAR(50) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	value NUMERIC(14, 2), 
	document_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE SET NULL, 
	FOREIGN KEY(vendor_id) REFERENCES vendors (id) ON DELETE CASCADE
);

CREATE INDEX ix_vendor_contracts_asset_id ON vendor_contracts (asset_id);
CREATE INDEX ix_vendor_contracts_document_id ON vendor_contracts (document_id);
CREATE INDEX ix_vendor_contracts_vendor_id ON vendor_contracts (vendor_id);
CREATE TABLE credential_grants (
	id VARCHAR(36) NOT NULL, 
	credential_id VARCHAR(36) NOT NULL, 
	principal_type VARCHAR(50) NOT NULL, 
	principal_id VARCHAR(36) NOT NULL, 
	level VARCHAR(50) NOT NULL, 
	granted_by VARCHAR(36), 
	valid_to DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(credential_id) REFERENCES credentials (id) ON DELETE CASCADE
);

CREATE INDEX ix_credential_grants_credential_id ON credential_grants (credential_id);
CREATE INDEX ix_credential_grants_principal_id ON credential_grants (principal_id);
CREATE TABLE license_seats (
	id VARCHAR(36) NOT NULL, 
	license_id VARCHAR(36) NOT NULL, 
	assignee_type VARCHAR(50) NOT NULL, 
	assignee_id VARCHAR(36) NOT NULL, 
	assigned_at DATETIME NOT NULL DEFAULT now(), 
	released_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(license_id) REFERENCES licenses (id) ON DELETE CASCADE
);

CREATE INDEX ix_license_seats_assignee_id ON license_seats (assignee_id);
CREATE INDEX ix_license_seats_license_id ON license_seats (license_id);
