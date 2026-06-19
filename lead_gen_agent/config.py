import os
import logging
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
