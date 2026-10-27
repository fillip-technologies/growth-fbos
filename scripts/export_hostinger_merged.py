#!/usr/bin/env python3
"""
FBOS Microservices - Hostinger Database Dump & Merge Script
============================================================
Safely exports all 9 FBOS microservice databases from Hostinger MySQL (READ-ONLY)
and merges them into consolidated SQL file(s).

Usage:
    python3 scripts/export_hostinger_merged.py
"""

import os
import sys
import time
import subprocess
from datetime import datetime, timezone

HOST = "srv1276.hstgr.io"
PORT = 3306

SERVICES = [
    {
        "id": "01_identity",
        "name": "Identity Service",
        "hostinger_user": "u516064072_identity_fbos",
        "hostinger_db": "u516064072_identity_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_identity",
    },
    {
        "id": "02_revenue",
        "name": "Revenue Service",
        "hostinger_user": "u516064072_revenue_fbos",
        "hostinger_db": "u516064072_revenue_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_revenue",
    },
    {
        "id": "03_delivery",
        "name": "Delivery Service",
        "hostinger_user": "u516064072_delivery_fbos",
        "hostinger_db": "u516064072_delivery_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_delivery",
    },
    {
        "id": "04_control",
        "name": "Control Service",
        "hostinger_user": "u516064072_control_fbos",
        "hostinger_db": "u516064072_control_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_control",
    },
    {
        "id": "05_documents",
        "name": "Documents Service",
        "hostinger_user": "u516064072_documents_fbos",
        "hostinger_db": "u516064072_documents_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_documents",
    },
    {
        "id": "06_communication",
        "name": "Communication Service",
        "hostinger_user": "u516064072_communi_fbos",
        "hostinger_db": "u516064072_communi_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_communication",
    },
    {
        "id": "07_management",
        "name": "Management Service",
        "hostinger_user": "u516064072_manage_fbos",
        "hostinger_db": "u516064072_manage_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_management",
    },
    {
        "id": "08_insight",
        "name": "Insight Service",
        "hostinger_user": "u516064072_insight_fbos",
        "hostinger_db": "u516064072_insight_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_insight",
    },
    {
        "id": "09_assets",
        "name": "Assets Service",
        "hostinger_user": "u516064072_assets_fbos",
        "hostinger_db": "u516064072_assets_fbos",
        "password": "N^9LVnD38q",
        "standard_db": "fbos_assets",
    },
]

HEADER_TEMPLATE = """-- =============================================================================
-- FBOS MICROSERVICES CONSOLIDATED DATABASE DUMP
-- =============================================================================
-- Cluster Host:       {host}:{port}
-- Extraction Time:    {timestamp}
-- Mode:               Full Schema + Data Dump (READ-ONLY source)
-- Database Scheme:    {naming_mode}
--
-- Included Microservices ({num_services} total):
{service_index}
-- Compatibility:
--   - MySQL 8.0+ / MariaDB 10.5+
--   - Foreign key checks and unique checks disabled during import
--   - Character Set: utf8mb4 / Collation: utf8mb4_unicode_ci
-- =============================================================================

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*M!100616 SET @OLD_NOTE_VERBOSITY=@@NOTE_VERBOSITY, NOTE_VERBOSITY=0 */;

"""

FOOTER_TEMPLATE = """
-- =============================================================================
-- END OF CONSOLIDATED DUMP
-- Restoring environment settings...
-- =============================================================================

/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;
/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*M!100616 SET NOTE_VERBOSITY=@OLD_NOTE_VERBOSITY */;

-- Dump completed on {timestamp}
"""

def dump_service(svc):
    """Run mariadb-dump in read-only mode for a service."""
    cmd = [
        "mariadb-dump",
        "-h", HOST,
        "-P", str(PORT),
        "-u", svc["hostinger_user"],
        f"-p{svc['password']}",
        "--single-transaction",
        "--quick",
        "--skip-lock-tables",
        "--routines",
        "--triggers",
        "--hex-blob",
        "--default-character-set=utf8mb4",
        svc["hostinger_db"],
    ]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0
    if res.returncode != 0:
        raise RuntimeError(f"mariadb-dump failed for {svc['id']}: {res.stderr}")
    return res.stdout, elapsed

def get_stats(svc):
    """Retrieve table count and approximate row count using read-only queries."""
    query = f"""
    SELECT COUNT(*), COALESCE(SUM(TABLE_ROWS), 0)
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = '{svc["hostinger_db"]}' AND TABLE_TYPE = 'BASE TABLE';
    """
    cmd = [
        "mariadb",
        "-h", HOST,
        "-P", str(PORT),
        "-u", svc["hostinger_user"],
        f"-p{svc['password']}",
        "-sN",
        "-e", query,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        parts = res.stdout.strip().split("\t")
        return int(parts[0]), int(parts[1])
    return 0, 0

def clean_dump_body(raw_dump):
    """
    Strip redundant server-level SET/RESTORE blocks from individual dumps,
    leaving clean DDL and DML statements.
    """
    lines = raw_dump.splitlines()
    cleaned = []
    skip_prefixes = (
        "/*M!999999\\- enable the sandbox mode */",
        "/*!40101 SET @OLD_CHARACTER_SET_CLIENT",
        "/*!40101 SET @OLD_CHARACTER_SET_RESULTS",
        "/*!40101 SET @OLD_COLLATION_CONNECTION",
        "/*!40101 SET NAMES",
        "/*!40103 SET @OLD_TIME_ZONE",
        "/*!40103 SET TIME_ZONE",
        "/*!40014 SET @OLD_UNIQUE_CHECKS",
        "/*!40014 SET @OLD_FOREIGN_KEY_CHECKS",
        "/*!40101 SET @OLD_SQL_MODE",
        "/*M!100616 SET @OLD_NOTE_VERBOSITY",
        "/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE",
        "/*!40101 SET SQL_MODE=@OLD_SQL_MODE",
        "/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS",
        "/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS",
        "/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT",
        "/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS",
        "/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION",
        "/*M!100616 SET NOTE_VERBOSITY=@OLD_NOTE_VERBOSITY",
        "-- Dump completed on",
    )
    for line in lines:
        if any(line.startswith(prefix) for prefix in skip_prefixes):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_standard_path = os.path.join(base_dir, "fbos_services_merged.sql")
    out_hostinger_path = os.path.join(base_dir, "fbos_services_hostinger_names_merged.sql")

    print(f"============================================================")
    print(f"🚀 FBOS Hostinger Database Merger (Read-Only Dump)")
    print(f"Source: {HOST}:{PORT}")
    print(f"Target files:")
    print(f"  1. {out_standard_path} (Standard FBOS names: fbos_*)")
    print(f"  2. {out_hostinger_path} (Hostinger names: u516064072_*)")
    print(f"============================================================")

    dump_data = []
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    for idx, svc in enumerate(SERVICES, 1):
        print(f"[{idx}/{len(SERVICES)}] Fetching stats & dumping {svc['id']} ({svc['name']})...", end="", flush=True)
        tables, rows = get_stats(svc)
        raw_body, elapsed = dump_service(svc)
        clean_body = clean_dump_body(raw_body)
        size_kb = len(clean_body.encode("utf-8")) / 1024
        dump_data.append({
            "svc": svc,
            "tables": tables,
            "rows": rows,
            "body": clean_body,
            "size_kb": size_kb,
            "elapsed": elapsed,
        })
        print(f" Done! ({tables} tables, ~{rows} rows, {size_kb:.1f} KB in {elapsed:.1f}s)")

    # Build Service Index comment
    index_lines = []
    for d in dump_data:
        s = d["svc"]
        index_lines.append(
            f"--   - {s['id']:<17} : {d['tables']:>2} tables, ~{d['rows']:>5} rows | "
            f"Hostinger: {s['hostinger_db']} -> Target: {s['standard_db']}"
        )
    service_index_str = "\n".join(index_lines)

    # Write Standard Names Version
    with open(out_standard_path, "w", encoding="utf-8") as f_std:
        f_std.write(HEADER_TEMPLATE.format(
            host=HOST,
            port=PORT,
            timestamp=now_str,
            naming_mode="Standard FBOS Microservice Names (fbos_*)",
            num_services=len(SERVICES),
            service_index=service_index_str,
        ))

        for d in dump_data:
            s = d["svc"]
            db_name = s["standard_db"]
            section_header = f"""
-- =============================================================================
-- DATABASE: {db_name}
-- Service:          {s['id']} ({s['name']})
-- Remote Source:    {s['hostinger_db']} @ {HOST}
-- Structure:        {d['tables']} tables, approx {d['rows']} rows
-- =============================================================================

CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `{db_name}`;

"""
            f_std.write(section_header)
            f_std.write(d["body"])
            f_std.write("\n\n")

        f_std.write(FOOTER_TEMPLATE.format(timestamp=now_str))

    # Write Hostinger Names Version
    with open(out_hostinger_path, "w", encoding="utf-8") as f_hst:
        f_hst.write(HEADER_TEMPLATE.format(
            host=HOST,
            port=PORT,
            timestamp=now_str,
            naming_mode="Hostinger Remote Database Names (u516064072_*)",
            num_services=len(SERVICES),
            service_index=service_index_str,
        ))

        for d in dump_data:
            s = d["svc"]
            db_name = s["hostinger_db"]
            section_header = f"""
-- =============================================================================
-- DATABASE: {db_name}
-- Service:          {s['id']} ({s['name']})
-- Remote Source:    {s['hostinger_db']} @ {HOST}
-- Structure:        {d['tables']} tables, approx {d['rows']} rows
-- =============================================================================

CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `{db_name}`;

"""
            f_hst.write(section_header)
            f_hst.write(d["body"])
            f_hst.write("\n\n")

        f_hst.write(FOOTER_TEMPLATE.format(timestamp=now_str))

    std_size_mb = os.path.getsize(out_standard_path) / (1024 * 1024)
    hst_size_mb = os.path.getsize(out_hostinger_path) / (1024 * 1024)

    print("\n" + "=" * 60)
    print("✨ Successfully generated merged SQL files:")
    print(f"  • Standard FBOS:     {out_standard_path} ({std_size_mb:.2f} MB)")
    print(f"  • Hostinger Names:   {out_hostinger_path} ({hst_size_mb:.2f} MB)")
    print("=" * 60)

if __name__ == "__main__":
    main()
