import sqlite3
import os

# 获取数据库路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edumatrix.db")

# 连接到数据库
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

try:
    # 检查并添加缺失的列
    # 添加 major 列
    cursor.execute("ALTER TABLE student_profiles ADD COLUMN major TEXT DEFAULT ''")
    print("Added 'major' column")
    
    # 添加 favorites 列
    cursor.execute("ALTER TABLE student_profiles ADD COLUMN favorites TEXT DEFAULT '[]'")
    print("Added 'favorites' column")
    
    # 添加 knowledge_traces· 列
    cursor.execute("ALTER TABLE student_profiles ADD COLUMN knowledge_traces TEXT DEFAULT '{}'")
    print("Added 'knowledge_traces' column")
    
    # 添加 profile_evidence 列
    cursor.execute("ALTER TABLE student_profiles ADD COLUMN profile_evidence TEXT DEFAULT '[]'")
    print("Added 'profile_evidence' column")
    
    conn.commit()
    print("All columns added successfully!")
    
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print(f"Column already exists: {e}")
    else:
        raise
finally:
    conn.close()
