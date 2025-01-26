import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from flask_wtf.csrf import CSRFProtect
from sweater import utils
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
import re
from pathlib import Path

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

app = Flask(__name__,
           template_folder=template_dir,
           static_folder=static_dir)
app.config['SECRET_KEY'] = os.urandom(32)  # Required for CSRF
csrf = CSRFProtect(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'zip', 'md'}

# Create uploads directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_safe_path(path):
    """Check if the path is safe (no directory traversal)"""
    return not (('..' in path) or ('/' in path) or ('\\' in path))

def sanitize_path(filename):
    """Sanitize the custom path"""
    # Remove any leading/trailing slashes and spaces
    filename = filename.strip('/ ').replace('\\', '/')
    # Replace multiple slashes with single slash
    filename = re.sub(r'/+', '/', filename)
    return filename

def get_file_type(filename):
    """Determine if file is an image or other type"""
    ext = filename.rsplit('.', 1)[1].lower()
    return 'image' if ext in {'png', 'jpg', 'jpeg', 'gif'} else 'article' if ext == 'md' else 'file'

content_manager = utils.Content()
link_shortener = utils.LinkShortener()
comments_manager = utils.Comments()

@app.errorhandler(HTTPException) # dynamic error page
def error(e):
    return render_template('error.html', status_code=e.code)

@app.route('/')
def index():
    return render_template('home.html', stats=content_manager.get_stats())

@app.route('/posts')
def posts():
    is_admin = request.cookies.get('admin_token') == utils.get_key()
    return render_template('posts.html', posts=content_manager.get_posts(), admin=is_admin)

@app.route('/post/<blog_name>')
def post(blog_name):
    post = content_manager.get_post(blog_name)
    if post:
        comments = comments_manager.get_comments(blog_name)
        # Add meta tags for Discord embed
        meta = {
            'title': post['title'],
            'type': 'article',
            'description': post['content'][:200] + '...' if len(post['content']) > 200 else post['content'],
            'url': request.url
        }
        return render_template('post.html', post=post, comments=comments, meta=meta)
    return "Post not found", 404

@app.route('/post/<blog_name>/comment', methods=['POST'])
def add_comment(blog_name):
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            try:
                comments_manager.add_comment(blog_name, content, request.remote_addr)
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('post', blog_name=blog_name))
    return redirect(url_for('post', blog_name=blog_name))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/l/<short_id>')
def short_link(short_id):
    url = link_shortener.get_link(short_id)
    if url:
        return redirect(url)
    return "Link not found", 404

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == utils.get_key():  # In production, use proper authentication
            response = redirect(request.args.get('next', url_for('admin')))
            response.set_cookie('admin_token', utils.get_key(), httponly=True, secure=True)
            return response
        flash('Invalid password', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    response = redirect(url_for('index'))
    response.delete_cookie('admin_token')
    return response

@app.route('/admin/links', methods=['GET', 'POST'])
@utils.requires_auth
def manage_links():
    if request.method == 'POST':
        url = request.form.get('url')
        custom_id = request.form.get('custom_id')
        if url:
            short_id = link_shortener.add_link(url, custom_id)
            return render_template('links.html', message=f"Created short link: {request.host_url}l/{short_id}")
    return render_template('links.html')

@app.route('/admin/moderate/<action>/<blog_name>/<int:comment_index>', methods=['POST'])
@utils.requires_auth
def moderate_comment(action, blog_name, comment_index):
    comment = comments_manager.comments.get(blog_name, [])[comment_index]
    
    if action in ['block', 'both']:
        comments_manager.block_ip(comment.get('ip'))
    
    if action in ['delete', 'both']:
        comments_manager.delete_comment(blog_name, comment_index)
    
    return '', 204

@app.route('/admin')
@utils.requires_auth
def admin():
    stats = {
        'total_comments': comments_manager.get_stats()['total'],
        'blocked_ips': comments_manager.get_stats()['blocked_ips'],
        'total_links': link_shortener.get_stats(),
        'total_posts': len(content_manager.blogs) if content_manager.blogs else 0
    }
    all_comments = comments_manager.get_all_comments()
    blocked_ips = comments_manager.blacklist.get('ips', [])
    password = utils.get_key()
    return render_template('admin.html', stats=stats, all_comments=all_comments, blocked_ips=blocked_ips, password=password)

@app.route('/admin/unblock/<ip>', methods=['POST'])
@utils.requires_auth
def unblock_ip(ip):
    comments_manager.unblock_ip(ip)
    flash('IP unblocked successfully', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/write', methods=['GET', 'POST'])
@utils.requires_auth
def write_post():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        folder_name = request.form.get('folder_name')
        if title and content:
            success = content_manager.create_post(title, content, folder_name)
            if success:
                flash('Post created successfully', 'success')
                return redirect(url_for('posts'))
            flash('Error creating post', 'error')
    return render_template('write_post.html')

@app.route('/admin/upload', methods=['GET', 'POST'])
@utils.requires_auth
def upload_post():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        folder_name = request.form.get('folder_name')
        
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
            
        if file and file.filename.endswith('.md'):
            success = content_manager.upload_post(file, folder_name)
            if success:
                flash('Post uploaded successfully', 'success')
                return redirect(url_for('posts'))
            flash('Error uploading post', 'error')
    return render_template('upload_post.html')

@app.route('/admin/upload-file', methods=['GET', 'POST'])
@utils.requires_auth
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        custom_path = request.form.get('custom_path', '').strip()
        
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            if custom_path:
                # Sanitize and create full path
                custom_path = sanitize_path(custom_path)
                # Create directories if they don't exist
                full_dir = os.path.join(UPLOAD_FOLDER, os.path.dirname(custom_path))
                os.makedirs(full_dir, exist_ok=True)
                # Save file
                file.save(os.path.join(UPLOAD_FOLDER, custom_path))
                saved_path = custom_path
            else:
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                saved_path = filename
            
            flash('File successfully uploaded', 'success')
            return redirect(url_for('uploaded_file', filename=saved_path))
            
        flash('File type not allowed', 'error')
        return redirect(request.url)
    
    # For GET requests, show list of uploaded files
    files = []
    for root, dirs, filenames in os.walk(UPLOAD_FOLDER):
        for filename in filenames:
            rel_path = os.path.relpath(os.path.join(root, filename), UPLOAD_FOLDER)
            files.append(rel_path)
            
    return render_template('upload.html', files=files)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """View file page with meta tags and proper display"""
    file_url = url_for('raw_file', filename=filename, _external=True)
    meta = {
        'title': filename,
        'type': get_file_type(filename),
        'url': file_url
    }
    return render_template('file_view.html', meta=meta, filename=filename)

@app.route('/raw-file/<path:filename>')
def raw_file(filename):
    """Serve the raw file directly from the uploads folder"""
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/admin/list-files')
@utils.requires_auth
def list_files():
    print('listing files')
    files = []
    for root, dirs, filenames in os.walk(UPLOAD_FOLDER):
        for filename in filenames:
            rel_path = os.path.relpath(os.path.join(root, filename), UPLOAD_FOLDER)
            files.append(rel_path)
    return render_template('list_files.html', files=files)

@app.route('/admin/git/pull')
@utils.requires_auth
def git_pull():
    try:
        utils.git_pull()
        flash('Git pull successful', 'success')
    except Exception as e:
        flash(f'Error during git pull: {e}', 'error')
    return redirect(url_for('admin'))

"""@app.route('/admin/exec_python', methods=['POST'])
@utils.requires_auth
def exec_python(code=None):
    print('got the request!')
    code = request.cookies.get('code')
    print(code)
    if code:
        try:
            print('executing code!')
            result = exec(code)
            crafted = {
                'result': result,
                'type': type(result).__name__,
                'code': code
            }
            print(crafted)
            flash('Code executed successfully', 'success')
            return result
        except Exception as e:
            flash(f'Error executing code: {e}', 'error')
    return redirect(url_for('admin'))"""