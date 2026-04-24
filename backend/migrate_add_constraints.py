# backend/migrate_add_constraints.py — Migration script to add unique constraints to existing database
"""
Migration script to add UNIQUE constraints to existing merchants table.
This script:
1. Checks for existing duplicates
2. Creates a backup of the database
3. Adds UNIQUE constraints for phone_number and shop_name
4. Verifies the migration was successful

Run this script BEFORE starting the backend after updating to v2.2+
"""

import sqlite3
import os
import shutil
from datetime import datetime

DB_PATH = os.getenv("DATABASE_PATH", "./data/zampos.db")
BACKUP_PATH = None


def print_header(message: str):
    """Print a formatted header"""
    print("\n" + "=" * 60)
    print(f"  {message}")
    print("=" * 60)


def print_success(message: str):
    """Print a success message"""
    print(f"✅ {message}")


def print_error(message: str):
    """Print an error message"""
    print(f"❌ {message}")


def print_warning(message: str):
    """Print a warning message"""
    print(f"⚠️ {message}")


def print_info(message: str):
    """Print an info message"""
    print(f"📌 {message}")


def backup_database():
    """Create a backup of the database before migration"""
    global BACKUP_PATH
    
    if not os.path.exists(DB_PATH):
        print_warning(f"Database not found at {DB_PATH}")
        return False
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_PATH = f"{DB_PATH}.backup_{timestamp}"
    
    try:
        shutil.copy2(DB_PATH, BACKUP_PATH)
        print_success(f"Database backed up to: {BACKUP_PATH}")
        return True
    except Exception as e:
        print_error(f"Failed to create backup: {e}")
        return False


def check_existing_duplicates():
    """Check for existing duplicate phone numbers or shop names"""
    print_header("Checking for Existing Duplicates")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check for duplicate phone numbers
        cursor.execute("""
            SELECT phone_number, COUNT(*) as count, GROUP_CONCAT(id) as ids
            FROM merchants 
            GROUP BY phone_number 
            HAVING COUNT(*) > 1
        """)
        dup_phones = cursor.fetchall()
        
        if dup_phones:
            print_warning("Found duplicate phone numbers:")
            for phone, count, ids in dup_phones:
                print(f"   📞 {phone}: {count} times (merchant IDs: {ids})")
        else:
            print_success("No duplicate phone numbers found")
        
        # Check for duplicate shop names
        cursor.execute("""
            SELECT shop_name, COUNT(*) as count, GROUP_CONCAT(id) as ids
            FROM merchants 
            GROUP BY shop_name 
            HAVING COUNT(*) > 1
        """)
        dup_names = cursor.fetchall()
        
        if dup_names:
            print_warning("Found duplicate shop names:")
            for name, count, ids in dup_names:
                print(f"   🏪 '{name}': {count} times (merchant IDs: {ids})")
        else:
            print_success("No duplicate shop names found")
        
        conn.close()
        
        return len(dup_phones) == 0 and len(dup_names) == 0
        
    except Exception as e:
        print_error(f"Error checking duplicates: {e}")
        return False


def fix_duplicates_interactive():
    """Interactive duplicate resolution"""
    print_header("Duplicate Resolution")
    print_warning("Duplicates found! You have the following options:")
    print("   1. Keep the first merchant and delete duplicates")
    print("   2. Keep the most recent merchant and delete others")
    print("   3. Keep the merchant with highest balance and delete others")
    print("   4. Manually resolve (exit and fix manually)")
    print("   5. Abort migration (keep database as-is)")
    
    choice = input("\nEnter your choice (1-5): ").strip()
    
    if choice == "5":
        print_info("Migration aborted. No changes made to database.")
        return False
    elif choice == "4":
        print_info("Please manually resolve duplicates and run this script again.")
        print_info("You can use: sqlite3 zampos.db")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get all merchants with their IDs and balances
        cursor.execute("""
            SELECT id, shop_name, phone_number, custodial_balance_sats, created_at
            FROM merchants
            ORDER BY id
        """)
        all_merchants = cursor.fetchall()
        
        # Group by phone number to find duplicates
        phone_groups = {}
        for merchant in all_merchants:
            phone = merchant[2]
            if phone not in phone_groups:
                phone_groups[phone] = []
            phone_groups[phone].append(merchant)
        
        merchants_to_delete = []
        merchants_to_keep = []
        
        for phone, merchants in phone_groups.items():
            if len(merchants) <= 1:
                merchants_to_keep.extend(merchants)
                continue
            
            # Found duplicates for this phone
            print_info(f"\nResolving duplicates for phone: {phone}")
            for m in merchants:
                print(f"   ID: {m[0]}, Shop: '{m[1]}', Balance: {m[3]} sats, Created: {m[4]}")
            
            if choice == "1":  # Keep first (lowest ID)
                keep = min(merchants, key=lambda x: x[0])
            elif choice == "2":  # Keep most recent
                keep = max(merchants, key=lambda x: x[4])
            elif choice == "3":  # Keep highest balance
                keep = max(merchants, key=lambda x: x[3])
            else:
                keep = merchants[0]  # Default to first
            
            for m in merchants:
                if m[0] == keep[0]:
                    merchants_to_keep.append(m)
                    print(f"   ✅ Keeping merchant ID {m[0]}")
                else:
                    merchants_to_delete.append(m)
                    print(f"   ❌ Will delete merchant ID {m[0]}")
        
        # Confirm deletion
        if merchants_to_delete:
            print_warning(f"\nWill delete {len(merchants_to_delete)} duplicate merchant(s):")
            for m in merchants_to_delete:
                print(f"   - ID {m[0]}: '{m[1]}' ({m[2]})")
            
            confirm = input("\nProceed with deletion? (yes/no): ").strip().lower()
            if confirm != "yes":
                print_info("Deletion cancelled. Migration aborted.")
                conn.close()
                return False
            
            # Delete duplicate merchants (cascade will handle related records)
            for m in merchants_to_delete:
                cursor.execute("DELETE FROM merchants WHERE id = ?", (m[0],))
                print(f"   Deleted merchant ID {m[0]}")
            
            conn.commit()
            print_success(f"Deleted {len(merchants_to_delete)} duplicate merchant(s)")
        
        conn.close()
        return True
        
    except Exception as e:
        print_error(f"Error fixing duplicates: {e}")
        return False


def add_unique_constraints():
    """Add UNIQUE constraints to the merchants table"""
    print_header("Adding UNIQUE Constraints")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if constraints already exist
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND name IN ('idx_unique_phone', 'idx_unique_shop_name')
        """)
        existing_indexes = cursor.fetchall()
        
        if len(existing_indexes) >= 2:
            print_success("UNIQUE constraints already exist")
            conn.close()
            return True
        
        # Add unique constraint for phone_number
        try:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_phone ON merchants(phone_number)")
            print_success("Added UNIQUE constraint for phone_number")
        except sqlite3.OperationalError as e:
            if "duplicate" in str(e).lower():
                print_error("Cannot add UNIQUE constraint: duplicate phone numbers exist")
                return False
            raise e
        
        # Add unique constraint for shop_name
        try:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_shop_name ON merchants(shop_name)")
            print_success("Added UNIQUE constraint for shop_name")
        except sqlite3.OperationalError as e:
            if "duplicate" in str(e).lower():
                print_error("Cannot add UNIQUE constraint: duplicate shop names exist")
                return False
            raise e
        
        conn.commit()
        conn.close()
        
        return True
        
    except Exception as e:
        print_error(f"Error adding constraints: {e}")
        return False


def verify_migration():
    """Verify that constraints were added successfully"""
    print_header("Verifying Migration")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check indexes
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND name IN ('idx_unique_phone', 'idx_unique_shop_name')
        """)
        indexes = cursor.fetchall()
        
        if len(indexes) == 2:
            print_success("Both UNIQUE constraints are present")
        else:
            print_warning(f"Found {len(indexes)} of 2 expected constraints")
        
        # Test unique constraint by attempting to insert duplicate
        cursor.execute("SELECT COUNT(*) FROM merchants")
        count = cursor.fetchone()[0]
        
        if count > 0:
            # Get a sample merchant
            cursor.execute("SELECT shop_name, phone_number FROM merchants LIMIT 1")
            sample = cursor.fetchone()
            
            if sample:
                print_info(f"Testing with sample: shop='{sample[0]}', phone='{sample[1]}'")
                
                # This should fail if constraints work
                try:
                    cursor.execute(
                        "INSERT INTO merchants (shop_name, phone_number, payout_mode) VALUES (?, ?, 'direct')",
                        (sample[0], sample[1])
                    )
                    conn.rollback()
                    print_error("UNIQUE constraint test FAILED - duplicates would be allowed!")
                except sqlite3.IntegrityError:
                    print_success("UNIQUE constraint test PASSED - duplicates blocked")
        
        conn.close()
        return len(indexes) == 2
        
    except Exception as e:
        print_error(f"Verification failed: {e}")
        return False


def restore_backup():
    """Restore database from backup"""
    if BACKUP_PATH and os.path.exists(BACKUP_PATH):
        try:
            shutil.copy2(BACKUP_PATH, DB_PATH)
            print_success(f"Restored database from backup: {BACKUP_PATH}")
            return True
        except Exception as e:
            print_error(f"Failed to restore backup: {e}")
            return False
    return False


def main():
    """Main migration function"""
    print_header("ZamPOS Database Migration")
    print_info(f"Database path: {DB_PATH}")
    print_info(f"Python version: {sqlite3.sqlite_version}")
    
    # Check if database exists
    if not os.path.exists(DB_PATH):
        print_error(f"Database not found at {DB_PATH}")
        print_info("Creating new database with constraints...")
        # Database will be created with correct schema on next backend start
        print_success("Run 'python main.py' to create new database with constraints")
        return
    
    # Create backup
    if not backup_database():
        print_error("Backup failed. Aborting migration.")
        return
    
    # Check for duplicates
    has_no_duplicates = check_existing_duplicates()
    
    if not has_no_duplicates:
        print_warning("Duplicates detected! They must be resolved before adding constraints.")
        
        # Fix duplicates interactively
        if not fix_duplicates_interactive():
            print_warning("Migration cancelled. Database unchanged.")
            return
        
        # Re-check duplicates after fixing
        has_no_duplicates = check_existing_duplicates()
        
        if not has_no_duplicates:
            print_error("Duplicates still exist after attempted fix.")
            print_info("You can restore backup and try manual resolution:")
            print_info(f"  cp {BACKUP_PATH} {DB_PATH}")
            return
    
    # Add unique constraints
    if add_unique_constraints():
        # Verify migration
        if verify_migration():
            print_header("Migration Complete!")
            print_success("Database migration successful!")
            print_info("Unique constraints now enforce:")
            print_info("  - No duplicate phone numbers")
            print_info("  - No duplicate shop names")
            print_info("\nYou can now restart your backend:")
            print_info("  python main.py")
        else:
            print_error("Migration verification failed!")
            print_info(f"You can restore backup: cp {BACKUP_PATH} {DB_PATH}")
    else:
        print_error("Failed to add constraints!")
        print_info(f"You can restore backup: cp {BACKUP_PATH} {DB_PATH}")


if __name__ == "__main__":
    main()