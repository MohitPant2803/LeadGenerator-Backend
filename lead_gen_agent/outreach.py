import google.generativeai as genai
from groq import Groq
from lead_gen_agent.config import GEMINI_API_KEY, GROQ_API_KEY, logger

def get_top_issues(audit_results: dict):
    """Sorts audit results by severity and returns descriptions of the top 2 issues."""
    issues = []
    
    # 1. SSL (Severity: 20)
    if not audit_results.get("has_ssl", False):
        issues.append((20.0, "lacks a secure SSL certificate (HTTPS)"))
        
    # 2. PageSpeed mobile performance (Severity: up to 35 depending on score)
    ps_score = audit_results.get("pagespeed_score")
    if ps_score is not None and ps_score < 70:
        ps_weight = 35.0 * (1.0 - (float(ps_score) / 100.0))
        issues.append((ps_weight, f"has a slow mobile page speed score of {ps_score}/100"))
        
    # 3. Google Analytics (Severity: 10)
    if not audit_results.get("has_google_analytics", False):
        issues.append((10.0, "lacks Google Analytics tracking to monitor visitor traffic"))
        
    # 4. Meta title & description (Severity: 7.5 each)
    if not audit_results.get("has_title", False):
        issues.append((7.5, "is missing an SEO meta title tag"))
    if not audit_results.get("has_description", False):
        issues.append((7.5, "is missing an SEO meta description tag"))
        
    # 5. Robots / Sitemap (Severity: 5.0 each)
    if not audit_results.get("has_robots", False):
        issues.append((5.0, "is missing a robots.txt file"))
    if not audit_results.get("has_sitemap", False):
        issues.append((5.0, "is missing a sitemap.xml file"))
        
    # Sort issues by severity weight (descending)
    issues.sort(key=lambda x: x[0], reverse=True)
    
    # Extract only the description string for top 2
    top_issues = [issue[1] for issue in issues[:2]]
    return top_issues

def get_default_outreach_email(business_name, website, top_issues):
    """Fallback static template email when LLM calls fail."""
    issues_phrase = "could benefit from some minor performance and SEO optimizations"
    if top_issues:
        if len(top_issues) == 2:
            issues_phrase = f"lacks some critical optimizations: it {top_issues[0]} and {top_issues[1]}"
        else:
            issues_phrase = f"lacks a critical optimization: it {top_issues[0]}"
            
    return f"Subject: Quick question about {business_name}'s website\n\n" \
           f"Hi team at {business_name},\n\n" \
           f"I was looking at your website ({website}) and noticed that it {issues_phrase}.\n\n" \
           f"We specialize in helping local businesses fix these exact performance and SEO issues. " \
           f"Are you open to a quick 5-minute chat next week to see how we can help you improve this?\n\n" \
           f"Best regards,\n" \
           f"Web Optimization Team"

def generate_cold_email(business_name: str, website: str, audit_results: dict) -> str:
    """Generates a short cold email targeting the top 2 issues, using Gemini with Groq fallback."""
    try:
        from lead_gen_agent.pipeline import pipeline_cancel_event
        if pipeline_cancel_event.is_set():
            logger.info("Pipeline cancellation requested. Skipping cold email generation.")
            return "Pipeline execution cancelled."
    except ImportError:
        pass

    top_issues = get_top_issues(audit_results)
    
    if top_issues:
        if len(top_issues) == 2:
            issues_phrase = f"lacks some critical optimizations: it {top_issues[0]} and {top_issues[1]}"
        else:
            issues_phrase = f"lacks a critical optimization: it {top_issues[0]}"
    else:
        issues_phrase = "could benefit from some minor performance and SEO optimizations"
        
    # Single-paragraph, token-optimized prompt
    prompt = (
        f"Write a short, friendly, and professional cold email (under 100 words) from 'Web Optimization Team' "
        f"to {business_name} (website: {website}) pointing out that their site {issues_phrase}. "
        f"Briefly explain why this hurts them and suggest a quick 5-minute call next week to fix it. "
        f"Write only the email with a subject line. Do not write placeholders like '[Your Name]' or '[My Name]'."
    )
    
    # 1. Try Gemini
    if GEMINI_API_KEY:
        try:
            logger.info("Generating email using primary model (gemini-2.5-flash)...")
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(
                prompt
            )
            email_text = response.text.strip()
            if email_text:
                return email_text
        except Exception as e:
            logger.warning(f"Gemini API generation failed or rate limited: {e}")
            
    # 2. Fallback to Groq
    if GROQ_API_KEY:
        try:
            logger.info("Attempting fallback model (llama-3.1-8b-instant) via Groq...")
            client = Groq(api_key=GROQ_API_KEY)
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150
            )
            email_text = response.choices[0].message.content.strip()
            if email_text:
                return email_text
        except Exception as e:
            logger.warning(f"Groq API generation failed: {e}")
            
    # 3. Fallback to static template
    logger.info("Using default template outreach email due to API failures.")
    return get_default_outreach_email(business_name, website, top_issues)
