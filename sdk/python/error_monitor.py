import requests
import traceback
from datetime import datetime
import logging
import json
from typing import Optional, Dict, Any
import threading
from queue import Queue
import time
import platform
import sys
import aiohttp
import asyncio

class ErrorMonitor:
    def __init__(
        self,
        project_token: str,
        api_url: str = "http://localhost:8000/api/v1",
        batch_size: int = 10,
        flush_interval: int = 60,
        heartbeat_interval: int = 3600  # 1 час
    ):
        self.project_token = project_token
        self.api_url = api_url.rstrip('/')
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.heartbeat_interval = heartbeat_interval
        
        self.error_queue = Queue()
        self.last_flush = datetime.now()
        self.last_heartbeat = datetime.now()
        
        # Системная информация для heartbeat
        self.system_info = {
            "python_version": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "machine": platform.machine()
        }
        
        # Запускаем фоновые потоки
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
        
        self.worker_thread.start()
        self.heartbeat_thread.start()
        
        self.logger = logging.getLogger('error_monitor')
        self.heartbeat_task = None

    def _worker(self):
        """Фоновый процесс для отправки ошибок"""
        while True:
            try:
                # Проверяем, нужно ли отправить накопленные ошибки
                if (datetime.now() - self.last_flush).seconds >= self.flush_interval:
                    self.flush()
                
                # Ждем немного перед следующей проверкой
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in worker thread: {e}")

    def _heartbeat_worker(self):
        """Фоновый процесс для отправки heartbeat"""
        while True:
            try:
                if (datetime.now() - self.last_heartbeat).seconds >= self.heartbeat_interval:
                    self.send_heartbeat()
                time.sleep(10)
            except Exception as e:
                self.logger.error(f"Error in heartbeat thread: {e}")

    def send_heartbeat(self):
        """Отправка сигнала, что проект работает"""
        try:
            heartbeat_data = {
                "project_token": self.project_token,
                "timestamp": datetime.now().isoformat(),
                "uptime": time.time() - self.start_time,
                "system_info": self.system_info
            }
            
            response = requests.post(
                f"{self.api_url}/heartbeat",
                json=heartbeat_data,
                timeout=5
            )
            
            if response.status_code != 200:
                raise Exception(f"API returned {response.status_code}: {response.text}")
            
            self.last_heartbeat = datetime.now()
            self.logger.debug("Heartbeat sent successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to send heartbeat: {e}")

    def log_error(
        self,
        error: Exception,
        severity: str = "error",
        context: Optional[Dict[str, Any]] = None
    ):
        """
        Логирование ошибки
        """
        try:
            error_data = {
                "project_token": self.project_token,
                "error": {
                    "type": error.__class__.__name__,
                    "message": str(error),
                    "stack_trace": ''.join(traceback.format_tb(error.__traceback__)),
                    "severity": severity,
                    "timestamp": datetime.now().isoformat(),
                    "context": {
                        **(context or {}),
                        "system_info": self.system_info
                    }
                }
            }
            
            # Добавляем ошибку в очередь
            self.error_queue.put(error_data)
            
            # Если накопилось достаточно ошибок, отправляем их
            if self.error_queue.qsize() >= self.batch_size:
                self.flush()
                
        except Exception as e:
            self.logger.error(f"Failed to log error: {e}")

    def flush(self):
        """
        Отправка накопленных ошибок на сервер
        """
        errors = []
        try:
            # Собираем все ошибки из очереди
            while not self.error_queue.empty() and len(errors) < self.batch_size:
                errors.append(self.error_queue.get_nowait())
            
            if not errors:
                return
            
            # Отправляем пакет ошибок
            response = requests.post(
                f"{self.api_url}/log",
                json={"errors": errors},
                timeout=5
            )
            
            if response.status_code != 200:
                raise Exception(f"API returned {response.status_code}: {response.text}")
            
            self.last_flush = datetime.now()
            
        except Exception as e:
            self.logger.error(f"Failed to flush errors: {e}")
            # Возвращаем ошибки обратно в очередь
            for error in errors:
                self.error_queue.put(error)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            self.log_error(exc_val)
        self.flush()  # Отправляем все оставшиеся ошибки

    async def send_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Отправка ошибки в систему мониторинга
        
        :param error: Объект исключения
        :param context: Дополнительный контекст ошибки
        :return: True если успешно, False если произошла ошибка
        """
        try:
            error_data = {
                "project_token": self.project_token,
                "error": {
                    "type": error.__class__.__name__,
                    "message": str(error),
                    "stack_trace": "".join(traceback.format_tb(error.__traceback__)),
                    "context": context or {},
                    "timestamp": datetime.utcnow().isoformat()
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/api/v1/log",
                    json=error_data,
                    timeout=10
                ) as response:
                    return response.status == 200

        except Exception as e:
            self.logger.error(f"Failed to send error: {e}")
            return False

    async def send_heartbeat(self, version: Optional[str] = None, additional_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Отправка сигнала heartbeat
        
        :param version: Версия проекта
        :param additional_data: Дополнительные данные
        :return: True если успешно, False если произошла ошибка
        """
        try:
            heartbeat_data = {
                "project_token": self.project_token,
                "status": "alive",
                "version": version,
                "additional_data": additional_data or {},
                "timestamp": datetime.utcnow().isoformat()
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/api/v1/heartbeat",
                    json=heartbeat_data,
                    timeout=10
                ) as response:
                    return response.status == 200

        except Exception as e:
            self.logger.error(f"Failed to send heartbeat: {e}")
            return False

    async def _heartbeat_loop(self, interval: int = 3600, version: Optional[str] = None):
        """
        Фоновая задача для периодической отправки heartbeat
        
        :param interval: Интервал между отправками в секундах
        :param version: Версия проекта
        """
        while True:
            try:
                await self.send_heartbeat(version=version)
                await asyncio.sleep(interval)
            except Exception as e:
                self.logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(60)  # Ждем минуту перед следующей попыткой

    def start_heartbeat(self, interval: int = 3600, version: Optional[str] = None):
        """
        Запуск периодической отправки heartbeat
        
        :param interval: Интервал между отправками в секундах
        :param version: Версия проекта
        """
        if self.heartbeat_task is None or self.heartbeat_task.done():
            self.heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(interval, version)
            )

    def stop_heartbeat(self):
        """
        Остановка периодической отправки heartbeat
        """
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()

# Пример использования:
if __name__ == "__main__":
    monitor = ErrorMonitor(
        "your-project-token",
        heartbeat_interval=60  # Для теста отправляем каждую минуту
    )
    
    # Простой пример
    try:
        1/0
    except Exception as e:
        monitor.log_error(e)
    
    # Использование контекстного менеджера
    with ErrorMonitor("your-project-token") as monitor:
        # Код, который может вызвать ошибку
        raise ValueError("Test error") 