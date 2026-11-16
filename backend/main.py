
from contextlib import asynccontextmanager
from time import sleep

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# --------------------------------------------------
# Adatbázis-kapcsolat
# --------------------------------------------------

def get_db_connection():
    with open("/run/secrets/postgres_password") as file:
        password = file.read().strip()

    return psycopg.connect(
        host="database",
        port=5432,
        dbname="taskmanager",
        user="taskuser",
        password=password,
        row_factory=dict_row,
        connect_timeout=5
    )


# --------------------------------------------------
# Adatbázistábla inicializálása
# --------------------------------------------------

def initialize_database():
    for attempt in range(30):
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS tasks (
                            id INTEGER GENERATED ALWAYS
                                AS IDENTITY PRIMARY KEY,
                            title VARCHAR(200) NOT NULL,
                            completed BOOLEAN NOT NULL
                                DEFAULT FALSE
                        )
                    """)
            return

        except psycopg.OperationalError:
            if attempt == 29:
                raise
            sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Mini Task Manager API",
    lifespan=lifespan
)


# --------------------------------------------------
# Pydantic modellek
# --------------------------------------------------

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class TaskUpdate(BaseModel):
    title: str | None = Field(
        default=None, min_length=1, max_length=200
    )
    completed: bool | None = None


# --------------------------------------------------
# Health endpoint
# --------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "taskmanager-backend"
    }


# --------------------------------------------------
# Feladatok listázása
# --------------------------------------------------

@app.get("/api/tasks")
def get_tasks():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, title, completed
                FROM tasks
                ORDER BY id
            """)
            return cursor.fetchall()


# --------------------------------------------------
# Új feladat létrehozása
# --------------------------------------------------

@app.post("/api/tasks", status_code=201)
def create_task(task: TaskCreate):
    title = task.title.strip()

    if not title:
        raise HTTPException(
            status_code=422,
            detail="A feladat címe nem lehet üres."
        )

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO tasks (title)
                VALUES (%s)
                RETURNING id, title, completed
            """, (title,))

            return cursor.fetchone()


# --------------------------------------------------
# Feladat módosítása
# --------------------------------------------------

@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, task: TaskUpdate):
    if task.title is None and task.completed is None:
        raise HTTPException(
            status_code=422,
            detail="Nincs módosítandó mező."
        )

    title = None

    if task.title is not None:
        title = task.title.strip()
        if not title:
            raise HTTPException(
                status_code=422,
                detail="A feladat címe nem lehet üres."
            )

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tasks
                SET
                    title = COALESCE(%s, title),
                    completed = COALESCE(%s, completed)
                WHERE id = %s
                RETURNING id, title, completed
            """, (title, task.completed, task_id))

            row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="A feladat nem található."
        )

    return row


# --------------------------------------------------
# Feladat törlése
# --------------------------------------------------

@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                DELETE FROM tasks
                WHERE id = %s
                RETURNING id
            """, (task_id,))

            row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="A feladat nem található."
        )
