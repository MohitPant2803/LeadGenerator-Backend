import os
import logging
import requests
import threading
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DB_PATH = os.getenv("DB_PATH", "leads.db")

# Setup logging
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.FileHandler("lead_gen.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("lead_gen_agent")

def safe_requests_get(url, headers=None, params=None, timeout=10, verify=True):
    """
    Performs a requests.get call in a background daemon thread with a strict join timeout
    to protect the pipeline from DNS hangs, TCP blackholes, or anti-bot tarpits.
    """
    result = {}
    def worker():
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify)
            result["response"] = response
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=float(timeout) + 1.5) # Add a tiny buffer above the internal requests timeout
    
    if t.is_alive():
        raise requests.exceptions.Timeout(f"Request to {url} timed out (hard thread limit of {timeout}s reached)")
        
    if "error" in result:
        raise result["error"]
        
    return result.get("response")
