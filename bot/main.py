import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler, CallbackQueryHandler
import os
import uuid
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database.database import get_db
from database.models import Project, Subscriber, ErrorLog, Heartbeat

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Состояния диалога добавления проекта
PROJECT_NAME, PROJECT_TYPE = range(2)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

async def check_projects_status(context: ContextTypes.DEFAULT_TYPE):
    """
    Периодическая проверка состояния проектов
    """
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
                # Получаем подписчиков проекта
                subscribers = db.query(Subscriber).filter(
                    Subscriber.subscribed_projects.contains([project.id])
                ).all()
                
                # Отправляем уведомления
                for subscriber in subscribers:
                    try:
                        await context.bot.send_message(
                            chat_id=subscriber.telegram_id,
                            text=(
                                f"⚠️ <b>Внимание! Проект неактивен</b>\n\n"
                                f"📝 Проект: <b>{project.name}</b>\n"
                                f"🏷️ Тип: <b>{project.type}</b>\n"
                                f"⏰ Последний heartbeat: <b>{project.last_heartbeat.strftime('%Y-%m-%d %H:%M:%S') if project.last_heartbeat else 'Никогда'}</b>\n\n"
                                "Проект не отправлял сигналы активности более часа."
                            ),
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Error sending notification to {subscriber.telegram_id}: {e}")

        finally:
            db.close()
    except Exception as e:
        logger.exception("Error in check_projects_status")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    full_name = update.effective_user.full_name

    # Добавляем пользователя в базу данных, если его там нет
    db = next(get_db())
    subscriber = db.query(Subscriber).filter_by(telegram_id=user_id).first()
    
    if not subscriber:
        subscriber = Subscriber(
            telegram_id=user_id,
            full_name=full_name
        )
        db.add(subscriber)
        db.commit()

    await update.message.reply_text(
        "Привет! Я бот для мониторинга ошибок. "
        "Используйте /help для просмотра доступных команд."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    is_admin = False
    db = next(get_db())
    subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
    
    if subscriber and subscriber.is_admin:
        is_admin = True

    help_text = """
Доступные команды:

/subscribe - Подписаться на уведомления проекта
/unsubscribe - Отписаться от уведомлений
/mysubs - Показать мои подписки
"""

    if is_admin:
        admin_commands = """
Админские команды:
/addproject - Добавить новый проект
/listprojects - Список всех проектов
/editproject - Редактировать проект
/deleteproject - Удалить проект
/addadmin - Добавить админа
/stats - Статистика по ошибкам
/broadcast - Отправить сообщение всем подписчикам
"""
        help_text += admin_commands

    await update.message.reply_text(help_text)

async def add_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога добавления проекта"""
    # Проверяем права администратора
    db = next(get_db())
    subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
    
    if not subscriber or not subscriber.is_admin:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END

    await update.message.reply_text(
        "Давайте добавим новый проект для мониторинга.\n"
        "Введите название проекта:"
    )
    return PROJECT_NAME

async def project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка названия проекта"""
    context.user_data['project_name'] = update.message.text
    
    keyboard = [
        [
            InlineKeyboardButton("Bot 🤖", callback_data='type_bot'),
            InlineKeyboardButton("Website 🌐", callback_data='type_website'),
            InlineKeyboardButton("Other 📦", callback_data='type_other')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите тип проекта:",
        reply_markup=reply_markup
    )
    return PROJECT_TYPE

async def project_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка типа проекта и сохранение"""
    query = update.callback_query
    await query.answer()
    
    project_type = query.data.replace('type_', '')
    project_name = context.user_data['project_name']
    project_token = str(uuid.uuid4())
    
    db = next(get_db())
    new_project = Project(
        name=project_name,
        type=project_type,
        token=project_token,
        is_active=True
    )
    db.add(new_project)
    db.commit()
    
    response_text = f"""
✅ Проект успешно добавлен!

📝 Название: {project_name}
🏷️ Тип: {project_type}
🔑 Токен: `{project_token}`

Используйте этот токен для интеграции с SDK.
"""
    await query.edit_message_text(response_text, parse_mode='Markdown')
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога"""
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats"""
    db = next(get_db())
    subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
    
    if not subscriber or not subscriber.is_admin:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    total_errors = db.query(ErrorLog).count()
    active_projects = db.query(Project).filter(Project.is_active == True).count()
    total_subscribers = db.query(Subscriber).count()

    stats_text = f"""
📊 Статистика:

Всего проектов: {active_projects}
Всего ошибок: {total_errors}
Подписчиков: {total_subscribers}
"""
    await update.message.reply_text(stats_text)

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подписаться на уведомления проекта"""
    db = next(get_db())
    try:
        # Получаем список активных проектов
        projects = db.query(Project).filter(Project.is_active == True).all()
        
        if not projects:
            await update.message.reply_text("В данный момент нет доступных проектов для подписки.")
            return

        # Создаем клавиатуру с проектами
        keyboard = []
        for project in projects:
            keyboard.append([InlineKeyboardButton(
                f"{project.name} ({project.type})", 
                callback_data=f"subscribe_{project.id}"
            )])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите проект для подписки:",
            reply_markup=reply_markup
        )
    finally:
        db.close()

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отписаться от уведомлений"""
    db = next(get_db())
    try:
        # Получаем подписки пользователя
        subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
        if not subscriber or not subscriber.subscribed_projects:
            await update.message.reply_text("У вас нет активных подписок.")
            return

        # Получаем проекты, на которые подписан пользователь
        projects = db.query(Project).filter(Project.id.in_(subscriber.subscribed_projects)).all()
        
        # Создаем клавиатуру с проектами
        keyboard = []
        for project in projects:
            keyboard.append([InlineKeyboardButton(
                f"{project.name} ({project.type})", 
                callback_data=f"unsubscribe_{project.id}"
            )])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите проект для отписки:",
            reply_markup=reply_markup
        )
    finally:
        db.close()

async def mysubs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать мои подписки"""
    db = next(get_db())
    try:
        subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
        if not subscriber or not subscriber.subscribed_projects:
            await update.message.reply_text("У вас нет активных подписок.")
            return

        projects = db.query(Project).filter(Project.id.in_(subscriber.subscribed_projects)).all()
        
        message = "Ваши подписки:\n\n"
        for project in projects:
            message += f"📌 {project.name} ({project.type})\n"
        
        await update.message.reply_text(message)
    finally:
        db.close()

async def listprojects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех проектов"""
    # Проверяем права администратора
    db = next(get_db())
    try:
        subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
        if not subscriber or not subscriber.is_admin:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return

        projects = db.query(Project).all()
        if not projects:
            await update.message.reply_text("Проекты отсутствуют.")
            return

        message = "Список проектов:\n\n"
        for project in projects:
            status = "✅ Активен" if project.is_active else "❌ Неактивен"
            last_heartbeat = project.last_heartbeat.strftime("%Y-%m-%d %H:%M:%S") if project.last_heartbeat else "Никогда"
            message += f"📝 {project.name}\n"
            message += f"🏷️ Тип: {project.type}\n"
            message += f"🔑 Токен: {project.token}\n"
            message += f"📊 Статус: {status}\n"
            message += f"⏰ Последний heartbeat: {last_heartbeat}\n\n"

        await update.message.reply_text(message)
    finally:
        db.close()

async def editproject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактировать проект"""
    db = next(get_db())
    try:
        subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
        if not subscriber or not subscriber.is_admin:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return

        projects = db.query(Project).all()
        if not projects:
            await update.message.reply_text("Проекты отсутствуют.")
            return

        keyboard = []
        for project in projects:
            keyboard.append([InlineKeyboardButton(
                f"{project.name} ({project.type})", 
                callback_data=f"edit_{project.id}"
            )])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите проект для редактирования:",
            reply_markup=reply_markup
        )
    finally:
        db.close()

async def deleteproject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить проект"""
    db = next(get_db())
    try:
        subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
        if not subscriber or not subscriber.is_admin:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return

        projects = db.query(Project).all()
        if not projects:
            await update.message.reply_text("Проекты отсутствуют.")
            return

        keyboard = []
        for project in projects:
            keyboard.append([InlineKeyboardButton(
                f"{project.name} ({project.type})", 
                callback_data=f"delete_{project.id}"
            )])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ Выберите проект для удаления:\n"
            "(Это действие нельзя отменить)",
            reply_markup=reply_markup
        )
    finally:
        db.close()

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить админа"""
    db = next(get_db())
    try:
        subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
        if not subscriber or not subscriber.is_admin:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return

        await update.message.reply_text(
            "Для добавления нового администратора, перешлите сообщение от пользователя, "
            "которого хотите назначить администратором."
        )
    finally:
        db.close()

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправить сообщение всем подписчикам"""
    db = next(get_db())
    try:
        subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
        if not subscriber or not subscriber.is_admin:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return

        # Проверяем, есть ли текст сообщения
        if not context.args:
            await update.message.reply_text(
                "Использование: /broadcast <текст сообщения>"
            )
            return

        message_text = " ".join(context.args)
        subscribers = db.query(Subscriber).all()
        success_count = 0
        fail_count = 0

        for sub in subscribers:
            try:
                await context.bot.send_message(
                    chat_id=sub.telegram_id,
                    text=f"📢 Объявление:\n\n{message_text}"
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Error sending broadcast to {sub.telegram_id}: {e}")
                fail_count += 1

        await update.message.reply_text(
            f"Сообщение отправлено:\n"
            f"✅ Успешно: {success_count}\n"
            f"❌ Ошибок: {fail_count}"
        )
    finally:
        db.close()

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    db = next(get_db())
    try:
        data = query.data
        if data.startswith("subscribe_"):
            project_id = int(data.split("_")[1])
            subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
            
            if not subscriber:
                subscriber = Subscriber(
                    telegram_id=update.effective_user.id,
                    full_name=update.effective_user.full_name
                )
                db.add(subscriber)
            
            if not subscriber.subscribed_projects:
                subscriber.subscribed_projects = []
            
            if project_id not in subscriber.subscribed_projects:
                subscriber.subscribed_projects.append(project_id)
                db.commit()
                project = db.query(Project).get(project_id)
                await query.edit_message_text(f"✅ Вы успешно подписались на проект {project.name}")
            else:
                await query.edit_message_text("Вы уже подписаны на этот проект")

        elif data.startswith("unsubscribe_"):
            project_id = int(data.split("_")[1])
            subscriber = db.query(Subscriber).filter_by(telegram_id=update.effective_user.id).first()
            
            if subscriber and subscriber.subscribed_projects and project_id in subscriber.subscribed_projects:
                subscriber.subscribed_projects.remove(project_id)
                db.commit()
                project = db.query(Project).get(project_id)
                await query.edit_message_text(f"✅ Вы успешно отписались от проекта {project.name}")
            else:
                await query.edit_message_text("Вы не были подписаны на этот проект")

        elif data.startswith("edit_"):
            project_id = int(data.split("_")[1])
            project = db.query(Project).get(project_id)
            if project:
                keyboard = [
                    [InlineKeyboardButton("Изменить статус", callback_data=f"toggle_status_{project_id}")],
                    [InlineKeyboardButton("Сгенерировать новый токен", callback_data=f"new_token_{project_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"Редактирование проекта {project.name}:\n"
                    f"Текущий статус: {'✅ Активен' if project.is_active else '❌ Неактивен'}\n"
                    f"Текущий токен: {project.token}",
                    reply_markup=reply_markup
                )

        elif data.startswith("toggle_status_"):
            project_id = int(data.split("_")[2])
            project = db.query(Project).get(project_id)
            if project:
                project.is_active = not project.is_active
                db.commit()
                await query.edit_message_text(
                    f"Статус проекта {project.name} изменен на: "
                    f"{'✅ Активен' if project.is_active else '❌ Неактивен'}"
                )

        elif data.startswith("new_token_"):
            project_id = int(data.split("_")[2])
            project = db.query(Project).get(project_id)
            if project:
                project.token = str(uuid.uuid4())
                db.commit()
                await query.edit_message_text(
                    f"Для проекта {project.name} сгенерирован новый токен:\n"
                    f"{project.token}"
                )

        elif data.startswith("delete_"):
            project_id = int(data.split("_")[1])
            project = db.query(Project).get(project_id)
            if project:
                # Удаляем проект из подписок всех пользователей
                subscribers = db.query(Subscriber).all()
                for subscriber in subscribers:
                    if subscriber.subscribed_projects and project_id in subscriber.subscribed_projects:
                        subscriber.subscribed_projects.remove(project_id)
                
                # Удаляем сам проект
                db.delete(project)
                db.commit()
                await query.edit_message_text(f"✅ Проект {project.name} успешно удален")

    finally:
        db.close()

def create_application() -> Application:
    """Создание и настройка приложения"""
    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем диалог добавления проекта
    add_project_handler = ConversationHandler(
        entry_points=[CommandHandler("addproject", add_project)],
        states={
            PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, project_name)],
            PROJECT_TYPE: [CallbackQueryHandler(project_type, pattern='^type_')],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(add_project_handler)
    application.add_handler(CommandHandler("stats", stats))
    
    # Добавляем новые обработчики
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("mysubs", mysubs))
    application.add_handler(CommandHandler("listprojects", listprojects))
    application.add_handler(CommandHandler("editproject", editproject))
    application.add_handler(CommandHandler("deleteproject", deleteproject))
    application.add_handler(CommandHandler("addadmin", addadmin))
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Добавляем обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_callback))

    # Настраиваем периодическую задачу
    job_queue = application.job_queue
    job_queue.run_repeating(check_projects_status, interval=3600, first=10)

    return application

def main() -> None:
    """Запуск бота"""
    application = create_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 