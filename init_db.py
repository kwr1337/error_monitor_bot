from bot import Base, engine

def init_db():
    Base.metadata.create_all(engine)
    print("База данных успешно инициализирована")

if __name__ == "__main__":
    init_db() 
 