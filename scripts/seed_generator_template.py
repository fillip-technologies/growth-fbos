#!/usr/bin/env python3
"""
FBOS Seed Data Generator Template
==================================
Generates valid, relational seed data conforming to the FBOS microservices schema.
Exports SQL statements or dict payloads with proper UUIDs, constraints, and valid enums.

Usage:
    python3 scripts/seed_generator_template.py > fbos_demo_seed.sql
"""

import uuid
from datetime import datetime, date, timedelta, timezone

def generate_sql():
    # -------------------------------------------------------------------------
    # 1. Deterministic Identifiers
    # -------------------------------------------------------------------------
    CLIENT_TENANT_ID = uuid.UUID("0191f3a2-0001-7001-8001-000000000001")
    ORG_ID           = uuid.UUID("0191f3a2-0002-7002-8002-000000000002")

    UNIT_DEV_ID      = uuid.UUID("0191f3a2-0010-7010-8010-000000000010")
    UNIT_SALES_ID    = uuid.UUID("0191f3a2-0010-7010-8010-000000000011")

    USER_ADMIN_ID    = uuid.UUID("0191f3a2-0020-7020-8020-000000000020")
    USER_DEV_ID      = uuid.UUID("0191f3a2-0020-7020-8020-000000000021")

    CRM_CLIENT_ID    = uuid.UUID("0191f3a2-0030-7030-8030-000000000030")
    LEAD_ID          = uuid.UUID("0191f3a2-0035-7035-8035-000000000035")
    OPPORTUNITY_ID   = uuid.UUID("0191f3a2-0036-7036-8036-000000000036")

    PROJECT_ID       = uuid.UUID("0191f3a2-0040-7040-8040-000000000040")
    MILESTONE_1_ID   = uuid.UUID("0191f3a2-0045-7045-8045-000000000045")
    MILESTONE_2_ID   = uuid.UUID("0191f3a2-0046-7046-8046-000000000046")

    TASK_1_ID        = uuid.UUID("0191f3a2-0050-7050-8050-000000000050")
    TASK_2_ID        = uuid.UUID("0191f3a2-0051-7051-8051-000000000051")

    # Built-in type UUIDs (matches builtin definitions in 03_delivery/services/builtins.py)
    # Namespace: 5b0c6f0e-3d1a-4c8e-9f27-03de11e7b001
    TYPE_PROJECT_ID  = uuid.uuid5(uuid.UUID("5b0c6f0e-3d1a-4c8e-9f27-03de11e7b001"), "work_unit_type:project")
    TYPE_FEATURE_ID  = uuid.uuid5(uuid.UUID("5b0c6f0e-3d1a-4c8e-9f27-03de11e7b001"), "task_type:feature")
    TYPE_TASK_ID     = uuid.uuid5(uuid.UUID("5b0c6f0e-3d1a-4c8e-9f27-03de11e7b001"), "task_type:task")

    today = date.today()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    sql_statements = []

    # -------------------------------------------------------------------------
    # 2. Identity Service Data
    # -------------------------------------------------------------------------
    sql_statements.append("-- ========================================================")
    sql_statements.append("-- 1. IDENTITY SERVICE (fbos_identity)")
    sql_statements.append("-- ========================================================")
    sql_statements.append("USE `fbos_identity`;\n")

    # Platform Client
    sql_statements.append(f"""INSERT INTO `clients` 
(`id`, `name`, `code`, `contact_email`, `status`, `max_organizations`, `max_users_per_org`, `subscription_start`, `subscription_end`, `created_at`)
VALUES ('{CLIENT_TENANT_ID}', 'Fillip Technologies Pvt Ltd', 'FILLIP', 'contact@fillipsoftware.com', 'active', 5, 100, '{today}', '{today + timedelta(days=365)}', '{now_str}')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # Organization
    sql_statements.append(f"""INSERT INTO `organizations` 
(`id`, `client_id`, `name`, `code`, `base_currency`, `fiscal_year_start`, `timezone`, `status`, `email`, `created_at`)
VALUES ('{ORG_ID}', '{CLIENT_TENANT_ID}', 'Fillip Demo Org', 'FILLIP-DEMO', 'INR', '01-04', 'Asia/Kolkata', 'active', 'ops@fillipsoftware.com', '{now_str}')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # Teams (Org Units)
    sql_statements.append(f"""INSERT INTO `org_units` 
(`id`, `organization_id`, `code`, `name`, `unit_type`, `parent_id`, `path`, `status`, `version`, `created_at`, `updated_at`)
VALUES 
('{UNIT_DEV_ID}', '{ORG_ID}', 'DEV', 'Engineering & Delivery', 'team', NULL, '/{ORG_ID}/{UNIT_DEV_ID}/', 'active', 0, '{now_str}', '{now_str}'),
('{UNIT_SALES_ID}', '{ORG_ID}', 'SALES', 'Sales & Commercial', 'team', NULL, '/{ORG_ID}/{UNIT_SALES_ID}/', 'active', 0, '{now_str}', '{now_str}')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # Users
    sql_statements.append(f"""INSERT INTO `users` 
(`id`, `organization_id`, `home_unit_id`, `name`, `email`, `employee_code`, `user_type`, `status`, `version`, `created_at`)
VALUES 
('{USER_ADMIN_ID}', '{ORG_ID}', '{UNIT_DEV_ID}', 'Ayush Admin', 'ayush.admin@fillip.test', 'EMP001', 'internal', 'active', 0, '{now_str}'),
('{USER_DEV_ID}', '{ORG_ID}', '{UNIT_DEV_ID}', 'Rohan Developer', 'rohan.dev@fillip.test', 'EMP002', 'internal', 'active', 0, '{now_str}')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # -------------------------------------------------------------------------
    # 3. Revenue Service Data
    # -------------------------------------------------------------------------
    sql_statements.append("\n-- ========================================================")
    sql_statements.append("-- 2. REVENUE SERVICE (fbos_revenue)")
    sql_statements.append("-- ========================================================")
    sql_statements.append("USE `fbos_revenue`;\n")

    # CRM Client
    sql_statements.append(f"""INSERT INTO `clients` 
(`id`, `organization_id`, `code`, `name`, `client_type`, `owner_user_id`, `status`, `version`, `created_at`)
VALUES ('{CRM_CLIENT_ID}', '{ORG_ID}', 'CLI-DEMO-001', 'Acme Global Technologies', 'enterprise', '{USER_ADMIN_ID}', 'active', 0, '{now_str}')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # Lead
    sql_statements.append(f"""INSERT INTO `leads` 
(`id`, `organization_id`, `name`, `contact_name`, `contact_email`, `contact_phone`, `company_name`, `source`, `owner_user_id`, `status`, `version`, `created_at`)
VALUES ('{LEAD_ID}', '{ORG_ID}', 'Client Portal Implementation Lead', 'Aarav Sharma', 'aarav@acmeglobal.test', '+91-9876543210', 'Acme Global Technologies', 'website', '{USER_ADMIN_ID}', 'qualified', 0, '{now_str}')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # Opportunity
    sql_statements.append(f"""INSERT INTO `opportunities` 
(`id`, `organization_id`, `client_id`, `lead_id`, `name`, `status`, `probability`, `expected_value`, `currency`, `owner_user_id`, `version`)
VALUES ('{OPPORTUNITY_ID}', '{ORG_ID}', '{CRM_CLIENT_ID}', '{LEAD_ID}', 'Client Portal Contract', 'proposal', 75, 450000.00, 'INR', '{USER_ADMIN_ID}', 0)
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # -------------------------------------------------------------------------
    # 4. Delivery Service Data
    # -------------------------------------------------------------------------
    sql_statements.append("\n-- ========================================================")
    sql_statements.append("-- 3. DELIVERY SERVICE (fbos_delivery)")
    sql_statements.append("-- ========================================================")
    sql_statements.append("USE `fbos_delivery`;\n")

    # Work Unit (Project)
    sql_statements.append(f"""INSERT INTO `work_units` 
(`id`, `organization_id`, `code`, `name`, `objective`, `work_unit_type_id`, `client_id`, `owning_unit_id`, `manager_user_id`, `planned_start`, `planned_end`, `status`, `priority`, `billable`, `currency`, `progress_pct`, `health`, `version`, `created_at`, `updated_at`)
VALUES ('{PROJECT_ID}', '{ORG_ID}', 'PRJ-PORTAL-01', 'Client Portal Implementation', 'Develop customer-facing portal and API integrations', '{TYPE_PROJECT_ID}', '{CRM_CLIENT_ID}', '{UNIT_DEV_ID}', '{USER_ADMIN_ID}', '{today}', '{today + timedelta(days=60)}', 'in_progress', 'high', 1, 'INR', 25.00, 'green', 0, '{now_str}', '{now_str}')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # Milestones
    sql_statements.append(f"""INSERT INTO `milestones` 
(`id`, `work_unit_id`, `code`, `name`, `seq`, `weight`, `planned_date`, `is_billing_milestone`, `requires_client_acceptance`, `status`)
VALUES 
('{MILESTONE_1_ID}', '{PROJECT_ID}', 'MS-01', 'Functional Architecture & Wireframes', 1, 30.00, '{today + timedelta(days=15)}', 1, 1, 'accepted'),
('{MILESTONE_2_ID}', '{PROJECT_ID}', 'MS-02', 'MVP Core Implementation', 2, 70.00, '{today + timedelta(days=45)}', 1, 1, 'pending')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`);""")

    # Tasks
    sql_statements.append(f"""INSERT INTO `tasks` 
(`id`, `organization_id`, `code`, `title`, `description`, `work_unit_id`, `task_type_id`, `owning_unit_id`, `assignee_user_id`, `priority`, `status`, `source`, `estimate_minutes`, `logged_minutes`, `progress_pct`, `review_round`, `version`, `created_at`, `updated_at`)
VALUES 
('{TASK_1_ID}', '{ORG_ID}', 'TSK-PORTAL-101', 'Build Authentication & RBAC', 'Integrate JWT auth with Identity service endpoints', '{PROJECT_ID}', '{TYPE_FEATURE_ID}', '{UNIT_DEV_ID}', '{USER_DEV_ID}', 'p1', 'done', 'manual', 360, 360, 100, 0, 0, '{now_str}', '{now_str}'),
('{TASK_2_ID}', '{ORG_ID}', 'TSK-PORTAL-102', 'Implement Client Dashboard API', 'Deliver aggregated metrics route for the portal landing screen', '{PROJECT_ID}', '{TYPE_FEATURE_ID}', '{UNIT_DEV_ID}', '{USER_DEV_ID}', 'p2', 'in_progress', 'manual', 480, 180, 40, 0, 0, '{now_str}', '{now_str}')
ON DUPLICATE KEY UPDATE `title`=VALUES(`title`);""")

    # Task Dependency (TASK_2 depends on TASK_1)
    sql_statements.append(f"""INSERT INTO `task_dependencies` 
(`task_id`, `depends_on_task_id`, `dependency_type`)
VALUES ('{TASK_2_ID}', '{TASK_1_ID}', 'finish_to_start')
ON DUPLICATE KEY UPDATE `dependency_type`=VALUES(`dependency_type`);""")

    return "\n".join(sql_statements)

if __name__ == "__main__":
    print(generate_sql())
