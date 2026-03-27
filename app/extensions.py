# backend/app/extensions.py
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_pymongo import PyMongo

jwt = JWTManager()
cors = CORS()
mongo = PyMongo()