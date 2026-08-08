from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Application settings, loaded from environment variables and .env file.
    """
    SPECTRIX_WORKER_URL: str = 'https://spectrix-worker.tariqmtaezeem.workers.dev/'
    AI_MODEL: str = 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free'
    ENABLE_SAFETY_CONFIRMATION: bool = False
    MAX_STEPS_DEFAULT: int = 25
    HEADLESS_DEFAULT: bool = True
    DB_PATH: str = './data/aegis.db'
    SCREENSHOT_MAX_WIDTH: int = 1280
    DOM_TOKEN_BUDGET: int = 3000
    PLAYWRIGHT_BROWSERS_PATH: str = 'D:\\playwright-browsers'

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

settings = Settings()
