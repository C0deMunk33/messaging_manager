import os
import shutil
from sqlmodel import create_engine, SQLModel

def reset_database_and_media():
    """Reset the database and media directory"""
    media_dir = "media"
    if os.path.exists(media_dir):
        print(f"Removing media directory: {media_dir}")
        shutil.rmtree(media_dir)
    os.makedirs(media_dir)
    print(f"Created fresh media directory: {media_dir}")

    # Delete the messages.db file
    db_path = "messages.db"
    if os.path.exists(db_path):
        print(f"Removing database file: {db_path}")
        os.remove(db_path)

    # Create a new empty database
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    print(f"Created fresh database: {db_path}")
    
    print("Reset complete!")

if __name__ == "__main__":
    reset_database_and_media() 