# backend/migrate_recovery.py - Add recovery_code column to existing database
import sqlite3
import os

DB_PATH = "./data/zampos.db"

def add_recovery_column():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if column already exists
    cursor.execute("PRAGMA table_info(merchants)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'recovery_code' in columns:
        print("✅ recovery_code column already exists")
        conn.close()
        return True
    
    # Add the column
    try:
        cursor.execute("ALTER TABLE merchants ADD COLUMN recovery_code TEXT")
        conn.commit()
        print("✅ Added recovery_code column to merchants table")
    except Exception as e:
        print(f"❌ Error adding column: {e}")
        conn.close()
        return False
    
    # Create index for faster lookups
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_merchants_recovery ON merchants(recovery_code)")
        conn.commit()
        print("✅ Created index on recovery_code")
    except Exception as e:
        print(f"⚠️ Could not create index: {e}")
    
    conn.close()
    return True

if __name__ == "__main__":
    print("🔧 ZamPOS Recovery Code Migration")
    print("=" * 40)
    add_recovery_column()
    print("\n✅ Migration complete. Restart your backend:")
    print("   python main.py")