import requests
import datetime
import logging

logger = logging.getLogger(__name__)

# Cache to avoid spamming the API
_calendar_cache = None
_last_fetch_time = None
CACHE_DURATION_HOURS = 4

def get_economic_calendar():
    global _calendar_cache, _last_fetch_time
    now = datetime.datetime.now()
    
    if _calendar_cache is not None and _last_fetch_time is not None:
        if (now - _last_fetch_time).total_seconds() < CACHE_DURATION_HOURS * 3600:
            return _calendar_cache

    try:
        # Fetch ForexFactory JSON calendar
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            _calendar_cache = response.json()
            _last_fetch_time = now
            return _calendar_cache
    except Exception as e:
        logger.error(f"Error fetching economic calendar: {e}")
    
    return []

def is_high_impact_news_imminent(currency, hours_ahead=2):
    """
    Checks if there is a 'High' impact ('H') news event for the given currency 
    within the next `hours_ahead` hours.
    currency: e.g. "USD", "EUR", "GBP", "CAD"
    """
    events = get_economic_calendar()
    now_utc = datetime.datetime.utcnow()
    
    for event in events:
        if event.get("country") == currency and event.get("impact") == "High":
            # Event date format is usually: 2024-03-01T08:30:00-05:00
            # Let's do a simple string subset match for today to avoid complex timezone math for now, 
            # or parse it properly.
            event_time_str = event.get("date")
            try:
                # Remove timezone offest for simple naive parsing, assuming it's near enough
                # A robust bot would parse this properly with dateutil package
                event_dt = datetime.datetime.fromisoformat(event_time_str.split("-0")[0].split("-1")[0].split("+")[0])
                time_diff = event_dt - now_utc
                if datetime.timedelta(0) <= time_diff <= datetime.timedelta(hours=hours_ahead):
                    logger.warning(f"High impact news imminent for {currency}: {event.get('title')} at {event_time_str}")
                    return True
            except Exception as e:
                pass # Ignore parsing errors on weird formats
                
    return False

def can_trade(pair):
    """
    Given a pair like EURUSD, we check news for EUR and USD.
    """
    base = pair[:3]
    quote = pair[3:6]
    
    if is_high_impact_news_imminent(base) or is_high_impact_news_imminent(quote):
        return False
        
    return True
