from lead_gen_agent.config import logger

def calculate_lead_score(audit_results: dict) -> float:
    """
    Calculates the number of failed checks (0 to 7).
    7 checks:
    - No SSL
    - Missing Meta Title
    - Missing Meta Description
    - Missing Robots.txt
    - Missing Sitemap.xml
    - No Google Analytics
    - PageSpeed Mobile Score < 80 (or PageSpeed failed)
    """
    issues_count = 0
    
    # 1. SSL
    if not audit_results.get("has_ssl", False):
        issues_count += 1
        
    # 2. Meta Tags
    if not audit_results.get("has_title", False):
        issues_count += 1
    if not audit_results.get("has_description", False):
        issues_count += 1
        
    # 3. Robots / Sitemap
    if not audit_results.get("has_robots", False):
        issues_count += 1
    if not audit_results.get("has_sitemap", False):
        issues_count += 1
        
    # 4. Google Analytics
    if not audit_results.get("has_google_analytics", False):
        issues_count += 1
        
    # 5. PageSpeed Performance Score < 80
    ps_score = audit_results.get("pagespeed_score")
    if ps_score is None or float(ps_score) < 80.0:
        issues_count += 1
        
    final_score = float(issues_count)
    logger.info(f"Calculated optimization gaps: {final_score}/7.0 based on audit: {audit_results}")
    return final_score

