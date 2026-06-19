import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import urllib3
from lead_gen_agent.config import PAGESPEED_API_KEY, logger, safe_requests_get

# Disable SSL warnings for cases where we check invalid/missing SSL certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def check_ssl(domain: str) -> bool:
    """Attempts to connect to the domain via HTTPS. Returns True if valid SSL, False otherwise."""
    url = f"https://{domain}"
    try:
        # verify=True is key: this forces requests to validate the SSL certificate
        response = safe_requests_get(url, headers={"User-Agent": USER_AGENT}, timeout=8, verify=True)
        return True
    except requests.exceptions.SSLError:
        logger.debug(f"SSL handshake failed for {url}")
        return False
    except Exception as e:
        logger.debug(f"HTTPS connection failed for {url}: {e}")
        return False

def check_robots_and_sitemap(base_url: str):
    """Checks if robots.txt and sitemap.xml exist at the root of the site. Returns (has_robots, has_sitemap)."""
    has_robots = False
    has_sitemap = False
    
    robots_url = urljoin(base_url, "/robots.txt")
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    
    headers = {"User-Agent": USER_AGENT}
    
    # Check robots.txt
    try:
        r = safe_requests_get(robots_url, headers=headers, timeout=5, verify=False)
        if r.status_code == 200:
            has_robots = True
    except Exception as e:
        logger.debug(f"Error checking robots.txt: {e}")
        
    # Check sitemap.xml
    try:
        r = safe_requests_get(sitemap_url, headers=headers, timeout=5, verify=False)
        if r.status_code == 200:
            has_sitemap = True
    except Exception as e:
        logger.debug(f"Error checking sitemap.xml: {e}")
        
    return has_robots, has_sitemap

def check_meta_tags(html_content: str):
    """Checks if title and meta description exist and are non-empty. Returns (has_title, has_desc)."""
    if not html_content:
        return False, False
        
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Check Title
    has_title = False
    title_tag = soup.find('title')
    if title_tag and title_tag.get_text().strip():
        has_title = True
        
    # Check Meta Description
    has_desc = False
    desc_tag = soup.find('meta', attrs={'name': lambda x: x and x.lower() == 'description'})
    if desc_tag and desc_tag.get('content', '').strip():
        has_desc = True
        
    return has_title, has_desc

def check_google_analytics(html_content: str) -> bool:
    """Checks if Google Analytics is present in the HTML page content."""
    if not html_content:
        return False
        
    # GA markers
    ga_patterns = [
        "gtag.js",
        "analytics.js",
        "googletagmanager.com/gtag/js",
        "googletagmanager.com/gtm.js",
        "UA-",
        "G-"
    ]
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Check all script tags (src and text)
    for script in soup.find_all('script'):
        src = script.get('src', '')
        if any(pat in src for pat in ga_patterns):
            return True
            
        script_text = script.get_text()
        if any(pat in script_text for pat in ga_patterns):
            return True
            
    # 2. Check raw html text just in case it is embedded elsewhere
    if any(pat in html_content for pat in ga_patterns):
         return True
         
    return False

def get_pagespeed_data(url: str):
    """Queries PageSpeed Insights API for performance score and SEO audits."""
    try:
        from lead_gen_agent.pipeline import pipeline_cancel_event
        if pipeline_cancel_event.is_set():
            logger.info("Pipeline cancellation requested. Skipping PageSpeed request.")
            return None, {"has_title": None, "has_description": None, "has_robots": None}
    except ImportError:
        pass

    logger.info(f"Requesting PageSpeed Insights for: {url}...")
    api_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = [
        ("url", url),
        ("strategy", "mobile"),
        ("category", "performance"),
        ("category", "seo")
    ]
    if PAGESPEED_API_KEY:
        params.append(("key", PAGESPEED_API_KEY))
        
    pagespeed_score = None
    seo_audits = {
        "has_title": None,
        "has_description": None,
        "has_robots": None
    }
    
    try:
        response = safe_requests_get(api_url, params=params, timeout=12)
        if response.status_code == 200:
            data = response.json()
            # Extract score
            categories = data.get("lighthouseResult", {}).get("categories", {})
            performance = categories.get("performance", {})
            score = performance.get("score")
            if score is not None:
                pagespeed_score = int(score * 100)
                
            # Extract SEO audits
            audits = data.get("lighthouseResult", {}).get("audits", {})
            
            title_audit = audits.get("document-title")
            if title_audit and title_audit.get("score") is not None:
                seo_audits["has_title"] = (title_audit.get("score") == 1)
                
            desc_audit = audits.get("meta-description")
            if desc_audit and desc_audit.get("score") is not None:
                seo_audits["has_description"] = (desc_audit.get("score") == 1)
                
            robots_audit = audits.get("robots-txt")
            if robots_audit and robots_audit.get("score") is not None:
                seo_audits["has_robots"] = (robots_audit.get("score") == 1)
                
            logger.info(f"PageSpeed mobile performance score for {url}: {pagespeed_score}/100. Fallback SEO audits parsed successfully.")
        else:
            logger.warning(f"PageSpeed API returned status code {response.status_code}: {response.text}")
    except requests.exceptions.Timeout:
        logger.warning(f"PageSpeed Insights API request timed out (12s limit) for {url}. Proceeding with fallback score (None).")
    except Exception as e:
        logger.warning(f"Error calling PageSpeed API for {url}: {e}")
         
    return pagespeed_score, seo_audits

def analyze_website(website_url: str):
    """Runs all SEO and technical audits for the website. Returns a dict of audit results."""
    if not website_url:
        return {
            "has_ssl": False,
            "has_title": False,
            "has_description": False,
            "has_robots": False,
            "has_sitemap": False,
            "has_google_analytics": False,
            "pagespeed_score": None
        }
        
    if not website_url.startswith("http://") and not website_url.startswith("https://"):
        website_url = "http://" + website_url
        
    parsed = urlparse(website_url)
    domain = parsed.netloc
    base_url = f"{parsed.scheme}://{domain}"
    
    logger.info(f"Running technical audit for {website_url}...")
    
    # 1. Fetch homepage content
    html_content = ""
    direct_fetch_success = False
    dns_failed = False
    try:
        resp = safe_requests_get(website_url, headers={"User-Agent": USER_AGENT}, timeout=10, verify=False)
        if resp.status_code == 200:
            html_content = resp.text
            base_url = resp.url # Update base URL if there was redirect
            domain = urlparse(base_url).netloc
            direct_fetch_success = True
    except requests.exceptions.ConnectionError as ce:
        err_msg = str(ce)
        if "NameResolutionError" in err_msg or "gaierror" in err_msg or "Failed to resolve" in err_msg:
            logger.warning(f"Domain resolution failed for {website_url}. Skipping further website audits.")
            dns_failed = True
        else:
            logger.warning(f"Could not fetch homepage for analysis on {website_url}: {ce}")
    except Exception as e:
        logger.warning(f"Could not fetch homepage for analysis on {website_url}: {e}")
        
    if dns_failed:
        results = {
            "dns_failed": True,
            "has_ssl": False,
            "has_title": False,
            "has_description": False,
            "has_robots": False,
            "has_sitemap": False,
            "has_google_analytics": False,
            "pagespeed_score": None
        }
        logger.info(f"Audit results for {website_url}: {results}")
        return results
        
    # 2. SSL check
    has_ssl = check_ssl(domain)
    
    # 3. Robots.txt and Sitemap.xml check
    has_robots, has_sitemap = check_robots_and_sitemap(base_url)
    
    # 4. Meta tags check
    has_title, has_description = check_meta_tags(html_content)
    
    # 5. Google Analytics check
    has_google_analytics = check_google_analytics(html_content)
    
    # 6. PageSpeed and Lighthouse check
    pagespeed_score, ps_seo_audits = get_pagespeed_data(base_url)
    
    # If direct fetch failed (e.g. 403), use PageSpeed/Lighthouse SEO audits as fallback
    if not direct_fetch_success and ps_seo_audits:
        logger.info(f"Direct homepage fetch failed for {website_url}. Using PageSpeed/Lighthouse SEO audits as fallback.")
        if ps_seo_audits.get("has_title") is not None:
            has_title = ps_seo_audits["has_title"]
        if ps_seo_audits.get("has_description") is not None:
            has_description = ps_seo_audits["has_description"]
        if ps_seo_audits.get("has_robots") is not None:
            has_robots = ps_seo_audits["has_robots"]
            
    results = {
        "dns_failed": False,
        "has_ssl": has_ssl,
        "has_title": has_title,
        "has_description": has_description,
        "has_robots": has_robots,
        "has_sitemap": has_sitemap,
        "has_google_analytics": has_google_analytics,
        "pagespeed_score": pagespeed_score
    }
    
    logger.info(f"Audit results for {website_url}: {results}")
    return results
