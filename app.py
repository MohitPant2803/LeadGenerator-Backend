import os
import threading
import logging
import json
from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS
from lead_gen_agent.config import DB_PATH, log_format, logger
from lead_gen_agent.storage import init_db, get_connection
from lead_gen_agent.pipeline import run_pipeline, pipeline_cancel_event

app = Flask(__name__)
CORS(app)

# Thread-safe log accumulator
class InMemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = []
        self.lock = threading.RLock()

    def emit(self, record):
        try:
            log_entry = self.format(record)
            with self.lock:
                self.logs.append(log_entry)
        except Exception:
            self.handleError(record)

    def get_new_logs(self, start_index):
        with self.lock:
            if start_index < len(self.logs):
                return self.logs[start_index:], len(self.logs)
            return [], len(self.logs)

    def clear(self):
        with self.lock:
            self.logs.clear()

# Initialize and register the in-memory log handler
log_handler = InMemoryLogHandler()
log_handler.setFormatter(logging.Formatter(log_format))
# Add to the lead_gen_agent logger to capture all module logs
logging.getLogger("lead_gen_agent").addHandler(log_handler)

# Global variables for pipeline status tracking
pipeline_status = "idle"  # "idle", "running", "completed", "failed"
pipeline_lock = threading.Lock()
active_thread = None

def bg_pipeline_runner(niche, location, limit, force):
    global pipeline_status, active_thread
    logger.info(f"Background thread started: niche='{niche}', location='{location}', limit={limit}, force={force}")
    try:
        run_pipeline(niche=niche, location=location, limit=limit, force=force)
        with pipeline_lock:
            if threading.current_thread() == active_thread:
                if pipeline_cancel_event.is_set():
                    pipeline_status = "idle"
                else:
                    pipeline_status = "completed"
        logger.info("Background pipeline execution completed successfully.")
    except Exception as e:
        logger.error(f"Background pipeline execution failed: {e}")
        with pipeline_lock:
            if threading.current_thread() == active_thread:
                pipeline_status = "failed"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/run", methods=["POST"])
def run_agent():
    global pipeline_status, active_thread
    
    # Check if pipeline is running, cancel if so
    is_running = False
    with pipeline_lock:
        if pipeline_status == "running" or (active_thread and active_thread.is_alive()):
            is_running = True
            
    if is_running:
        logger.info("A pipeline is already running. Triggering cancellation...")
        pipeline_cancel_event.set()
        if active_thread:
            active_thread.join(timeout=5.0)
            
    # Clear the cancel event so the new run can proceed without being cancelled
    pipeline_cancel_event.clear()
    
    with pipeline_lock:
        pipeline_status = "running"
        
    # Clear logs for a fresh run
    log_handler.clear()
    
    # Parse inputs
    data = request.json or {}
    niche = data.get("niche", "").strip()
    location = data.get("location", "").strip()
    limit = int(data.get("limit", 10))
    force = bool(data.get("force", False))
    
    if not niche or not location:
        with pipeline_lock:
            pipeline_status = "idle"
        return jsonify({"status": "error", "message": "Niche and Location are required fields."}), 400
        
    # Start thread
    active_thread = threading.Thread(
        target=bg_pipeline_runner,
        args=(niche, location, limit, force),
        daemon=True
    )
    active_thread.start()
    
    return jsonify({"status": "success", "message": "Pipeline started successfully."})

@app.route("/api/cancel", methods=["POST"])
def cancel_pipeline():
    logger.info("Pipeline cancellation requested by user via API.")
    pipeline_cancel_event.set()
    return jsonify({"status": "success", "message": "Pipeline cancellation requested."})

@app.route("/api/status", methods=["GET"])
def get_status():
    last_seen = int(request.args.get("last_index", 0))
    new_logs, current_length = log_handler.get_new_logs(last_seen)
    
    return jsonify({
        "status": pipeline_status,
        "logs": new_logs,
        "last_index": current_length
    })

def get_spelling_suggestions(niche):
    valid_keys = [
        "restaurant", "restaurants", "cafe", "cafes", "bar", "bars",
        "dentist", "dentists", "doctor", "doctors", "hotel", "hotels",
        "gym", "gyms", "salon", "salons", "spa", "spas", "plumber",
        "plumbers", "locksmith", "locksmiths", "school", "schools",
        "office", "offices", "bank", "banks", "grocery", "groceries",
        "supermarket", "supermarkets", "bakery", "bakeries", "pharmacy",
        "pharmacies", "hospital", "hospitals", "mechanic", "car repair"
    ]
    
    def levenshtein(s1, s2):
        if len(s1) < len(s2):
            return levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]

    suggestions = []
    for key in valid_keys:
        dist = levenshtein(niche.lower(), key)
        if dist <= 2:
            suggestions.append(key)
    return suggestions

@app.route("/api/leads", methods=["GET"])
def get_leads():
    niche = request.args.get("niche", "").strip().lower()
    location = request.args.get("location", "").strip().lower()
    
    try:
        conn = get_connection(DB_PATH)
        cursor = conn.cursor()
        
        if niche and location:
            cursor.execute(
                "SELECT * FROM leads WHERE LOWER(niche) = ? AND LOWER(location) = ? ORDER BY score ASC, name ASC",
                (niche, location)
            )
        elif niche:
            cursor.execute(
                "SELECT * FROM leads WHERE LOWER(niche) = ? ORDER BY score ASC, name ASC",
                (niche,)
            )
        elif location:
            cursor.execute(
                "SELECT * FROM leads WHERE LOWER(location) = ? ORDER BY score ASC, name ASC",
                (location,)
            )
        else:
            cursor.execute("SELECT * FROM leads ORDER BY score ASC, name ASC")
            
        rows = cursor.fetchall()
        conn.close()
        
        leads_list = []
        for r in rows:
            lead = dict(r)
            # Parse emails JSON
            try:
                lead["emails"] = json.loads(lead["emails"]) if lead["emails"] else []
            except Exception:
                lead["emails"] = []
            leads_list.append(lead)
            
        reason = None
        suggestions = []
        
        if not leads_list and niche and location:
            # Check geocoding first
            try:
                from lead_gen_agent.discovery import geocode_location
                from lead_gen_agent.config import GEOAPIFY_API_KEY
                geocode_location(location, GEOAPIFY_API_KEY)
                location_ok = True
            except Exception:
                location_ok = False
                reason = f"We couldn't resolve the location '{location}'. Please check your spelling."
                
            if location_ok:
                from lead_gen_agent.discovery import NICHE_TO_CATEGORY
                niche_clean = niche.strip().lower()
                is_recognized = (
                    niche_clean in NICHE_TO_CATEGORY or 
                    "." in niche_clean or 
                    "," in niche_clean
                )
                
                spelling_suggestions = get_spelling_suggestions(niche_clean)
                if spelling_suggestions:
                    suggestions = spelling_suggestions
                    reason = f"No businesses found for '{niche}' in '{location}'. Did you mean to search for: {', '.join(spelling_suggestions)}?"
                elif not is_recognized:
                    reason = f"The niche '{niche}' is not a recognized category. We tried searching for businesses with '{niche}' in their name near '{location}', but found 0 results."
                    suggestions = ["grocery", "restaurant", "dentist", "plumber", "salon"]
                else:
                    reason = f"No businesses matching the category '{niche}' found within 10km of '{location}'."
                    suggestions = []
            
        return jsonify({
            "status": "success",
            "leads": leads_list,
            "reason": reason,
            "suggestions": suggestions
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/download_excel", methods=["GET"])
def download_excel():
    niche = request.args.get("niche", "").strip().lower()
    location = request.args.get("location", "").strip().lower()
    
    try:
        import io
        conn = get_connection(DB_PATH)
        cursor = conn.cursor()
        
        if niche and location:
            cursor.execute(
                "SELECT * FROM leads WHERE LOWER(niche) = ? AND LOWER(location) = ? ORDER BY score ASC, name ASC",
                (niche, location)
            )
        elif niche:
            cursor.execute(
                "SELECT * FROM leads WHERE LOWER(niche) = ? ORDER BY score ASC, name ASC",
                (niche,)
            )
        elif location:
            cursor.execute(
                "SELECT * FROM leads WHERE LOWER(location) = ? ORDER BY score ASC, name ASC",
                (location,)
            )
        else:
            cursor.execute("SELECT * FROM leads ORDER BY score ASC, name ASC")
            
        rows = cursor.fetchall()
        conn.close()
        
        try:
            import pandas as pd
            data_dicts = [dict(r) for r in rows]
            
            for d in data_dicts:
                try:
                    if d.get("emails"):
                        d["emails"] = ", ".join(json.loads(d["emails"]))
                except Exception:
                    pass
            
            df = pd.DataFrame(data_dicts)
            cols_order = ["score", "name", "address", "phone", "website", "emails", 
                          "has_ssl", "has_title", "has_description", "has_robots", 
                          "has_sitemap", "has_google_analytics", "pagespeed_score", 
                          "email_draft", "status", "created_at", "updated_at"]
            existing_cols = [c for c in cols_order if c in df.columns]
            if existing_cols:
                df = df[existing_cols]
                
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Leads')
            output.seek(0)
            
            return send_file(
                output,
                as_attachment=True,
                download_name="leads.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as pe:
            logger.warning(f"Pandas excel export failed: {pe}. Falling back to CSV.")
            import csv
            output = io.StringIO()
            writer = csv.writer(output)
            
            if rows:
                headers = list(rows[0].keys())
                writer.writerow(headers)
                for r in rows:
                    row_data = list(r)
                    try:
                        if row_data[5]:
                            row_data[5] = ", ".join(json.loads(row_data[5]))
                    except Exception:
                        pass
                    writer.writerow(row_data)
            
            mem = io.BytesIO()
            mem.write(output.getvalue().encode('utf-8-sig'))
            mem.seek(0)
            
            return send_file(
                mem,
                as_attachment=True,
                download_name="leads.csv",
                mimetype="text/csv"
            )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    init_db()
    logger.info("Starting Flask web server on port 5001...")
    app.run(host="0.0.0.0", port=5001, debug=False)
