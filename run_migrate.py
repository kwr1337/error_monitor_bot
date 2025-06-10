import os
from database.database import engine
from database.models import Base
import sqlite3
from datetime import datetime

def run_migrations():
    # Удаляем старую базу данных, если она существует
    db_path = "error_monitor.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        print("🗑️ Старая база данных удалена")
    
    # Создаем все таблицы заново
    Base.metadata.create_all(engine)
    print("✅ База данных успешно создана")

    # Подключаемся к базе данных
    conn = sqlite3.connect('error_monitor.db')
    cursor = conn.cursor()
    
    try:
        # Добавляем колонку last_heartbeat, если её нет
        cursor.execute('''
        ALTER TABLE projects 
        ADD COLUMN last_heartbeat TIMESTAMP
        ''')
        print("✅ Колонка last_heartbeat добавлена")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ Колонка last_heartbeat уже существует")
        else:
            print(f"❌ Ошибка: {e}")
    
    conn.commit()
    conn.close()
    print("✅ База данных успешно обновлена")

if __name__ == "__main__":
    run_migrations() 