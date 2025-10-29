import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Tuple

class DatabaseManager:
    def __init__(self, db_path: str = "archive.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create files table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    custom_name TEXT NOT NULL,
                    description TEXT,
                    file_size INTEGER,
                    mime_type TEXT,
                    uploaded_by INTEGER NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    download_count INTEGER DEFAULT 0,
                    is_multipart INTEGER DEFAULT 0,
                    part_number INTEGER DEFAULT 1,
                    total_parts INTEGER DEFAULT 1,
                    multipart_group_id TEXT
                )
            ''')
            
            # Add new columns if they don't exist (migration)
            try:
                cursor.execute('ALTER TABLE files ADD COLUMN is_multipart INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            try:
                cursor.execute('ALTER TABLE files ADD COLUMN part_number INTEGER DEFAULT 1')
            except sqlite3.OperationalError:
                pass
            
            try:
                cursor.execute('ALTER TABLE files ADD COLUMN total_parts INTEGER DEFAULT 1')
            except sqlite3.OperationalError:
                pass
            
            try:
                cursor.execute('ALTER TABLE files ADD COLUMN multipart_group_id TEXT')
            except sqlite3.OperationalError:
                pass
            
            # Create users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    files_uploaded INTEGER DEFAULT 0
                )
            ''')
            
            conn.commit()
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Add or update user information"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            conn.commit()
    
    def add_file(self, file_id: str, original_name: str, custom_name: str, 
                 description: str, file_size: int, mime_type: str, uploaded_by: int,
                 is_multipart: bool = False, part_number: int = 1, total_parts: int = 1,
                 multipart_group_id: str = None) -> int:
        """Add a new file to the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO files (file_id, original_name, custom_name, description, 
                                 file_size, mime_type, uploaded_by, is_multipart,
                                 part_number, total_parts, multipart_group_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (file_id, original_name, custom_name, description, file_size, mime_type, 
                  uploaded_by, int(is_multipart), part_number, total_parts, multipart_group_id))
            
            # Update user's file count only for single files or first part of multipart
            if not is_multipart or part_number == 1:
                cursor.execute('''
                    UPDATE users SET files_uploaded = files_uploaded + 1 WHERE user_id = ?
                ''', (uploaded_by,))
            
            conn.commit()
            return cursor.lastrowid
    
    def search_files(self, query: str, limit: int = 10) -> List[Tuple]:
        """Search files by name or description"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.id, f.file_id, f.custom_name, f.description, f.file_size, 
                       f.uploaded_at, f.download_count, u.username, u.first_name
                FROM files f
                LEFT JOIN users u ON f.uploaded_by = u.user_id
                WHERE f.custom_name LIKE ? OR f.description LIKE ?
                ORDER BY f.uploaded_at DESC
                LIMIT ?
            ''', (f'%{query}%', f'%{query}%', limit))
            return cursor.fetchall()
    
    def get_file_by_id(self, file_id: int) -> Optional[Tuple]:
        """Get file information by database ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.id, f.file_id, f.custom_name, f.description, f.file_size, 
                       f.uploaded_at, f.download_count, u.username, u.first_name,
                       f.is_multipart, f.part_number, f.total_parts, f.multipart_group_id
                FROM files f
                LEFT JOIN users u ON f.uploaded_by = u.user_id
                WHERE f.id = ?
            ''', (file_id,))
            return cursor.fetchone()
    
    def increment_download_count(self, file_id: int):
        """Increment download count for a file"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE files SET download_count = download_count + 1 WHERE id = ?
            ''', (file_id,))
            conn.commit()
    
    def get_recent_files(self, limit: int = 10) -> List[Tuple]:
        """Get recently uploaded files"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.id, f.file_id, f.custom_name, f.description, f.file_size, 
                       f.uploaded_at, f.download_count, u.username, u.first_name
                FROM files f
                LEFT JOIN users u ON f.uploaded_by = u.user_id
                ORDER BY f.uploaded_at DESC
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
    
    def get_user_files(self, user_id: int, limit: int = 10) -> List[Tuple]:
        """Get files uploaded by a specific user"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.id, f.file_id, f.custom_name, f.description, f.file_size, 
                       f.uploaded_at, f.download_count
                FROM files f
                WHERE f.uploaded_by = ?
                ORDER BY f.uploaded_at DESC
                LIMIT ?
            ''', (user_id, limit))
            return cursor.fetchall()
    
    def get_stats(self) -> dict:
        """Get archive statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Total files
            cursor.execute('SELECT COUNT(*) FROM files')
            total_files = cursor.fetchone()[0]
            
            # Total users
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            # Total downloads
            cursor.execute('SELECT SUM(download_count) FROM files')
            total_downloads = cursor.fetchone()[0] or 0
            
            # Total size
            cursor.execute('SELECT SUM(file_size) FROM files')
            total_size = cursor.fetchone()[0] or 0
            
            return {
                'total_files': total_files,
                'total_users': total_users,
                'total_downloads': total_downloads,
                'total_size': total_size
            }
    
    def get_multipart_files(self, multipart_group_id: str) -> List[Tuple]:
        """Get all parts of a multipart file"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.id, f.file_id, f.custom_name, f.description, f.file_size, 
                       f.uploaded_at, f.download_count, u.username, u.first_name,
                       f.part_number, f.total_parts
                FROM files f
                LEFT JOIN users u ON f.uploaded_by = u.user_id
                WHERE f.multipart_group_id = ?
                ORDER BY f.part_number
            ''', (multipart_group_id,))
            return cursor.fetchall()
    
    def search_files_grouped(self, query: str, limit: int = 10) -> List[Tuple]:
        """Search files by name or description, grouping multipart files"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.id, f.file_id, f.custom_name, f.description, 
                       CASE 
                           WHEN f.is_multipart = 1 THEN 
                               (SELECT SUM(file_size) FROM files WHERE multipart_group_id = f.multipart_group_id)
                           ELSE f.file_size
                       END as total_size,
                       f.uploaded_at, f.download_count, u.username, u.first_name,
                       f.is_multipart, f.total_parts, f.multipart_group_id
                FROM files f
                LEFT JOIN users u ON f.uploaded_by = u.user_id
                WHERE (f.custom_name LIKE ? OR f.description LIKE ?)
                  AND (f.is_multipart = 0 OR f.part_number = 1)
                ORDER BY f.uploaded_at DESC
                LIMIT ?
            ''', (f'%{query}%', f'%{query}%', limit))
            return cursor.fetchall()
    
    def get_recent_files_grouped(self, limit: int = 10) -> List[Tuple]:
        """Get recently uploaded files, grouping multipart files"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.id, f.file_id, f.custom_name, f.description, 
                       CASE 
                           WHEN f.is_multipart = 1 THEN 
                               (SELECT SUM(file_size) FROM files WHERE multipart_group_id = f.multipart_group_id)
                           ELSE f.file_size
                       END as total_size,
                       f.uploaded_at, f.download_count, u.username, u.first_name,
                       f.is_multipart, f.total_parts, f.multipart_group_id
                FROM files f
                LEFT JOIN users u ON f.uploaded_by = u.user_id
                WHERE f.is_multipart = 0 OR f.part_number = 1
                ORDER BY f.uploaded_at DESC
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
    
    def delete_file(self, file_id: int, user_id: int) -> bool:
        """Delete a file if it belongs to the user"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Check if file belongs to user
            cursor.execute('''
                SELECT uploaded_by, is_multipart, multipart_group_id FROM files WHERE id = ?
            ''', (file_id,))
            result = cursor.fetchone()
            
            if not result:
                return False
            
            uploaded_by, is_multipart, multipart_group_id = result
            if uploaded_by != user_id:
                return False
            
            # If it's a multipart file, delete all parts
            if is_multipart and multipart_group_id:
                cursor.execute('''
                    DELETE FROM files WHERE multipart_group_id = ?
                ''', (multipart_group_id,))
            else:
                # Delete single file
                cursor.execute('''
                    DELETE FROM files WHERE id = ?
                ''', (file_id,))
            
            # Update user's file count
            cursor.execute('''
                UPDATE users SET files_uploaded = files_uploaded - 1 WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            return True
    
    def is_filename_unique(self, custom_name: str) -> bool:
        """Check if custom filename is unique"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM files WHERE custom_name = ?
            ''', (custom_name,))
            count = cursor.fetchone()[0]
            return count == 0
    
    def suggest_unique_filename(self, base_name: str) -> str:
        """Suggest a unique filename by adding numbers"""
        if self.is_filename_unique(base_name):
            return base_name
        
        # Split name and extension
        if '.' in base_name:
            name_part, ext_part = base_name.rsplit('.', 1)
            ext_part = '.' + ext_part
        else:
            name_part = base_name
            ext_part = ''
        
        # Try adding numbers
        for i in range(2, 100):  # Try up to 99 variations
            suggested_name = f"{name_part}_{i}{ext_part}"
            if self.is_filename_unique(suggested_name):
                return suggested_name
        
        # If all numbers are taken, add timestamp
        import time
        timestamp = int(time.time())
        return f"{name_part}_{timestamp}{ext_part}"
    
    def get_all_users(self):
        """Get all users for admin broadcast"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username, first_name, last_name FROM users
            ''')
            return cursor.fetchall()
    
    def get_admin_stats(self):
        """Get detailed admin statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            # Total users
            cursor.execute('SELECT COUNT(*) FROM users')
            stats['total_users'] = cursor.fetchone()[0]
            
            # Total files
            cursor.execute('SELECT COUNT(*) FROM files')
            stats['total_files'] = cursor.fetchone()[0]
            
            # Total size
            cursor.execute('SELECT SUM(file_size) FROM files')
            result = cursor.fetchone()[0]
            stats['total_size'] = result if result else 0
            
            # Total downloads
            cursor.execute('SELECT SUM(download_count) FROM files')
            result = cursor.fetchone()[0]
            stats['total_downloads'] = result if result else 0
            
            # URL files count
            cursor.execute('SELECT COUNT(*) FROM files WHERE file_id LIKE "%url%"')
            stats['url_files'] = cursor.fetchone()[0]
            
            # Multipart files count
            cursor.execute('SELECT COUNT(*) FROM files WHERE is_multipart = 1')
            stats['multipart_files'] = cursor.fetchone()[0]
            
            # Today's stats
            cursor.execute('''
                SELECT COUNT(*) FROM users 
                WHERE DATE(joined_at) = DATE('now')
            ''')
            stats['users_today'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM files 
                WHERE DATE(uploaded_at) = DATE('now')
            ''')
            stats['files_today'] = cursor.fetchone()[0]
            
            # Downloads today (approximate, since we don't track download dates)
            stats['downloads_today'] = 0  # Would need additional tracking
            
            return stats
    
    def get_top_users(self, limit=10):
        """Get top users by file count"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT u.user_id, u.username, u.first_name, u.files_uploaded
                FROM users u
                ORDER BY u.files_uploaded DESC
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
    
    def get_largest_files(self, limit=10):
        """Get largest files in the system"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, custom_name, file_size, download_count
                FROM files
                ORDER BY file_size DESC
                LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
    
    def get_file_by_id(self, file_id):
        """Get file info by ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, file_id, custom_name, description, file_size, 
                       uploaded_at, download_count, uploaded_by
                FROM files
                WHERE id = ?
            ''', (file_id,))
            return cursor.fetchone()
