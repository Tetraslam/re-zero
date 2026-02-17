from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    convex_url: str = ""
    convex_deploy_key: str = ""
    modal_token_id: str = ""
    modal_token_secret: str = ""
    frontend_url: str = "http://localhost:3000"
    autumn_secret_key: str = ""
    use_bedrock: bool = False
    aws_region: str = "us-west-2"

    model_config = {"env_file": ".env"}


settings = Settings()
