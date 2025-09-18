"""
Thread Classes Module
Contains all worker thread classes for background processing in YouTube OSINT Tool.
"""

import base64, csv, io, json, os, re, sys, time, urllib.parse, pathlib, random, math
from datetime import datetime, timedelta
from typing import List, Dict, Any

import requests
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QThread, pyqtSignal, Qt

# Import yt-dlp
try:
    import yt_dlp as ytdlp
except ImportError:
    print("pip install yt-dlp")
    sys.exit(1)
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("pip install beautifulsoup4")
    sys.exit(1)

# Constants
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class YouTubeSearchThread(QThread):
    """Generic worker that uses yt-dlp and web scraping for YouTube search."""
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, query, search_type="video", max_results=50):
        super().__init__()
        self.query = query
        self.search_type = search_type
        self.max_results = max_results
        self._abort = False

    def run(self):
        try:
            self.log.emit(f"Searching YouTube ({self.search_type}s) for: {self.query}")
            
            # Use yt-dlp to extract information
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'playlistend': self.max_results,
                'default_search': 'ytsearch' + str(self.max_results),
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                search_results = ydl.extract_info(f"ytsearch{self.max_results}:{self.query}", download=False)
            
            items = []
            if 'entries' in search_results:
                for entry in search_results['entries'][:self.max_results]:
                    if self._abort:
                        break
                    
                    # Convert yt-dlp format to API-like format
                    item = {
                        'id': {
                            'videoId': entry.get('id', '') if self.search_type == 'video' else '',
                            'channelId': entry.get('channel_id', '')
                        },
                        'snippet': {
                            'title': entry.get('title', ''),
                            'description': entry.get('description', ''),
                            'channelTitle': entry.get('channel', ''),
                            'publishedAt': entry.get('upload_date', ''),
                            'thumbnails': {
                                'default': {'url': entry.get('thumbnail', '')},
                                'medium': {'url': entry.get('thumbnail', '')},
                                'high': {'url': entry.get('thumbnail', '')}
                            }
                        }
                    }
                    items.append(item)
            
            self.log.emit(f"Found {len(items)} {self.search_type}(s)")
            self.result_ready.emit({"type": self.search_type, "items": items})
        except Exception as e:
            self.error.emit(str(e))
    
    def abort(self):
        self._abort = True


class ChannelDetailsThread(QThread):
    """Fetch full channel statistics + uploads playlist using yt-dlp."""
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, channel_url_or_id):
        super().__init__()
        self.channel_url_or_id = channel_url_or_id
        self._abort = False

    def run(self):
        try:
            self.log.emit(f"Fetching channel details for {self.channel_url_or_id}")
            
            # Handle both URLs and channel IDs
            if self.channel_url_or_id.startswith(('http://', 'https://')):
                channel_url = self.channel_url_or_id
            else:
                # Convert channel ID to URL
                channel_url = f"https://www.youtube.com/channel/{self.channel_url_or_id}"
            
            # Use yt-dlp to extract channel information
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'playlistend': 1,
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(channel_url, download=False)
                except Exception as e:
                    # Try alternative URL format
                    if not self.channel_url_or_id.startswith(('http://', 'https://')):
                        channel_url = f"https://www.youtube.com/c/{self.channel_url_or_id}"
                        info = ydl.extract_info(channel_url, download=False)
                    else:
                        raise
            
            if not info:
                self.error.emit("Channel not found")
                return
            
            # Convert yt-dlp format to API-like format
            channel_data = {
                'id': info.get('channel_id', ''),
                'snippet': {
                    'title': info.get('channel', ''),
                    'description': info.get('description', ''),
                    'publishedAt': info.get('upload_date', ''),
                    'thumbnails': {
                        'default': {'url': info.get('thumbnail', '')},
                        'medium': {'url': info.get('thumbnail', '')},
                        'high': {'url': info.get('thumbnail', '')}
                    }
                },
                'statistics': {
                    'subscriberCount': info.get('channel_follower_count', 0),
                    'videoCount': info.get('n_entries', 0),
                    'viewCount': info.get('view_count', 0)
                },
                'contentDetails': {
                    'relatedPlaylists': {
                        'uploads': info.get('channel_id', '')
                    }
                }
            }
            
            self.result_ready.emit(channel_data)
        except Exception as e:
            self.error.emit(str(e))
    
    def abort(self):
        self._abort = True


class VideoDetailsThread(QThread):
    """Deep-dive on a single video (+ comments) using yt-dlp."""
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, video_url):
        super().__init__()
        self.video_url = video_url
        self._abort = False

    def run(self):
        try:
            self.log.emit(f"Fetching video details for {self.video_url}")
            
            # Use yt-dlp to extract video information
            ydl_opts = {
                'quiet': True,
                'getcomments': True,
                'commentsort': 'top',
                'writeinfojson': False,
                'writethumbnail': False,
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.video_url, download=False)
            
            if not info:
                self.error.emit("Video not found")
                return
            
            # Convert yt-dlp format to API-like format
            video_data = {
                'id': info.get('id', ''),
                'snippet': {
                    'title': info.get('title', ''),
                    'description': info.get('description', ''),
                    'channelTitle': info.get('channel', ''),
                    'publishedAt': info.get('upload_date', ''),
                    'thumbnails': {
                        'default': {'url': info.get('thumbnail', '')},
                        'medium': {'url': info.get('thumbnail', '')},
                        'high': {'url': info.get('thumbnail', '')}
                    },
                    'tags': info.get('tags', []),
                    'categoryId': str(info.get('category', 0)),
                    'liveBroadcastContent': 'none' if not info.get('is_live', False) else 'live',
                    'defaultLanguage': info.get('language', ''),
                    'defaultAudioLanguage': info.get('language', ''),
                },
                'statistics': {
                    'viewCount': info.get('view_count', 0),
                    'likeCount': info.get('like_count', 0),
                    'dislikeCount': 0,  # YouTube removed this
                    'favoriteCount': 0,
                    'commentCount': info.get('comment_count', 0)
                },
                'contentDetails': {
                    'duration': info.get('duration', 0),
                    'dimension': '2d',
                    'definition': 'hd' if info.get('height', 0) >= 720 else 'sd',
                    'caption': 'true' if info.get('subtitles') else 'false',
                    'licensedContent': False
                },
                'status': {
                    'uploadStatus': 'processed',
                    'privacyStatus': 'public',
                    'license': 'youtube',
                    'embeddable': True,
                    'publicStatsViewable': True
                }
            }
            
            # Add comments if available
            if 'comments' in info:
                comments = []
                for comment in info['comments'][:20]:  # Limit to top 20 comments
                    if self._abort:
                        break
                    comments.append({
                        'id': comment.get('id', ''),
                        'snippet': {
                            'authorDisplayName': comment.get('author', ''),
                            'textDisplay': comment.get('text', ''),
                            'likeCount': comment.get('like_count', 0),
                            'publishedAt': comment.get('timestamp', ''),
                            'authorProfileImageUrl': comment.get('author_thumbnail', '')
                        }
                    })
                video_data['comments'] = comments
            
            self.result_ready.emit(video_data)
        except Exception as e:
            self.error.emit(str(e))
    
    def abort(self):
        self._abort = True


class ProfileImageDownloadThread(QThread):
    """Download high-quality profile images from YouTube channels."""
    download_complete = pyqtSignal(str, str)  # channel_id, file_path
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, channel_data, output_dir):
        super().__init__()
        self.channel_data = channel_data
        self.output_dir = output_dir
        self._abort = False

    def run(self):
        try:
            channel_id = self.channel_data.get('id', '')
            channel_name = self.channel_data.get('snippet', {}).get('title', 'unknown')
            
            self.log.emit(f"Downloading profile image for channel: {channel_name}")
            
            # Get the highest quality thumbnail URL
            thumbnails = self.channel_data.get('snippet', {}).get('thumbnails', {})
            thumbnail_url = thumbnails.get('high', {}).get('url') or \
                           thumbnails.get('medium', {}).get('url') or \
                           thumbnails.get('default', {}).get('url')
            
            if not thumbnail_url:
                self.error.emit(f"No thumbnail URL found for channel {channel_name}")
                return
            
            # Create output directory if it doesn't exist
            os.makedirs(self.output_dir, exist_ok=True)
            
            # Sanitize filename
            safe_channel_name = re.sub(r'[^\w\-_\. ]', '_', channel_name)
            filename = f"{safe_channel_name}_{channel_id}.jpg"
            filepath = os.path.join(self.output_dir, filename)
            
            # Download the image
            headers = {'User-Agent': USER_AGENT}
            response = requests.get(thumbnail_url, headers=headers, stream=True)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self._abort:
                        return
                    f.write(chunk)
            
            self.log.emit(f"Profile image downloaded: {filename}")
            self.download_complete.emit(channel_id, filepath)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def abort(self):
        self._abort = True


class GoogleDorkingThread(QThread):
    """Google Dorking automation for cross-platform discovery."""
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, target_info, platforms):
        super().__init__()
        self.target_info = target_info
        self.platforms = platforms
        self._abort = False

    def run(self):
        try:
            self.log.emit(f"Starting Google Dorking for target: {self.target_info}")
            results = {}
            
            total_platforms = len(self.platforms)
            for i, platform in enumerate(self.platforms):
                if self._abort:
                    break
                
                self.progress.emit(int((i + 1) / total_platforms * 100))
                
                # Construct dork queries based on platform and target info
                queries = self._construct_queries(platform, self.target_info)
                platform_results = []
                
                for query in queries:
                    if self._abort:
                        break
                    
                    try:
                        # Simple Google search simulation
                        search_results = self._simulate_google_search(query)
                        platform_results.extend(search_results)
                    except Exception as e:
                        self.log.emit(f"Error searching '{query}': {str(e)}")
                
                results[platform] = platform_results
                self.log.emit(f"Completed dorking for {platform}: {len(platform_results)} results")
            
            self.result_ready.emit(results)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _construct_queries(self, platform, target_info):
        """Construct Google dork queries based on platform and target info."""
        queries = []
        channel_name = target_info.get('channel_name', '')
        channel_id = target_info.get('channel_id', '')
        description = target_info.get('description', '')
        
        if platform == 'twitter':
            queries.extend([
                f'site:twitter.com "{channel_name}"',
                f'site:twitter.com "{channel_id}"',
                f'site:twitter.com "{description[:50]}"'
            ])
        elif platform == 'facebook':
            queries.extend([
                f'site:facebook.com "{channel_name}"',
                f'site:facebook.com "{channel_id}"'
            ])
        elif platform == 'instagram':
            queries.extend([
                f'site:instagram.com "{channel_name}"',
                f'site:instagram.com "{channel_id}"'
            ])
        elif platform == 'linkedin':
            queries.extend([
                f'site:linkedin.com "{channel_name}"',
                f'site:linkedin.com "{channel_id}"'
            ])
        elif platform == 'tiktok':
            queries.extend([
                f'site:tiktok.com "{channel_name}"',
                f'site:tiktok.com "{channel_id}"'
            ])
        
        return queries
    
    def _simulate_google_search(self, query):
        """Simulate Google search (in real implementation, use Google API or scraping)."""
        # This is a simulation - in real implementation, you would use Google Custom Search API
        # or web scraping with proper error handling and rate limiting
        
        time.sleep(0.5)  # Simulate network delay
        
        # Return mock results
        return [
            {
                'title': f'Mock result for: {query}',
                'url': f'https://example.com/result?q={urllib.parse.quote(query)}',
                'snippet': f'This is a mock search result for the query: {query}'
            }
        ]
    
    def abort(self):
        self._abort = True


class DocumentIntelligenceThread(QThread):
    """Worker thread for Document Intelligence Search."""
    log = pyqtSignal(str)
    error = pyqtSignal(str)
    result_ready = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, target_info, search_engines):
        super().__init__()
        self.target_info = target_info
        self.search_engines = search_engines
        self._abort = False

    def run(self):
        try:
            self.log.emit(f"Starting Document Intelligence Search with target info: {self.target_info}")
            results = {}
            
            total_engines = len(self.search_engines)
            for i, engine in enumerate(self.search_engines):
                if self._abort:
                    break
                
                self.progress.emit(int((i + 1) / total_engines * 100))
                
                # Search for documents related to the target
                engine_results = self._search_documents(engine, self.target_info)
                results[engine] = engine_results
                
                self.log.emit(f"Completed document search on {engine}: {len(engine_results)} results")
            
            self.result_ready.emit(results)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _search_documents(self, engine, target_info):
        """Search for documents related to the target."""
        # This is a simulation - in real implementation, you would use various APIs
        # or web scraping to find documents
        
        time.sleep(1)  # Simulate search delay
        
        # Mock document results
        return [
            {
                'title': f'Mock document found on {engine}',
                'url': f'https://example.com/doc.pdf',
                'snippet': f'Document related to {target_info.get("channel_name", "target")}',
                'file_type': 'pdf',
                'size': '1.2 MB'
            }
        ]
    
    def abort(self):
        self._abort = True


class VideoAnalysisThread(QThread):
    """Worker thread for Enhanced Video Analysis with engagement metrics and performance analytics using yt-dlp."""
    log = pyqtSignal(str)
    error = pyqtSignal(str)
    result_ready = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, api_key, video_ids):
        super().__init__()
        self.api_key = api_key
        self.video_ids = video_ids
        self._abort = False

    def run(self):
        try:
            self.log.emit(f"Starting enhanced video analysis for {len(self.video_ids)} videos...")
            results = {"videos": [], "summary": self._initialize_summary()}
            
            total_videos = len(self.video_ids)
            for i, video_id in enumerate(self.video_ids):
                if self._abort:
                    break
                
                self.progress.emit(int((i + 1) / total_videos * 100))
                
                try:
                    # Get video data using yt-dlp
                    video_data = self._get_video_data(video_id)
                    if video_data:
                        # Perform analysis
                        analyzed_video = self._analyze_video(video_data)
                        results["videos"].append(analyzed_video)
                        
                        # Update summary statistics
                        self._update_summary_statistics(results, analyzed_video)
                        
                        self.log.emit(f"Analyzed video: {video_data.get('title', video_id)}")
                
                except Exception as e:
                    self.log.emit(f"Error analyzing video {video_id}: {str(e)}")
            
            # Calculate final summary metrics
            self._calculate_final_summary(results)
            
            self.result_ready.emit(results)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _initialize_summary(self):
        """Initialize summary statistics structure."""
        return {
            "total_videos": 0,
            "total_views": 0,
            "total_likes": 0,
            "total_comments": 0,
            "average_engagement_rate": 0,
            "engagement_distribution": {"high": 0, "medium": 0, "low": 0},
            "top_performing_videos": []
        }
    
    def _get_video_data(self, video_id):
        """Get video data using yt-dlp."""
        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            ydl_opts = {
                'quiet': True,
                'getcomments': False,
                'writeinfojson': False,
                'writethumbnail': False,
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
            
            if info:
                return {
                    'id': info.get('id', ''),
                    'title': info.get('title', ''),
                    'description': info.get('description', ''),
                    'channel_title': info.get('channel', ''),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'comment_count': info.get('comment_count', 0),
                    'duration': info.get('duration', 0),
                    'upload_date': info.get('upload_date', ''),
                    'tags': info.get('tags', []),
                    'category': info.get('category', ''),
                    'thumbnail': info.get('thumbnail', '')
                }
        
        except Exception as e:
            self.log.emit(f"Error fetching video data for {video_id}: {str(e)}")
            return None
    
    def _analyze_video(self, video_data):
        """Perform comprehensive analysis on video data."""
        # Calculate engagement metrics
        view_count = video_data.get("view_count", 0)
        like_count = video_data.get("like_count", 0)
        comment_count = video_data.get("comment_count", 0)
        
        # Engagement rate calculation
        if view_count > 0:
            engagement_rate = ((like_count + comment_count) / view_count) * 100
        else:
            engagement_rate = 0
        
        # Determine engagement level
        if engagement_rate >= 5:
            engagement_level = "high"
        elif engagement_rate >= 1:
            engagement_level = "medium"
        else:
            engagement_level = "low"
        
        # Calculate engagement score (0-100)
        engagement_score = min(100, engagement_rate * 10)
        
        # Calculate virality score based on view count and engagement
        virality_score = min(100, math.log10(max(1, view_count)) * 10 + engagement_score * 0.3)
        
        # Calculate performance score
        performance_score = (engagement_score * 0.6) + (virality_score * 0.4)
        
        # Add analytics to video data
        video_data["engagement_metrics"] = {
            "engagement_rate": round(engagement_rate, 2),
            "engagement_level": engagement_level,
            "engagement_score": round(engagement_score, 2),
            "virality_score": round(virality_score, 2)
        }
        
        video_data["performance_analytics"] = {
            "performance_score": round(performance_score, 2),
            "performance_category": self._get_performance_category(performance_score),
            "growth_potential": self._calculate_growth_potential(video_data),
            "content_effectiveness": self._calculate_content_effectiveness(video_data),
            "audience_retention": self._simulate_audience_retention(video_data)
        }
        
        return video_data
    
    def _calculate_content_effectiveness(self, video_data):
        """Calculate content effectiveness based on various factors."""
        description_length = len(video_data.get("description", ""))
        tag_count = len(video_data.get("tags", []))
        has_caption = video_data.get("caption") == "true"
        
        # Score based on content optimization
        description_score = min(100, description_length / 10)  # 1 point per 10 characters
        tag_score = min(100, tag_count * 10)  # 10 points per tag
        caption_score = 20 if has_caption else 0
        
        content_effectiveness = (description_score * 0.4) + (tag_score * 0.4) + (caption_score * 0.2)
        return content_effectiveness
    
    def _simulate_audience_retention(self, video_data):
        """Simulate audience retention based on video characteristics."""
        duration = video_data.get("duration", "")
        like_count = video_data.get("like_count", 0)
        view_count = video_data.get("view_count", 0)
        
        # Parse duration to seconds
        duration_seconds = self._parse_duration(duration)
        
        # Calculate engagement ratio
        if view_count > 0:
            engagement_ratio = like_count / view_count
        else:
            engagement_ratio = 0
        
        # Duration factor (longer videos typically have lower retention)
        duration_factor = max(0.3, 1 - (duration_seconds / 3600))  # Reduce retention for very long videos
        
        # Calculate retention rate
        retention_rate = (engagement_ratio * 100) * duration_factor
        return min(95, max(5, retention_rate))
    
    def _parse_duration(self, duration_str):
        """Parse ISO 8601 duration string to seconds."""
        import re
        pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
        match = re.match(pattern, duration_str)
        if match:
            hours, minutes, seconds = match.groups()
            hours = int(hours) if hours else 0
            minutes = int(minutes) if minutes else 0
            seconds = int(seconds) if seconds else 0
            return hours * 3600 + minutes * 60 + seconds
        return 0
    
    def _calculate_growth_potential(self, video_data):
        """Calculate growth potential based on current performance and trends."""
        engagement_score = video_data.get("engagement_metrics", {}).get("engagement_score", 0)
        virality_score = video_data.get("engagement_metrics", {}).get("virality_score", 0)
        performance_score = video_data.get("performance_analytics", {}).get("performance_score", 0)
        
        # Growth potential based on multiple factors
        growth_potential = (engagement_score * 0.4) + (virality_score * 0.3) + (performance_score * 0.3)
        return growth_potential
    
    def _get_performance_category(self, performance_score):
        """Get performance category based on score."""
        if performance_score >= 80:
            return "Excellent"
        elif performance_score >= 60:
            return "Good"
        elif performance_score >= 40:
            return "Average"
        else:
            return "Below Average"
    
    def _update_summary_statistics(self, results, video_data):
        """Update summary statistics with video data."""
        view_count = video_data.get("view_count", 0)
        like_count = video_data.get("like_count", 0)
        comment_count = video_data.get("comment_count", 0)
        engagement_level = video_data.get("engagement_metrics", {}).get("engagement_level", "low")
        
        results["summary"]["total_views"] += view_count
        results["summary"]["total_likes"] += like_count
        results["summary"]["total_comments"] += comment_count
        results["summary"]["engagement_distribution"][engagement_level] += 1
    
    def _calculate_final_summary(self, results):
        """Calculate final summary metrics."""
        total_views = results["summary"]["total_views"]
        total_likes = results["summary"]["total_likes"]
        total_comments = results["summary"]["total_comments"]
        total_videos = results["summary"]["total_videos"]
        
        if total_views > 0:
            avg_engagement_rate = ((total_likes + total_comments) / total_views) * 100
        else:
            avg_engagement_rate = 0
        
        results["summary"]["average_engagement_rate"] = round(avg_engagement_rate, 2)
        
        # Find top performing videos
        sorted_videos = sorted(results["videos"], 
                             key=lambda x: x.get("performance_analytics", {}).get("performance_score", 0), 
                             reverse=True)
        results["summary"]["top_performing_videos"] = sorted_videos[:5]  # Top 5
    
    def abort(self):
        self._abort = True


class RelatedVideosThread(QThread):
    """Worker thread for extracting related videos and content recommendations using yt-dlp."""
    log = pyqtSignal(str)
    error = pyqtSignal(str)
    result_ready = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, api_key, video_ids):
        super().__init__()
        self.api_key = api_key
        self.video_ids = video_ids
        self._abort = False

    def run(self):
        try:
            self.log.emit(f"Starting related videos extraction for {len(self.video_ids)} videos...")
            results = {}
            
            total_videos = len(self.video_ids)
            for i, video_id in enumerate(self.video_ids):
                if self._abort:
                    break
                
                self.progress.emit(int((i + 1) / total_videos * 100))
                
                try:
                    # Get related videos using yt-dlp
                    related_videos = self._get_related_videos(video_id)
                    results[video_id] = related_videos
                    
                    self.log.emit(f"Extracted {len(related_videos)} related videos for {video_id}")
                
                except Exception as e:
                    self.log.emit(f"Error extracting related videos for {video_id}: {str(e)}")
            
            self.result_ready.emit(results)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _get_related_videos(self, video_id):
        """Get related videos using yt-dlp."""
        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'playlistend': 10,  # Get top 10 related videos
                'getcomments': False,
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
            
            related_videos = []
            
            # Try to get related videos from yt-dlp
            if 'related_videos' in info:
                for related in info['related_videos'][:10]:
                    related_videos.append({
                        'id': related.get('id', ''),
                        'title': related.get('title', ''),
                        'channel': related.get('channel', ''),
                        'duration': related.get('duration', 0),
                        'view_count': related.get('view_count', 0),
                        'thumbnail': related.get('thumbnail', ''),
                        'description': related.get('description', '')
                    })
            
            return related_videos
        
        except Exception as e:
            self.log.emit(f"Error getting related videos for {video_id}: {str(e)}")
            return []
    
    def abort(self):
        self._abort = True
