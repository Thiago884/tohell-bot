import asyncmy
import pytz
from datetime import datetime, timedelta
import json
import os
from typing import Optional, Dict, List, Any

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Conexão assíncrona com o banco de dados MySQL
async def connect_db():
    try:
        conn = await asyncmy.connect(
            host="192.185.214.113",
            user="thia5326_tohell",
            password="Thi@goba1102@@",
            database="thia5326_tohell_bot"
        )
        return conn
    except Exception as err:
        print(f"Erro ao conectar ao banco de dados: {err}")
        return None

# Inicializar o banco de dados
async def init_db():
    conn = await connect_db()
    if conn is None:
        return
    
    try:
        async with conn.cursor() as cursor:
            # Verifica se a tabela já existe antes de criar
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS boss_timers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                boss_name VARCHAR(50) NOT NULL,
                sala INT NOT NULL,
                death_time DATETIME NOT NULL,
                respawn_time DATETIME NOT NULL,
                closed_time DATETIME NOT NULL,
                recorded_by VARCHAR(50) NOT NULL,
                opened_notified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY boss_sala (boss_name, sala)
            )
            """)
            
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id VARCHAR(20) PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                count INT DEFAULT 0,
                last_recorded DATETIME,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """)
            
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_notifications (
                user_id VARCHAR(20) NOT NULL,
                boss_name VARCHAR(50) NOT NULL,
                PRIMARY KEY (user_id, boss_name)
            )
            """)
            
            await conn.commit()
        print("Banco de dados verificado com sucesso!")
    except Exception as err:
        print(f"Erro ao inicializar banco de dados: {err}")
    finally:
        await conn.ensure_closed()

# Carregar dados do banco de dados
async def load_db_data(boss_timers: Dict, user_stats: Dict, user_notifications: Dict):
    conn = await connect_db()
    if conn is None:
        return
    
    try:
        async with conn.cursor() as cursor:
            # Carregar timers de boss
            await cursor.execute("SELECT * FROM boss_timers")
            timers = await cursor.fetchall()
            
            for timer in timers:
                boss_name = timer['boss_name']
                sala = timer['sala']
                
                if boss_name in boss_timers and sala in boss_timers[boss_name]:
                    boss_timers[boss_name][sala] = {
                        'death_time': timer['death_time'].replace(tzinfo=brazil_tz) if timer['death_time'] else None,
                        'respawn_time': timer['respawn_time'].replace(tzinfo=brazil_tz) if timer['respawn_time'] else None,
                        'closed_time': timer['closed_time'].replace(tzinfo=brazil_tz) if timer['closed_time'] else None,
                        'recorded_by': timer['recorded_by'],
                        'opened_notified': timer['opened_notified']
                    }
            
            # Carregar estatísticas de usuários
            await cursor.execute("SELECT * FROM user_stats")
            stats = await cursor.fetchall()
            
            for stat in stats:
                user_stats[stat['user_id']] = {
                    'count': stat['count'],
                    'last_recorded': stat['last_recorded'].replace(tzinfo=brazil_tz) if stat['last_recorded'] else None
                }
            
            # Carregar notificações personalizadas
            await cursor.execute("SELECT * FROM user_notifications")
            notifications = await cursor.fetchall()
            
            for notification in notifications:
                user_id = notification['user_id']
                boss_name = notification['boss_name']
                
                if user_id not in user_notifications:
                    user_notifications[user_id] = []
                if boss_name not in user_notifications[user_id]:
                    user_notifications[user_id].append(boss_name)
        
        print("Dados carregados do banco de dados com sucesso!")
    except Exception as err:
        print(f"Erro ao carregar dados do banco: {err}")
    finally:
        await conn.ensure_closed()

# Salvar dados no banco de dados
async def save_timer(boss_name: str, sala: int, death_time: Optional[datetime], 
                    respawn_time: Optional[datetime], closed_time: Optional[datetime], 
                    recorded_by: str, opened_notified: bool = False):
    conn = await connect_db()
    if conn is None:
        return
    
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("""
            INSERT INTO boss_timers (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                death_time = VALUES(death_time),
                respawn_time = VALUES(respawn_time),
                closed_time = VALUES(closed_time),
                recorded_by = VALUES(recorded_by),
                opened_notified = VALUES(opened_notified)
            """, (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified))
            
            await conn.commit()
    except Exception as err:
        print(f"Erro ao salvar timer: {err}")
    finally:
        await conn.ensure_closed()

async def save_user_stats(user_id: str, username: str, count: int, last_recorded: datetime):
    conn = await connect_db()
    if conn is None:
        return
    
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("""
            INSERT INTO user_stats (user_id, username, count, last_recorded)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                username = VALUES(username),
                count = VALUES(count),
                last_recorded = VALUES(last_recorded)
            """, (user_id, username, count, last_recorded))
            
            await conn.commit()
    except Exception as err:
        print(f"Erro ao salvar estatísticas do usuário: {err}")
    finally:
        await conn.ensure_closed()

async def clear_timer(boss_name: str, sala: Optional[int] = None):
    conn = await connect_db()
    if conn is None:
        return
    
    try:
        async with conn.cursor() as cursor:
            if sala is None:
                await cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s", (boss_name,))
            else:
                await cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s AND sala = %s", (boss_name, sala))
            
            await conn.commit()
    except Exception as err:
        print(f"Erro ao limpar timer: {err}")
    finally:
        await conn.ensure_closed()

async def add_user_notification(user_id: str, boss_name: str) -> bool:
    conn = await connect_db()
    if conn is None:
        return False
    
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("""
            INSERT INTO user_notifications (user_id, boss_name)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                boss_name = VALUES(boss_name)
            """, (user_id, boss_name))
            
            await conn.commit()
            return True
    except Exception as err:
        print(f"Erro ao adicionar notificação: {err}")
        return False
    finally:
        await conn.ensure_closed()

async def remove_user_notification(user_id: str, boss_name: str) -> bool:
    conn = await connect_db()
    if conn is None:
        return False
    
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("""
            DELETE FROM user_notifications
            WHERE user_id = %s AND boss_name = %s
            """, (user_id, boss_name))
            
            await conn.commit()
            return cursor.rowcount > 0
    except Exception as err:
        print(f"Erro ao remover notificação: {err}")
        return False
    finally:
        await conn.ensure_closed()

async def get_user_notifications(user_id: str) -> List[str]:
    conn = await connect_db()
    if conn is None:
        return []
    
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("""
            SELECT boss_name FROM user_notifications
            WHERE user_id = %s
            """, (user_id,))
            
            return [row['boss_name'] for row in await cursor.fetchall()]
    except Exception as err:
        print(f"Erro ao obter notificações: {err}")
        return []
    finally:
        await conn.ensure_closed()

# Funções para backup do banco de dados
async def create_backup() -> Optional[str]:
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_{timestamp}.json"
        
        conn = await connect_db()
        if conn is None:
            return None
            
        async with conn.cursor() as cursor:
            # Backup dos timers de boss
            await cursor.execute("SELECT * FROM boss_timers")
            boss_timers_data = await cursor.fetchall()
            
            # Backup das estatísticas de usuários
            await cursor.execute("SELECT * FROM user_stats")
            user_stats_data = await cursor.fetchall()
            
            # Backup das notificações personalizadas
            await cursor.execute("SELECT * FROM user_notifications")
            user_notifications_data = await cursor.fetchall()
            
            backup_data = {
                'boss_timers': boss_timers_data,
                'user_stats': user_stats_data,
                'user_notifications': user_notifications_data,
                'timestamp': timestamp
            }
            
            with open(backup_file, 'w') as f:
                json.dump(backup_data, f, indent=4, default=str)
                
        print(f"Backup criado com sucesso: {backup_file}")
        return backup_file
        
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None
    finally:
        if conn:
            await conn.ensure_closed()

async def restore_backup(backup_file: str) -> bool:
    try:
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
            
        conn = await connect_db()
        if conn is None:
            return False
            
        async with conn.cursor() as cursor:
            # Limpar tabelas antes de restaurar
            await cursor.execute("DELETE FROM boss_timers")
            await cursor.execute("DELETE FROM user_stats")
            await cursor.execute("DELETE FROM user_notifications")
            
            # Restaurar timers de boss
            for timer in backup_data['boss_timers']:
                await cursor.execute("""
                INSERT INTO boss_timers (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    timer['boss_name'],
                    timer['sala'],
                    timer['death_time'],
                    timer['respawn_time'],
                    timer['closed_time'],
                    timer['recorded_by'],
                    timer['opened_notified']
                ))
            
            # Restaurar estatísticas de usuários
            for stat in backup_data['user_stats']:
                await cursor.execute("""
                INSERT INTO user_stats (user_id, username, count, last_recorded)
                VALUES (%s, %s, %s, %s)
                """, (
                    stat['user_id'],
                    stat['username'],
                    stat['count'],
                    stat['last_recorded']
                ))
            
            # Restaurar notificações personalizadas (se existirem no backup)
            if 'user_notifications' in backup_data:
                for notification in backup_data['user_notifications']:
                    await cursor.execute("""
                    INSERT INTO user_notifications (user_id, boss_name)
                    VALUES (%s, %s)
                    """, (
                        notification['user_id'],
                        notification['boss_name']
                    ))
            
            await conn.commit()
        print(f"Backup restaurado com sucesso: {backup_file}")
        return True
        
    except Exception as e:
        print(f"Erro ao restaurar backup: {e}")
        return False
    finally:
        if conn:
            await conn.ensure_closed()