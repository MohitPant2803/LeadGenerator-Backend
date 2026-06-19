import requests
from bs4 import BeautifulSoup
import re
import urllib.robotparser
from urllib.parse import urlparse, urljoin
import time
import random
from lead_gen_agent.config import logger

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

robots_cache = {}

def get_robots_parser(base_url):
    parsed = urlparse(base_url)
    netloc = parsed.netloc
    if netloc in robots_cache:
        return robots_cache[netloc]
        
    robots_url = urljoin(f"{parsed.scheme}://{netloc}", "/robots.txt")
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        # Prevent long hangs on reading robots.txt
        requests_session = requests.Session()
        resp = requests_session.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=5)
        if resp.status_code == 200:
            lines = resp.text.splitlines()
            rp.parse(lines)
        else:
            # If robots.txt doesn't exist, allow all
            rp.allow_all = True
    except Exception as e:
        logger.debug(f"Could not read robots.txt for {netloc}: {e}. Defaulting to allow all.")
        rp.allow_all = True
        
    robots_cache[netloc] = rp
    return rp

def is_allowed(url):
    try:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        rp = get_robots_parser(base_url)
        return rp.can_fetch(USER_AGENT, url)
    except Exception as e:
        logger.debug(f"Error checking robots.txt for {url}: {e}. Defaulting to allow.")
        return True

def fetch_url(url):
    """Fetches a URL with a real User-Agent, random delay, and robots.txt check."""
    try:
        from lead_gen_agent.pipeline import pipeline_cancel_event
        if pipeline_cancel_event.is_set():
            logger.info("Pipeline cancellation requested. Aborting fetch.")
            return None
    except ImportError:
        pass

    if not is_allowed(url):
        logger.warning(f"URL disallowed by robots.txt: {url}")
        return None
        
    # Politeness delay
    delay = random.uniform(1.0, 3.0)
    logger.debug(f"Sleeping for {delay:.2f} seconds before requesting {url}...")
    try:
        from lead_gen_agent.pipeline import pipeline_cancel_event
        if pipeline_cancel_event.wait(timeout=delay):
            logger.info("Pipeline cancellation requested during delay. Aborting fetch.")
            return None
    except ImportError:
        time.sleep(delay)
    
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # Handle redirects and keep track of actual URL
        if response.status_code == 200:
            return response
        else:
            logger.debug(f"Failed to fetch {url}, status code: {response.status_code}")
            return None
    except Exception as e:
        logger.debug(f"Network error fetching {url}: {e}")
        return None

def extract_emails_from_text(text):
    if not text:
        return set()
    # Find all regex matches
    found = EMAIL_REGEX.findall(text)
    emails = set()
    for email in found:
        email_lower = email.lower().strip()
        # Filter out common false positives (e.g. image extensions, placeholder emails)
        if not any(email_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js']):
            emails.add(email_lower)
    return emails

def extract_emails_from_html(html_content, base_url):
    if not html_content:
        return set()
        
    soup = BeautifulSoup(html_content, 'html.parser')
    emails = set()
    
    # 1. Look for mailto links
    for link in soup.find_all('a', href=True):
        href = link['href'].strip()
        if href.lower().startswith('mailto:'):
            email = href[7:].split('?')[0].strip() # strip out query params like ?subject=...
            if EMAIL_REGEX.match(email):
                emails.add(email.lower())
                
    # 2. Extract from page text
    text_emails = extract_emails_from_text(soup.get_text())
    emails.update(text_emails)
    
    return emails

def find_candidate_urls(homepage_html, homepage_url):
    """Parses homepage to find candidate contact/about links."""
    if not homepage_html:
        return set(), set()
        
    soup = BeautifulSoup(homepage_html, 'html.parser')
    contact_candidates = set()
    about_candidates = set()
    
    for link in soup.find_all('a', href=True):
        href = link['href'].strip()
        text = link.get_text().lower()
        href_lower = href.lower()
        
        # Normalize relative link
        full_url = urljoin(homepage_url, href)
        
        # Simple domain checks to avoid leaving the base site
        parsed_home = urlparse(homepage_url)
        parsed_link = urlparse(full_url)
        if parsed_link.netloc != parsed_home.netloc:
            continue
            
        # Detect contact links
        if "contact" in href_lower or "contact" in text or "write-to-us" in href_lower:
            contact_candidates.add(full_url)
            
        # Detect about links
        if "about" in href_lower or "about" in text or "company" in href_lower or "who-we-are" in href_lower:
            about_candidates.add(full_url)
            
    return contact_candidates, about_candidates

def search_email_ddg(query: str):
    """Searches DuckDuckGo HTML interface for email snippets."""
    import urllib.parse
    logger.debug(f"Searching DuckDuckGo for: '{query}'")
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": USER_AGENT
    }
    found_emails = set()
    try:
        # Politeness delay to avoid rate limiting
        try:
            from lead_gen_agent.pipeline import pipeline_cancel_event
            if pipeline_cancel_event.wait(timeout=random.uniform(1.5, 3.0)):
                logger.info("Pipeline cancellation requested during DDG delay. Aborting.")
                return []
        except ImportError:
            time.sleep(random.uniform(1.5, 3.0))
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            snippets = []
            for r in soup.find_all('a', class_='result__snippet'):
                snippets.append(r.get_text())
            for r in soup.find_all('td', class_='result-snippet'):
                snippets.append(r.get_text())
                
            combined_text = "\n".join(snippets)
            matches = EMAIL_REGEX.findall(combined_text)
            for email in matches:
                email_lower = email.lower().strip()
                if not any(email_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js']):
                    found_emails.add(email_lower)
        else:
            logger.debug(f"DuckDuckGo search returned non-200 code: {resp.status_code}")
    except Exception as e:
        logger.debug(f"DuckDuckGo request error: {e}")
    return list(found_emails)

def enrich_business_website(website_url, business_name=None):
    """Performs site-wide crawl of homepage + contact + about to find email addresses."""
    if not website_url:
        return []
        
    # Ensure scheme exists, default to http://
    if not website_url.startswith("http://") and not website_url.startswith("https://"):
        website_url = "http://" + website_url
        
    logger.info(f"Enriching business site: {website_url}...")
    emails = set()
    
    # 1. Fetch Homepage
    resp = fetch_url(website_url)
    if not resp:
        # Try https if http failed or vice versa
        if website_url.startswith("http://"):
            alternative_url = website_url.replace("http://", "https://")
            logger.debug(f"HTTP failed. Trying HTTPS alternative: {alternative_url}")
            resp = fetch_url(alternative_url)
            if resp:
                website_url = alternative_url
                
    if resp:
        homepage_url = resp.url # Actual URL after redirects
        homepage_html = resp.text
        
        # Extract emails from homepage
        homepage_emails = extract_emails_from_html(homepage_html, homepage_url)
        emails.update(homepage_emails)
        logger.debug(f"Found {len(homepage_emails)} emails on homepage.")
        
        # Find candidate contact and about links
        contact_links, about_links = find_candidate_urls(homepage_html, homepage_url)
        
        # Fallback to standard paths if no candidate links found
        if not contact_links:
            contact_links.add(urljoin(homepage_url, "/contact"))
            contact_links.add(urljoin(homepage_url, "/contact-us"))
        if not about_links:
            about_links.add(urljoin(homepage_url, "/about"))
            about_links.add(urljoin(homepage_url, "/about-us"))
            
        # Fetch at most one contact page and one about page to be polite and save time
        contact_to_try = list(contact_links)[:2] # Try up to 2 contact pages
        about_to_try = list(about_links)[:2] # Try up to 2 about pages
        
        # Crawl Contact Pages
        for link in contact_to_try:
            # Don't recrawl homepage
            if link == homepage_url or link == website_url:
                continue
            logger.debug(f"Crawling contact page candidate: {link}")
            page_resp = fetch_url(link)
            if page_resp:
                page_emails = extract_emails_from_html(page_resp.text, link)
                emails.update(page_emails)
                if page_emails:
                    logger.debug(f"Found {len(page_emails)} emails on contact page: {link}")
                    break # If we found emails, we can stop crawling other contact candidates
                    
        # Crawl About Pages
        for link in about_to_try:
            if link == homepage_url or link == website_url or link in contact_to_try:
                continue
            logger.debug(f"Crawling about page candidate: {link}")
            page_resp = fetch_url(link)
            if page_resp:
                page_emails = extract_emails_from_html(page_resp.text, link)
                emails.update(page_emails)
                if page_emails:
                    logger.debug(f"Found {len(page_emails)} emails on about page: {link}")
                    break
    else:
        logger.warning(f"Could not fetch homepage for: {website_url}. Skipping direct crawl.")

    # 3. Fallback to DuckDuckGo search if no emails found
    if not emails:
        logger.info(f"No emails found via direct website crawling for {website_url}. Trying DuckDuckGo search fallback...")
        ddg_emails = []
        parsed = urlparse(website_url)
        domain = parsed.netloc.replace("www.", "")
        
        # Scenario A: Search with domain
        if domain:
            query = f'"{domain}" email'
            try:
                ddg_emails = search_email_ddg(query)
            except Exception as e:
                logger.debug(f"DuckDuckGo search failed for query '{query}': {e}")
                
        # Scenario B: Search with business name (if provided)
        if not ddg_emails and business_name:
            query = f'"{business_name}" email'
            try:
                ddg_emails = search_email_ddg(query)
            except Exception as e:
                logger.debug(f"DuckDuckGo search failed for query '{query}': {e}")
                
        if ddg_emails:
            logger.info(f"Found emails via DuckDuckGo fallback search: {ddg_emails}")
            emails.update(ddg_emails)
            
    email_list = list(emails)
    logger.info(f"Enrichment completed for {website_url}. Total unique emails found: {len(email_list)} ({email_list})")
    return email_list
