import os
import re
import requests
import uuid
from urllib.parse import urlparse, unquote
from typing import Optional, Tuple

def format_file_size(size_bytes: int) -> str:
    """Convert bytes to human readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"

def get_file_extension(filename: str) -> str:
    """Get file extension from filename"""
    return os.path.splitext(filename)[1].lower()

def is_allowed_file_type(filename: str, max_size_mb: int = 4096) -> tuple[bool, str]:
    """Check if file type is allowed and size is within limits"""
    # NO RESTRICTIONS - ALL FILE TYPES ALLOWED
    return True, "OK"

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage"""
    # Remove or replace dangerous characters
    dangerous_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in dangerous_chars:
        filename = filename.replace(char, '_')
    
    # Limit length
    if len(filename) > 100:
        name, ext = os.path.splitext(filename)
        filename = name[:95] + ext
    
    return filename

def create_file_info_text(file_info: tuple) -> str:
    """Create formatted text for file information"""
    (file_id, telegram_file_id, custom_name, description, file_size, 
     uploaded_at, download_count, username, first_name) = file_info
    
    uploader = username or first_name or "Неизвестный пользователь"
    size_str = format_file_size(file_size)
    
    text = f"📁 **{custom_name}**\n"
    if description:
        text += f"📝 {description}\n"
    text += f"📊 Размер: {size_str}\n"
    text += f"👤 Загрузил: {uploader}\n"
    text += f"📅 Дата: {uploaded_at[:16]}\n"
    text += f"⬇️ Скачиваний: {download_count}"
    
    return text

def generate_multipart_group_id() -> str:
    """Generate unique ID for multipart file group"""
    return str(uuid.uuid4())

def escape_markdown(text: str) -> str:
    """Escape markdown special characters"""
    if not text:
        return ""
    
    # Convert to string if not already
    text = str(text)
    
    # Escape markdown special characters in correct order
    # Backslash must be escaped first
    text = text.replace('\\', '\\\\')
    text = text.replace('*', '\\*')
    text = text.replace('_', '\\_')
    text = text.replace('[', '\\[')
    text = text.replace(']', '\\]')
    text = text.replace('(', '\\(')
    text = text.replace(')', '\\)')
    text = text.replace('~', '\\~')
    text = text.replace('`', '\\`')
    text = text.replace('>', '\\>')
    text = text.replace('#', '\\#')
    text = text.replace('+', '\\+')
    text = text.replace('-', '\\-')
    text = text.replace('=', '\\=')
    text = text.replace('|', '\\|')
    text = text.replace('{', '\\{')
    text = text.replace('}', '\\}')
    text = text.replace('.', '\\.')
    text = text.replace('!', '\\!')
    
    return text

def is_valid_url(url: str) -> bool:
    """Check if URL is valid"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

import time
from collections import defaultdict, deque
from typing import Dict, Deque

class AntiSpam:
    """Anti-spam system for rate limiting and flood protection"""
    
    def __init__(self):
        # Rate limiting: user_id -> deque of timestamps
        self.user_requests: Dict[int, Deque[float]] = defaultdict(lambda: deque(maxlen=10))
        
        # Blocked users: user_id -> unblock_time
        self.blocked_users: Dict[int, float] = {}
        
        # Command cooldowns: (user_id, command) -> last_used_time
        self.command_cooldowns: Dict[tuple, float] = {}
        
        # Spam detection: user_id -> consecutive_same_commands
        self.spam_detection: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # Rate limits configuration
        self.REQUESTS_PER_MINUTE = 20  # Max requests per minute
        self.REQUESTS_PER_HOUR = 100   # Max requests per hour
        self.COMMAND_COOLDOWN = 2      # Seconds between same commands
        self.SPAM_THRESHOLD = 5        # Same command X times = spam
        self.BLOCK_DURATION = 300      # Block for 5 minutes
        
    def is_user_blocked(self, user_id: int) -> bool:
        """Check if user is currently blocked"""
        if user_id not in self.blocked_users:
            return False
        
        if time.time() > self.blocked_users[user_id]:
            # Unblock user
            del self.blocked_users[user_id]
            return False
        
        return True
    
    def get_block_time_left(self, user_id: int) -> int:
        """Get remaining block time in seconds"""
        if user_id not in self.blocked_users:
            return 0
        
        remaining = self.blocked_users[user_id] - time.time()
        return max(0, int(remaining))
    
    def check_rate_limit(self, user_id: int) -> tuple[bool, str]:
        """Check if user exceeds rate limits"""
        if self.is_user_blocked(user_id):
            time_left = self.get_block_time_left(user_id)
            return False, f"Вы заблокированы на {time_left} секунд за спам"
        
        current_time = time.time()
        user_requests = self.user_requests[user_id]
        
        # Add current request
        user_requests.append(current_time)
        
        # Check requests per minute
        minute_ago = current_time - 60
        recent_requests = [t for t in user_requests if t > minute_ago]
        
        if len(recent_requests) > self.REQUESTS_PER_MINUTE:
            self._block_user(user_id, "Превышен лимит запросов в минуту")
            return False, f"Слишком много запросов! Заблокированы на {self.BLOCK_DURATION} секунд"
        
        # Check requests per hour
        hour_ago = current_time - 3600
        hour_requests = [t for t in user_requests if t > hour_ago]
        
        if len(hour_requests) > self.REQUESTS_PER_HOUR:
            self._block_user(user_id, "Превышен лимит запросов в час")
            return False, f"Превышен часовой лимит! Заблокированы на {self.BLOCK_DURATION} секунд"
        
        return True, ""
    
    def check_command_spam(self, user_id: int, command: str) -> tuple[bool, str]:
        """Check for command spam and cooldowns"""
        current_time = time.time()
        
        # Check command cooldown
        cooldown_key = (user_id, command)
        if cooldown_key in self.command_cooldowns:
            time_since_last = current_time - self.command_cooldowns[cooldown_key]
            if time_since_last < self.COMMAND_COOLDOWN:
                remaining = self.COMMAND_COOLDOWN - time_since_last
                return False, f"Подождите {remaining:.1f} секунд перед повторным использованием команды"
        
        # Update command usage
        self.command_cooldowns[cooldown_key] = current_time
        
        # Check spam detection
        self.spam_detection[user_id][command] += 1
        
        # Reset spam counter after some time
        if command + "_last_reset" not in self.spam_detection[user_id]:
            self.spam_detection[user_id][command + "_last_reset"] = current_time
        elif current_time - self.spam_detection[user_id][command + "_last_reset"] > 60:
            self.spam_detection[user_id][command] = 1
            self.spam_detection[user_id][command + "_last_reset"] = current_time
        
        # Check if user is spamming same command
        if self.spam_detection[user_id][command] > self.SPAM_THRESHOLD:
            self._block_user(user_id, f"Спам команды {command}")
            return False, f"Обнаружен спам команды {command}! Заблокированы на {self.BLOCK_DURATION} секунд"
        
        return True, ""
    
    def _block_user(self, user_id: int, reason: str):
        """Block user for specified duration"""
        self.blocked_users[user_id] = time.time() + self.BLOCK_DURATION
        print(f"User {user_id} blocked for {self.BLOCK_DURATION}s. Reason: {reason}")
    
    def is_allowed(self, user_id: int, command: str = "general") -> tuple[bool, str]:
        """Main method to check if user action is allowed"""
        # Check rate limits
        rate_ok, rate_msg = self.check_rate_limit(user_id)
        if not rate_ok:
            return False, rate_msg
        
        # Check command spam
        spam_ok, spam_msg = self.check_command_spam(user_id, command)
        if not spam_ok:
            return False, spam_msg
        
        return True, ""
    
    def cleanup_old_data(self):
        """Clean up old data to prevent memory leaks"""
        current_time = time.time()
        
        # Clean old blocked users
        expired_blocks = [uid for uid, unblock_time in self.blocked_users.items() 
                         if current_time > unblock_time]
        for uid in expired_blocks:
            del self.blocked_users[uid]
        
        # Clean old cooldowns (older than 1 hour)
        old_cooldowns = [(key) for key, timestamp in self.command_cooldowns.items() 
                        if current_time - timestamp > 3600]
        for key in old_cooldowns:
            del self.command_cooldowns[key]
        
        # Clean old spam detection data
        for user_id in list(self.spam_detection.keys()):
            user_data = self.spam_detection[user_id]
            for command in list(user_data.keys()):
                if command.endswith("_last_reset") and current_time - user_data[command] > 3600:
                    # Remove old data
                    base_command = command.replace("_last_reset", "")
                    if base_command in user_data:
                        del user_data[base_command]
                    del user_data[command]
            
            # Remove empty user data
            if not user_data:
                del self.spam_detection[user_id]

def get_filename_from_url(url: str) -> str:
    """Extract filename from URL"""
    try:
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        
        # Decode URL encoding
        filename = unquote(filename)
        
        # If no filename in path, try to get from URL
        if not filename or '.' not in filename:
            # Try to extract from the last part of URL
            path_parts = parsed_url.path.strip('/').split('/')
            if path_parts and path_parts[-1]:
                filename = unquote(path_parts[-1])
            else:
                filename = "downloaded_file"
        
        # Sanitize filename
        filename = sanitize_filename(filename)
        
        # Ensure it has an extension
        if '.' not in filename:
            filename += ".bin"
            
        return filename
    except:
        return "downloaded_file.bin"

def download_file_from_url(url: str, max_size_mb: int = 4096) -> Tuple[bool, str, bytes, str, int]:
    """
    Download file from URL - works with any link including cloud storage, redirects, etc.
    Returns: (success, error_message, file_content, filename, file_size)
    """
    try:
        # Validate URL
        if not is_valid_url(url):
            return False, "Неверный формат URL", b"", "", 0
        
        # Enhanced headers to bypass most restrictions
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        }
        
        # Handle special URLs
        processed_url = process_special_urls(url)
        
        # Create session for better handling of redirects and cookies
        session = requests.Session()
        session.headers.update(headers)
        
        # Make HEAD request first to check file size (with multiple attempts)
        try:
            head_response = session.head(processed_url, timeout=15, allow_redirects=True)
            content_length = head_response.headers.get('content-length')
            
            if content_length:
                file_size = int(content_length)
                if file_size > max_size_mb * 1024 * 1024:
                    return False, f"Файл слишком большой ({format_file_size(file_size)}). Максимум: {max_size_mb} МБ", b"", "", 0
        except:
            # If HEAD fails, try GET with range header
            try:
                range_response = session.get(processed_url, headers={'Range': 'bytes=0-1023'}, timeout=10, allow_redirects=True)
                content_range = range_response.headers.get('content-range')
                if content_range and '/' in content_range:
                    total_size = content_range.split('/')[-1]
                    if total_size.isdigit():
                        file_size = int(total_size)
                        if file_size > max_size_mb * 1024 * 1024:
                            return False, f"Файл слишком большой ({format_file_size(file_size)}). Максимум: {max_size_mb} МБ", b"", "", 0
            except:
                pass  # Continue without size check
        
        # Download file with extended timeout and retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = session.get(processed_url, timeout=60, stream=True, allow_redirects=True)
                response.raise_for_status()
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt == max_retries - 1:
                    return False, f"Не удалось скачать после {max_retries} попыток: {str(e)}", b"", "", 0
                continue
        
        # Get filename from multiple sources
        filename = get_enhanced_filename(response, processed_url, url)
        
        # Download content with size limit and progress
        content = b""
        max_size_bytes = max_size_mb * 1024 * 1024
        downloaded = 0
        
        for chunk in response.iter_content(chunk_size=32768):  # Larger chunks for better performance
            if chunk:
                content += chunk
                downloaded += len(chunk)
                if downloaded > max_size_bytes:
                    return False, f"Файл слишком большой. Максимум: {max_size_mb} МБ", b"", "", 0
        
        # Validate downloaded content
        if len(content) == 0:
            return False, "Скачанный файл пуст", b"", "", 0
        
        # Check file type
        is_allowed, error_msg = is_allowed_file_type(filename)
        if not is_allowed:
            return False, error_msg, b"", "", 0
        
        return True, "", content, filename, len(content)
        
    except requests.exceptions.Timeout:
        return False, "Превышено время ожидания загрузки (60 сек)", b"", "", 0
    except requests.exceptions.ConnectionError:
        return False, "Ошибка подключения к серверу", b"", "", 0
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP ошибка: {e.response.status_code} - {e.response.reason}", b"", "", 0
    except requests.exceptions.TooManyRedirects:
        return False, "Слишком много редиректов", b"", "", 0
    except Exception as e:
        return False, f"Ошибка загрузки: {str(e)}", b"", "", 0

def process_special_urls(url: str) -> str:
    """Process special URLs to make them downloadable"""
    # Google Drive
    if 'drive.google.com' in url:
        if '/file/d/' in url:
            file_id = url.split('/file/d/')[1].split('/')[0]
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        elif 'id=' in url:
            return url.replace('view?usp=sharing', 'export=download')
    
    # Dropbox
    elif 'dropbox.com' in url:
        if '?dl=0' in url:
            return url.replace('?dl=0', '?dl=1')
        elif not '?dl=1' in url:
            return url + ('&dl=1' if '?' in url else '?dl=1')
    
    # OneDrive
    elif 'onedrive.live.com' in url or '1drv.ms' in url:
        if 'view.aspx' in url:
            return url.replace('view.aspx', 'download.aspx')
    
    # Yandex.Disk
    elif 'disk.yandex' in url:
        if '/d/' in url:
            return url + '/download'
    
    # GitHub
    elif 'github.com' in url and '/blob/' in url:
        return url.replace('/blob/', '/raw/')
    
    # GitLab
    elif 'gitlab.com' in url and '/blob/' in url:
        return url.replace('/blob/', '/raw/')
    
    return url

def get_enhanced_filename(response, processed_url: str, original_url: str) -> str:
    """Get filename from multiple sources with enhanced detection"""
    filename = None
    
    # 1. Try Content-Disposition header
    content_disposition = response.headers.get('content-disposition', '')
    if content_disposition:
        # Try different patterns
        patterns = [
            r'filename\*=UTF-8\'\'([^;]+)',
            r'filename="([^"]+)"',
            r'filename=([^;]+)',
            r'filename\*=([^;]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, content_disposition, re.IGNORECASE)
            if match:
                filename = unquote(match.group(1).strip('\'"'))
                break
    
    # 2. Try final URL after redirects
    if not filename:
        final_url = response.url
        filename = get_filename_from_url(final_url)
    
    # 3. Try original processed URL
    if not filename or filename == "downloaded_file.bin":
        filename = get_filename_from_url(processed_url)
    
    # 4. Try original URL
    if not filename or filename == "downloaded_file.bin":
        filename = get_filename_from_url(original_url)
    
    # 5. Try Content-Type header
    if not filename or filename == "downloaded_file.bin":
        content_type = response.headers.get('content-type', '')
        if content_type:
            if 'image/' in content_type:
                ext = content_type.split('/')[-1]
                filename = f"image.{ext}"
            elif 'video/' in content_type:
                ext = content_type.split('/')[-1]
                filename = f"video.{ext}"
            elif 'audio/' in content_type:
                ext = content_type.split('/')[-1]
                filename = f"audio.{ext}"
            elif 'application/pdf' in content_type:
                filename = "document.pdf"
            elif 'application/zip' in content_type:
                filename = "archive.zip"
    
    # 6. Fallback with timestamp
    if not filename or filename == "downloaded_file.bin":
        import time
        timestamp = int(time.time())
        filename = f"file_{timestamp}.bin"
    
    return sanitize_filename(filename)
