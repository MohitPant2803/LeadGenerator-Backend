import argparse
import sys
from lead_gen_agent.config import logger, GEOAPIFY_API_KEY
from lead_gen_agent.storage import (
    init_db,
    save_discovered_leads,
    get_lead,
    update_lead,
    is_lead_processed
)
from lead_gen_agent.discovery import discover_businesses
from lead_gen_agent.enrichment import enrich_business_website
from lead_gen_agent.analysis import analyze_website
from lead_gen_agent.scoring import calculate_lead_score
from lead_gen_agent.outreach import generate_cold_email

import threading
pipeline_cancel_event = threading.Event()

def run_pipeline(niche: str, location: str, limit: int, force: bool):
    logger.info("=" * 60)
    logger.info(f"Starting Lead Gen Pipeline: Niche='{niche}', Location='{location}', Limit={limit}, Force={force}")
    logger.info("=" * 60)
    
    # Reset cancellation event at start of run
    pipeline_cancel_event.clear()
    
    # 1. Initialize SQLite Database
    init_db()
    
    # 2. Run Lead Discovery (Geoapify Places API)
    discovery_limit = max(limit * 5, 50)
    try:
        discovered_leads = discover_businesses(niche, location, limit=discovery_limit)
    except Exception as e:
        logger.error(f"Discovery step failed critically: {e}")
        sys.exit(1)
        
    if not discovered_leads:
        logger.warning("No leads discovered. Exiting pipeline.")
        return
        
    # 3. Save discovered leads to DB (INSERT or UPDATE conflict)
    save_discovered_leads(discovered_leads, niche=niche, location=location)
    
    # 4. Process each lead
    processed_count = 0
    skipped_count = 0
    failed_count = 0
    
    for item in discovered_leads:
        if pipeline_cancel_event.is_set():
            logger.info("Pipeline cancellation requested. Aborting execution loop.")
            break
            
        place_id = item["place_id"]
        business_name = item["name"]
        
        logger.info("-" * 50)
        logger.info(f"Processing Lead: {business_name} (ID: {place_id})")
        
        # Caching check: skip already processed leads unless --force is set
        if is_lead_processed(place_id) and not force:
            logger.info(f"Lead '{business_name}' is already processed (caching hit). Skipping.")
            skipped_count += 1
            processed_count += 1
            if processed_count >= limit:
                logger.info(f"Reached requested limit of {limit} valid leads (including caching hits). Ending loop.")
                break
            continue
            
        # Retrieve the lead from DB to get the website stored (in case it differs or contains extra info)
        lead_data = get_lead(place_id)
        if not lead_data:
            logger.warning(f"Could not find lead data in database for {business_name}. Skipping.")
            continue
            
        website = lead_data.get("website")
        if not website:
            logger.warning(f"Lead '{business_name}' has no website. Discarding.")
            update_lead(place_id, {"status": "discarded"})
            continue
            
        # Wrap all network / scraping / API calls in try/except so one failure doesn't halt the pipeline
        try:
            # A. Enrichment (fetch homepage + contact + about, extract emails)
            logger.info(f"[{business_name}] Step 1: Web Enrichment (Extracting emails)...")
            emails = []
            try:
                emails = enrich_business_website(website, business_name=business_name)
            except Exception as e:
                logger.error(f"[{business_name}] Enrichment failed: {e}")
                # We continue with empty email list rather than crashing
                
            # B. Technical & SEO Analysis (meta tags, SSL, robots, sitemap, GA, PageSpeed)
            logger.info(f"[{business_name}] Step 2: Running SEO & Tech Audits...")
            audit_results = {
                "dns_failed": False,
                "has_ssl": False,
                "has_title": False,
                "has_description": False,
                "has_robots": False,
                "has_sitemap": False,
                "has_google_analytics": False,
                "pagespeed_score": None
            }
            try:
                audit_results = analyze_website(website)
            except Exception as e:
                logger.error(f"[{business_name}] SEO/Tech analysis failed: {e}")
                
            if audit_results.get("dns_failed"):
                logger.warning(f"[{business_name}] Website DNS resolution failed. Discarding lead.")
                update_lead(place_id, {"status": "discarded"})
                continue
                
            # C. Scoring
            logger.info(f"[{business_name}] Step 3: Scoring lead...")
            score = 0.0
            try:
                score = calculate_lead_score(audit_results)
            except Exception as e:
                logger.error(f"[{business_name}] Scoring failed: {e}")
                
            # D. Outreach Email Generation
            logger.info(f"[{business_name}] Step 4: Generating cold outreach draft...")
            email_draft = ""
            try:
                email_draft = generate_cold_email(business_name, website, audit_results)
            except Exception as e:
                logger.error(f"[{business_name}] Email generation failed: {e}")
                email_draft = "Failed to generate outreach email due to LLM error."
                
            # E. Update database record with final details and mark status as 'processed'
            update_data = {
                "emails": emails,
                "has_ssl": 1 if audit_results["has_ssl"] else 0,
                "has_title": 1 if audit_results["has_title"] else 0,
                "has_description": 1 if audit_results["has_description"] else 0,
                "has_robots": 1 if audit_results["has_robots"] else 0,
                "has_sitemap": 1 if audit_results["has_sitemap"] else 0,
                "has_google_analytics": 1 if audit_results["has_google_analytics"] else 0,
                "pagespeed_score": audit_results["pagespeed_score"],
                "score": score,
                "email_draft": email_draft,
                "status": "processed"
            }
            update_lead(place_id, update_data)
            logger.info(f"[{business_name}] Lead processed successfully. Prioritization Score: {score}/100.0")
            processed_count += 1
            
            if processed_count >= limit:
                logger.info(f"Reached requested limit of {limit} valid leads. Ending loop.")
                break
            
        except Exception as e:
            logger.error(f"[{business_name}] Unexpected critical error during processing: {e}")
            update_lead(place_id, {"status": "failed"})
            failed_count += 1
            
    logger.info("=" * 60)
    logger.info("Pipeline Execution Summary:")
    logger.info(f"  Processed (valid): {processed_count}")
    logger.info(f"  Skipped (cached): {skipped_count}")
    logger.info(f"  Failed: {failed_count}")
    logger.info("=" * 60)

def main():
    parser = argparse.ArgumentParser(description="Lead Generation and SEO Audit Agent")
    parser.add_argument("--niche", required=True, help="Niche of local businesses (e.g. 'restaurants', 'dentists', or direct category)")
    parser.add_argument("--location", required=True, help="City and State/Country (e.g. 'Seattle, WA')")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of leads to fetch (default: 10)")
    parser.add_argument("--force", action="store_true", help="Force refresh and re-run analysis/outreach on existing leads")
    
    args = parser.parse_args()
    
    run_pipeline(
        niche=args.niche,
        location=args.location,
        limit=args.limit,
        force=args.force
    )

if __name__ == "__main__":
    main()
