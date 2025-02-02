from sweater import app
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)
wsgi_app = app.wsgi_app

if __name__ == '__main__':
    app.run(debug=not False, port=5005)