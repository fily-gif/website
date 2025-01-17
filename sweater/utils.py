import os
from faker import Faker
import random as rng
import psutil
from datetime import datetime
import markdown
import frontmatter
from functools import wraps
from flask import request, redirect, url_for
import json
import string
import re
from collections import defaultdict
import time

fake = Faker('en_US')

def get_key():
    return 'TH1is1s4n)t4ctu4!!y4s3cur#t0k3n'

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.cookies.get('admin_token')
        if not auth or auth != get_key():
            return "Go away." # redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated

def git_pull():
    os.system('git pull')

class LinkShortener:
    def __init__(self):
        self.links_file = os.path.join(os.path.dirname(__file__), "static/links.json")
        self.links = self._load_links()

    def _load_links(self):
        if os.path.exists(self.links_file):
            with open(self.links_file, 'r') as f:
                return json.load(f)
        return {}

    def _save_links(self):
        with open(self.links_file, 'w') as f:
            json.dump(self.links, f, indent=2)

    def add_link(self, url, custom_id=None):
        if custom_id:
            short_id = custom_id
        else:
            short_id = ''.join(rng.choices(string.ascii_lowercase + string.digits, k=6))
        
        self.links[short_id] = url
        self._save_links()
        return short_id

    def get_link(self, short_id):
        return self.links.get(short_id)
    
    def get_stats(self):
        return len(self.links)

class Content:
    files = {}
    root = os.path.join(os.path.dirname(__file__), "static/md")
    
    def __init__(self):
        if os.path.exists(self.root):
            self.blogs = []
            for blog_dir in os.listdir(self.root):
                dir_path = os.path.join(self.root, blog_dir)
                if os.path.isdir(dir_path):
                    blog_file = os.path.join(dir_path, f"{blog_dir}.md")
                    if os.path.exists(blog_file):
                        self.blogs.append(blog_dir)
    
    def _extract_title(self, content):
        """Extract first h1 header from markdown content"""
        lines = content.split('\n')
        for line in lines:
            if line.startswith('# '):
                return line.replace('# ', '').strip()
        return None
    
    def get_stats(self):
        try:
            post_count = len(self.blogs)
        except AttributeError:
            post_count = 0
        
        return {
            'posts': post_count,
            'uptime': psutil.boot_time()
        }
    
    def get_posts(self):
        try:
            posts = []
            if self.blogs:
                for blog_name in self.blogs:
                    post_path = os.path.join(self.root, blog_name, f"{blog_name}.md")
                    with open(post_path, 'r') as f:
                        content = f.read()
                    title = self._extract_title(content) or blog_name
                    html = markdown.markdown(content)
                    posts.append({
                        'filename': blog_name,
                        'title': title,
                        'path': f'/post/{blog_name}',
                        'content': html
                    })
                return posts
            else:
                return None
        except AttributeError:
            return None

    def get_post(self, blog_name):
        post_path = os.path.join(self.root, blog_name, f"{blog_name}.md")
        if os.path.exists(post_path):
            with open(post_path, 'r') as f:
                content = f.read()
            title = self._extract_title(content) or blog_name
            content = re.sub(r'<script.*?>.*?</script>', '', content, flags=re.DOTALL)
            return {
                'filename': blog_name,
                'title': title,
                'content': markdown.markdown(content)
            }
        return None

    def _get_next_number(self):
        """Get the next available number for post folder"""
        numbers = []
        for blog_dir in os.listdir(self.root):
            try:
                num = int(blog_dir.split('-')[0])
                numbers.append(num)
            except (ValueError, IndexError):
                continue
        return max(numbers, default=0) + 1

    def create_post(self, title, content, custom_name=None):
        try:
            if custom_name:
                folder_name = custom_name
            else:
                # Create slug from title
                slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
                next_num = self._get_next_number()
                folder_name = f"{next_num:02d}-{slug}"
            
            post_dir = os.path.join(self.root, folder_name)
            os.makedirs(post_dir, exist_ok=True)
            
            # Add title as h1 if not present
            if not content.startswith('# '):
                content = f"# {title}\n\n{content}"
            
            with open(os.path.join(post_dir, f"{folder_name}.md"), 'w') as f:
                f.write(content)
            
            if folder_name not in self.blogs:
                self.blogs.append(folder_name)
            return True
        except Exception:
            return False
    
    def upload_post(self, file, custom_name=None):
        try:
            if custom_name:
                folder_name = custom_name
            else:
                filename = file.filename
                slug = os.path.splitext(filename)[0]
                next_num = self._get_next_number()
                folder_name = f"{next_num:02d}-{slug}"
            
            post_dir = os.path.join(self.root, folder_name)
            os.makedirs(post_dir, exist_ok=True)
            
            file.save(os.path.join(post_dir, f"{folder_name}.md"))
            
            if folder_name not in self.blogs:
                self.blogs.append(folder_name)
            return True
        except Exception:
            return False

class Comments:
    def __init__(self):
        self.comments_file = os.path.join(os.path.dirname(__file__), "static/comments.json")
        self.comments = self._load_comments()
        self.rate_limits = defaultdict(list)
        self.max_comment_length = 500
        self.rate_limit_period = 60  # seconds
        self.max_comments_per_period = 3
        self.blacklist_file = os.path.join(os.path.dirname(__file__), "static/ip_blacklist.json")
        self.blacklist = self._load_blacklist()

    def _load_comments(self):
        if os.path.exists(self.comments_file):
            with open(self.comments_file, 'r') as f:
                return json.load(f)
        return {}

    def _save_comments(self):
        with open(self.comments_file, 'w') as f:
            json.dump(self.comments, f, indent=2)

    def _load_blacklist(self):
        if os.path.exists(self.blacklist_file):
            with open(self.blacklist_file, 'r') as f:
                return json.load(f)
        return {'ips': []}

    def _save_blacklist(self):
        with open(self.blacklist_file, 'w') as f:
            json.dump(self.blacklist, f, indent=2)

    def is_ip_blocked(self, ip):
        return ip in self.blacklist['ips']

    def block_ip(self, ip):
        if ip not in self.blacklist['ips']:
            self.blacklist['ips'].append(ip)
            self._save_blacklist()

    def delete_comment(self, post_id, comment_index):
        if post_id in self.comments and 0 <= comment_index < len(self.comments[post_id]):
            del self.comments[post_id][comment_index]
            self._save_comments()
            return True
        return False

    @staticmethod
    def name():
        return fake.name()

    def _is_rate_limited(self, ip):
        now = time.time()
        # Clean old entries
        self.rate_limits[ip] = [t for t in self.rate_limits[ip] 
                               if t > now - self.rate_limit_period]
        # Check if too many comments
        if len(self.rate_limits[ip]) >= self.max_comments_per_period:
            return True
        self.rate_limits[ip].append(now)
        return False

    def add_comment(self, post_id, content, ip):
        if self.is_ip_blocked(ip):
            raise ValueError("Your IP has been blocked from commenting")
        if self._is_rate_limited(ip):
            raise ValueError("Too many comments. Please wait a minute.")
        
        if len(content) > self.max_comment_length:
            raise ValueError(f"Comment too long (max {self.max_comment_length} characters)")

        if post_id not in self.comments:
            self.comments[post_id] = []
        
        self.comments[post_id].append({
            'name': self.name(),
            'content': content,
            'date': datetime.now().isoformat().split(".")[0].replace("T", " "),
        })
        self._save_comments()

    def get_comments(self, post_id):
        return self.comments.get(post_id, [])
    
    def get_stats(self):
        total_comments = sum(len(comments) for comments in self.comments.values())
        return {
            'total': total_comments,
            'blocked_ips': len(self.blacklist['ips'])
        }

    def unblock_ip(self, ip):
        if ip in self.blacklist['ips']:
            self.blacklist['ips'].remove(ip)
            self._save_blacklist()

    def get_all_comments(self):
        all_comments = []
        for post_id, comments in self.comments.items():
            for i, comment in enumerate(comments):
                all_comments.append({
                    'post_id': post_id,
                    'index': i,
                    'name': comment['name'],
                    'content': comment['content'],
                    'date': comment['date']
                })
        return sorted(all_comments, key=lambda x: x['date'], reverse=True)
