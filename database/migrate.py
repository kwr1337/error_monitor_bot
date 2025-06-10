from .database import engine
from .models import Base
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    try:
        # Создаем все таблицы
        Base.metadata.create_all(engine)
        logger.info("Database migration completed successfully")
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        raise

if __name__ == "__main__":
    migrate() 