import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'staywise-secret-key-2026-prod-qual-super-secret')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///staywise.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'staywise-jwt-secret-key-2026-production-qual-32bytes-secure')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)
