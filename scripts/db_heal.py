import os
import sqlite3
import shutil

def heal_database():
    # 路径配置
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "edumatrix.db")
    backup_dir = os.path.join(base_dir, "data", "backups")
    backup_path = os.path.join(backup_dir, "edumatrix_safe_backup.db")

    # 强制建立备份目录
    os.makedirs(backup_dir, exist_ok=True)

    print("=" * 60)
    print("      EduMatrix Database Integrity Guard & Auto-Heal")
    print("=" * 60)
    print("[STATUS] Running 0.05s fast diagnosis on SQLite database...")

    # 1. 临时死锁防线：如果后端服务还没启动，先静默清理残留的 WAL 锁文件，释放任何残留死锁
    wal_file = db_path + "-wal"
    shm_file = db_path + "-shm"
    
    # 2. 数据库完整性校验 (PRAGMA integrity_check)
    db_is_healthy = False
    if os.path.exists(db_path):
        try:
            # 尝试连接数据库并运行完整性检查
            conn = sqlite3.connect(db_path, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0] == "ok":
                db_is_healthy = True
                print("[HEALTH] Database integrity check: OK")
            else:
                print(f"[WARNING] Integrity check failed: {result}")
        except Exception as e:
            print(f"[ERROR] Database is corrupted or locked: {e}")
    else:
        print("[STATUS] Database does not exist yet. Uvicorn will seed it on startup.")
        db_is_healthy = True  # 允许后端在初次启动时自动创建表

    # 3. 终极自愈逻辑 (The Self-Healing Defense)
    if db_is_healthy:
        # 如果当前数据库极其健康，且文件存在，自动生成一个最新的“冷备份”
        if os.path.exists(db_path):
            try:
                shutil.copy2(db_path, backup_path)
                print(f"[BACKUP] Safe cold backup successfully updated at: {os.path.basename(backup_path)}")
            except Exception as e:
                print(f"[WARNING] Failed to update cold backup: {e}")
    else:
        # ⚠️ 只有当数据库发生致命崩溃、完全打不开、或校验失败时，才启动“用备份强制覆盖自愈”
        print("\n\033[31m[CRITICAL] DATABASE CORRUPTION DETECTED!\033[0m")
        if os.path.exists(backup_path):
            print("[HEAL] Found healthy cold backup. Initiating 0.1s recovery...")
            try:
                # 先安全清理残留的锁文件
                if os.path.exists(wal_file): os.remove(wal_file)
                if os.path.exists(shm_file): os.remove(shm_file)
                
                # 覆盖还原
                shutil.copy2(backup_path, db_path)
                print("\033[32m[SUCCESS] Database successfully restored to the latest healthy backup!\033[0m")
            except Exception as e:
                print(f"[FATAL ERROR] Restore failed: {e}")
        else:
            print("[FATAL ERROR] No safe backup found! Removing corrupted database to allow seeding...")
            try:
                if os.path.exists(db_path): os.remove(db_path)
                if os.path.exists(wal_file): os.remove(wal_file)
                if os.path.exists(shm_file): os.remove(shm_file)
                print("[HEAL] Corrupted database wiped. System will auto-seed standard course tables on startup.")
            except Exception as e:
                print(f"[FATAL ERROR] Clean wipe failed: {e}")

    print("=" * 60)

if __name__ == "__main__":
    heal_database()
