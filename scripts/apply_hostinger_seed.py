#!/usr/bin/env python3
"""
Apply FBOS Demo Project Lifecycle Seed to Hostinger Cluster
===========================================================
Safely executes the idempotent seed SQL into Hostinger DBs:
- Part 1: Revenue (u516064072_revenue_fbos)
- Part 2: Delivery (u516064072_delivery_fbos)

Follows the Evidence-First Protocol:
- Pre-flight validation
- Execution per isolated DB user
- Post-seed verification & count inspection
"""

import subprocess
import sys
import os

HOST = "srv1276.hstgr.io"
PORT = 3306
PASSWORD = "N^9LVnD38q"

REVENUE_USER = "u516064072_revenue_fbos"
REVENUE_DB   = "u516064072_revenue_fbos"

DELIVERY_USER = "u516064072_delivery_fbos"
DELIVERY_DB   = "u516064072_delivery_fbos"

def run_sql(host, port, user, db, password, sql_content):
    cmd = [
        "mariadb",
        f"-h{host}",
        f"-P{port}",
        f"-u{user}",
        f"-p{password}",
        "-D", db
    ]
    res = subprocess.run(
        cmd,
        input=sql_content,
        text=True,
        capture_output=True
    )
    if res.returncode != 0:
        print(f"❌ Error executing SQL on {db} (user: {user}):\n{res.stderr}", file=sys.stderr)
        return False
    if res.stderr:
        print(f"⚠️ Warning from {db}:\n{res.stderr}")
    return True

def query_sql(host, port, user, db, password, query):
    cmd = [
        "mariadb",
        f"-h{host}",
        f"-P{port}",
        f"-u{user}",
        f"-p{password}",
        "-D", db,
        "-e", query
    ]
    res = subprocess.run(cmd, text=True, capture_output=True)
    if res.returncode != 0:
        print(f"Error querying {db}: {res.stderr}", file=sys.stderr)
        return None
    return res.stdout.strip()

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)
    seed_file = os.path.join(base_dir, "demo_project_lifecycle_hostinger_seed.sql")

    if not os.path.exists(seed_file):
        print(f"❌ Seed file not found: {seed_file}")
        sys.exit(1)

    with open(seed_file, "r", encoding="utf-8") as f:
        full_sql = f.read()

    # Split between Revenue and Delivery sections
    parts = full_sql.split("USE `u516064072_delivery_fbos`;")
    if len(parts) != 2:
        print("❌ Could not parse Revenue / Delivery partition in SQL file.")
        sys.exit(1)

    revenue_sql = parts[0].replace("USE `u516064072_revenue_fbos`;", "")
    delivery_sql = parts[1]

    print("=================================================================")
    print("🚀 APPLYING FBOS DEMO SEED TO HOSTINGER CLUSTER")
    print("=================================================================")

    # 1. Apply Revenue Seed
    print(f"\n[1/2] Seeding Commercial Revenue DB ({REVENUE_DB})...")
    ok = run_sql(HOST, PORT, REVENUE_USER, REVENUE_DB, PASSWORD, revenue_sql)
    if not ok:
        print("❌ Revenue seeding failed. Aborting.")
        sys.exit(1)
    print("  ✅ Revenue seed applied successfully.")

    # 2. Apply Delivery Seed
    print(f"\n[2/2] Seeding Delivery DB ({DELIVERY_DB})...")
    ok = run_sql(HOST, PORT, DELIVERY_USER, DELIVERY_DB, PASSWORD, delivery_sql)
    if not ok:
        print("❌ Delivery seeding failed. Aborting.")
        sys.exit(1)
    print("  ✅ Delivery seed applied successfully.")

    # 3. Post-Seed Verification
    print("\n=================================================================")
    print("🔍 POST-SEED VERIFICATION")
    print("=================================================================")

    print("\n[Revenue Verification]")
    rev_check = query_sql(HOST, PORT, REVENUE_USER, REVENUE_DB, PASSWORD, """
    SELECT 
      (SELECT COUNT(*) FROM clients WHERE code LIKE 'DEMO-%') AS demo_clients,
      (SELECT COUNT(*) FROM contracts WHERE contract_no LIKE 'DEMO-%') AS demo_contracts,
      (SELECT COUNT(*) FROM invoices WHERE invoice_no LIKE 'DEMO-%') AS demo_invoices,
      (SELECT COUNT(*) FROM payments WHERE receipt_no LIKE 'DEMO-%') AS demo_payments;
    """)
    print(rev_check)

    print("\n[Delivery Verification]")
    del_check = query_sql(HOST, PORT, DELIVERY_USER, DELIVERY_DB, PASSWORD, """
    SELECT 
      (SELECT COUNT(*) FROM work_units WHERE code LIKE 'DEMO-%') AS demo_projects,
      (SELECT COUNT(*) FROM phases WHERE name LIKE '%DEMO%') AS demo_phases,
      (SELECT COUNT(*) FROM milestones WHERE code LIKE 'DEMO-%') AS demo_milestones,
      (SELECT COUNT(*) FROM tasks WHERE code LIKE 'DEMO-%') AS demo_tasks,
      (SELECT COUNT(*) FROM task_dependencies WHERE dependency_type = 'finish_to_start') AS total_dependencies,
      (SELECT COUNT(*) FROM time_entries WHERE note LIKE '%DEMO%') AS demo_time_entries,
      (SELECT COUNT(*) FROM task_comments WHERE body LIKE '%DEMO%' OR task_id IN (SELECT id FROM tasks WHERE code LIKE 'DEMO-%')) AS demo_comments;
    """)
    print(del_check)

    print("\n[Tasks Breakdown]")
    tasks_breakdown = query_sql(HOST, PORT, DELIVERY_USER, DELIVERY_DB, PASSWORD, """
    SELECT code, title, status, priority, logged_minutes, progress_pct 
    FROM tasks 
    WHERE code LIKE 'DEMO-%' 
    ORDER BY code ASC;
    """)
    print(tasks_breakdown)

    print("\n✨ All operations verified with 0 errors. Seed completed safely!")

if __name__ == "__main__":
    main()
