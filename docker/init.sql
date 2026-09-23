-- -----------------------------------------------------------------------------
-- FBOS Microservices: Docker MySQL 10-Database Initialization
-- Automatically executed on container first boot from /docker-entrypoint-initdb.d
-- -----------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS fbos_identity CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_revenue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_delivery CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_control CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_documents CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_communication CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_insight CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS fbos_assets CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Grant privileges to the user created by environment variables
GRANT ALL PRIVILEGES ON `fbos\_%`.* TO 'fbos_user'@'%';
GRANT ALL PRIVILEGES ON `fbos`.* TO 'fbos_user'@'%';

FLUSH PRIVILEGES;
