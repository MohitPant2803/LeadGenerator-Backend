import sqlite3
import json
from datetime import datetime
from lead_gen_agent.config import DB_PATH, logger

def get_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=DB_PATH):
    logger.info(f"Initializing database at {db_path}...")
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            place_id TEXT PRIMARY KEY,
            name TEXT,
            address TEXT,
            phone TEXT,
            website TEXT,
            emails TEXT, -- JSON array of strings
            has_ssl INTEGER,
            has_title INTEGER,
            has_description INTEGER,
            has_robots INTEGER,
            has_sitemap INTEGER,
            has_google_analytics INTEGER,
            pagespeed_score INTEGER,
            score REAL,
            email_draft TEXT,
            status TEXT DEFAULT 'discovered', -- 'discovered', 'processed', 'failed'
            created_at TEXT,
            updated_at TEXT,
            niche TEXT,
            location TEXT
        )
    """)
    
    # Check if niche column exists (for upgrading existing database)
    cursor.execute("PRAGMA table_info(leads)")
    columns = [row[1] for row in cursor.fetchall()]
    if "niche" not in columns:
        try:
            cursor.execute("ALTER TABLE leads ADD COLUMN niche TEXT")
            cursor.execute("ALTER TABLE leads ADD COLUMN location TEXT")
            logger.info("Upgraded database schema with niche and location columns.")
        except Exception as e:
            logger.warning(f"Failed to add niche/location columns: {e}")
            
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

def save_discovered_leads(leads_list, niche=None, location=None, db_path=DB_PATH):
    if not leads_list:
        return
    
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    
    saved_count = 0
    for lead in leads_list:
        place_id = lead.get("place_id")
        name = lead.get("name")
        address = lead.get("address")
        phone = lead.get("phone")
        website = lead.get("website")
        
        # INSERT or UPDATE conflict
        cursor.execute("""
            INSERT INTO leads (
                place_id, name, address, phone, website, status, created_at, updated_at, niche, location
            ) VALUES (?, ?, ?, ?, ?, 'discovered', ?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                niche = excluded.niche,
                location = excluded.location,
                updated_at = excluded.updated_at
        """, (place_id, name, address, phone, website, now_str, now_str, niche, location))
        if cursor.rowcount > 0:
            saved_count += 1
            
    conn.commit()
    conn.close()
    if saved_count > 0:
        logger.info(f"Saved/Updated {saved_count} discovered leads in the database.")
    else:
        logger.info("No new leads were added.")

def get_leads_for_processing(db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_lead(place_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_lead(place_id, update_dict, db_path=DB_PATH):
    if not update_dict:
        return
    
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Build SET clause dynamically
    set_clauses = []
    values = []
    for key, val in update_dict.items():
        # Handle emails list by converting to JSON string
        if key == "emails" and isinstance(val, list):
            val = json.dumps(val)
        set_clauses.append(f"{key} = ?")
        values.append(val)
        
    set_clauses.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    
    values.append(place_id)
    
    set_clause_str = ", ".join(set_clauses)
    query = f"UPDATE leads SET {set_clause_str} WHERE place_id = ?"
    
    cursor.execute(query, tuple(values))
    conn.commit()
    conn.close()
    logger.debug(f"Updated lead {place_id} with data: {update_dict}")

def is_lead_processed(place_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM leads WHERE place_id = ?", (place_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row["status"] == "processed":
        return True
    return False
