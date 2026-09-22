-- -----------------------------------------------------------------------------
-- FBOS Microservices: Docker MySQL 10-Database Initialization
-- Automatically executed on container first boot from /docker-entrypoint-initdb.d
-- -----------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS fbos_identity CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_revenue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_billing CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_work CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_workflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_task CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_approval CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_doc_notify_audit CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_res_plan_perf CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_asset_analytic CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Grant privileges to the user created by environment variables
GRANT ALL PRIVILEGES ON `fbos\_%`.* TO 'fbos_user'@'%';
GRANT ALL PRIVILEGES ON `fbos`.* TO 'fbos_user'@'%';

FLUSH PRIVILEGES;
