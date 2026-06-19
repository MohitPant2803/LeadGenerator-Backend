from lead_gen_agent.config import logger

def calculate_lead_score(audit_results: dict) -> float:
    """
    Calculates a lead prioritization score from 0.0 to 100.0.
    Lower score represents a higher priority lead (more issues / better opportunity).
    
    Rubric:
    - Base: 100 points
    - No SSL: -20 points
    - Missing Meta Title: -7.5 points
    - Missing Meta Description: -7.5 points
    - Missing Robots.txt: -5.0 points
    - Missing Sitemap.xml: -5.0 points
    - No Google Analytics: -10.0 points
    - PageSpeed Mobile Score: deduction of 35 * (1 - (score / 100)).
      If unavailable, defaults to -17.5 points.
    """
    score = 100.0
    
    # 1. SSL Penalty
    if not audit_results.get("has_ssl", False):
        score -= 20.0
        
    # 2. Meta Tags Penalties
    if not audit_results.get("has_title", False):
        score -= 7.5
    if not audit_results.get("has_description", False):
        score -= 7.5
        
    # 3. Robots / Sitemap Penalties
    if not audit_results.get("has_robots", False):
        score -= 5.0
    if not audit_results.get("has_sitemap", False):
        score -= 5.0
        
    # 4. Google Analytics Penalty
    if not audit_results.get("has_google_analytics", False):
        score -= 10.0
        
    # 5. PageSpeed Performance Score
    ps_score = audit_results.get("pagespeed_score")
    if ps_score is not None:
        # Scale deduction from 0 (if 100) to 35 (if 0)
        deduction = 35.0 * (1.0 - (float(ps_score) / 100.0))
        score -= deduction
    else:
        # Default middle-ground deduction if speed test fails
        score -= 17.5
        
    # Clamp score between 0.0 and 100.0
    final_score = max(0.0, min(100.0, score))
    final_score = round(final_score, 2)
    
    logger.info(f"Calculated lead score: {final_score}/100.0 based on audit: {audit_results}")
    return final_score
