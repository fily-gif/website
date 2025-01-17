import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_wtf.csrf import CSRFProtect
from sweater import utils

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

app = Flask(__name__,
           template_folder=template_dir,
           static_folder=static_dir)
app.config['SECRET_KEY'] = os.urandom(32)  # Required for CSRF
csrf = CSRFProtect(app)

content_manager = utils.Content()
link_shortener = utils.LinkShortener()
comments_manager = utils.Comments()

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
        return render_template('post.html', post=post, comments=comments)
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
        'total_posts': len(content_manager.blogs)
    }
    all_comments = comments_manager.get_all_comments()
    blocked_ips = comments_manager.blacklist.get('ips', [])
    return render_template('admin.html', stats=stats, all_comments=all_comments, blocked_ips=blocked_ips)

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

@app.route('/admin/api/git/pull', methods=['GET'])
@utils.requires_auth
def git_pull():
    utils.git_pull()
    return redirect(url_for('admin'))