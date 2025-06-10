from sqlalchemy import Column, Integer, String, JSON, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Project(Base):
    __tablename__ = 'projects'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # 'bot', 'website', 'other'
    token = Column(String, unique=True, nullable=False)
    url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    last_heartbeat = Column(DateTime, nullable=True)  # Добавляем поле для последнего heartbeat

    error_logs = relationship("ErrorLog", back_populates="project")
    heartbeats = relationship("Heartbeat", back_populates="project")

class Subscriber(Base):
    __tablename__ = 'subscribers'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    full_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    subscribed_projects = Column(JSON, default=list)
    notification_level = Column(String, default='error')  # error/warning/info
    created_at = Column(DateTime, default=datetime.utcnow)

class ErrorLog(Base):
    __tablename__ = 'error_logs'

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    error_type = Column(String, nullable=False)
    error_message = Column(String, nullable=False)
    stack_trace = Column(String, nullable=True)
    additional_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    severity_level = Column(String, default='error')
    is_resolved = Column(Boolean, default=False)

    project = relationship("Project", back_populates="error_logs")

class Heartbeat(Base):
    __tablename__ = 'heartbeats'

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    status = Column(String, nullable=False)  # alive/dead
    version = Column(String, nullable=True)
    additional_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="heartbeats") 