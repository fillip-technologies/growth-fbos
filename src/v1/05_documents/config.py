from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8005
    debug: bool = False

    jwt_secret: str = "fbos-local-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"

    # Physical / Presigned Storage Settings
    s3_bucket: str = "fbos-documents"
    s3_region: str = "ap-south-1"
    s3_endpoint_url: str = ""
    public_share_base_url: str = "https://share.fbos.example.com/s"
    max_upload_size_bytes: int = 104857600  # 100 MB default max

    # Database
    database_url: str = "mysql+aiomysql://root:fbos_root_password@db:3306/fbos_documents"
    db_ssl: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800


settings = Settings()
