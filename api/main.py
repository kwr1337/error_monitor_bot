from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any
from datetime import datetime, timedelta
import json
import logging
import asyncio
from aiogram import Bot

from database.database import get_db
from database.models import Project, ErrorLog, Heartbeat, Subscriber

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Конфигурация бота для уведомлений
NOTIFICATION_BOT_TOKEN = "7766927049:AAHajpHBYK6-rHMp1sSyGW6AAirAZWH4oIE"
notification_bot = Bot(token=NOTIFICATION_BOT_TOKEN)

app = FastAPI(title="Error Monitor API")

async def check_projects_status():
    """
    Фоновая задача для проверки состояния проектов
    """
    while True:
        try:
            db = next(get_db())
            try:
                # Проверяем проекты, от которых не было heartbeat более часа
                one_hour_ago = datetime.utcnow() - timedelta(hours=1)
                inactive_projects = db.query(Project).filter(
                    Project.is_active == True,
                    (Project.last_heartbeat < one_hour_ago) | (Project.last_heartbeat == None)
                ).all()

                for project in inactive_projects:
                    logger.warning(f"Project {project.name} hasn't sent heartbeat in the last hour!")
                    
                    # Получаем подписчиков проекта
                    subscribers = db.query(Subscriber).filter(
                        Subscriber.subscribed_projects.contains([project.id])
                    ).all()
                    
                    # Отправляем уведомления через бота
                    for subscriber in subscribers:
                        try:
                            message = (
                                f"❌ <b>Внимание! Проект не отвечает</b>\n\n"
                                f"📝 Проект: <b>{project.name}</b>\n"
                                f"🏷️ Тип: <b>{project.type}</b>\n"
                                f"⚠️ Статус: <b>Нет активности более часа</b>\n"
                                f"⏰ Последняя активность: <b>{project.last_heartbeat.strftime('%d-%m-%Y %H:%M:%S') if project.last_heartbeat else 'Никогда'}</b>"
                            )
                            
                            await notification_bot.send_message(
                                chat_id=subscriber.telegram_id,
                                text=message,
                                parse_mode="HTML"
                            )
                            logger.info(f"Sent inactive project notification to subscriber {subscriber.telegram_id}")
                        except Exception as e:
                            logger.error(f"Failed to send notification to subscriber {subscriber.telegram_id}: {e}")

            finally:
                db.close()
        except Exception as e:
            logger.exception("Error in check_projects_status")
        
        await asyncio.sleep(3600)  # Проверяем каждый час

@app.post("/api/v1/heartbeat")
async def heartbeat(data: Dict[Any, Any], db: Session = Depends(get_db)):
    """
    Принимает сигналы heartbeat от проектов
    """
    try:
        logger.debug(f"Received heartbeat data: {data}")
        
        # Проверяем токен проекта
        project = db.query(Project).filter(
            Project.token == data.get("project_token"),
            Project.is_active == True
        ).first()
        
        logger.debug(f"Found project: {project}")
        
        if not project:
            logger.warning(f"Invalid project token: {data.get('project_token')}")
            raise HTTPException(status_code=401, detail="Invalid project token")

        # Обновляем время последнего heartbeat
        current_time = datetime.utcnow()
        project.last_heartbeat = current_time

        # Создаем запись о heartbeat
        heartbeat = Heartbeat(
            project_id=project.id,
            status=data.get("status", "alive"),
            version=data.get("version"),
            additional_data=data.get("additional_data", {}),
            created_at=current_time
        )
        
        db.add(heartbeat)
        db.commit()

        # Получаем подписчиков проекта для уведомления
        subscribers = db.query(Subscriber).filter(
            Subscriber.subscribed_projects.contains([project.id])
        ).all()

        # Отправляем уведомление о работающем проекте
        for subscriber in subscribers:
            try:
                message = (
                    f"✅ <b>Проект активен</b>\n\n"
                    f"📝 Проект: <b>{project.name}</b>\n"
                    f"🏷️ Тип: <b>{project.type}</b>\n"
                    f"📊 Статус: <b>{data.get('status', 'alive')}</b>\n"
                    f"🔄 Версия: <b>{data.get('version', 'N/A')}</b>\n"
                    f"⏰ Время: <b>{current_time.strftime('%d-%m-%Y %H:%M:%S')}</b>"
                )
                
                if data.get("metadata"):
                    message += "\n\n📋 Дополнительная информация:"
                    for key, value in data["metadata"].items():
                        message += f"\n• {key}: <b>{value}</b>"
                
                await notification_bot.send_message(
                    chat_id=subscriber.telegram_id,
                    text=message,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending notification to subscriber {subscriber.telegram_id}: {e}")

        return {"status": "success", "message": "Heartbeat received"}
    
    except Exception as e:
        logger.exception("Error in heartbeat endpoint")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def startup_event():
    """
    Запускаем фоновые задачи при старте приложения
    """
    asyncio.create_task(check_projects_status())

async def send_notification(telegram_id: int, message: str):
    """
    Отправляет уведомление пользователю через Telegram бота
    """
    try:
        await notification_bot.send_message(
            chat_id=telegram_id,
            text=message,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send notification to {telegram_id}: {e}")

async def notify_subscribers_about_error(db: Session, project: Project, error_data: Dict):
    """
    Уведомляет всех подписчиков проекта о новой ошибке
    """
    subscribers = db.query(Subscriber).filter(
        Subscriber.subscribed_projects.contains([project.id])
    ).all()
    
    error_message = (
        f"🚨 <b>Новая ошибка в проекте {project.name}</b>\n\n"
        f"Тип: {error_data.get('type', 'Unknown')}\n"
        f"Сообщение: {error_data.get('message', 'No message')}\n"
        f"Важность: {error_data.get('severity', 'error')}\n"
        f"Время: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}"
    )
    
    for subscriber in subscribers:
        await send_notification(subscriber.telegram_id, error_message)

@app.post("/api/v1/log")
async def log_error(data: Dict[Any, Any], db: Session = Depends(get_db)):
    """
    Принимает логи ошибок от проектов
    """
    try:
        # Проверяем токен проекта
        project = db.query(Project).filter(
            Project.token == data.get("project_token"),
            Project.is_active == True
        ).first()
        
        if not project:
            raise HTTPException(status_code=401, detail="Invalid project token")

        error_data = data.get("error", {})
        
        # Создаем запись об ошибке
        error_log = ErrorLog(
            project_id=project.id,
            error_type=error_data.get("type", "Unknown"),
            error_message=error_data.get("message", "No message provided"),
            stack_trace=error_data.get("stack_trace"),
            severity_level=error_data.get("severity", "error"),
            additional_data=error_data.get("context", {}),
            created_at=datetime.now()
        )
        
        db.add(error_log)
        db.commit()

        # Отправляем уведомления подписчикам
        await notify_subscribers_about_error(db, project, error_data)

        return {"status": "success", "message": "Error logged successfully"}
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/projects")
async def get_projects(db: Session = Depends(get_db)):
    """
    Получает список всех проектов
    """
    projects = db.query(Project).all()
    return {"projects": [{"id": p.id, "name": p.name, "type": p.type} for p in projects]}

@app.get("/api/v1/stats")
async def get_stats(db: Session = Depends(get_db)):
    """
    Получает статистику по ошибкам
    """
    total_errors = db.query(ErrorLog).count()
    active_projects = db.query(Project).filter(Project.is_active == True).count()
    
    return {
        "total_errors": total_errors,
        "active_projects": active_projects
    } 