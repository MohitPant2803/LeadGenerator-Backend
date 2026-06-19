import requests
from lead_gen_agent.config import GEOAPIFY_API_KEY, logger

NICHE_TO_CATEGORY = {
    "restaurant": "catering.restaurant",
    "restaurants": "catering.restaurant",
    "cafe": "catering.cafe",
    "cafes": "catering.cafe",
    "bar": "catering.bar",
    "bars": "catering.bar",
    "dentist": "healthcare.dentist",
    "dentists": "healthcare.dentist",
    "doctor": "healthcare.clinic",
    "doctors": "healthcare.clinic",
    "hotel": "accommodation.hotel",
    "hotels": "accommodation.hotel",
    "gym": "sport.fitness",
    "gyms": "sport.fitness",
    "salon": "service.beauty",
    "salons": "service.beauty",
    "spa": "service.beauty",
    "spas": "service.beauty",
    "plumber": "service",
    "plumbers": "service",
    "locksmith": "service",
    "locksmiths": "service",
    "school": "education.school",
    "schools": "education.school",
    "office": "commercial.office",
    "offices": "commercial.office",
    "bank": "commercial.bank",
    "banks": "commercial.bank",
    "grocery": "commercial.supermarket",
    "groceries": "commercial.supermarket",
    "supermarket": "commercial.supermarket",
    "supermarkets": "commercial.supermarket",
    "bakery": "commercial.food_and_drink.bakery",
    "bakeries": "commercial.food_and_drink.bakery",
    "pharmacy": "healthcare.pharmacy",
    "pharmacies": "healthcare.pharmacy",
    "hospital": "healthcare.hospital",
    "hospitals": "healthcare.hospital",
    "laundry": "service.laundry",
    "mechanic": "service.car_repair",
    "car repair": "service.car_repair",
    "gas station": "service.vehicle.fuel",
}

def geocode_location(location_name: str, api_key: str):
    logger.info(f"Geocoding location: '{location_name}'...")
    url = "https://api.geoapify.com/v1/geocode/search"
    params = {
        "text": location_name,
        "apiKey": api_key
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("features"):
            raise ValueError(f"No geocoding results found for location: {location_name}")
            
        first_feature = data["features"][0]
        properties = first_feature.get("properties", {})
        lat = properties.get("lat")
        lon = properties.get("lon")
        formatted_name = properties.get("formatted", location_name)
        
        if lat is None or lon is None:
            # Try coordinates from geometry
            geometry = first_feature.get("geometry", {})
            coords = geometry.get("coordinates", [])
            if len(coords) >= 2:
                lon, lat = coords[0], coords[1]
                
        if lat is None or lon is None:
            raise ValueError(f"Could not extract lat/lon coordinates for {location_name}")
            
        logger.info(f"Geocoded '{location_name}' to lat={lat}, lon={lon} ({formatted_name})")
        return lat, lon
    except Exception as e:
        logger.error(f"Error geocoding location '{location_name}': {e}")
        raise

def get_place_details(place_id: str, api_key: str):
    logger.debug(f"Fetching Place Details for ID: {place_id}...")
    url = "https://api.geoapify.com/v2/place-details"
    params = {
        "id": place_id,
        "apiKey": api_key
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        features = data.get("features", [])
        if not features:
            # Try getting properties directly if structure is different
            if "properties" in data:
                return data["properties"]
            return {}
            
        return features[0].get("properties", {})
    except Exception as e:
        logger.warning(f"Failed to fetch place details for {place_id}: {e}")
        return {}

def discover_businesses(niche: str, location: str, limit: int = 10):
    if not GEOAPIFY_API_KEY:
        raise ValueError("GEOAPIFY_API_KEY environment variable is missing. Please set it in .env")
        
    # 1. Geocode location to get lat/lon
    lat, lon = geocode_location(location, GEOAPIFY_API_KEY)
    
    # 2. Determine category and name filtering
    niche_lower = niche.lower().strip()
    category = None
    name_filter = None
    
    if "." in niche_lower or "," in niche_lower:
        # User entered a direct Geoapify category (e.g. "catering.restaurant" or a list)
        category = niche_lower
    elif niche_lower in NICHE_TO_CATEGORY:
        category = NICHE_TO_CATEGORY[niche_lower]
    else:
        # Fallback: search under commercial, office, and service, using name filter
        category = "commercial,service,catering,accommodation,healthcare,education"
        name_filter = niche
        
    logger.info(f"Searching places with category='{category}', name_filter='{name_filter}' within 10km of ({lat}, {lon})...")
    
    # 3. Call Geoapify Places API (v2)
    url = "https://api.geoapify.com/v2/places"
    params = {
        "categories": category,
        "filter": f"circle:{lon},{lat},10000", # 10km radius
        "limit": limit,
        "apiKey": GEOAPIFY_API_KEY
    }
    if name_filter:
        params["name"] = name_filter
        
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Error querying Geoapify Places API: {e}")
        return []
        
    features = data.get("features", [])
    logger.info(f"Found {len(features)} matching places in initial search. Extracting details...")
    
    discovered_leads = []
    for feature in features:
        try:
            from lead_gen_agent.pipeline import pipeline_cancel_event
            if pipeline_cancel_event.is_set():
                logger.info("Pipeline cancellation requested during discovery loop. Aborting discovery.")
                break
        except ImportError:
            pass
            
        prop = feature.get("properties", {})
        place_id = prop.get("place_id")
        
        if not place_id:
            continue
            
        # Extract details directly from initial properties to avoid slow sequential API calls
        name = prop.get("name") or "Unknown Business"
        address = (
            prop.get("formatted") or 
            prop.get("address_line2") or 
            prop.get("address_line1") or 
            "Unknown Address"
        )
        
        contact = prop.get("contact") or {}
        phone = contact.get("phone") if isinstance(contact, dict) else None
        website = prop.get("website")
        
        lead_dict = {
            "place_id": place_id,
            "name": name,
            "address": address,
            "phone": phone if phone else None,
            "website": website if website else None
        }
        
        discovered_leads.append(lead_dict)
        logger.info(f"Discovered: {name} | Website: {lead_dict['website']} | Phone: {lead_dict['phone']}")
        
    return discovered_leads
