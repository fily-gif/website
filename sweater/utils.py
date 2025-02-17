import os
from faker import Faker
import random as rng
import psutil
from datetime import datetime, timedelta
import markdown
from functools import wraps
from flask import request
import json
import string
import re
from collections import defaultdict
import time
import subprocess
import io
import contextlib
import hmac

fake = Faker('en_US')

def get_key():
    key_path = os.path.join(os.path.dirname(__file__), 'key.txt')
    with open(key_path, 'r') as f:
        return f.read().strip()

class SecurityManager:
    def __init__(self):
        self.login_attempts = defaultdict(list)
        self.max_attempts = 5
        self.block_duration = 3600  # 1 hour in seconds
        self.session_duration = 3600  # 1 hour in seconds
        self.blocked_ips = set()

    def is_ip_blocked(self, ip):
        return ip in self.blocked_ips

    def _clean_old_attempts(self, ip):
        now = time.time()
        self.login_attempts[ip] = [
            attempt for attempt in self.login_attempts[ip]
            if now - attempt < self.block_duration
        ]

    def check_rate_limit(self, ip):
        if self.is_ip_blocked(ip):
            return False

        self._clean_old_attempts(ip)
        if len(self.login_attempts[ip]) >= self.max_attempts:
            self.blocked_ips.add(ip)
            return False
        return True

    def record_attempt(self, ip):
        self.login_attempts[ip].append(time.time())

    def get_attempts(self, ip = None):
        if ip:
            return len(self.login_attempts.get(ip, []))
        return {ip: len(attempts) for ip, attempts in self.login_attempts.items()}

    def validate_session(self, token, ip):
        if not token:
            return False
        try:
            # Split token into timestamp, ip hash, and signature
            timestamp_str, ip_hash, sig = token.split('.')
            timestamp = int(timestamp_str)

            # Check if session is expired
            if time.time() - timestamp > self.session_duration:
                return False

            # Verify IP hasn't changed
            if ip_hash != hmac.new(get_key().encode(), ip.encode(), 'sha256').hexdigest()[:8]:
                return False

            # Verify signature
            expected_sig = self.generate_signature(timestamp_str, ip_hash)
            return hmac.compare_digest(sig, expected_sig)
        except:
            return False

    def generate_session_token(self, ip):
        timestamp = str(int(time.time()))
        ip_hash = hmac.new(get_key().encode(), ip.encode(), 'sha256').hexdigest()[:8]
        signature = self.generate_signature(timestamp, ip_hash)
        return f"{timestamp}.{ip_hash}.{signature}"

    def generate_signature(self, timestamp, ip_hash):
        msg = f"{timestamp}.{ip_hash}".encode()
        return hmac.new(get_key().encode(), msg, 'sha256').hexdigest()[:16]

security_manager = SecurityManager()

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.cookies.get('admin_token')
        client_ip = request.remote_addr

        if not auth or not security_manager.validate_session(auth, client_ip):
            return "Go away.", 403
        return f(*args, **kwargs)
    return decorated


class GitManager:
    @staticmethod
    def git_pull():
        try:
            pardir = os.path.dirname(__file__)
            print(pardir)
            result = subprocess.run(['bash', '-c', './pull.sh'], 
                        check=True, 
                        capture_output=True,
                        cwd=os.path.dirname(pardir))
            output = result.stdout.decode().strip()
            print(f"{output} {datetime.now()}")
            if "Already up to date" in output:
                return {'status': 'success', 'message': 'Already up to date'}
            return {'status': 'success', 'message': output.split('\n')[-1]}
        except subprocess.CalledProcessError as e:
            print(e)
            return {'status': 'error', 'message': str(e)}
        except Exception as e:
            print(e)
            return {'status': 'error', 'message': str(e)}

    @staticmethod
    def branch():
        try:
            result = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], 
                        check=True, 
                        capture_output=True,
                        cwd=os.path.dirname(__file__))
            return {
                'status': 'success',
                'message': result.stdout.decode().strip()
            }
        except subprocess.CalledProcessError as e:
            return {'status': 'error', 'message': str(e)}

    @staticmethod
    def can_pull():
        try:
            subprocess.run(['git', 'fetch'], check=True, capture_output=True,
                         cwd=os.path.dirname(__file__))
            result = subprocess.run(['git', 'rev-list', 'HEAD..origin/HEAD', '--count'], 
                        check=True, 
                        capture_output=True,
                        cwd=os.path.dirname(__file__))
            count = int(result.stdout.decode().strip())
            return {
                'status': 'success',
                'message': count
            }
        except subprocess.CalledProcessError as e:
            return {'status': 'error', 'message': str(e)}

    @staticmethod
    def commit():
        try:
            result = subprocess.run(['git', 'log', '-1', '--format=%H %s'], 
                        check=True, 
                        capture_output=True,
                        cwd=os.path.dirname(__file__))
            return {
                'status': 'success',
                'message': result.stdout.decode().strip()
            }
        except subprocess.CalledProcessError as e:
            return {'status': 'error', 'message': str(e)}

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
        self.blogs = []
        if os.path.exists(self.root):
            for blog_dir in os.listdir(self.root):
                dir_path = os.path.join(self.root, blog_dir)
                if os.path.isdir(dir_path):
                    blog_file = os.path.join(dir_path, f"{blog_dir}.md")
                    if os.path.exists(blog_file):
                        self.blogs.append(blog_dir)
    
    def _extract_title(self, content):
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
        # Sanitize blog_name to prevent path traversal
        if not re.match(r'^[a-zA-Z0-9-]+$', blog_name):
            return None
            
        post_path = os.path.join(self.root, blog_name, f"{blog_name}.md")
        post_path = os.path.abspath(post_path)
        if not post_path.startswith(self.root):
            return None
            
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
        self.name_seeds = {}
        self.random_hex = ''.join(rng.choices(string.hexdigits, k=16))

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

    def name(self, ip):
        if ip not in self.name_seeds:
            self.name_seeds[ip] = rng.randint(0, 2**32)
        rng.seed(self.name_seeds[ip])
        return 'Anon-' + ''.join(rng.choices(string.hexdigits, k=6))

    def _is_rate_limited(self, ip):
        now = time.time()
        self.rate_limits[ip] = [t for t in self.rate_limits[ip] 
                               if t > now - self.rate_limit_period]
        if len(self.rate_limits[ip]) >= self.max_comments_per_period:
            return True
        self.rate_limits[ip].append(now)
        return False

    def sanitize_html(self, content):
        if '<img' not in content:
            return content.replace('<', '&lt;').replace('>', '&gt;')
        
        parts = []
        remaining = content
        while '<img' in remaining:
            before, rest = remaining.split('<img', 1)
            if '>' in rest:
                img_part, after = rest.split('>', 1)
                if 'src="/static/emojis/' in img_part and \
                   'class="emoji"' in img_part and \
                   not any(bad in img_part.lower() for bad in ['onerror', 'onload', 'javascript:', 'data:']):
                    parts.append(before.replace('<', '&lt;').replace('>', '&gt;'))
                    parts.append(f'<img{img_part}>')
                    remaining = after
                else:
                    parts.append(before.replace('<', '&lt;').replace('>', '&gt;'))
                    parts.append('&lt;img' + img_part.replace('<', '&lt;').replace('>', '&gt;') + '&gt;')
                    remaining = after
            else:
                remaining = before + '<img' + rest
                break
        
        if remaining:
            parts.append(remaining.replace('<', '&lt;').replace('>', '&gt;'))
        
        return ''.join(parts)

    def add_comment(self, post_id, content, ip):
        content = content.strip()
        if not content:
            raise ValueError("Empty comment")
        
        if self.is_ip_blocked(ip):
            raise ValueError("Your IP has been blocked from commenting")
        if self._is_rate_limited(ip):
            raise ValueError("Too many comments. Please wait a minute.")
        
        if len(content) > self.max_comment_length:
            raise ValueError(f"Comment too long (max {self.max_comment_length} characters)")

        if post_id not in self.comments:
            self.comments[post_id] = []
        
        self.comments[post_id].append({
            'name': self.name(ip),
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

class PythonExecutor:
    SAFE_BUILTINS = {
        'abs': abs,
        'all': all,
        'any': any,
        'ascii': ascii,
        'bin': bin,
        'bool': bool,
        'chr': chr,
        'dict': dict,
        'dir': dir,
        'divmod': divmod,
        'enumerate': enumerate,
        'filter': filter,
        'float': float,
        'format': format,
        'hex': hex,
        'int': int,
        'isinstance': isinstance,
        'len': len,
        'list': list,
        'map': map,
        'max': max,
        'min': min,
        'oct': oct,
        'ord': ord,
        'pow': pow,
        'print': print,
        'range': range,
        'repr': repr,
        'reversed': reversed,
        'round': round,
        'set': set,
        'slice': slice,
        'sorted': sorted,
        'str': str,
        'sum': sum,
        'tuple': tuple,
        'zip': zip,
    }

    def execute(self, code):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                exec(code, {'__builtins__': self.SAFE_BUILTINS}, {})
            except Exception as e:
                print(f"Error: {str(e)}")
        return output.getvalue()

class EmojiManager:
    def __init__(self):
        self.emoji_file = os.path.join(os.path.dirname(__file__), "static/emojis/emoji.json")
        self.emojis = self._load_emojis()
        self.extension_pattern = re.compile(r'\.(gif|png|jpg|jpeg)$', re.IGNORECASE)
        
    def _load_emojis(self):
        if os.path.exists(self.emoji_file):
            with open(self.emoji_file, 'r') as f:
                return json.load(f)
        return {}

    def get_emoji_path(self, name):
        for filename, data in self.emojis.items():
            if (name == data['names']['used'] or 
                name == data['names']['actual'] or 
                name in data['names']['aliases']):
                return f"/static/emojis/{filename}"
        return None

    def is_valid_emoji_path(self, path):
        if not path.startswith('/static/emojis/'):
            return False
        
        filename = path.split('/')[-1]
        
        return any(filename == f for f in self.emojis.keys())

    def sanitize_html(self, content):
        if '<img' not in content:
            return content.replace('<', '&lt;').replace('>', '&gt;')
        
        parts = []
        remaining = content
        while '<img' in remaining:
            before, rest = remaining.split('<img', 1)
            if '>' in rest:
                img_part, after = rest.split('>', 1)
                src_match = re.search(r'src="([^"]+)"', img_part)
                if src_match and self.is_valid_emoji_path(src_match.group(1)) and \
                   'class="emoji"' in img_part and \
                   not any(bad in img_part.lower() for bad in ['onerror', 'onload', 'javascript:', 'data:']):
                    parts.append(before.replace('<', '&lt;').replace('>', '&gt;'))
                    parts.append(f'<img{img_part}>')
                    remaining = after
                else:
                    parts.append(before.replace('<', '&lt;').replace('>', '&gt;'))
                    parts.append('&lt;img' + img_part.replace('<', '&lt;').replace('>', '&gt;') + '&gt;')
                    remaining = after
            else:
                remaining = before + '<img' + rest
                break
        
        if remaining:
            parts.append(remaining.replace('<', '&lt;').replace('>', '&gt;'))
        
        return ''.join(parts)

    def replace_emoji_tags(self, text):
        pattern = r':([^:\s]+):'
        
        def replace(match):
            emoji_name = match.group(1)
            emoji_path = self.get_emoji_path(emoji_name)
            if emoji_path and self.is_valid_emoji_path(emoji_path):
                return f'<img src="{emoji_path}" alt=":{emoji_name}:" class="emoji">'
            return match.group(0)
        
        return re.sub(pattern, replace, text)

    def get_all_emojis(self):
        return [{
            'path': f"/static/emojis/{filename}",
            'names': data['names'],
            'tags': data['tags']
        } for filename, data in self.emojis.items()]

    def search_emojis(self, query):
        query = query.lower()
        results = []
        
        for filename, data in self.emojis.items():
            if (query in data['names']['used'].lower() or
                query in data['names']['actual'].lower() or
                any(query in alias.lower() for alias in data['names']['aliases']) or
                any(query in tag.lower() for tag in data['tags'])):
                
                results.append({
                    'path': f"/static/emojis/{filename}",
                    'names': data['names'],
                    'tags': data['tags']
                })
        
        return results

emoji_manager = EmojiManager()