import os
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config
from models import db
from routes.auth_routes import auth_bp
from routes.student_routes import student_bp
from routes.admin_routes import admin_bp
from routes.payment_routes import payment_bp

# Locate frontend dist folder (supports both local and Docker container layouts)
frontend_dist = os.environ.get(
    'FRONTEND_DIST',
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist'))
)

app = Flask(__name__, static_folder=frontend_dist if os.path.exists(frontend_dist) else None)
app.config.from_object(Config)

# Enable CORS for all routes and origins
CORS(app, resources={r"/api/*": {"origins": "*", "allow_headers": ["Content-Type", "Authorization", "Access-Control-Allow-Origin"]}}, supports_credentials=True)

# Initialize extensions
db.init_app(app)
jwt = JWTManager(app)

# JWT Error handling
@jwt.unauthorized_loader
def unauthorized_callback(callback):
    return jsonify({'error': 'Missing Authorization Header or Token'}), 401

@jwt.invalid_token_loader
def invalid_token_callback(callback):
    return jsonify({'error': 'Invalid Authorization Token'}), 401

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({'error': 'Session Token Has Expired. Please Log In Again.'}), 401

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(student_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(payment_bp)

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'system': 'StayWise Smart Hostel Booking System API', 'version': '1.0.0'}), 200

# Serve React Frontend SPA routes
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path.startswith('api/'):
        return jsonify({'error': 'Endpoint not found'}), 404
    file_path = os.path.join(frontend_dist, path)
    if path != "" and os.path.exists(file_path):
        return send_from_directory(frontend_dist, path)
    index_file = os.path.join(frontend_dist, 'index.html')
    if os.path.exists(index_file):
        return send_from_directory(frontend_dist, 'index.html')
    return jsonify({
        'status': 'StayWise API Server is running',
        'health_check': '/api/health',
        'note': 'Frontend dist directory not found.'
    }), 200

# Auto-initialize and seed database on startup (for both gunicorn and direct python)
with app.app_context():
    db.create_all()
    try:
        from seed import seed_database
        from models import User
        if not User.query.first():
            seed_database()
    except Exception as e:
        print(f"Startup DB check note: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
