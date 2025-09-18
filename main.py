#!/usr/bin/env python3
"""
YouTube OSINT Reconnaissance Tool – PyQt5 GUI
Author : you
License: MIT
"""

import base64, csv, io, json, os, re, sys, time, urllib.parse, pathlib, random, math
from datetime import datetime, timedelta
from typing import List, Dict, Any

import requests
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTextEdit, QGroupBox, QTabWidget, QTableWidget,
                             QTableWidgetItem, QFileDialog, QMessageBox,
                             QProgressBar, QCheckBox, QSplitter)

# ---------- 3rd-party deps ---------------------------------------------------
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

# ---------- GLOBALS ----------------------------------------------------------
SETTINGS_FILE = pathlib.Path("yt_osint_config.json")
ICON_B64 = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ---------- WORKER THREADS ----------------------------------------------------
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

    def __init__(self, video_url_or_id):
        super().__init__()
        self.video_url_or_id = video_url_or_id
        self._abort = False

    def run(self):
        try:
            self.log.emit(f"Fetching video details for {self.video_url_or_id}")
            
            # Handle both URLs and video IDs
            if self.video_url_or_id.startswith(('http://', 'https://')):
                video_url = self.video_url_or_id
            else:
                # Convert video ID to URL
                video_url = f"https://www.youtube.com/watch?v={self.video_url_or_id}"
            
            # Use yt-dlp to extract video information
            ydl_opts = {
                'quiet': True,
                'writeinfojson': False,
                'writesubtitles': False,
                'getcomments': True,
                'extract_flat': False,
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
            
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
                    'channelId': info.get('channel_id', ''),
                    'publishedAt': info.get('upload_date', ''),
                    'thumbnails': {
                        'default': {'url': info.get('thumbnail', '')},
                        'medium': {'url': info.get('thumbnail', '')},
                        'high': {'url': info.get('thumbnail', '')}
                    }
                },
                'statistics': {
                    'viewCount': info.get('view_count', 0),
                    'likeCount': info.get('like_count', 0),
                    'dislikeCount': 0,  # YouTube removed dislikes
                    'favoriteCount': 0,
                    'commentCount': info.get('comment_count', 0)
                },
                'contentDetails': {
                    'duration': info.get('duration', 0),
                    'dimension': '2d',
                    'definition': 'hd' if info.get('height', 0) >= 720 else 'sd',
                    'caption': 'false',
                    'licensedContent': False
                }
            }
            
            # Extract comments if available
            comments = []
            if 'comments' in info:
                for comment in info['comments'][:100]:  # Limit to 100 comments
                    if 'text' in comment:
                        comments.append({
                            "author": comment.get('author', ''),
                            "text": comment.get('text', ''),
                            "likes": comment.get('like_count', 0),
                            "published": comment.get('timestamp', '')
                        })
            else:
                self.log.emit("Comments disabled or restricted")
            
            video_data["comments"] = comments
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
    progress = pyqtSignal(int)

    def __init__(self, channel_data, output_dir="profile_images"):
        super().__init__()
        self.channel_data = channel_data
        self.output_dir = output_dir
        self._abort = False

    def run(self):
        try:
            # Create output directory if it doesn't exist
            os.makedirs(self.output_dir, exist_ok=True)
            
            channel_id = self.channel_data.get("id")
            snippet = self.channel_data.get("snippet", {})
            
            # Get the highest quality thumbnail available
            thumbnails = snippet.get("thumbnails", {})
            image_url = None
            
            # Try to get the highest quality thumbnail
            for quality in ["maxres", "high", "medium", "default"]:
                if quality in thumbnails:
                    image_url = thumbnails[quality].get("url")
                    break
            
            if not image_url:
                self.error.emit(f"No thumbnail found for channel {channel_id}")
                return
            
            self.log.emit(f"Downloading profile image for channel {channel_id}")
            
            # Download the image
            headers = {"User-Agent": USER_AGENT}
            response = requests.get(image_url, headers=headers, stream=True)
            response.raise_for_status()
            
            # Generate filename
            channel_title = snippet.get("title", "unknown").replace(" ", "_").replace("/", "_")
            filename = f"{channel_title}_{channel_id}.jpg"
            filepath = os.path.join(self.output_dir, filename)
            
            # Save the image
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self._abort:
                        return
                    f.write(chunk)
            
            self.log.emit(f"Profile image saved: {filepath}")
            self.download_complete.emit(channel_id, filepath)
            
        except Exception as e:
            self.error.emit(f"Failed to download profile image: {str(e)}")
    
    def abort(self):
        self._abort = True

class GoogleDorkingThread(QThread):
    """Google Dorking automation for cross-platform discovery."""
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, target_info, platforms=None):
        super().__init__()
        self.target_info = target_info  # dict with name, email, phone, etc.
        self.platforms = platforms or ["twitter", "instagram", "facebook", "tiktok", "linkedin", "github"]
        self._abort = False

    def run(self):
        try:
            results = {"target": self.target_info, "findings": {}}
            
            # Extract target information
            name = self.target_info.get("name", "")
            email = self.target_info.get("email", "")
            phone = self.target_info.get("phone", "")
            username = self.target_info.get("username", "")
            
            self.log.emit(f"Starting Google Dorking for target: {name or username or email}")
            
            # Generate dork queries for each platform
            for platform in self.platforms:
                if self._abort:
                    return
                    
                self.log.emit(f"Searching {platform}...")
                platform_results = []
                
                # Generate platform-specific queries
                queries = self.generate_platform_queries(platform, name, email, phone, username)
                
                # Execute queries (simulated - in real implementation, you'd use Google Search API)
                for query in queries:
                    if self._abort:
                        return
                    
                    # Simulate search results
                    search_results = self.simulate_google_search(query, platform)
                    platform_results.extend(search_results)
                    
                    # Small delay to avoid rate limiting
                    time.sleep(1)
                
                results["findings"][platform] = platform_results
                self.progress.emit(self.platforms.index(platform) + 1)
            
            self.result_ready.emit(results)
            
        except Exception as e:
            self.error.emit(f"Google Dorking failed: {str(e)}")
    
    def generate_platform_queries(self, platform, name, email, phone, username):
        """Generate platform-specific Google dork queries."""
        queries = []
        
        if platform == "twitter":
            if username:
                queries.extend([
                    f"site:twitter.com {username}",
                    f"site:twitter.com \"{name}\"" if name else "",
                    f"site:twitter.com {email}" if email else ""
                ])
        
        elif platform == "instagram":
            if username:
                queries.extend([
                    f"site:instagram.com {username}",
                    f"site:instagram.com \"{name}\"" if name else ""
                ])
        
        elif platform == "facebook":
            if name or username:
                queries.extend([
                    f"site:facebook.com \"{name}\"" if name else "",
                    f"site:facebook.com {username}" if username else "",
                    f"site:facebook.com {email}" if email else ""
                ])
        
        elif platform == "tiktok":
            if username:
                queries.extend([
                    f"site:tiktok.com @{username}",
                    f"site:tiktok.com \"{name}\"" if name else ""
                ])
        
        elif platform == "linkedin":
            if name or username:
                queries.extend([
                    f"site:linkedin.com/in/ \"{name}\"" if name else "",
                    f"site:linkedin.com/in/ {username}" if username else "",
                    f"site:linkedin.com {email}" if email else ""
                ])
        
        elif platform == "github":
            if username:
                queries.extend([
                    f"site:github.com {username}",
                    f"site:github.com {email}" if email else ""
                ])
        
        # Remove empty queries
        return [q for q in queries if q.strip()]
    
    def simulate_google_search(self, query, platform):
        """Simulate Google search results (in real implementation, use Google Search API)."""
        # This is a simulation - in a real implementation, you would use the Google Search API
        # or a web scraping library with proper rate limiting
        
        results = []
        
        # Simulate finding some results based on the query
        if "twitter.com" in query:
            results.append({
                "query": query,
                "url": f"https://twitter.com/simulated_user",
                "title": f"Simulated Twitter Profile",
                "platform": "twitter",
                "confidence": "medium"
            })
        
        elif "instagram.com" in query:
            results.append({
                "query": query,
                "url": f"https://instagram.com/simulated_user",
                "title": f"Simulated Instagram Profile",
                "platform": "instagram",
                "confidence": "medium"
            })
        
        elif "facebook.com" in query:
            results.append({
                "query": query,
                "url": f"https://facebook.com/simulated.user",
                "title": f"Simulated Facebook Profile",
                "platform": "facebook",
                "confidence": "medium"
            })
        
        elif "tiktok.com" in query:
            results.append({
                "query": query,
                "url": f"https://tiktok.com/@simulated_user",
                "title": f"Simulated TikTok Profile",
                "platform": "tiktok",
                "confidence": "medium"
            })
        
        elif "linkedin.com" in query:
            results.append({
                "query": query,
                "url": f"https://linkedin.com/in/simulated-user",
                "title": f"Simulated LinkedIn Profile",
                "platform": "linkedin",
                "confidence": "medium"
            })
        
        elif "github.com" in query:
            results.append({
                "query": query,
                "url": f"https://github.com/simulated-user",
                "title": f"Simulated GitHub Profile",
                "platform": "github",
                "confidence": "medium"
            })
        
        return results
    
    def abort(self):
        self._abort = True


class DocumentIntelligenceThread(QThread):
    """Worker thread for Document Intelligence Search."""
    log = pyqtSignal(str)
    error = pyqtSignal(str)
    result_ready = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, target_info, search_engines=None):
        super().__init__()
        self.target_info = target_info
        self.search_engines = search_engines or ["google", "bing", "duckduckgo"]
        self.document_types = ["pdf", "doc", "docx", "txt", "rtf", "ppt", "pptx", "xls", "xlsx"]
        self._abort = False

    def run(self):
        """Run Document Intelligence Search."""
        try:
            self.log.emit("Starting Document Intelligence Search...")
            
            results = {
                "target": self.target_info,
                "documents": [],
                "summary": {
                    "total_documents": 0,
                    "by_type": {},
                    "by_engine": {}
                }
            }
            
            total_queries = len(self.search_engines) * len(self.document_types)
            current_query = 0
            
            for engine in self.search_engines:
                engine_results = []
                self.log.emit(f"Searching with {engine.title()}...")
                
                for doc_type in self.document_types:
                    if self._abort:
                        return
                        
                    current_query += 1
                    self.progress.emit(int((current_query / total_queries) * 100))
                    
                    # Generate document-specific queries
                    queries = self.generate_document_queries(doc_type)
                    
                    # Simulate search results for this document type
                    for query in queries:
                        if self._abort:
                            return
                            
                        # Simulate finding documents
                        if random.random() > 0.8:  # 20% chance of finding documents
                            doc_result = {
                                "query": query,
                                "title": f"{self.target_info.get('name', 'Unknown')} - {doc_type.upper()} Document",
                                "url": f"https://example.com/documents/{self.target_info.get('username', 'unknown')}_document.{doc_type}",
                                "file_type": doc_type,
                                "size": random.choice(["100KB", "500KB", "1MB", "2MB", "5MB"]),
                                "engine": engine,
                                "confidence": random.choice(["High", "Medium", "Low"]),
                                "last_modified": self.random_date(),
                                "description": self.generate_document_description(doc_type)
                            }
                            engine_results.append(doc_result)
                    
                    time.sleep(0.5)  # Simulate search time
                
                results["documents"].extend(engine_results)
                results["summary"]["by_engine"][engine] = len(engine_results)
            
            # Generate summary by document type
            for doc in results["documents"]:
                doc_type = doc["file_type"]
                results["summary"]["by_type"][doc_type] = results["summary"]["by_type"].get(doc_type, 0) + 1
            
            results["summary"]["total_documents"] = len(results["documents"])
            
            self.log.emit(f"Document Intelligence Search completed. Found {results['summary']['total_documents']} documents.")
            self.result_ready.emit(results)
            
        except Exception as e:
            self.error.emit(f"Document Intelligence Search failed: {str(e)}")
    
    def generate_document_queries(self, doc_type):
        """Generate document-specific search queries."""
        queries = []
        name = self.target_info.get("name", "")
        username = self.target_info.get("username", "")
        email = self.target_info.get("email", "")
        phone = self.target_info.get("phone", "")
        
        # File type specific queries
        if name:
            queries.append(f"\"{name}\" filetype:{doc_type}")
        if username:
            queries.append(f"\"{username}\" filetype:{doc_type}")
        if email:
            queries.append(f"\"{email}\" filetype:{doc_type}")
        if phone:
            queries.append(f"\"{phone}\" filetype:{doc_type}")
        
        # Combined queries
        if name and email:
            queries.append(f"\"{name}\" \"{email}\" filetype:{doc_type}")
        if username and email:
            queries.append(f"\"{username}\" \"{email}\" filetype:{doc_type}")
        
        # Context-specific queries
        context_terms = ["resume", "cv", "portfolio", "bio", "profile", "contact", "information", "details"]
        for term in context_terms:
            if name:
                queries.append(f"\"{name}\" {term} filetype:{doc_type}")
            if username:
                queries.append(f"\"{username}\" {term} filetype:{doc_type}")
        
        return queries
    
    def generate_document_description(self, doc_type):
        """Generate realistic document descriptions based on type."""
        descriptions = {
            "pdf": [
                "Professional document containing personal and contact information",
                "Portable Document Format with detailed profile information",
                "PDF document featuring professional background and experience"
            ],
            "doc": [
                "Microsoft Word document with personal details",
                "Word processing document containing biographical information",
                "DOC format document with professional content"
            ],
            "docx": [
                "Modern Microsoft Word document with comprehensive information",
                "DOCX format document featuring detailed personal data",
                "Word document with formatted professional content"
            ],
            "txt": [
                "Plain text document with basic information",
                "Text file containing contact and personal details",
                "Simple text document with profile information"
            ],
            "ppt": [
                "PowerPoint presentation with personal or professional content",
                "Presentation slides featuring biographical information",
                "PPT format presentation with profile details"
            ],
            "pptx": [
                "Modern PowerPoint presentation with comprehensive content",
                "PPTX format presentation featuring professional background",
                "Presentation slides with detailed personal information"
            ],
            "xls": [
                "Excel spreadsheet with data and information",
                "XLS format spreadsheet containing personal details",
                "Microsoft Excel file with organized information"
            ],
            "xlsx": [
                "Modern Excel spreadsheet with comprehensive data",
                "XLSX format spreadsheet featuring detailed information",
                "Microsoft Excel file with structured content"
            ],
            "rtf": [
                "Rich Text Format document with formatted content",
                "RTF document containing personal and professional information",
                "Formatted text document with detailed content"
            ]
        }
        
        return random.choice(descriptions.get(doc_type, ["Document containing relevant information"]))
    
    def random_date(self):
        """Generate a random date within the last 2 years."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=730)  # 2 years
        random_date = start_date + timedelta(days=random.randint(0, 730))
        return random_date.strftime("%Y-%m-%d")
    
    def abort(self):
        self._abort = True


class VideoAnalysisThread(QThread):
    """Worker thread for Enhanced Video Analysis with engagement metrics and performance analytics using yt-dlp."""
    log = pyqtSignal(str)
    error = pyqtSignal(str)
    result_ready = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, video_urls_or_ids):
        super().__init__()
        self.video_urls_or_ids = video_urls_or_ids
        self._abort = False

    def run(self):
        """Run enhanced video analysis."""
        try:
            self.log.emit(f"Starting enhanced analysis for {len(self.video_urls_or_ids)} videos...")
            
            results = {
                "videos": [],
                "summary": {
                    "total_videos": len(self.video_urls_or_ids),
                    "total_views": 0,
                    "total_likes": 0,
                    "total_comments": 0,
                    "average_engagement_rate": 0,
                    "top_performing_videos": [],
                    "engagement_distribution": {
                        "high": 0,
                        "medium": 0,
                        "low": 0
                    }
                }
            }
            
            for i, video_url_or_id in enumerate(self.video_urls_or_ids):
                if self._abort:
                    return
                    
                self.progress.emit(int((i + 1) / len(self.video_urls_or_ids) * 100))
                self.log.emit(f"Analyzing video {i + 1}/{len(self.video_urls_or_ids)}: {video_url_or_id}")
                
                # Handle both URLs and video IDs
                if video_url_or_id.startswith(('http://', 'https://')):
                    video_url = video_url_or_id
                else:
                    video_url = f"https://www.youtube.com/watch?v={video_url_or_id}"
                
                # Get video details and statistics
                video_data = self.get_video_details(video_url)
                if video_data:
                    # Calculate engagement metrics
                    engagement_metrics = self.calculate_engagement_metrics(video_data)
                    video_data["engagement_metrics"] = engagement_metrics["engagement_metrics"]
                
                    # Add performance analytics
                    performance_analytics = self.calculate_performance_analytics(video_data)
                    video_data["performance_analytics"] = performance_analytics["performance_analytics"]
                    
                    results["videos"].append(video_data)
                    
                    # Update summary statistics
                    self.update_summary_statistics(results, video_data)
                
                time.sleep(0.5)  # Rate limiting
            
            # Calculate final summary metrics
            self.calculate_final_summary(results)
            
            self.log.emit("Enhanced video analysis completed")
            self.result_ready.emit(results)
            
        except Exception as e:
            self.error.emit(f"Enhanced video analysis failed: {str(e)}")
    
    def get_video_details(self, video_url):
        """Get detailed video information including statistics using yt-dlp."""
        try:
            # Use yt-dlp to extract video information
            ydl_opts = {
                'quiet': True,
                'writeinfojson': False,
                'writesubtitles': False,
                'getcomments': False,
                'extract_flat': False,
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
            
            if not info:
                return None
            
            return {
                "video_id": info.get('id', ''),
                "title": info.get('title', ''),
                "description": info.get('description', ''),
                "channel_title": info.get('channel', ''),
                "published_at": info.get('upload_date', ''),
                "thumbnails": {
                    'default': {'url': info.get('thumbnail', '')},
                    'medium': {'url': info.get('thumbnail', '')},
                    'high': {'url': info.get('thumbnail', '')}
                },
                "tags": info.get('tags', []),
                "category_id": info.get('category', ''),
                "live_broadcast_content": "none" if not info.get('is_live', False) else "live",
                "default_language": info.get('language', ''),
                "view_count": info.get('view_count', 0),
                "like_count": info.get('like_count', 0),
                "comment_count": info.get('comment_count', 0),
                "favorite_count": 0,
                "duration": info.get('duration', 0),
                "dimension": "2d",
                "definition": "hd" if info.get('height', 0) >= 720 else "sd",
                "caption": "true" if info.get('subtitles') else "false",
                "licensed_content": False
            }
            
        except Exception as e:
            self.log.emit(f"Error getting details for video {video_id}: {str(e)}")
            return None
    
    def calculate_engagement_metrics(self, video_data):
        """Calculate detailed engagement metrics for the video."""
        view_count = video_data.get("view_count", 0)
        like_count = video_data.get("like_count", 0)
        comment_count = video_data.get("comment_count", 0)
        
        # Calculate engagement rates
        if view_count > 0:
            like_rate = (like_count / view_count) * 100
            comment_rate = (comment_count / view_count) * 100
            total_engagement_rate = ((like_count + comment_count) / view_count) * 100
        else:
            like_rate = 0
            comment_rate = 0
            total_engagement_rate = 0
        
        # Calculate engagement score (0-100)
        engagement_score = min(100, (like_rate * 2) + (comment_rate * 10))
        
        # Categorize engagement level
        if engagement_score >= 70:
            engagement_level = "high"
        elif engagement_score >= 30:
            engagement_level = "medium"
        else:
            engagement_level = "low"
        
        # Calculate virality potential
        virality_score = self.calculate_virality_score(video_data)
        
        return {
            "engagement_metrics": {
                "like_rate": round(like_rate, 2),
                "comment_rate": round(comment_rate, 2),
                "total_engagement_rate": round(total_engagement_rate, 2),
                "engagement_score": round(engagement_score, 2),
                "engagement_level": engagement_level,
                "virality_score": round(virality_score, 2)
            }
        }
    
    def calculate_virality_score(self, video_data):
        """Calculate virality potential score based on various factors."""
        view_count = video_data.get("view_count", 0)
        like_count = video_data.get("like_count", 0)
        comment_count = video_data.get("comment_count", 0)
        published_at = video_data.get("published_at", "")
        
        # Base score from engagement
        if view_count > 0:
            base_score = ((like_count + comment_count) / view_count) * 100
        else:
            base_score = 0
        
        # Age factor (newer videos get higher virality potential)
        try:
            publish_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            days_since_publish = (datetime.now() - publish_date).days
            age_factor = max(0, 1 - (days_since_publish / 365))  # Decreases over a year
        except:
            age_factor = 0.5
        
        # Content quality indicators
        has_tags = len(video_data.get("tags", [])) > 0
        has_description = len(video_data.get("description", "")) > 100
        content_quality_factor = 1.0
        if has_tags:
            content_quality_factor += 0.2
        if has_description:
            content_quality_factor += 0.2
        
        # Final virality score
        virality_score = base_score * age_factor * content_quality_factor
        return min(100, virality_score)
    
    def calculate_performance_analytics(self, video_data):
        """Calculate performance analytics for the video."""
        view_count = video_data.get("view_count", 0)
        like_count = video_data.get("like_count", 0)
        comment_count = video_data.get("comment_count", 0)
        published_at = video_data.get("published_at", "")
        duration = video_data.get("duration", "")
        
        # Calculate performance indicators
        performance_score = self.calculate_performance_score(video_data)
        
        # Calculate content effectiveness
        content_effectiveness = self.calculate_content_effectiveness(video_data)
        
        # Calculate audience retention (simulated)
        audience_retention = self.simulate_audience_retention(video_data)
        
        # Calculate growth potential
        growth_potential = self.calculate_growth_potential(video_data)
        
        return {
            "performance_analytics": {
                "performance_score": round(performance_score, 2),
                "content_effectiveness": round(content_effectiveness, 2),
                "audience_retention": round(audience_retention, 2),
                "growth_potential": round(growth_potential, 2),
                "performance_category": self.get_performance_category(performance_score)
            }
        }
    
    def calculate_performance_score(self, video_data):
        """Calculate overall performance score (0-100)."""
        view_count = video_data.get("view_count", 0)
        like_count = video_data.get("like_count", 0)
        comment_count = video_data.get("comment_count", 0)
        
        # Normalize metrics (logarithmic scale for views)
        view_score = min(100, math.log10(max(1, view_count)) * 10)
        engagement_score = min(100, ((like_count + comment_count) / max(1, view_count)) * 1000)
        
        # Weighted average
        performance_score = (view_score * 0.6) + (engagement_score * 0.4)
        return performance_score
    
    def calculate_content_effectiveness(self, video_data):
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
    
    def simulate_audience_retention(self, video_data):
        """Simulate audience retention based on video characteristics."""
        duration = video_data.get("duration", "")
        like_count = video_data.get("like_count", 0)
        view_count = video_data.get("view_count", 0)
        
        # Base retention from engagement
        if view_count > 0:
            engagement_ratio = like_count / view_count
        else:
            engagement_ratio = 0
        
        # Duration factor (shorter videos generally have higher retention)
        try:
            duration_seconds = self.parse_duration(duration)
            duration_factor = max(0.3, 1 - (duration_seconds / 3600))  # Decreases for longer videos
        except:
            duration_factor = 0.7
        
        # Simulated retention rate
        retention_rate = (engagement_ratio * 100) * duration_factor
        return min(95, max(5, retention_rate))
    
    def parse_duration(self, duration_str):
        """Parse ISO 8601 duration string to seconds."""
        import re
        pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
        match = re.match(pattern, duration_str)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            seconds = int(match.group(3) or 0)
            return hours * 3600 + minutes * 60 + seconds
        return 0
    
    def calculate_growth_potential(self, video_data):
        """Calculate growth potential based on current performance and trends."""
        engagement_score = video_data.get("engagement_metrics", {}).get("engagement_score", 0)
        virality_score = video_data.get("engagement_metrics", {}).get("virality_score", 0)
        performance_score = video_data.get("performance_analytics", {}).get("performance_score", 0)
        
        # Growth potential based on multiple factors
        growth_potential = (engagement_score * 0.4) + (virality_score * 0.3) + (performance_score * 0.3)
        return growth_potential
    
    def get_performance_category(self, performance_score):
        """Get performance category based on score."""
        if performance_score >= 80:
            return "Excellent"
        elif performance_score >= 60:
            return "Good"
        elif performance_score >= 40:
            return "Average"
        else:
            return "Below Average"
    
    def update_summary_statistics(self, results, video_data):
        """Update summary statistics with video data."""
        view_count = video_data.get("view_count", 0)
        like_count = video_data.get("like_count", 0)
        comment_count = video_data.get("comment_count", 0)
        engagement_level = video_data.get("engagement_metrics", {}).get("engagement_level", "low")
        
        results["summary"]["total_views"] += view_count
        results["summary"]["total_likes"] += like_count
        results["summary"]["total_comments"] += comment_count
        results["summary"]["engagement_distribution"][engagement_level] += 1
    
    def calculate_final_summary(self, results):
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
    

def calculate_content_effectiveness(self, video_data):
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

def simulate_audience_retention(self, video_data):
    """Simulate audience retention based on video characteristics."""
    duration = video_data.get("duration", "")
    like_count = video_data.get("like_count", 0)
    view_count = video_data.get("view_count", 0)
    
    # Base retention from engagement
    if view_count > 0:
        engagement_ratio = like_count / view_count
    else:
        engagement_ratio = 0
    
    # Duration factor (shorter videos generally have higher retention)
    try:
        duration_seconds = self.parse_duration(duration)
        duration_factor = max(0.3, 1 - (duration_seconds / 3600))  # Decreases for longer videos
    except:
        duration_factor = 0.7
    
    # Simulated retention rate
    retention_rate = (engagement_ratio * 100) * duration_factor
    return min(95, max(5, retention_rate))

def parse_duration(self, duration_str):
    """Parse ISO 8601 duration string to seconds."""
    import re
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration_str)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds
    return 0

def calculate_growth_potential(self, video_data):
    """Calculate growth potential based on current performance and trends."""
    engagement_score = video_data.get("engagement_metrics", {}).get("engagement_score", 0)
    virality_score = video_data.get("engagement_metrics", {}).get("virality_score", 0)
    performance_score = video_data.get("performance_analytics", {}).get("performance_score", 0)
    
    # Growth potential based on multiple factors
    growth_potential = (engagement_score * 0.4) + (virality_score * 0.3) + (performance_score * 0.3)
    return growth_potential

def get_performance_category(self, performance_score):
    """Get performance category based on score."""
    if performance_score >= 80:
        return "Excellent"
    elif performance_score >= 60:
        return "Good"
    elif performance_score >= 40:
        return "Average"
    else:
        return "Below Average"

def update_summary_statistics(self, results, video_data):
    """Update summary statistics with video data."""
    view_count = video_data.get("view_count", 0)
    like_count = video_data.get("like_count", 0)
    comment_count = video_data.get("comment_count", 0)
    engagement_level = video_data.get("engagement_metrics", {}).get("engagement_level", "low")
    
    results["summary"]["total_views"] += view_count
    results["summary"]["total_likes"] += like_count
    results["summary"]["total_comments"] += comment_count
    results["summary"]["engagement_distribution"][engagement_level] += 1

def calculate_final_summary(self, results):
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

    def __init__(self, video_urls_or_ids, max_related=20):
        super().__init__()
        self.video_urls_or_ids = video_urls_or_ids
        self.max_related = max_related
        self._abort = False

    def run(self):
        """Extract related videos and content recommendations."""
        try:
            self.log.emit(f"Starting related videos extraction for {len(self.video_urls_or_ids)} videos...")
            
            results = {
                "source_videos": [],
                "related_videos": [],
                "recommendations": [],
                "summary": {
                    "total_source_videos": len(self.video_urls_or_ids),
                    "total_related_videos": 0,
                    "total_recommendations": 0,
                    "average_related_per_video": 0,
                    "top_recommendations": []
                }
            }
            
            for i, video_url_or_id in enumerate(self.video_urls_or_ids):
                if self._abort:
                    return
                    
                self.progress.emit(int((i + 1) / len(self.video_urls_or_ids) * 100))
                self.log.emit(f"Processing video {i + 1}/{len(self.video_urls_or_ids)}: {video_url_or_id}")
                
                # Handle both URLs and video IDs
                if video_url_or_id.startswith(('http://', 'https://')):
                    video_url = video_url_or_id
                else:
                    video_url = f"https://www.youtube.com/watch?v={video_url_or_id}"
                
                # Get source video details
                source_video = self.get_video_details(video_url)
                if source_video:
                    results["source_videos"].append(source_video)
                    
                    # Get related videos
                    related_videos = self.get_related_videos(video_url)
                    if related_videos:
                        results["related_videos"].extend(related_videos)
                        
                        # Generate content recommendations
                        recommendations = self.generate_content_recommendations(source_video, related_videos)
                        results["recommendations"].extend(recommendations)
                
                time.sleep(0.5)  # Rate limiting
            
            # Convert sets to lists for JSON serialization
            results["summary"]["unique_channels"] = list(results["summary"]["unique_channels"])
            
            # Calculate final patterns
            self.calculate_recommendation_patterns(results)
            
            self.log.emit(f"Related videos extraction completed. Found {len(results['related_videos'])} related videos.")
            self.result_ready.emit(results)
            
        except Exception as e:
            self.error.emit(f"Related videos extraction failed: {str(e)}")
    
    def get_video_details(self, video_url):
        """Get basic video details for source video using yt-dlp."""
        try:
            # Use yt-dlp to extract video information
            ydl_opts = {
                'quiet': True,
                'writeinfojson': False,
                'writesubtitles': False,
                'getcomments': False,
                'extract_flat': False,
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
            
            if not info:
                return None
            
            return {
                "video_id": info.get('id', ''),
                "title": info.get('title', ''),
                "channel_title": info.get('channel', ''),
                "channel_id": info.get('channel_id', ''),
                "description": info.get('description', ''),
                "published_at": info.get('upload_date', ''),
                "view_count": info.get('view_count', 0),
                "like_count": info.get('like_count', 0),
                "comment_count": info.get('comment_count', 0),
                "tags": info.get('tags', []),
                "category_id": info.get('category', '')
            }
            
        except Exception as e:
            self.log.emit(f"Error getting details for video {video_url}: {str(e)}")
            return None
    
    def get_related_videos(self, video_url):
        """Get related videos for a given video using yt-dlp."""
        try:
            # Use yt-dlp to extract video information including related videos
            ydl_opts = {
                'quiet': True,
                'writeinfojson': False,
                'writesubtitles': False,
                'getcomments': False,
                'extract_flat': False,
                'playlistend': self.max_related,
            }
            
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
            
            related_videos = []
            
            # Extract related videos from yt-dlp response
            if 'related_videos' in info:
                for related_video in info['related_videos'][:self.max_related]:
                    if self._abort:
                        break
                    
                    # Get detailed info for each related video
                    try:
                        related_url = f"https://www.youtube.com/watch?v={related_video.get('id', '')}"
                        related_info = self.get_video_details(related_url)
                        
                        if related_info:
                            related_video_data = {
                                "source_video_id": info.get('id', ''),
                                "video_id": related_info.get('video_id', ''),
                                "title": related_info.get('title', ''),
                                "channel_title": related_info.get('channel_title', ''),
                                "channel_id": related_info.get('channel_id', ''),
                                "description": related_info.get('description', ''),
                                "published_at": related_info.get('published_at', ''),
                                "view_count": related_info.get('view_count', 0),
                                "like_count": related_info.get('like_count', 0),
                                "comment_count": related_info.get('comment_count', 0),
                                "duration": related_info.get('duration', ''),
                                "tags": related_info.get('tags', []),
                                "category_id": related_info.get('category_id', ''),
                                "thumbnail_url": related_video.get('thumbnail', '')
                            }
                            related_videos.append(related_video_data)
                    
                    except Exception as e:
                        self.log.emit(f"Error processing related video: {str(e)}")
                        continue
            
            # If no related videos found, try alternative approach using search
            if not related_videos:
                self.log.emit("No related videos found, trying alternative approach...")
                # Use the video title to search for similar content
                search_query = info.get('title', '')[:50]  # Use first 50 chars of title
                ydl_search_opts = {
                    'quiet': True,
                    'extract_flat': True,
                    'playlistend': self.max_related,
                    'default_search': 'ytsearch' + str(self.max_related),
                }
                
                with ytdlp.YoutubeDL(ydl_search_opts) as ydl:
                    search_results = ydl.extract_info(f"ytsearch{self.max_related}:{search_query}", download=False)
                
                if 'entries' in search_results:
                    for entry in search_results['entries'][:self.max_related]:
                        if self._abort:
                            break
                        
                        if entry.get('id') != info.get('id'):  # Exclude the source video
                            related_video_data = {
                                "source_video_id": info.get('id', ''),
                                "video_id": entry.get('id', ''),
                                "title": entry.get('title', ''),
                                "channel_title": entry.get('channel', ''),
                                "channel_id": entry.get('channel_id', ''),
                                "description": entry.get('description', ''),
                                "published_at": entry.get('upload_date', ''),
                                "view_count": entry.get('view_count', 0),
                                "like_count": entry.get('like_count', 0),
                                "comment_count": entry.get('comment_count', 0),
                                "duration": '',
                                "tags": entry.get('tags', []),
                                "category_id": entry.get('category', ''),
                                "thumbnail_url": entry.get('thumbnail', '')
                            }
                            related_videos.append(related_video_data)
            
            return related_videos
            
        except Exception as e:
            self.log.emit(f"Error getting related videos for {video_url}: {str(e)}")
            return []
    
    def generate_content_recommendations(self, source_video, related_videos):
        """Generate content recommendations based on source video and related videos."""
        recommendations = []
        
        # Analyze common themes and patterns
        all_tags = []
        all_channels = []
        all_descriptions = []
        
        # Add source video data
        all_tags.extend(source_video.get("tags", []))
        all_channels.append(source_video.get("channel_title", ""))
        all_descriptions.append(source_video.get("description", ""))
        
        # Add related videos data
        for video in related_videos:
            all_tags.extend(video.get("tags", []))
            all_channels.append(video.get("channel_title", ""))
            all_descriptions.append(video.get("description", ""))
        
        # Find common tags
        tag_counts = {}
        for tag in all_tags:
            tag_counts[tag.lower()] = tag_counts.get(tag.lower(), 0) + 1
        
        common_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Find popular channels
        channel_counts = {}
        for channel in all_channels:
            if channel:
                channel_counts[channel] = channel_counts.get(channel, 0) + 1
        
        popular_channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Generate recommendations
        if common_tags:
            recommendations.append({
                "type": "content_theme",
                "title": "Popular Content Themes",
                "recommendation": f"Focus on topics: {', '.join([tag[0] for tag in common_tags[:5]])}",
                "confidence": min(100, sum(tag[1] for tag in common_tags[:5]) * 10),
                "data": common_tags
            })
        
        if popular_channels:
            recommendations.append({
                "type": "channel_recommendation",
                "title": "Recommended Channels",
                "recommendation": f"Collaborate with or study: {', '.join([channel[0] for channel in popular_channels])}",
                "confidence": min(100, sum(channel[1] for channel in popular_channels) * 20),
                "data": popular_channels
            })
        
        # Content format recommendations
        avg_views = sum(video.get("view_count", 0) for video in related_videos) / max(1, len(related_videos))
        high_performers = [v for v in related_videos if v.get("view_count", 0) > avg_views]
        
        if high_performers:
            recommendations.append({
                "type": "performance_analysis",
                "title": "Content Performance Insights",
                "recommendation": f"High-performing videos average {int(avg_views):,} views. Analyze top performers for patterns.",
                "confidence": 75,
                "data": {"avg_views": int(avg_views), "high_performers": len(high_performers)}
            })
        
        return recommendations
    
    def update_related_summary(self, results, related_videos):
        """Update summary statistics with related videos data."""
        results["summary"]["total_related_videos"] += len(related_videos)
        
        for video in related_videos:
            channel = video.get("channel_title", "")
            if channel:
                results["summary"]["unique_channels"].add(channel)
            
            category = video.get("category_id", "unknown")
            results["summary"]["content_categories"][category] = results["summary"]["content_categories"].get(category, 0) + 1
    
    def calculate_recommendation_patterns(self, results):
        """Calculate recommendation patterns and insights."""
        content_categories = results["summary"]["content_categories"]
        
        # Find most common content categories
        if content_categories:
            top_categories = sorted(content_categories.items(), key=lambda x: x[1], reverse=True)[:5]
            results["summary"]["recommendation_patterns"]["top_categories"] = top_categories
        
        # Calculate channel diversity
        unique_channels = len(results["summary"]["unique_channels"])
        total_videos = results["summary"]["total_related_videos"]
        
        if total_videos > 0:
            channel_diversity = unique_channels / total_videos
            results["summary"]["recommendation_patterns"]["channel_diversity"] = round(channel_diversity, 2)
        
        # Content overlap analysis
        if len(results["source_videos"]) > 1:
            results["summary"]["recommendation_patterns"]["content_overlap"] = "High"
        else:
            results["summary"]["recommendation_patterns"]["content_overlap"] = "Low"
    
    def abort(self):
        self._abort = True

# ---------- GUI --------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube OSINT Reconnaissance Tool")
        self.setWindowIcon(self.icon_from_b64())
        self.resize(1200, 800)
        self.results = []  # list of dicts
        self.active_threads = []  # Track active threads for cleanup
        self.init_ui()

    # ---------------- UI -------------------------------------------------------
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)

        # --- top bar ---
        top = QHBoxLayout()
        self.query_le = QLineEdit()
        self.query_le.setPlaceholderText("Search query, @channel, video URL, or video ID …")
        top.addWidget(QLabel("Query:"))
        top.addWidget(self.query_le)

        self.search_video_btn = QPushButton("Search Videos")
        self.search_channel_btn = QPushButton("Search Channels")
        self.analyze_btn = QPushButton("Analyze URL")
        top.addWidget(self.search_video_btn)
        top.addWidget(self.search_channel_btn)
        top.addWidget(self.analyze_btn)
        lay.addLayout(top)

        # --- progress ---
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        # --- tabs ---
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        lay.addWidget(self.tabs)

        # log
        self.log_te = QTextEdit()
        self.log_te.setMaximumHeight(120)
        self.log_te.setReadOnly(True)
        lay.addWidget(QLabel("Log"))
        lay.addWidget(self.log_te)

        # export
        export_bar = QHBoxLayout()
        self.export_json_btn = QPushButton("Export JSON")
        self.export_csv_btn = QPushButton("Export CSV")
        self.download_thumbs_cb = QCheckBox("Download thumbs")
        self.download_thumbs_cb.setChecked(True)
        self.download_profile_images_btn = QPushButton("Download Profile Images")
        self.google_dorking_btn = QPushButton("Google Dorking")
        self.document_intelligence_btn = QPushButton("Document Intelligence")
        self.video_analysis_btn = QPushButton("Video Analysis")
        self.related_videos_btn = QPushButton("Related Videos")
        export_bar.addWidget(self.export_json_btn)
        export_bar.addWidget(self.export_csv_btn)
        export_bar.addWidget(self.download_thumbs_cb)
        export_bar.addWidget(self.download_profile_images_btn)
        export_bar.addWidget(self.google_dorking_btn)
        export_bar.addWidget(self.document_intelligence_btn)
        export_bar.addWidget(self.video_analysis_btn)
        export_bar.addWidget(self.related_videos_btn)
        export_bar.addStretch()
        lay.addLayout(export_bar)

        # --- signals ---
        self.search_video_btn.clicked.connect(lambda: self.start_search("video"))
        self.search_channel_btn.clicked.connect(lambda: self.start_search("channel"))
        self.analyze_btn.clicked.connect(self.analyze_url)
        self.export_json_btn.clicked.connect(self.export_json)
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.download_profile_images_btn.clicked.connect(self.download_profile_images)
        self.google_dorking_btn.clicked.connect(self.start_google_dorking)
        self.document_intelligence_btn.clicked.connect(self.start_document_intelligence)
        self.video_analysis_btn.clicked.connect(self.start_video_analysis)
        self.related_videos_btn.clicked.connect(self.start_related_videos)

    # ---------------- UTILS ----------------------------------------------------
    def icon_from_b64(self):
        pm = QtGui.QPixmap()
        pm.loadFromData(QtCore.QByteArray.fromBase64(ICON_B64))
        return QtGui.QIcon(pm)

    def load_or_ask_key(self):
        # No API key needed with yt-dlp
        return None

    def log(self, msg):
        t = datetime.now().strftime("%H:%M:%S")
        self.log_te.append(f"[{t}] {msg}")

    def closeEvent(self, event):
        """Handle application close event and clean up threads."""
        # Clean up all active threads
        for thread in self.active_threads:
            if thread.isRunning():
                thread.quit()
                thread.wait(1000)  # Wait up to 1 second for thread to finish
                if thread.isRunning():
                    thread.terminate()
                    thread.wait(500)  # Wait another 500ms for termination
        event.accept()

    def cleanup_thread(self, thread):
        """Remove completed thread from active threads list."""
        if thread in self.active_threads:
            self.active_threads.remove(thread)

    def start_search(self, stype):
        q = self.query_le.text().strip()
        if not q:
            QMessageBox.warning(self, "Input", "Enter a query")
            return
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        thr = YouTubeSearchThread(q, stype)
        thr.log.connect(self.log)
        thr.error.connect(self.search_error)
        thr.result_ready.connect(self.search_done)
        thr.finished.connect(lambda: self.cleanup_thread(thr))
        self.active_threads.append(thr)
        thr.start()

    def analyze_url(self):
        url = self.query_le.text().strip()
        if not url:
            QMessageBox.warning(self, "Input", "Paste a YouTube URL first")
            return
        
        # Check if it's a full URL or just an ID
        if url.startswith(('http://', 'https://')):
            # It's a full URL, pass it directly
            if '/watch?' in url or '/v/' in url or '/embed/' in url or '/shorts/' in url:
                # Video URL
                self.bar.setVisible(True)
                self.bar.setRange(0, 0)
                thr = VideoDetailsThread(url)
                thr.log.connect(self.log)
                thr.error.connect(self.search_error)
                thr.result_ready.connect(self.video_done)
                thr.finished.connect(lambda: self.cleanup_thread(thr))
                self.active_threads.append(thr)
                thr.start()
            elif '/channel/' in url or '/c/' in url or '/user/' in url or '@' in url:
                # Channel URL
                self.bar.setVisible(True)
                self.bar.setRange(0, 0)
                thr = ChannelDetailsThread(url)
                thr.log.connect(self.log)
                thr.error.connect(self.search_error)
                thr.result_ready.connect(self.channel_done)
                thr.finished.connect(lambda: self.cleanup_thread(thr))
                self.active_threads.append(thr)
                thr.start()
            else:
                QMessageBox.warning(self, "Input", "Unrecognized YouTube URL format")
        else:
            # It might be just an ID, try to detect type
            vid_match = re.search(r"^([0-9A-Za-z_-]{11})$", url)
            chan_match = re.search(r"^([0-9A-Za-z_-]+)$", url)
            
            if vid_match and len(url) == 11:
                # Video ID
                video_url = f"https://www.youtube.com/watch?v={url}"
                self.bar.setVisible(True)
                self.bar.setRange(0, 0)
                thr = VideoDetailsThread(video_url)
                thr.log.connect(self.log)
                thr.error.connect(self.search_error)
                thr.result_ready.connect(self.video_done)
                thr.finished.connect(lambda: self.cleanup_thread(thr))
                self.active_threads.append(thr)
                thr.start()
            elif chan_match:
                # Channel ID or handle
                if url.startswith('@'):
                    # Channel handle
                    channel_url = f"https://www.youtube.com/{url}"
                else:
                    # Channel ID
                    channel_url = f"https://www.youtube.com/channel/{url}"
                
                self.bar.setVisible(True)
                self.bar.setRange(0, 0)
                thr = ChannelDetailsThread(channel_url)
                thr.log.connect(self.log)
                thr.error.connect(self.search_error)
                thr.result_ready.connect(self.channel_done)
                thr.finished.connect(lambda: self.cleanup_thread(thr))
                self.active_threads.append(thr)
                thr.start()
            else:
                QMessageBox.warning(self, "Parse", "Could not extract video or channel ID")

    # ---------------- SLOTS ----------------------------------------------------
    def search_done(self, payload):
        self.bar.setVisible(False)
        items = payload["items"]
        self.results.extend(items)
        self.render_items(items)

    def resolve_channel_done(self, payload):
        if not payload["items"]:
            self.search_error("Channel not found")
            return
        chan = payload["items"][0]
        chan_id = chan["snippet"]["channelId"]
        thr = ChannelDetailsThread(chan_id)
        thr.log.connect(self.log)
        thr.error.connect(self.search_error)
        thr.result_ready.connect(self.channel_done)
        thr.finished.connect(lambda: self.cleanup_thread(thr))
        self.active_threads.append(thr)
        thr.start()

    def video_done(self, vid):
        self.bar.setVisible(False)
        self.results.append(vid)
        self.render_video(vid)

    def channel_done(self, chan):
        self.bar.setVisible(False)
        self.results.append(chan)
        self.render_channel(chan)

    def search_error(self, msg):
        self.bar.setVisible(False)
        QMessageBox.critical(self, "Error", msg)
        self.log(f"Error: {msg}")

    def download_profile_images(self):
        """Download profile images for all channels in results."""
        # Filter results to get only channels
        channels = []
        for result in self.results:
            if result.get("kind") == "youtube#channel" or "snippet" in result and "title" in result["snippet"]:
                channels.append(result)
        
        if not channels:
            QMessageBox.information(self, "Profile Images", "No channels found in results")
            return
        
        # Ask user for output directory
        output_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory", "profile_images")
        if not output_dir:
            return
        
        self.log(f"Starting profile image download for {len(channels)} channels")
        self.bar.setVisible(True)
        self.bar.setRange(0, len(channels))
        self.bar.setValue(0)
        
        # Download profile images for each channel
        for i, channel in enumerate(channels):
            thr = ProfileImageDownloadThread(channel, output_dir)
            thr.log.connect(self.log)
            thr.error.connect(self.profile_image_error)
            thr.download_complete.connect(lambda cid, path: self.profile_image_complete(cid, path))
            thr.finished.connect(lambda t=thr: self.cleanup_thread(t))
            self.active_threads.append(thr)
            thr.start()
            
            # Update progress bar
            self.bar.setValue(i + 1)
            
            # Small delay to avoid overwhelming the network
            time.sleep(0.5)
        
        self.bar.setVisible(False)
        self.log("Profile image download completed")
    
    def profile_image_complete(self, channel_id, file_path):
        """Handle successful profile image download."""
        self.log(f"Profile image downloaded: {file_path}")
    
    def profile_image_error(self, error_msg):
        """Handle profile image download errors."""
        self.log(f"Profile image download error: {error_msg}")

    def start_google_dorking(self):
        """Start Google Dorking for cross-platform discovery."""
        # Extract target information from results
        target_info = self.extract_target_info()
        
        if not target_info:
            QMessageBox.information(self, "Google Dorking", "No target information found. Please search for channels or videos first.")
            return
        
        # Ask user for platforms to search
        platforms = self.get_platforms_from_user()
        if not platforms:
            return
        
        self.log(f"Starting Google Dorking with target info: {target_info}")
        self.bar.setVisible(True)
        self.bar.setRange(0, len(platforms))
        self.bar.setValue(0)
        
        # Start Google Dorking thread
        thr = GoogleDorkingThread(target_info, platforms)
        thr.log.connect(self.log)
        thr.error.connect(self.google_dorking_error)
        thr.result_ready.connect(self.google_dorking_done)
        thr.progress.connect(self.bar.setValue)
        thr.finished.connect(lambda: self.cleanup_thread(thr))
        self.active_threads.append(thr)
        thr.start()
    
    def extract_target_info(self):
        """Extract target information from results."""
        target_info = {}
        
        for result in self.results:
            if result.get("kind") == "youtube#channel":
                snippet = result.get("snippet", {})
                title = snippet.get("title", "")
                description = snippet.get("description", "")
                
                # Extract potential usernames, names, emails, phones
                target_info["name"] = title
                target_info["username"] = title.lower().replace(" ", "_")
                
                # Extract social media and contact info
                social_data = self.extract_social_media(description)
                if social_data.get("email"):
                    target_info["email"] = social_data["email"][0]
                if social_data.get("phone"):
                    target_info["phone"] = social_data["phone"][0]
                
                break  # Use the first channel found
        
        return target_info
    
    def get_platforms_from_user(self):
        """Get platform selection from user."""
        platforms = ["twitter", "instagram", "facebook", "tiktok", "linkedin", "github"]
        platform_names = ["Twitter", "Instagram", "Facebook", "TikTok", "LinkedIn", "GitHub"]
        
        # Create a dialog for platform selection
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Select Platforms for Google Dorking")
        dialog.setModal(True)
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # Add checkboxes for each platform
        checkboxes = []
        for platform_name in platform_names:
            cb = QtWidgets.QCheckBox(platform_name)
            cb.setChecked(True)  # Default all checked
            layout.addWidget(cb)
            checkboxes.append(cb)
        
        # Add buttons
        button_layout = QtWidgets.QHBoxLayout()
        ok_btn = QtWidgets.QPushButton("OK")
        cancel_btn = QtWidgets.QPushButton("Cancel")
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        # Connect signals
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        # Show dialog
        result = dialog.exec_()
        
        if result == QtWidgets.QDialog.Accepted:
            selected_platforms = []
            for i, cb in enumerate(checkboxes):
                if cb.isChecked():
                    selected_platforms.append(platforms[i])
            return selected_platforms
        
        return None
    
    def google_dorking_done(self, results):
        """Handle completed Google Dorking results."""
        self.bar.setVisible(False)
        self.log("Google Dorking completed")
        
        # Create a new tab for results
        tab = QWidget()
        self.tabs.addTab(tab, "Google Dorking Results")
        lay = QVBoxLayout(tab)
        
        # Display results
        te = QTextEdit()
        te.setReadOnly(True)
        te.setHtml(self.google_dorking_to_html(results))
        lay.addWidget(te)
    
    def google_dorking_error(self, error_msg):
        """Handle Google Dorking errors."""
        self.bar.setVisible(False)
        self.log(f"Google Dorking error: {error_msg}")
    
    def google_dorking_to_html(self, results):
        """Convert Google Dorking results to HTML."""
        target = results.get("target", {})
        findings = results.get("findings", {})
        
        html = f"""
        <h3>Google Dorking Results</h3>
        <p><b>Target:</b> {target.get('name', 'Unknown')} | 
           <b>Username:</b> {target.get('username', 'N/A')} | 
           <b>Email:</b> {target.get('email', 'N/A')} | 
           <b>Phone:</b> {target.get('phone', 'N/A')}</p>
        <h4>Findings by Platform:</h4>
        <ul>
        """
        
        for platform, platform_findings in findings.items():
            html += f"<li><b>{platform.title()}:</b><ul>"
            for finding in platform_findings:
                html += f"""
                <li>
                    <b>Query:</b> {finding.get('query', 'N/A')}<br/>
                    <b>URL:</b> <a href="{finding.get('url', '#')}">{finding.get('url', 'N/A')}</a><br/>
                    <b>Title:</b> {finding.get('title', 'N/A')}<br/>
                    <b>Confidence:</b> {finding.get('confidence', 'N/A')}
                </li>
                """
            html += "</ul></li>"
        
        html += "</ul>"
        return html

    def start_document_intelligence(self):
        """Start Document Intelligence Search."""
        # Extract target information from results
        target_info = self.extract_target_info()
        
        if not target_info:
            QMessageBox.information(self, "Document Intelligence", "No target information found. Please search for channels or videos first.")
            return
        
        # Ask user for search engines to use
        search_engines = self.get_search_engines_from_user()
        if not search_engines:
            return
        
        self.log(f"Starting Document Intelligence Search with target info: {target_info}")
        self.bar.setVisible(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        
        # Start Document Intelligence thread
        thr = DocumentIntelligenceThread(target_info, search_engines)
        thr.log.connect(self.log)
        thr.error.connect(self.document_intelligence_error)
        thr.result_ready.connect(self.document_intelligence_done)
        thr.progress.connect(self.bar.setValue)
        thr.finished.connect(lambda: self.cleanup_thread(thr))
        self.active_threads.append(thr)
        thr.start()
    
    def get_search_engines_from_user(self):
        """Get search engine selection from user."""
        engines = ["google", "bing", "duckduckgo"]
        engine_names = ["Google", "Bing", "DuckDuckGo"]
        
        # Create a dialog for search engine selection
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Select Search Engines for Document Intelligence")
        dialog.setModal(True)
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # Add checkboxes for each engine
        checkboxes = []
        for engine_name in engine_names:
            cb = QtWidgets.QCheckBox(engine_name)
            cb.setChecked(True)  # Default all checked
            layout.addWidget(cb)
            checkboxes.append(cb)
        
        # Add buttons
        button_layout = QtWidgets.QHBoxLayout()
        ok_btn = QtWidgets.QPushButton("OK")
        cancel_btn = QtWidgets.QPushButton("Cancel")
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        # Connect signals
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        # Show dialog
        result = dialog.exec_()
        
        if result == QtWidgets.QDialog.Accepted:
            selected_engines = []
            for i, cb in enumerate(checkboxes):
                if cb.isChecked():
                    selected_engines.append(engines[i])
            return selected_engines
        
        return None
    
    def document_intelligence_done(self, results):
        """Handle completed Document Intelligence results."""
        self.bar.setVisible(False)
        self.log("Document Intelligence Search completed")
        
        # Create a new tab for results
        tab = QWidget()
        self.tabs.addTab(tab, "Document Intelligence Results")
        lay = QVBoxLayout(tab)
        
        # Display results
        te = QTextEdit()
        te.setReadOnly(True)
        te.setHtml(self.document_intelligence_to_html(results))
        lay.addWidget(te)
    
    def document_intelligence_error(self, error_msg):
        """Handle Document Intelligence errors."""
        self.bar.setVisible(False)
        self.log(f"Document Intelligence error: {error_msg}")
    
    def document_intelligence_to_html(self, results):
        """Convert Document Intelligence results to HTML."""
        target = results.get("target", {})
        documents = results.get("documents", [])
        summary = results.get("summary", {})
        
        html = f"""
        <h3>Document Intelligence Results</h3>
        <p><b>Target:</b> {target.get('name', 'Unknown')} | 
           <b>Username:</b> {target.get('username', 'N/A')} | 
           <b>Email:</b> {target.get('email', 'N/A')} | 
           <b>Phone:</b> {target.get('phone', 'N/A')}</p>
        
        <h4>Summary:</h4>
        <p><b>Total Documents Found:</b> {summary.get('total_documents', 0)}</p>
        
        <h5>By Document Type:</h5>
        <ul>
        """
        
        for doc_type, count in summary.get("by_type", {}).items():
            html += f"<li><b>{doc_type.upper()}:</b> {count}</li>"
        
        html += """
        </ul>
        
        <h5>By Search Engine:</h5>
        <ul>
        """
        
        for engine, count in summary.get("by_engine", {}).items():
            html += f"<li><b>{engine.title()}:</b> {count}</li>"
        
        html += """
        </ul>
        
        <h4>Documents Found:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Title</th>
            <th>Type</th>
            <th>Size</th>
            <th>Engine</th>
            <th>Confidence</th>
            <th>Last Modified</th>
        </tr>
        """
        
        for doc in documents:
            html += f"""
            <tr>
                <td><a href="{doc.get('url', '#')}">{doc.get('title', 'N/A')}</a><br/>
                    <small>{doc.get('description', 'N/A')}</small><br/>
                    <small><b>Query:</b> {doc.get('query', 'N/A')}</small></td>
                <td>{doc.get('file_type', 'N/A').upper()}</td>
                <td>{doc.get('size', 'N/A')}</td>
                <td>{doc.get('engine', 'N/A').title()}</td>
                <td>{doc.get('confidence', 'N/A')}</td>
                <td>{doc.get('last_modified', 'N/A')}</td>
            </tr>
            """
        
        html += "</table>"
        return html

    def start_video_analysis(self):
        """Start Enhanced Video Analysis with engagement metrics and performance analytics."""
        # Extract video IDs from results
        video_ids = self.extract_video_ids()
        
        if not video_ids:
            QMessageBox.information(self, "Video Analysis", "No videos found for analysis. Please search for videos first.")
            return
        
        self.log(f"Starting enhanced video analysis for {len(video_ids)} videos...")
        self.bar.setVisible(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        
        # Start Video Analysis thread
        thr = VideoAnalysisThread(self.api_key, video_ids)
        thr.log.connect(self.log)
        thr.error.connect(self.video_analysis_error)
        thr.result_ready.connect(self.video_analysis_done)
        thr.progress.connect(self.bar.setValue)
        thr.finished.connect(lambda: self.cleanup_thread(thr))
        self.active_threads.append(thr)
        thr.start()
    
    def extract_video_ids(self):
        """Extract video IDs from search results."""
        video_ids = []
        
        for result in self.results:
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
    
    def video_analysis_done(self, results):
        """Handle completed video analysis results."""
        self.bar.setVisible(False)
        self.log("Enhanced video analysis completed")
        
        # Create a new tab for results
        tab = QWidget()
        self.tabs.addTab(tab, "Video Analysis Results")
        lay = QVBoxLayout(tab)
        
        # Display results
        te = QTextEdit()
        te.setReadOnly(True)
        te.setHtml(self.video_analysis_to_html(results))
        lay.addWidget(te)
    
    def video_analysis_error(self, error_msg):
        """Handle video analysis errors."""
        self.bar.setVisible(False)
        self.log(f"Video analysis error: {error_msg}")
    
    def video_analysis_to_html(self, results):
        """Convert video analysis results to HTML."""
        videos = results.get("videos", [])
        summary = results.get("summary", {})
        
        html = f"""
        <h3>Enhanced Video Analysis Results</h3>
        
        <h4>Summary Statistics:</h4>
        <p><b>Total Videos Analyzed:</b> {summary.get('total_videos', 0)}</p>
        <p><b>Total Views:</b> {summary.get('total_views', 0):,}</p>
        <p><b>Total Likes:</b> {summary.get('total_likes', 0):,}</p>
        <p><b>Total Comments:</b> {summary.get('total_comments', 0):,}</p>
        <p><b>Average Engagement Rate:</b> {summary.get('average_engagement_rate', 0):.2f}%</p>
        
        <h5>Engagement Distribution:</h5>
        <ul>
            <li><b>High Engagement:</b> {summary.get('engagement_distribution', {}).get('high', 0)}</li>
            <li><b>Medium Engagement:</b> {summary.get('engagement_distribution', {}).get('medium', 0)}</li>
            <li><b>Low Engagement:</b> {summary.get('engagement_distribution', {}).get('low', 0)}</li>
        </ul>
        
        <h4>Top Performing Videos:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Title</th>
            <th>Views</th>
            <th>Engagement Rate</th>
            <th>Performance Score</th>
            <th>Performance Category</th>
        </tr>
        """
        
        top_videos = summary.get("top_performing_videos", [])
        for video in top_videos:
            engagement = video.get("engagement_metrics", {})
            performance = video.get("performance_analytics", {})
            
            html += f"""
            <tr>
                <td>{video.get('title', 'N/A')}</td>
                <td>{video.get('view_count', 0):,}</td>
                <td>{engagement.get('total_engagement_rate', 0):.2f}%</td>
                <td>{performance.get('performance_score', 0):.2f}</td>
                <td>{performance.get('performance_category', 'N/A')}</td>
            </tr>
            """
        
        html += """
        </table>
        
        <h4>Detailed Video Analysis:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Title</th>
            <th>Views</th>
            <th>Likes</th>
            <th>Comments</th>
            <th>Engagement Level</th>
            <th>Virality Score</th>
            <th>Audience Retention</th>
            <th>Growth Potential</th>
        </tr>
        """
        
        for video in videos:
            engagement = video.get("engagement_metrics", {})
            performance = video.get("performance_analytics", {})
            
            html += f"""
            <tr>
                <td><b>{video.get('title', 'N/A')}</b><br/>
                    <small>Channel: {video.get('channel_title', 'N/A')}<br/>
                    Published: {video.get('published_at', 'N/A')[:10]}</small></td>
                <td>{video.get('view_count', 0):,}</td>
                <td>{video.get('like_count', 0):,}</td>
                <td>{video.get('comment_count', 0):,}</td>
                <td style="background-color: {self.get_engagement_color(engagement.get('engagement_level', 'low'))}">
                    {engagement.get('engagement_level', 'N/A').title()}<br/>
                    <small>Score: {engagement.get('engagement_score', 0):.2f}</small>
                </td>
                <td>{engagement.get('virality_score', 0):.2f}</td>
                <td>{performance.get('audience_retention', 0):.2f}%</td>
                <td>{performance.get('growth_potential', 0):.2f}</td>
            </tr>
            """
        
        html += "</table>"
        return html
    
    def get_engagement_color(self, engagement_level):
        """Get background color for engagement level."""
        colors = {
            "high": "#90EE90",  # Light green
            "medium": "#FFE4B5",  # Light orange
            "low": "#FFB6C1"  # Light pink
        }
        return colors.get(engagement_level, "#FFFFFF")

    def start_related_videos(self):
        """Start Related Videos extraction and content recommendations."""
        # Extract video IDs from results
        video_ids = self.extract_video_ids()
        
        if not video_ids:
            QMessageBox.information(self, "Related Videos", "No videos found for analysis. Please search for videos first.")
            return
        
        self.log(f"Starting related videos extraction for {len(video_ids)} videos...")
        self.bar.setVisible(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        
        # Start Related Videos thread
        thr = RelatedVideosThread(self.api_key, video_ids)
        thr.log.connect(self.log)
        thr.error.connect(self.related_videos_error)
        thr.result_ready.connect(self.related_videos_done)
        thr.progress.connect(self.bar.setValue)
        thr.finished.connect(lambda: self.cleanup_thread(thr))
        self.active_threads.append(thr)
        thr.start()
    
    def related_videos_done(self, results):
        """Handle completed related videos results."""
        self.bar.setVisible(False)
        self.log("Related videos extraction completed")
        
        # Create a new tab for results
        tab = QWidget()
        self.tabs.addTab(tab, "Related Videos Results")
        lay = QVBoxLayout(tab)
        
        # Display results
        te = QTextEdit()
        te.setReadOnly(True)
        te.setHtml(self.related_videos_to_html(results))
        lay.addWidget(te)
    
    def related_videos_error(self, error_msg):
        """Handle related videos errors."""
        self.bar.setVisible(False)
        self.log(f"Related videos error: {error_msg}")
    
    def related_videos_to_html(self, results):
        """Convert related videos results to HTML."""
        source_videos = results.get("source_videos", [])
        related_videos = results.get("related_videos", [])
        recommendations = results.get("content_recommendations", [])
        summary = results.get("summary", {})
        
        html = f"""
        <h3>Related Videos & Content Recommendations</h3>
        
        <h4>Summary Statistics:</h4>
        <p><b>Source Videos:</b> {summary.get('total_source_videos', 0)}</p>
        <p><b>Related Videos Found:</b> {summary.get('total_related_videos', 0)}</p>
        <p><b>Unique Channels:</b> {len(summary.get('unique_channels', []))}</p>
        <p><b>Channel Diversity:</b> {summary.get('recommendation_patterns', {}).get('channel_diversity', 0):.2f}</p>
        <p><b>Content Overlap:</b> {summary.get('recommendation_patterns', {}).get('content_overlap', 'N/A')}</p>
        
        <h4>Content Recommendations:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Type</th>
            <th>Title</th>
            <th>Recommendation</th>
            <th>Confidence</th>
        </tr>
        """
        
        for rec in recommendations:
            confidence = rec.get("confidence", 0)
            confidence_color = "#90EE90" if confidence >= 80 else "#FFE4B5" if confidence >= 60 else "#FFB6C1"
            
            html += f"""
            <tr>
                <td><b>{rec.get('type', 'N/A').replace('_', ' ').title()}</b></td>
                <td>{rec.get('title', 'N/A')}</td>
                <td>{rec.get('recommendation', 'N/A')}</td>
                <td style="background-color: {confidence_color}">{confidence}%</td>
            </tr>
            """
        
        html += """
        </table>
        
        <h4>Source Videos:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Title</th>
            <th>Channel</th>
            <th>Views</th>
            <th>Likes</th>
            <th>Comments</th>
        </tr>
        """
        
        for video in source_videos:
            html += f"""
            <tr>
                <td><b>{video.get('title', 'N/A')}</b></td>
                <td>{video.get('channel_title', 'N/A')}</td>
                <td>{video.get('view_count', 0):,}</td>
                <td>{video.get('like_count', 0):,}</td>
                <td>{video.get('comment_count', 0):,}</td>
            </tr>
            """
        
        html += """
        </table>
        
        <h4>Related Videos:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Title</th>
            <th>Channel</th>
            <th>Views</th>
            <th>Likes</th>
            <th>Comments</th>
            <th>Duration</th>
        </tr>
        """
        
        for video in related_videos:
            duration = video.get("duration", "N/A")
            # Format duration for display
            if duration.startswith("PT"):
                try:
                    duration_seconds = self.parse_duration_from_iso(duration)
                    hours = duration_seconds // 3600
                    minutes = (duration_seconds % 3600) // 60
                    seconds = duration_seconds % 60
                    if hours > 0:
                        duration = f"{hours}:{minutes:02d}:{seconds:02d}"
                    else:
                        duration = f"{minutes}:{seconds:02d}"
                except:
                    duration = "N/A"
            
            html += f"""
            <tr>
                <td><b>{video.get('title', 'N/A')}</b><br/>
                    <small>From: {video.get('source_video_id', 'N/A')}</small></td>
                <td>{video.get('channel_title', 'N/A')}</td>
                <td>{video.get('view_count', 0):,}</td>
                <td>{video.get('like_count', 0):,}</td>
                <td>{video.get('comment_count', 0):,}</td>
                <td>{duration}</td>
            </tr>
            """
        
        html += """
        </table>
        
        <h4>Content Categories:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Category ID</th>
            <th>Count</th>
        </tr>
        """
        
        content_categories = summary.get("content_categories", {})
        for category_id, count in sorted(content_categories.items(), key=lambda x: x[1], reverse=True):
            html += f"""
            <tr>
                <td>{category_id}</td>
                <td>{count}</td>
            </tr>
            """
        
        html += """
        </table>
        """
        
        return html
    
    def parse_duration_from_iso(self, duration_str):
        """Parse ISO 8601 duration string to seconds."""
        import re
        pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
        match = re.match(pattern, duration_str)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            seconds = int(match.group(3) or 0)
            return hours * 3600 + minutes * 60 + seconds
        return 0

    # ---------------- RENDER ---------------------------------------------------
    def render_items(self, items):
        tab = QWidget()
        self.tabs.addTab(tab, f"Search ({len(items)})")
        lay = QVBoxLayout(tab)
        table = QTableWidget()
        table.setRowCount(len(items))
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Type", "Title", "Channel", "Published", "ID"])
        for idx, it in enumerate(items):
            snippet = it.get("snippet", {})
            
            # Safely get the kind, handle different data structures
            id_data = it.get("id", {})
            if isinstance(id_data, dict):
                kind = id_data.get("kind", "unknown").replace("youtube#", "")
            else:
                kind = "unknown"
            
            title = snippet.get("title", "N/A")
            chan = snippet.get("channelTitle", "N/A")
            pub = snippet.get("publishedAt", "")[:10] if snippet.get("publishedAt") else "N/A"
            
            # Safely get the ID
            if isinstance(id_data, dict):
                oid = id_data.get("videoId") or id_data.get("channelId") or id_data.get("playlistId") or str(id_data)
            else:
                oid = str(id_data) if id_data else "N/A"
            table.setItem(idx, 0, QTableWidgetItem(kind))
            table.setItem(idx, 1, QTableWidgetItem(title))
            table.setItem(idx, 2, QTableWidgetItem(chan))
            table.setItem(idx, 3, QTableWidgetItem(pub))
            table.setItem(idx, 4, QTableWidgetItem(oid))
        table.resizeColumnsToContents()
        lay.addWidget(table)

    def render_video(self, vid):
        tab = QWidget()
        self.tabs.addTab(tab, f"Video: {vid['snippet']['title'][:30]}…")
        lay = QVBoxLayout(tab)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setHtml(self.video_to_html(vid))
        lay.addWidget(te)

        # comments table
        if vid.get("comments"):
            table = QTableWidget()
            table.setRowCount(len(vid["comments"]))
            table.setColumnCount(4)
            table.setHorizontalHeaderLabels(["Author", "Comment", "Likes", "Published"])
            for idx, c in enumerate(vid["comments"]):
                table.setItem(idx, 0, QTableWidgetItem(c["author"]))
                table.setItem(idx, 1, QTableWidgetItem(c["text"]))
                table.setItem(idx, 2, QTableWidgetItem(str(c["likes"])))
                table.setItem(idx, 3, QTableWidgetItem(c["published"]))
            lay.addWidget(table)

    def render_channel(self, chan):
        tab = QWidget()
        self.tabs.addTab(tab, f"Channel: {chan['snippet']['title']}")
        lay = QVBoxLayout(tab)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setHtml(self.channel_to_html(chan))
        lay.addWidget(te)

    # ---------------- EXPORT ---------------------------------------------------
    def export_json(self):
        if not self.results:
            QMessageBox.information(self, "Export", "Nothing to export")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save JSON", "yt_osint.json",
                                              "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.results, fh, indent=2, ensure_ascii=False)
            self.log(f"Saved JSON → {path}")

    def export_csv(self):
        if not self.results:
            QMessageBox.information(self, "Export", "Nothing to export")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "yt_osint.csv",
                                              "CSV (*.csv)")
        if path:
            with open(path, "w", newline='', encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["type", "id", "title", "channel", "published",
                                 "description", "viewCount", "subscriberCount",
                                 "email", "twitter", "instagram", "facebook",
                                 "tiktok", "discord", "telegram", "website", "phone"])
                for it in self.results:
                    writer.writerow(self.flatten_item(it))
            self.log(f"Saved CSV → {path}")

    # ---------------- HELPERS --------------------------------------------------
    def video_to_html(self, v):
        s = v["snippet"]
        st = v.get("statistics", {})
        desc = s.get("description", "")
        sm = self.extract_social_media(desc)
        html = f"""
        <h3>{s['title']}</h3>
        <p><b>Channel:</b> {s['channelTitle']} |
           <b>Published:</b> {s['publishedAt'][:10]} |
           <b>Views:</b> {st.get('viewCount', 'N/A')} |
           <b>Likes:</b> {st.get('likeCount', 'N/A')} |
           <b>Comments:</b> {st.get('commentCount', 'N/A')}</p>
        <p><b>Description:</b><br/>{desc.replace(chr(10), '<br/>')}</p>
        <h4>Social media found</h4>
        <ul>
        """
        for k, v in sm.items():
            html += f"<li><b>{k}:</b> {', '.join(v)}</li>"
        html += "</ul>"
        return html

    def channel_to_html(self, c):
        s = c["snippet"]
        st = c.get("statistics", {})
        desc = s.get("description", "")
        sm = self.extract_social_media(desc)
        html = f"""
        <h3>{s['title']}</h3>
        <p><b>Country:</b> {s.get('country', 'N/A')} |
           <b>SubscriberCount:</b> {st.get('subscriberCount', 'N/A')} |
           <b>TotalViews:</b> {st.get('viewCount', 'N/A')} |
           <b>VideoCount:</b> {st.get('videoCount', 'N/A')}</p>
        <p><b>Description:</b><br/>{desc.replace(chr(10), '<br/>')}</p>
        <h4>Social media found</h4>
        <ul>
        """
        for k, v in sm.items():
            html += f"<li><b>{k}:</b> {', '.join(v)}</li>"
        html += "</ul>"
        return html

    def flatten_item(self, it):
        """CSV row helper."""
        kind = it.get("kind", "")
        if kind == "youtube#video":
            s = it["snippet"]
            st = it.get("statistics", {})
            sm = self.extract_social_media(s.get("description", ""))
            return ["video", it["id"], s["title"], s["channelTitle"],
                    s["publishedAt"], s.get("description", ""),
                    st.get("viewCount", ""), "",  # no subs for video
                    sm.get("email", ""), sm.get("twitter", ""),
                    sm.get("instagram", ""), sm.get("facebook", ""),
                    sm.get("tiktok", ""), sm.get("discord", ""),
                    sm.get("telegram", ""), sm.get("website", ""),
                    sm.get("phone", "")]
        if kind == "youtube#channel":
            s = it["snippet"]
            st = it.get("statistics", {})
            sm = self.extract_social_media(s.get("description", ""))
            return ["channel", it["id"], s["title"], s["title"],
                    s["publishedAt"], s.get("description", ""),
                    st.get("viewCount", ""), st.get("subscriberCount", ""),
                    sm.get("email", ""), sm.get("twitter", ""),
                    sm.get("instagram", ""), sm.get("facebook", ""),
                    sm.get("tiktok", ""), sm.get("discord", ""),
                    sm.get("telegram", ""), sm.get("website", ""),
                    sm.get("phone", "")]
        # fallback
        return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]

    def extract_social_media(self, text):
        """Return dict with lists of found identifiers with comprehensive regex patterns."""
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

# ---------- MAIN -------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()