from database.database import get_db
from database.models import Project

def add_project(name: str, project_type: str, token: str):
    db = next(get_db())
    try:
        # Проверяем, существует ли проект с таким токеном
        project = db.query(Project).filter_by(token=token).first()
        
        if project:
            # Если проект существует, активируем его
            project.is_active = True
            print(f"✅ Проект {name} активирован")
        else:
            # Если проекта нет, создаем новый
            project = Project(
                name=name,
                type=project_type,
                token=token,
                is_active=True
            )
            db.add(project)
            print(f"✅ Проект {name} добавлен")
        
        db.commit()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Добавляем проект с заданным токеном
    add_project(
        name="HR Club RT Bot",
        project_type="telegram_bot",
        token="17e1dbbf-fb53-43b0-9f0f-1cae81f95bfa"
    )
    print("✨ Готово!") 