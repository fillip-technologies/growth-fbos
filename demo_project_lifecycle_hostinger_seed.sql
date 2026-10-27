-- =============================================================================
-- FBOS COMPLETE DEMO PROJECT LIFECYCLE SEED
-- Generated: 2026-10-27 08:55:05 UTC
-- Organization: Fillip Technologies (Patna Branch)
-- Scope: Revenue (Client, Contract, Invoices) & Delivery (Dev + Mkt Projects)
-- Full 10-Task Development Lifecycle with Strict Dependencies
-- Sakshi completely excluded; [DEMO] tagged on all entities.
-- Idempotent: Safe to execute multiple times (ON DUPLICATE KEY UPDATE).
-- =============================================================================

USE `u516064072_revenue_fbos`;
-- -----------------------------------------------------------------------------
-- 1.1 Commercial Client
-- -----------------------------------------------------------------------------
INSERT INTO `clients` 
(`id`, `organization_id`, `code`, `name`, `legal_name`, `client_type`, `pan`, `gstin`, `status`, `billing_address`, `owner_user_id`, `source`, `version`, `created_at`)
VALUES 
('0191f3a2-0030-7030-8030-000000000001', 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-CLI-PATNA-001', '[DEMO] Patna Smart Infra Pvt Ltd', 'Patna Smart Infra Private Limited', 'enterprise', 'AAACP1234E', '10AAACP1234E1Z4', 'active', '{"line1":"Bailey Road, Near High Court","city":"Patna","state":"Bihar","postal_code":"800001","country":"IN"}', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'inbound_referral', 1, '2026-10-27 08:55:05')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`), `legal_name`=VALUES(`legal_name`), `status`=VALUES(`status`);

-- -----------------------------------------------------------------------------
-- 1.2 Commercial Contracts (Development & Marketing)
-- -----------------------------------------------------------------------------
INSERT INTO `contracts` 
(`id`, `organization_id`, `client_id`, `accepted_quotation_id`, `opportunity_id`, `deal_id`, `parent_contract_id`, `contract_no`, `contract_type`, `status`, `sla_tier`, `start_date`, `end_date`, `total_value`, `currency`, `payment_terms_days`, `sla_fee`, `gst_fee`, `signed_at`, `version`)
VALUES 
('0191f3a2-0035-7035-8035-000000000001', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0030-7030-8030-000000000001', NULL, NULL, NULL, NULL, 'DEMO-CNT-2026-DEV01', 'fixed_price', 'active', 'standard', '2026-10-01', '2026-12-31', 350000.00, 'INR', 15, 0.00, 63000.00, '2026-10-01 10:00:00', 1),
('0191f3a2-0035-7035-8035-000000000002', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0030-7030-8030-000000000001', NULL, NULL, NULL, NULL, 'DEMO-CNT-2026-MKT01', 'retainer', 'active', 'standard', '2026-10-01', '2026-12-31', 75000.00, 'INR', 15, 0.00, 13500.00, '2026-10-01 10:00:00', 1)
ON DUPLICATE KEY UPDATE `status`=VALUES(`status`), `total_value`=VALUES(`total_value`);

-- -----------------------------------------------------------------------------
-- 1.3 Invoices (Advance Paid & In-Progress Milestone)
-- -----------------------------------------------------------------------------
INSERT INTO `invoices` 
(`id`, `organization_id`, `series_id`, `original_invoice_id`, `invoice_no`, `doc_type`, `context_id`, `contract_id`, `work_unit_id`, `client_id`, `issue_date`, `due_date`, `supplier_gstin`, `recipient_gstin`, `place_of_supply`, `reverse_charge`, `currency`, `exchange_rate`, `taxable_total`, `igst_total`, `cgst_total`, `sgst_total`, `grand_total`, `amount_settled`, `balance_due`, `status`, `issued_by`, `created_at`, `version`, `supply_type`, `round_off`)
VALUES 
('0191f3a2-0038-7038-8038-000000000001', 'b0e83920-ce43-4888-9900-dfcc44de8cde', NULL, NULL, 'DEMO-INV-2026-0001', 'tax_invoice', NULL, '0191f3a2-0035-7035-8035-000000000001', '0191f3a2-0040-7040-8040-000000000001', '0191f3a2-0030-7030-8030-000000000001', '2026-10-05', '2026-10-20', '10AAACF0000F1Z5', '10AAACP1234E1Z4', 'Bihar (10)', 0, 'INR', 1.000000, 100000.00, 0.00, 9000.00, 9000.00, 118000.00, 118000.00, 0.00, 'paid', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05', 1, 'B2B', 0.00),
('0191f3a2-0038-7038-8038-000000000002', 'b0e83920-ce43-4888-9900-dfcc44de8cde', NULL, NULL, 'DEMO-INV-2026-0002', 'tax_invoice', NULL, '0191f3a2-0035-7035-8035-000000000001', '0191f3a2-0040-7040-8040-000000000001', '0191f3a2-0030-7030-8030-000000000001', '2026-10-25', '2026-11-10', '10AAACF0000F1Z5', '10AAACP1234E1Z4', 'Bihar (10)', 0, 'INR', 1.000000, 150000.00, 0.00, 13500.00, 13500.00, 177000.00, 0.00, 177000.00, 'issued', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05', 1, 'B2B', 0.00)
ON DUPLICATE KEY UPDATE `status`=VALUES(`status`), `amount_settled`=VALUES(`amount_settled`), `balance_due`=VALUES(`balance_due`);

-- -----------------------------------------------------------------------------
-- 1.4 Invoice Lines
-- -----------------------------------------------------------------------------
INSERT INTO `invoice_lines` 
(`id`, `invoice_id`, `schedule_line_id`, `offering_id`, `line_no`, `description`, `hsn_code`, `quantity`, `unit_price`, `discount`, `taxable_value`, `igst_amount`, `cgst_amount`, `sgst_amount`, `line_total`, `tax_category_code`, `tax_rate`)
VALUES 
('e6e5131b-a4e5-50fd-8817-4058f9e2428b', '0191f3a2-0038-7038-8038-000000000001', NULL, NULL, 1, '[DEMO] Project Mobilization & Requirements Sign-off (Milestone 1)', '998314', 1.0000, 100000.00, 0.00, 100000.00, 0.00, 9000.00, 9000.00, 118000.00, 'GST_18', 18.0000),
('632a3194-1abf-5c68-8e64-0243a4f0044b', '0191f3a2-0038-7038-8038-000000000002', NULL, NULL, 1, '[DEMO] Fullstack Platform Implementation & CMS (Milestone 2)', '998314', 1.0000, 150000.00, 0.00, 150000.00, 0.00, 13500.00, 13500.00, 177000.00, 'GST_18', 18.0000)
ON DUPLICATE KEY UPDATE `taxable_value`=VALUES(`taxable_value`), `line_total`=VALUES(`line_total`);

-- -----------------------------------------------------------------------------
-- 1.5 Payments & Allocations
-- -----------------------------------------------------------------------------
INSERT INTO `payments` 
(`id`, `organization_id`, `client_id`, `receipt_no`, `amount`, `currency`, `method`, `bank_reference`, `charges`, `unapplied_amount`, `status`, `recorded_by`, `received_at`, `version`, `tds_amount`)
VALUES 
('0191f3a2-0039-7039-8039-000000000001', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0030-7030-8030-000000000001', 'DEMO-RCT-2026-0001', 118000.00, 'INR', 'bank_transfer', 'HDFC-NEFT-9948201284', 0.00, 0.00, 'cleared', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-06 14:20:00', 1, 0.00)
ON DUPLICATE KEY UPDATE `status`=VALUES(`status`), `amount`=VALUES(`amount`);

INSERT INTO `payment_allocations` 
(`id`, `payment_id`, `invoice_id`, `amount`, `allocated_at`, `tds_amount`, `gst_tds_amount`)
VALUES 
('e75b69a3-462c-56fd-ba75-5e7a04feffba', '0191f3a2-0039-7039-8039-000000000001', '0191f3a2-0038-7038-8038-000000000001', 118000.00, '2026-10-06 14:30:00', 0.00, 0.00)
ON DUPLICATE KEY UPDATE `amount`=VALUES(`amount`);

USE `u516064072_delivery_fbos`;
-- -----------------------------------------------------------------------------
-- 2.1 Work Units (Development & Digital Marketing Projects)
-- -----------------------------------------------------------------------------
INSERT INTO `work_units` 
(`id`, `parent_work_unit_id`, `organization_id`, `code`, `name`, `objective`, `work_unit_type_id`, `template_version_id`, `vertical_id`, `owning_unit_id`, `scope_path`, `client_id`, `contract_id`, `deal_id`, `manager_user_id`, `planned_start`, `planned_end`, `status`, `priority`, `billable`, `currency`, `progress_pct`, `health`, `version`, `created_at`, `updated_at`)
VALUES 
('0191f3a2-0040-7040-8040-000000000001', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-PRJ-DEV-001', '[DEMO] Patna Smart Infra — Smart Operations Enterprise Portal', 'Full-stack enterprise operations web application, CMS integration, and citizen portal.', '2ea578fa-ada1-5e23-8112-99c47f5668fb', NULL, 'b3d4b502-74f4-44d4-afe5-e7b0225f5dab', '1a60889b-62de-4d92-af29-67338ceffa1b', '/13a35fd1-c477-4f29-9e58-aab1be1b6ab1/1a60889b-62de-4d92-af29-67338ceffa1b/', '0191f3a2-0030-7030-8030-000000000001', '0191f3a2-0035-7035-8035-000000000001', NULL, '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-01', '2026-12-31', 'active', 'high', 1, 'INR', 35.00, 'green', 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0040-7040-8040-000000000002', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-PRJ-MKT-001', '[DEMO] Patna Smart Infra — Regional Brand Growth & Digital Outreach', 'SEO visibility audit, content marketing, and Google Ads paid acquisition campaign.', '2ea578fa-ada1-5e23-8112-99c47f5668fb', NULL, 'c589d0a0-792c-49dc-abce-116c26c73f24', '32846f36-6926-4cf5-8438-55a6726c9a9f', '/13a35fd1-c477-4f29-9e58-aab1be1b6ab1/32846f36-6926-4cf5-8438-55a6726c9a9f/', '0191f3a2-0030-7030-8030-000000000001', '0191f3a2-0035-7035-8035-000000000002', NULL, 'd3e4a37c-29a3-44ae-badd-027701b2fd38', '2026-10-01', '2026-12-31', 'active', 'medium', 1, 'INR', 45.00, 'green', 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`), `status`=VALUES(`status`), `progress_pct`=VALUES(`progress_pct`);

-- -----------------------------------------------------------------------------
-- 2.2 Project Phases (Phased Lifecycle Structure)
-- -----------------------------------------------------------------------------
INSERT INTO `phases` 
(`id`, `work_unit_id`, `seq`, `name`, `planned_start`, `planned_end`, `actual_start`, `actual_end`, `status`)
VALUES 
('0191f3a2-0042-7042-8042-000000000001', '0191f3a2-0040-7040-8040-000000000001', 1, '[DEMO] Discovery, Sitemap & UI/UX Design', '2026-10-01', '2026-10-14', '2026-10-01', '2026-10-14', 'completed'),
('0191f3a2-0042-7042-8042-000000000002', '0191f3a2-0040-7040-8040-000000000001', 2, '[DEMO] Fullstack Development & CMS Integration', '2026-10-15', '2026-11-05', '2026-10-15', NULL, 'in_progress'),
('0191f3a2-0042-7042-8042-000000000003', '0191f3a2-0040-7040-8040-000000000001', 3, '[DEMO] QA Testing, Bug Fixing & Mobile Audit', '2026-11-06', '2026-11-18', NULL, NULL, 'planned'),
('0191f3a2-0042-7042-8042-000000000004', '0191f3a2-0040-7040-8040-000000000001', 4, '[DEMO] Client UAT, Production Launch & Handover', '2026-11-19', '2026-12-31', NULL, NULL, 'planned')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`), `status`=VALUES(`status`);

-- -----------------------------------------------------------------------------
-- 2.3 Milestones (Key Delivery & Billing Gates)
-- -----------------------------------------------------------------------------
INSERT INTO `milestones` 
(`id`, `work_unit_id`, `phase_id`, `code`, `name`, `seq`, `weight`, `planned_date`, `is_billing_milestone`, `requires_client_acceptance`, `status`)
VALUES 
('0191f3a2-0045-7045-8045-000000000001', '0191f3a2-0040-7040-8040-000000000001', '0191f3a2-0042-7042-8042-000000000001', 'DEMO-MS-01', '[DEMO] Milestone 1: Requirements & UI/UX Sign-off', 1, 30.00, '2026-10-14', 1, 1, 'accepted'),
('0191f3a2-0045-7045-8045-000000000002', '0191f3a2-0040-7040-8040-000000000001', '0191f3a2-0042-7042-8042-000000000002', 'DEMO-MS-02', '[DEMO] Milestone 2: Functional Core MVP & CMS API', 2, 40.00, '2026-11-05', 1, 1, 'in_progress'),
('0191f3a2-0045-7045-8045-000000000003', '0191f3a2-0040-7040-8040-000000000001', '0191f3a2-0042-7042-8042-000000000004', 'DEMO-MS-03', '[DEMO] Milestone 3: Client UAT Sign-off & Production Launch', 3, 30.00, '2026-11-28', 1, 1, 'pending'),
('0191f3a2-0045-7045-8045-000000000004', '0191f3a2-0040-7040-8040-000000000002', NULL, 'DEMO-MS-MKT-01', '[DEMO] Milestone 1: SEO Audit & Keyword Architecture Complete', 1, 50.00, '2026-10-15', 1, 0, 'accepted'),
('0191f3a2-0045-7045-8045-000000000005', '0191f3a2-0040-7040-8040-000000000002', NULL, 'DEMO-MS-MKT-02', '[DEMO] Milestone 2: Ad Campaigns Live & First 100 Inquiries', 2, 50.00, '2026-11-20', 1, 1, 'in_progress')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`), `status`=VALUES(`status`);

-- -----------------------------------------------------------------------------
-- 2.4 Work Unit Members Allocation (Real Active Staff from Patna)
-- -----------------------------------------------------------------------------
INSERT INTO `work_unit_members` (`id`, `work_unit_id`, `user_id`, `member_role`, `allocation_pct`, `valid_from`, `valid_to`)
VALUES
('59292a09-e35e-525d-97fc-451606ff7ca6', '0191f3a2-0040-7040-8040-000000000001', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'Project Manager', 100.00, '2026-10-01', '2026-12-31'),
('cb0c1d30-5e21-5b5d-9e92-ce40cabad52b', '0191f3a2-0040-7040-8040-000000000001', 'bdfc3878-0bd8-4373-b30e-c614117f3a73', 'UI/UX Designer', 80.00, '2026-10-01', '2026-12-31'),
('ab60b144-1f36-547e-a053-199d8d6cf62f', '0191f3a2-0040-7040-8040-000000000001', '49d177e8-01ba-422d-8e0c-a6311bd55fd3', 'Frontend Engineer', 100.00, '2026-10-01', '2026-12-31'),
('76fb5395-82c0-5214-9be6-d776ad1ebe53', '0191f3a2-0040-7040-8040-000000000001', '0ccb34fa-6833-4fc8-88d7-4af504d8ba51', 'Backend Lead', 80.00, '2026-10-01', '2026-12-31'),
('63be775a-b971-5cd0-8478-56a720615606', '0191f3a2-0040-7040-8040-000000000001', '4da6a393-b958-4495-b7aa-c59aee120c24', 'Fullstack Engineer', 75.00, '2026-10-01', '2026-12-31'),
('926e6ff5-7305-5b7e-8c3a-d969ab94e780', '0191f3a2-0040-7040-8040-000000000001', 'f7156971-c056-4491-a721-5e97f404ba78', 'Backend Developer', 75.00, '2026-10-01', '2026-12-31'),
('4f2845f1-d1ed-56dc-a32a-9c1d1e650fbd', '0191f3a2-0040-7040-8040-000000000001', 'd851ffcf-5ea5-4c69-9a3e-96a8cdac06db', 'QA & DevOps Engineer', 50.00, '2026-10-01', '2026-12-31'),
('49a52411-1d23-57b5-acd8-3b785d8bfadc', '0191f3a2-0040-7040-8040-000000000002', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'Marketing Director', 100.00, '2026-10-01', '2026-12-31'),
('18540a74-b955-56f3-beb9-bda76b22191c', '0191f3a2-0040-7040-8040-000000000002', '505f1422-c51e-41ce-aeee-6cb18ae4830a', 'SEO Lead', 80.00, '2026-10-01', '2026-12-31'),
('8f8d797c-a61a-56b8-8eb3-b35283ee613a', '0191f3a2-0040-7040-8040-000000000002', '177fca7c-b35b-43d4-adf8-0ff787322e96', 'SEO Specialist', 80.00, '2026-10-01', '2026-12-31'),
('45c6acf6-a6d4-5c56-b9ed-bf43dc219fe1', '0191f3a2-0040-7040-8040-000000000002', '48985bb5-8b9f-4331-9a23-4317e5b0a6ad', 'Content Strategist', 80.00, '2026-10-01', '2026-12-31'),
('0fbf1677-0ed4-5948-a8bc-c40677851a85', '0191f3a2-0040-7040-8040-000000000002', 'bdfc3878-0bd8-4373-b30e-c614117f3a73', 'Creative Designer', 50.00, '2026-10-01', '2026-12-31')
ON DUPLICATE KEY UPDATE `member_role`=VALUES(`member_role`);

-- -----------------------------------------------------------------------------
-- 2.5 Tasks Table (10 Dev Tasks + 5 Digital Marketing Tasks)
-- -----------------------------------------------------------------------------
INSERT INTO `tasks` 
(`id`, `parent_task_id`, `organization_id`, `code`, `title`, `description`, `work_unit_id`, `task_type_id`, `owning_unit_id`, `assignee_user_id`, `reviewer_user_id`, `priority`, `status`, `source`, `review_round`, `start_at`, `due_at`, `completed_at`, `estimate_minutes`, `logged_minutes`, `progress_pct`, `version`, `created_at`, `updated_at`)
VALUES
('0191f3a2-0050-7050-8050-000000000001', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-001', '[DEMO] Collect client requirements', 'Initial discovery workshop and requirements gathering session with Patna Smart Infra executive stakeholders. Identify core functional deliverables and technical constraints.', '0191f3a2-0040-7040-8040-000000000001', '89fc1d43-aa4e-5ef3-8bc8-e594b784f66d', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p1', 'done', 'manual', 0, '2026-10-02 10:00:00', '2026-10-04 18:00:00', '2026-10-04 16:30:00', 180, 180, 100, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000002', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-002', '[DEMO] Prepare sitemap and wireframes', 'Draft comprehensive information architecture sitemap, interactive Figma wireframes, and design layout structure for responsive desktop and mobile views.', '0191f3a2-0040-7040-8040-000000000001', 'f814a4e7-71ac-5d67-9243-90bf3d3fd075', '108de574-eb76-4282-b9fe-9b9dca562f25', 'bdfc3878-0bd8-4373-b30e-c614117f3a73', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p1', 'done', 'manual', 0, '2026-10-05 09:30:00', '2026-10-10 18:00:00', '2026-10-10 17:45:00', 480, 480, 100, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000003', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-003', '[DEMO] Approve UI/UX design', 'Conduct design walkthrough session with the client executive committee. Review user flows, color system, accessibility criteria, and secure formal design sign-off.', '0191f3a2-0040-7040-8040-000000000001', 'a37e9467-4457-5093-952f-3219bc35066a', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p1', 'in_review', 'manual', 0, '2026-10-11 11:00:00', '2026-10-14 18:00:00', NULL, 120, 90, 80, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000004', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-004', '[DEMO] Develop homepage and inner pages', 'Build responsive frontend user interfaces for Homepage, About, Service Catalogs, and Analytics views using React, TypeScript, and Tailwind CSS.', '0191f3a2-0040-7040-8040-000000000001', '39de8558-b9c2-586a-b673-375f88a33bf4', '6b85e04e-5f79-4f55-ba35-352a7b69ef6f', '49d177e8-01ba-422d-8e0c-a6311bd55fd3', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p1', 'open', 'manual', 0, '2026-10-15 09:30:00', '2026-11-05 18:00:00', NULL, 960, 120, 25, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000005', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-005', '[DEMO] Implement CMS and contact forms', 'Implement backend microservice REST APIs for dynamic CMS content publishing, contact inquiry processing, rate limiting, and email dispatch.', '0191f3a2-0040-7040-8040-000000000001', '39de8558-b9c2-586a-b673-375f88a33bf4', '0a44e04b-fc73-4b98-bcc0-a2306797ac54', '0ccb34fa-6833-4fc8-88d7-4af504d8ba51', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p2', 'open', 'manual', 0, '2026-10-15 09:30:00', '2026-11-05 18:00:00', NULL, 600, 60, 15, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000006', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-006', '[DEMO] Test mobile responsiveness', 'Execute cross-browser and cross-device responsiveness validation across iOS Safari, Android Chrome, tablet breakpoints, and desktop monitors.', '0191f3a2-0040-7040-8040-000000000001', 'f814a4e7-71ac-5d67-9243-90bf3d3fd075', '1a60889b-62de-4d92-af29-67338ceffa1b', '4da6a393-b958-4495-b7aa-c59aee120c24', 'd851ffcf-5ea5-4c69-9a3e-96a8cdac06db', 'p2', 'open', 'manual', 0, '2026-11-06 09:30:00', '2026-11-12 18:00:00', NULL, 300, 0, 0, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000007', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-007', '[DEMO] Fix reported bugs', 'Resolve any UI discrepancies, mobile layout breaks, form validation edge cases, or API anomalies detected during responsiveness testing.', '0191f3a2-0040-7040-8040-000000000001', 'ea1008b8-9868-51d3-ae97-696d2043d0f0', '0a44e04b-fc73-4b98-bcc0-a2306797ac54', 'f7156971-c056-4491-a721-5e97f404ba78', '0ccb34fa-6833-4fc8-88d7-4af504d8ba51', 'p1', 'open', 'manual', 0, '2026-11-13 09:30:00', '2026-11-18 18:00:00', NULL, 420, 0, 0, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000008', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-008', '[DEMO] Obtain client UAT approval', 'Deliver release candidate to staging environment, facilitate client UAT testing walkthrough, and obtain formal User Acceptance sign-off.', '0191f3a2-0040-7040-8040-000000000001', '5cd00b31-1e08-5d66-8e7d-6a1e2e6d5519', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p1', 'open', 'manual', 0, '2026-11-19 10:00:00', '2026-11-25 18:00:00', NULL, 240, 0, 0, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000009', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-009', '[DEMO] Deploy to production', 'Execute production zero-downtime deployment, configure custom domain DNS, provision SSL certificates, and configure database connection pooling.', '0191f3a2-0040-7040-8040-000000000001', 'f814a4e7-71ac-5d67-9243-90bf3d3fd075', '1a60889b-62de-4d92-af29-67338ceffa1b', 'd851ffcf-5ea5-4c69-9a3e-96a8cdac06db', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p1', 'open', 'manual', 0, '2026-11-26 09:30:00', '2026-11-28 18:00:00', NULL, 240, 0, 0, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0050-7050-8050-000000000010', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-010', '[DEMO] Handover documentation', 'Prepare and transfer full administrative operations documentation, architecture diagrams, user manuals, and maintenance credentials pack.', '0191f3a2-0040-7040-8040-000000000001', '5cd00b31-1e08-5d66-8e7d-6a1e2e6d5519', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p3', 'open', 'manual', 0, '2026-11-29 09:30:00', '2026-12-05 18:00:00', NULL, 180, 0, 0, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0060-7060-8060-000000000001', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-DM-01', '[DEMO] Comprehensive Website SEO Audit & Keyword Research', 'Perform complete baseline SEO audit, competitive gap analysis, and high-intent keyword clustering for Patna regional market.', '0191f3a2-0040-7040-8040-000000000002', 'f814a4e7-71ac-5d67-9243-90bf3d3fd075', 'fb59ee8c-a143-434f-8fa0-b3246b961cc9', '505f1422-c51e-41ce-aeee-6cb18ae4830a', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'p1', 'done', 'manual', 0, '2026-10-02 09:30:00', '2026-10-08 18:00:00', '2026-10-08 17:00:00', 360, 360, 100, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0060-7060-8060-000000000002', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-DM-02', '[DEMO] On-Page SEO Optimization & Meta Tags Setup', 'Implement JSON-LD schema markup, canonical tags, Open Graph meta headers, and sitemap XML generation.', '0191f3a2-0040-7040-8040-000000000002', 'f814a4e7-71ac-5d67-9243-90bf3d3fd075', 'fb59ee8c-a143-434f-8fa0-b3246b961cc9', '177fca7c-b35b-43d4-adf8-0ff787322e96', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'p1', 'in_progress', 'manual', 0, '2026-10-09 09:30:00', '2026-10-22 18:00:00', NULL, 300, 150, 50, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0060-7060-8060-000000000003', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-DM-03', '[DEMO] Content Strategy & Blog Articles Drafting', 'Draft conversion-focused pillar articles, authority thought leadership content, and FAQs optimized for regional search ranking.', '0191f3a2-0040-7040-8040-000000000002', '5cd00b31-1e08-5d66-8e7d-6a1e2e6d5519', '77ed4af0-d074-4d3d-9d95-8732350b8c95', '48985bb5-8b9f-4331-9a23-4317e5b0a6ad', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'p2', 'in_progress', 'manual', 0, '2026-10-09 09:30:00', '2026-10-25 18:00:00', NULL, 480, 240, 50, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0060-7060-8060-000000000004', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-DM-04', '[DEMO] Google Ads & Meta Ads Campaign Setup', 'Structure high-conversion Google Search campaigns, configure negative keyword lists, design Meta lead-gen ads, and set up conversion tracking pixels.', '0191f3a2-0040-7040-8040-000000000002', 'f814a4e7-71ac-5d67-9243-90bf3d3fd075', '32846f36-6926-4cf5-8438-55a6726c9a9f', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'p1', 'open', 'manual', 0, '2026-10-26 09:30:00', '2026-11-10 18:00:00', NULL, 360, 0, 0, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05'),
('0191f3a2-0060-7060-8060-000000000005', NULL, 'b0e83920-ce43-4888-9900-dfcc44de8cde', 'DEMO-TSK-DM-05', '[DEMO] Monthly Performance & ROI Analytics Report', 'Generate executive Looker Studio dashboard tracking cost-per-click, conversion volume, organic impression growth, and cost-per-acquisition.', '0191f3a2-0040-7040-8040-000000000002', '5cd00b31-1e08-5d66-8e7d-6a1e2e6d5519', '32846f36-6926-4cf5-8438-55a6726c9a9f', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'p2', 'open', 'manual', 0, '2026-11-15 09:30:00', '2026-11-30 18:00:00', NULL, 180, 0, 0, 1, '2026-10-27 08:55:05', '2026-10-27 08:55:05')
ON DUPLICATE KEY UPDATE `title`=VALUES(`title`), `status`=VALUES(`status`), `progress_pct`=VALUES(`progress_pct`), `logged_minutes`=VALUES(`logged_minutes`);

-- -----------------------------------------------------------------------------
-- 2.6 Task Assignments (Assignee & Reviewer Links)
-- -----------------------------------------------------------------------------
INSERT INTO `task_assignments` 
(`id`, `task_id`, `unit_id`, `user_id`, `assignment_role`, `assigned_by`, `assigned_at`)
VALUES
('dd063a71-4ffe-5f60-b084-64a1e92a9c72', '0191f3a2-0050-7050-8050-000000000001', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('d19756dd-d3be-584d-ace1-741a926986bc', '0191f3a2-0050-7050-8050-000000000001', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('1d3b3b23-b290-5493-b380-b0b61c0b2adc', '0191f3a2-0050-7050-8050-000000000002', '108de574-eb76-4282-b9fe-9b9dca562f25', 'bdfc3878-0bd8-4373-b30e-c614117f3a73', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('e69f37ec-46d8-519c-8115-395018b86ed2', '0191f3a2-0050-7050-8050-000000000002', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('dff4979e-f18e-531b-bdfd-177b19030899', '0191f3a2-0050-7050-8050-000000000003', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('2ca25678-290e-5d86-b08e-4ad1ca3a6a13', '0191f3a2-0050-7050-8050-000000000003', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('100f4379-d877-51ab-996e-6d91ff1b00b7', '0191f3a2-0050-7050-8050-000000000004', '6b85e04e-5f79-4f55-ba35-352a7b69ef6f', '49d177e8-01ba-422d-8e0c-a6311bd55fd3', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('ff321feb-edcc-50ec-a58b-9ae3800e094b', '0191f3a2-0050-7050-8050-000000000004', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('8560e6a3-78e0-5bfa-848e-cad869763e95', '0191f3a2-0050-7050-8050-000000000005', '0a44e04b-fc73-4b98-bcc0-a2306797ac54', '0ccb34fa-6833-4fc8-88d7-4af504d8ba51', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('6bfd8618-46e0-509b-9ef9-8a27e010f889', '0191f3a2-0050-7050-8050-000000000005', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('0f860108-b6b0-54c3-ba42-80234ec73988', '0191f3a2-0050-7050-8050-000000000006', '1a60889b-62de-4d92-af29-67338ceffa1b', '4da6a393-b958-4495-b7aa-c59aee120c24', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('b1f6d5a7-32f8-5d0f-82e2-e456552d64a1', '0191f3a2-0050-7050-8050-000000000006', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', 'd851ffcf-5ea5-4c69-9a3e-96a8cdac06db', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('b334b41e-4469-512c-96f7-3ad8a805effd', '0191f3a2-0050-7050-8050-000000000007', '0a44e04b-fc73-4b98-bcc0-a2306797ac54', 'f7156971-c056-4491-a721-5e97f404ba78', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('ca17c2dd-83a3-5007-aaca-e20ac9dc26e1', '0191f3a2-0050-7050-8050-000000000007', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '0ccb34fa-6833-4fc8-88d7-4af504d8ba51', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('acc44537-6691-582d-83fb-e75c75c4533d', '0191f3a2-0050-7050-8050-000000000008', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('2cceb92b-3991-5466-86a1-7e5b1b200e11', '0191f3a2-0050-7050-8050-000000000008', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('c68e1abb-74f2-58cc-a7b1-954f5820cba2', '0191f3a2-0050-7050-8050-000000000009', '1a60889b-62de-4d92-af29-67338ceffa1b', 'd851ffcf-5ea5-4c69-9a3e-96a8cdac06db', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('213a83aa-1cb2-5991-bf12-d4db8f1faeab', '0191f3a2-0050-7050-8050-000000000009', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('dad07660-7de9-5f7b-ad3c-226d0e7f87b3', '0191f3a2-0050-7050-8050-000000000010', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('c03fea88-6ace-5fbb-8530-1df703fc778e', '0191f3a2-0050-7050-8050-000000000010', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('39cb1443-dbf3-5032-9afa-7a4d03287174', '0191f3a2-0060-7060-8060-000000000001', 'fb59ee8c-a143-434f-8fa0-b3246b961cc9', '505f1422-c51e-41ce-aeee-6cb18ae4830a', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('8cb6919b-464d-5dc1-8d7e-4ea36625eba4', '0191f3a2-0060-7060-8060-000000000001', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('8806552c-2fe0-5093-900f-30329e34e75a', '0191f3a2-0060-7060-8060-000000000002', 'fb59ee8c-a143-434f-8fa0-b3246b961cc9', '177fca7c-b35b-43d4-adf8-0ff787322e96', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('701b9fc2-bd70-5668-8e12-696fd09de0f8', '0191f3a2-0060-7060-8060-000000000002', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('f2d33611-8c14-5936-b34e-9f98d69de501', '0191f3a2-0060-7060-8060-000000000003', '77ed4af0-d074-4d3d-9d95-8732350b8c95', '48985bb5-8b9f-4331-9a23-4317e5b0a6ad', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('fd33ff29-c7ad-5a6a-a1c6-6dc47b2c6647', '0191f3a2-0060-7060-8060-000000000003', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('f5a77edd-5ffb-56a8-b2e5-2cb6f23f30d2', '0191f3a2-0060-7060-8060-000000000004', '32846f36-6926-4cf5-8438-55a6726c9a9f', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('cb5794f6-e8ef-58ce-9ee7-1fd48addb38e', '0191f3a2-0060-7060-8060-000000000004', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('b70664d6-2d84-58c3-bbad-3ac33046fa9a', '0191f3a2-0060-7060-8060-000000000005', '32846f36-6926-4cf5-8438-55a6726c9a9f', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'assignee', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('ea86f73c-6f39-521f-a33a-0a6fe530c399', '0191f3a2-0060-7060-8060-000000000005', '648938a6-19b9-4c3b-ab80-8b4f99d07d9a', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'reviewer', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05')
ON DUPLICATE KEY UPDATE `assignment_role`=VALUES(`assignment_role`);

-- -----------------------------------------------------------------------------
-- 2.7 Task Dependencies (Strict Finish-to-Start Sequential Flow)
-- -----------------------------------------------------------------------------
INSERT INTO `task_dependencies` 
(`task_id`, `depends_on_task_id`, `dependency_type`)
VALUES
('0191f3a2-0050-7050-8050-000000000002', '0191f3a2-0050-7050-8050-000000000001', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000003', '0191f3a2-0050-7050-8050-000000000002', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000004', '0191f3a2-0050-7050-8050-000000000003', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000005', '0191f3a2-0050-7050-8050-000000000003', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000006', '0191f3a2-0050-7050-8050-000000000004', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000006', '0191f3a2-0050-7050-8050-000000000005', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000007', '0191f3a2-0050-7050-8050-000000000006', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000008', '0191f3a2-0050-7050-8050-000000000007', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000009', '0191f3a2-0050-7050-8050-000000000008', 'finish_to_start'),
('0191f3a2-0050-7050-8050-000000000010', '0191f3a2-0050-7050-8050-000000000009', 'finish_to_start'),
('0191f3a2-0060-7060-8060-000000000002', '0191f3a2-0060-7060-8060-000000000001', 'finish_to_start'),
('0191f3a2-0060-7060-8060-000000000003', '0191f3a2-0060-7060-8060-000000000001', 'finish_to_start'),
('0191f3a2-0060-7060-8060-000000000004', '0191f3a2-0060-7060-8060-000000000002', 'finish_to_start'),
('0191f3a2-0060-7060-8060-000000000004', '0191f3a2-0060-7060-8060-000000000003', 'finish_to_start'),
('0191f3a2-0060-7060-8060-000000000005', '0191f3a2-0060-7060-8060-000000000004', 'finish_to_start')
ON DUPLICATE KEY UPDATE `dependency_type`=VALUES(`dependency_type`);

-- -----------------------------------------------------------------------------
-- 2.8 Time Entries (Timesheet Records for Completed & Active Tasks)
-- -----------------------------------------------------------------------------
INSERT INTO `time_entries` 
(`id`, `organization_id`, `task_id`, `user_id`, `work_date`, `started_at`, `ended_at`, `minutes`, `billable`, `source`, `note`, `approved_by`, `created_at`)
VALUES
('c81237e8-8718-505a-b72d-4d92e77b856f', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0050-7050-8050-000000000001', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-02', '2026-10-02 10:00:00', '2026-10-02 16:00:00', 180, 1, 'timer', 'Logged effort for DEMO-TSK-001: [DEMO] Collect client requirements', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('bce24a2e-b898-5dc8-b020-10440714fb80', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0050-7050-8050-000000000002', 'bdfc3878-0bd8-4373-b30e-c614117f3a73', '2026-10-05', '2026-10-05 10:00:00', '2026-10-05 16:00:00', 480, 1, 'timer', 'Logged effort for DEMO-TSK-002: [DEMO] Prepare sitemap and wireframes', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('72d583f1-2af5-5385-a2d2-e05bdc73d6c7', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0050-7050-8050-000000000003', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-11', '2026-10-11 10:00:00', '2026-10-11 16:00:00', 90, 1, 'timer', 'Logged effort for DEMO-TSK-003: [DEMO] Approve UI/UX design', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('c1d07a1a-84d1-5e36-b8af-f8c558f8ca24', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0050-7050-8050-000000000004', '49d177e8-01ba-422d-8e0c-a6311bd55fd3', '2026-10-15', '2026-10-15 10:00:00', '2026-10-15 16:00:00', 120, 1, 'timer', 'Logged effort for DEMO-TSK-004: [DEMO] Develop homepage and inner pages', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('950eb744-7246-5db1-9d7c-a7999f7a46a1', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0050-7050-8050-000000000005', '0ccb34fa-6833-4fc8-88d7-4af504d8ba51', '2026-10-15', '2026-10-15 10:00:00', '2026-10-15 16:00:00', 60, 1, 'timer', 'Logged effort for DEMO-TSK-005: [DEMO] Implement CMS and contact forms', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('f236c201-7325-5184-9850-e5c1ef199bfe', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0060-7060-8060-000000000001', '505f1422-c51e-41ce-aeee-6cb18ae4830a', '2026-10-02', '2026-10-02 10:00:00', '2026-10-02 16:00:00', 360, 1, 'timer', 'Logged effort for DEMO-TSK-DM-01: [DEMO] Comprehensive Website SEO Audit & Keyword Research', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('102678c9-597e-52c8-80c1-ca30370d7de6', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0060-7060-8060-000000000002', '177fca7c-b35b-43d4-adf8-0ff787322e96', '2026-10-09', '2026-10-09 10:00:00', '2026-10-09 16:00:00', 150, 1, 'timer', 'Logged effort for DEMO-TSK-DM-02: [DEMO] On-Page SEO Optimization & Meta Tags Setup', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05'),
('95ac591f-562f-5290-a901-da8d21b8a57b', 'b0e83920-ce43-4888-9900-dfcc44de8cde', '0191f3a2-0060-7060-8060-000000000003', '48985bb5-8b9f-4331-9a23-4317e5b0a6ad', '2026-10-09', '2026-10-09 10:00:00', '2026-10-09 16:00:00', 240, 1, 'timer', 'Logged effort for DEMO-TSK-DM-03: [DEMO] Content Strategy & Blog Articles Drafting', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', '2026-10-27 08:55:05')
ON DUPLICATE KEY UPDATE `minutes`=VALUES(`minutes`), `note`=VALUES(`note`);

-- -----------------------------------------------------------------------------
-- 2.9 Task Comments (Realistic Team Updates)
-- -----------------------------------------------------------------------------
INSERT INTO `task_comments` 
(`id`, `task_id`, `author_id`, `body`, `mentions`, `edited_at`, `deleted_at`, `created_at`)
VALUES
('15e7110c-234b-59fd-809e-4a62a640e300', '0191f3a2-0050-7050-8050-000000000001', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'Requirements workshop concluded. Signed PRD document received and uploaded to project docs.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('6a12c7b1-d0ec-541d-a1c0-ef628f486dc5', '0191f3a2-0050-7050-8050-000000000002', 'bdfc3878-0bd8-4373-b30e-c614117f3a73', 'Wireframes complete in Figma with responsive component system ready for review.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('1db58b48-3e8c-5e6e-b599-009dbdfda20c', '0191f3a2-0050-7050-8050-000000000003', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'Client feedback incorporated on dark theme contrast. Final verbal sign-off received, pending written acceptance note.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('f3cabc1a-5233-53df-b8db-dcb09f261f98', '0191f3a2-0050-7050-8050-000000000004', '49d177e8-01ba-422d-8e0c-a6311bd55fd3', 'Homepage layout scaffolded, integrating navigation and hero banner components.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('0e4826ab-5357-56b5-97d2-d5abcc8c58ad', '0191f3a2-0050-7050-8050-000000000005', '0ccb34fa-6833-4fc8-88d7-4af504d8ba51', 'FastAPI CMS endpoints created and tested via Swagger UI - database models verified.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('b4e32250-5d96-5c65-b1de-b5470c4daa55', '0191f3a2-0050-7050-8050-000000000006', '4da6a393-b958-4495-b7aa-c59aee120c24', 'Queued: awaiting completion of homepage and CMS integration.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('9fbab59d-92ba-5941-85c7-c9555690e126', '0191f3a2-0050-7050-8050-000000000007', 'f7156971-c056-4491-a721-5e97f404ba78', 'Ready for assignment once testing log is compiled.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('2b0e83f0-56a1-5252-80b6-26366394716f', '0191f3a2-0050-7050-8050-000000000008', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'Staging environment provisioned on demo cluster.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('fe0f91fe-d42f-530e-b6dd-22c6bf0ec152', '0191f3a2-0050-7050-8050-000000000009', 'd851ffcf-5ea5-4c69-9a3e-96a8cdac06db', 'Deployment pipeline configured, waiting for UAT milestone gate.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('33b9a508-4f50-5aaf-97d6-cfb7d6604328', '0191f3a2-0050-7050-8050-000000000010', '31f3a10d-68f2-41c8-8cf5-13db5a9aa4ab', 'Operations handover template prepared.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('466a802a-f7c4-5d8e-94e6-4bf3473046d4', '0191f3a2-0060-7060-8060-000000000001', '505f1422-c51e-41ce-aeee-6cb18ae4830a', 'Target keyword list identified with high commercial intent and favorable search volume.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('b9aa5cb2-4e3a-55cc-8d38-b11cad75a05a', '0191f3a2-0060-7060-8060-000000000002', '177fca7c-b35b-43d4-adf8-0ff787322e96', 'Core meta titles and descriptions populated for main landing sections.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('a78399ca-9f30-51f0-9130-fb2961c67e5b', '0191f3a2-0060-7060-8060-000000000003', '48985bb5-8b9f-4331-9a23-4317e5b0a6ad', '3 pillar blog posts drafted and submitted for editorial review.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('6db9a21a-abbd-5301-8095-4327d8c5af12', '0191f3a2-0060-7060-8060-000000000004', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'Ad account permissions configured. Awaiting content and SEO sign-off.', NULL, NULL, NULL, '2026-10-27 08:55:05'),
('6d95ef48-35d9-5ba0-a69d-0e745002cc08', '0191f3a2-0060-7060-8060-000000000005', 'd3e4a37c-29a3-44ae-badd-027701b2fd38', 'Analytics dashboard template connected to demo data source.', NULL, NULL, NULL, '2026-10-27 08:55:05')
ON DUPLICATE KEY UPDATE `body`=VALUES(`body`);
