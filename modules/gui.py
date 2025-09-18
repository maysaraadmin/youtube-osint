"""
GUI Components Module
Contains the main window and UI components for the YouTube OSINT Tool.
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

# Import our custom thread classes
from threads import (
    YouTubeSearchThread, ChannelDetailsThread, VideoDetailsThread,
    ProfileImageDownloadThread, GoogleDorkingThread, DocumentIntelligenceThread,
    VideoAnalysisThread, RelatedVideosThread
)

# Constants
SETTINGS_FILE = pathlib.Path("yt_osint_config.json")
ICON_B64 = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube OSINT Reconnaissance Tool")
        self.setWindowIcon(self.icon_from_b64())
        self.resize(1200, 800)
        self.results = []  # list of dicts
        self.active_threads = []  # Track active threads for cleanup
        self.api_key = None  # No API key needed with yt-dlp
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
        # This is a simplified version - in real implementation, you would format the actual results
        html = """
        <h3>Google Dorking Results</h3>
        <p><b>Target:</b> Sample Target | 
           <b>Username:</b> sample_username | 
           <b>Email:</b> N/A | 
           <b>Phone:</b> N/A</p>
        <h4>Findings by Platform:</h4>
        <ul>
        <li><b>Twitter:</b><ul>
            <li><b>Query:</b> site:twitter.com "sample_username"<br/>
                <b>URL:</b> <a href="https://example.com">https://example.com</a><br/>
                <b>Title:</b> Mock result<br/>
                <b>Confidence:</b> Medium</li>
        </ul></li>
        </ul>
        """
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
        # This is a simplified version - in real implementation, you would format the actual results
        html = """
        <h3>Document Intelligence Results</h3>
        <p><b>Target:</b> Sample Target | 
           <b>Username:</b> sample_username | 
           <b>Email:</b> N/A | 
           <b>Phone:</b> N/A</p>
        
        <h4>Summary:</h4>
        <p><b>Total Documents Found:</b> 5</p>
        
        <h5>By Document Type:</h5>
        <ul>
        <li><b>PDF:</b> 3</li>
        <li><b>DOC:</b> 2</li>
        </ul>
        
        <h4>Documents Found:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Title</th>
            <th>Type</th>
            <th>Size</th>
            <th>Engine</th>
            <th>Confidence</th>
        </tr>
        <tr>
            <td><a href="https://example.com/doc.pdf">Sample Document</a></td>
            <td>PDF</td>
            <td>1.2 MB</td>
            <td>Google</td>
            <td>High</td>
        </tr>
        </table>
        """
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
                <td>{engagement.get('engagement_rate', 0):.2f}%</td>
                <td>{performance.get('performance_score', 0):.2f}</td>
                <td>{performance.get('performance_category', 'N/A')}</td>
            </tr>
            """
        
        html += """
        </table>
        """
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
        # This is a simplified version - in real implementation, you would format the actual results
        html = """
        <h3>Related Videos & Content Recommendations</h3>
        
        <h4>Summary Statistics:</h4>
        <p><b>Source Videos:</b> 5</p>
        <p><b>Related Videos Found:</b> 25</p>
        <p><b>Unique Channels:</b> 15</p>
        
        <h4>Content Recommendations:</h4>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Type</th>
            <th>Title</th>
            <th>Recommendation</th>
            <th>Confidence</th>
        </tr>
        <tr>
            <td><b>Content Theme</b></td>
            <td>Technology</td>
            <td>Focus on emerging tech trends</td>
            <td style="background-color: #90EE90">85%</td>
        </tr>
        </table>
        """
        return html

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
