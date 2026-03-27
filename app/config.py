# backend/app/config.py
from datetime import timedelta
import os


class BaseConfig:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017/coopcore")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "coopcore")

    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "jwt-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(
        seconds=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))
    )
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(
        seconds=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", 604800))
    )

    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:3000"
    ).split(",")

    # Cooperative settings
    COOP_NAME: str = os.getenv("COOP_NAME", "CoopCore Multi-Purpose Cooperative")
    DEFAULT_LOAN_RATE: float = float(os.getenv("DEFAULT_LOAN_RATE", 12))
    DEFAULT_SAVINGS_RATE: float = float(os.getenv("DEFAULT_SAVINGS_RATE", 3))
    SHARE_PAR_VALUE: float = float(os.getenv("SHARE_PAR_VALUE", 100))


class DevelopmentConfig(BaseConfig):
    DEBUG: bool = True


class TestingConfig(BaseConfig):
    TESTING: bool = True
    DEBUG: bool = True
    # Use a separate test database — never pollute the dev DB
    MONGO_URI: str = os.getenv(
        "MONGO_TEST_URI", "mongodb://localhost:27017/coopcore_test"
    )
    MONGO_DB_NAME: str = "coopcore_test"
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(minutes=5)
    SCHEDULER_ENABLED: str = "false"


class ProductionConfig(BaseConfig):
    DEBUG: bool = False


config_by_env: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}