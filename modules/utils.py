"""
Utilities Module
Contains utility functions and helpers for the YouTube OSINT Tool.
"""

import re
import json
import csv
import os
from datetime import datetime
from typing import Dict, List, Any, Optional


def extract_social_media(text: str) -> Dict[str, List[str]]:
    """
    Return dict with lists of found identifiers with comprehensive regex patterns.
    
    Args:
        text: The text to search for social media information
        
    Returns:
        Dictionary with social media platform names as keys and lists of found identifiers as values
    """
    data = {
        # Email addresses with various formats
        "email": list(set(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', text))),
        
        # Twitter/X handles and URLs
        "twitter": list(set(re.findall(r'(?:https?://(?:www\.)?(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,15})|@([A-Za-z0-9_]{1,15}))\b', text))) + 
                 list(set(re.findall(r'twitter\.com/([A-Za-z0-9_]{1,15})', text))),
        
        # Instagram handles and URLs
        "instagram": list(set(re.findall(r'(?:https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]{1,30})|@([A-Za-z0-9_.]{1,30}))\b', text))) + 
                   list(set(re.findall(r'instagram\.com/([A-Za-z0-9_.]{1,30})', text))),
        
        # Facebook pages, profiles, and groups
        "facebook": list(set(re.findall(r'(?:https?://(?:www\.)?facebook\.com/(?:pages/|profile\.php\?id=)?([A-Za-z0-9_.-]+)|fb\.com/([A-Za-z0-9_.-]+))', text))) + 
                   list(set(re.findall(r'facebook\.com/groups/([A-Za-z0-9_.-]+)', text))),
        
        # TikTok usernames and URLs
        "tiktok": list(set(re.findall(r'(?:https?://(?:www\.)?tiktok\.com/@?([A-Za-z0-9_.]{1,24})|@([A-Za-z0-9_.]{1,24}))\b', text))) + 
                 list(set(re.findall(r'tiktok\.com/@?([A-Za-z0-9_.]{1,24})', text))),
        
        # Discord server invites and community links
        "discord": list(set(re.findall(r'(?:discord\.gg/([\w-]+)|discordapp\.com/invite/([\w-]+)|discord\.com/invite/([\w-]+))', text))) + 
                 list(set(re.findall(r'discord\.gg/([\w-]+)', text))),
        
        # Telegram channels, groups, and bots
        "telegram": list(set(re.findall(r'(?:t\.me/|telegram\.me/|telegram\.dog/)([A-Za-z0-9_]{5,32})', text))) + 
                   list(set(re.findall(r't\.me/([A-Za-z0-9_]{5,32})', text))),
        
        # Websites and domains
        "website": list(set(re.findall(r'https?://(?:www\.)?([A-Za-z0-9_.-]+\.[A-Za-z]{2,})(?:/[A-Za-z0-9_.-]*)?', text))) + 
                 list(set(re.findall(r'(?:www\.)?([A-Za-z0-9_.-]+\.[A-Za-z]{2,})', text))),
        
        # Phone numbers with various international formats
        "phone": list(set(re.findall(r'(?:\+?(?:1|44|91|61|86|49|33|81|82|55|52|34|39|31|46|47|45|43|41|48|351|353|358|372|371|370|375|380|996|995|994|993|992|976|975|974|973|972|971|968|967|966|965|964|963|962|961|880|855|856|95|94|93|92|91|90|98|20|27|234|233|232|231|225|224|223|221|220|218|213|212|211|98|971|966|965|964|963|962|961|968|967|972|973|974|975|976|977|94|93|92|91|90|81|82|86|852|853|886|65|60|63|62|84|855|856|95|673|674|675|676|679|680|685|689|682|683|686|687|689|690|691|692|699|670|672|673|674|675|676|677|678|679|680|681|682|683|684|685|686|687|688|689|690|691|692|693|694|695|696|697|698|699)\s?)?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text))) + 
                 list(set(re.findall(r'(?:\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})', text))),
        
        # LinkedIn profiles and company pages
        "linkedin": list(set(re.findall(r'(?:https?://(?:www\.)?linkedin\.com/(?:in/|company/)([A-Za-z0-9_-]+))', text))) + 
                  list(set(re.findall(r'linkedin\.com/(?:in/|company/)([A-Za-z0-9_-]+)', text))),
        
        # YouTube channel handles and custom URLs
        "youtube": list(set(re.findall(r'(?:https?://(?:www\.)?youtube\.com/(?:channel/|c/|user/|@)([A-Za-z0-9_-]+))', text))) + 
                  list(set(re.findall(r'youtube\.com/(?:channel/|c/|user/|@)([A-Za-z0-9_-]+)', text))),
        
        # Reddit usernames and subreddits
        "reddit": list(set(re.findall(r'(?:https?://(?:www\.)?reddit\.com/(?:u/|user/|r/)([A-Za-z0-9_-]+))', text))) + 
                 list(set(re.findall(r'reddit\.com/(?:u/|user/|r/)([A-Za-z0-9_-]+)', text))),
        
        # Twitch usernames
        "twitch": list(set(re.findall(r'(?:https?://(?:www\.)?twitch\.tv/([A-Za-z0-9_]+))', text))) + 
                  list(set(re.findall(r'twitch\.tv/([A-Za-z0-9_]+)', text))),
        
        # Snapchat usernames
        "snapchat": list(set(re.findall(r'(?:https?://(?:www\.)?snapchat\.com/add/([A-Za-z0-9_.-]+))', text))) + 
                    list(set(re.findall(r'snapchat\.com/add/([A-Za-z0-9_.-]+)', text))),
        
        # Pinterest profiles and boards
        "pinterest": list(set(re.findall(r'(?:https?://(?:www\.)?pinterest\.(?:com|co\.uk|fr|de|it|es)/(?:[A-Za-z0-9_.-]+))', text))) + 
                     list(set(re.findall(r'pinterest\.(?:com|co\.uk|fr|de|it|es)/([A-Za-z0-9_.-]+)', text))),
        
        # GitHub repositories and user profiles
        "github": list(set(re.findall(r'(?:https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)(?:/[A-Za-z0-9_.-]+)?)', text))) + 
                 list(set(re.findall(r'github\.com/([A-Za-z0-9_.-]+)(?:/[A-Za-z0-9_.-]+)?', text)))
    }
    
    # Clean up the data by removing empty strings and duplicates
    cleaned_data = {}
    for key, values in data.items():
        if isinstance(values, list):
            # Flatten nested tuples from regex groups
            flat_values = []
            for item in values:
                if isinstance(item, tuple):
                    for subitem in item:
                        if subitem and subitem.strip():
                            flat_values.append(subitem.strip())
                elif item and item.strip():
                    flat_values.append(item.strip())
            # Remove duplicates while preserving order
            seen = set()
            unique_values = []
            for value in flat_values:
                if value not in seen:
                    seen.add(value)
                    unique_values.append(value)
            cleaned_data[key] = unique_values
        else:
            cleaned_data[key] = values
    
    return cleaned_data


def flatten_item(item: Dict[str, Any]) -> List[str]:
    """
    Convert a YouTube API item to a CSV row.
    
    Args:
        item: Dictionary containing YouTube API item data
        
    Returns:
        List of strings representing a CSV row
    """
    kind = item.get("kind", "")
    if kind == "youtube#video":
        snippet = item["snippet"]
        statistics = item.get("statistics", {})
        social_media = extract_social_media(snippet.get("description", ""))
        return ["video", item["id"], snippet["title"], snippet["channelTitle"],
                snippet["publishedAt"], snippet.get("description", ""),
                statistics.get("viewCount", ""), "",  # no subs for video
                social_media.get("email", ""), social_media.get("twitter", ""),
                social_media.get("instagram", ""), social_media.get("facebook", ""),
                social_media.get("tiktok", ""), social_media.get("discord", ""),
                social_media.get("telegram", ""), social_media.get("website", ""),
                social_media.get("phone", "")]
    if kind == "youtube#channel":
        snippet = item["snippet"]
        statistics = item.get("statistics", {})
        social_media = extract_social_media(snippet.get("description", ""))
        return ["channel", item["id"], snippet["title"], snippet["title"],
                snippet["publishedAt"], snippet.get("description", ""),
                statistics.get("viewCount", ""), statistics.get("subscriberCount", ""),
                social_media.get("email", ""), social_media.get("twitter", ""),
                social_media.get("instagram", ""), social_media.get("facebook", ""),
                social_media.get("tiktok", ""), social_media.get("discord", ""),
                social_media.get("telegram", ""), social_media.get("website", ""),
                social_media.get("phone", "")]
    # fallback
    return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]


def parse_duration_from_iso(duration_str: str) -> int:
    """
    Parse ISO 8601 duration string to seconds.
    
    Args:
        duration_str: ISO 8601 duration string (e.g., "PT1H30M15S")
        
    Returns:
        Duration in seconds
    """
    import re
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration_str)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds
    return 0


def format_duration(seconds: int) -> str:
    """
    Format duration in seconds to human-readable format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string (e.g., "1:30:15" or "30:15")
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"


def get_engagement_color(engagement_level: str) -> str:
    """
    Get background color for engagement level.
    
    Args:
        engagement_level: Engagement level (high, medium, low)
        
    Returns:
        Hex color code
    """
    colors = {
        "high": "#90EE90",  # Light green
        "medium": "#FFE4B5",  # Light orange
        "low": "#FFB6C1"  # Light pink
    }
    return colors.get(engagement_level, "#FFFFFF")


def extract_video_ids(results: List[Dict[str, Any]]) -> List[str]:
    """
    Extract video IDs from search results.
    
    Args:
        results: List of search result items
        
    Returns:
        List of video IDs
    """
    video_ids = []
    
    for result in results:
        if result.get("kind") == "youtube#video":
            video_id = result.get("id", {}).get("videoId", "")
            if video_id:
                video_ids.append(video_id)
        elif result.get("kind") == "youtube#searchResult":
            # Handle search results
            if result.get("id", {}).get("kind") == "youtube#video":
                video_id = result.get("id", {}).get("videoId", "")
                if video_id:
                    video_ids.append(video_id)
    
    return video_ids


def extract_target_info(results: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Extract target information from results.
    
    Args:
        results: List of search result items
        
    Returns:
        Dictionary with target information
    """
    target_info = {}
    
    for result in results:
        if result.get("kind") == "youtube#channel":
            snippet = result.get("snippet", {})
            title = snippet.get("title", "")
            description = snippet.get("description", "")
            
            # Extract potential usernames, names, emails, phones
            target_info["name"] = title
            target_info["username"] = title.lower().replace(" ", "_")
            
            # Extract social media and contact info
            social_data = extract_social_media(description)
            if social_data.get("email"):
                target_info["email"] = social_data["email"][0]
            if social_data.get("phone"):
                target_info["phone"] = social_data["phone"][0]
            
            break  # Use the first channel found
    
    return target_info


def safe_get_nested(data: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    """
    Safely get nested dictionary values.
    
    Args:
        data: Dictionary to search
        keys: List of keys to traverse
        default: Default value if key not found
        
    Returns:
        Value at nested key path or default
    """
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def format_number(number: int) -> str:
    """
    Format large numbers with commas.
    
    Args:
        number: Number to format
        
    Returns:
        Formatted number string
    """
    return f"{number:,}"


def get_timestamp() -> str:
    """
    Get current timestamp in HH:MM:SS format.
    
    Returns:
        Current timestamp string
    """
    return datetime.now().strftime("%H:%M:%S")


def is_valid_youtube_url(url: str) -> bool:
    """
    Check if a URL is a valid YouTube URL.
    
    Args:
        url: URL to validate
        
    Returns:
        True if valid YouTube URL, False otherwise
    """
    youtube_patterns = [
        r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/v/[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/embed/[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/shorts/[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/channel/[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/c/[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/user/[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/@[\w-]+',
        r'^https?://youtu\.be/[\w-]+'
    ]
    
    for pattern in youtube_patterns:
        if re.match(pattern, url):
            return True
    return False


def extract_video_id_from_url(url: str) -> Optional[str]:
    """
    Extract video ID from YouTube URL.
    
    Args:
        url: YouTube URL
        
    Returns:
        Video ID if found, None otherwise
    """
    patterns = [
        r'(?:v=|/v/|/embed/|/shorts/)([\w-]{11})',
        r'^([\w-]{11})$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_channel_id_from_url(url: str) -> Optional[str]:
    """
    Extract channel ID from YouTube URL.
    
    Args:
        url: YouTube URL
        
    Returns:
        Channel ID if found, None otherwise
    """
    patterns = [
        r'/channel/([\w-]+)',
        r'/c/([\w-]+)',
        r'/user/([\w-]+)',
        r'/@([\w-]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None
