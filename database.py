import aiomysql
import pytz
from datetime import datetime, timedelta
import json
import os
from typing import Optional

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Pool de conexões global
pool: Optional[aiomysql.Pool] = None

async def create_pool():
    """Cria o pool de conexões com o banco de dados"""
    global pool
    pool = await aiomysql.create_pool(
        host="192.185.214.113",
        user="thia5326_tohell",
        password="Thi@goba1102@@",
        db="thia5326_tohell_bot",
        minsize=1,
        maxsize=5,
        autocommit=True
    )

async def close_pool():
    """Fecha o pool de conexões"""
    global pool
    if pool is not None:
        pool.close()
        await pool.wait_closed()

async def connect_db():
    """Obtém uma conexão do pool"""
    if pool is None:
        await create_pool()
    try:
        conn = await pool.acquire()
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
            # Tabela de timers de boss
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
            
            # Tabela de estatísticas de usuários
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id VARCHAR(20) PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                count INT DEFAULT 0,
                last_recorded DATETIME,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """)
            
            # Tabela de notificações personalizadas
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_notifications (
                user_id VARCHAR(20) NOT NULL,
                boss_name VARCHAR(50) NOT NULL,
                PRIMARY KEY (user_id, boss_name)
            )
            """)
            
        print("Banco de dados inicializado com sucesso!")
    except Exception as err:
        print(f"Erro ao inicializar banco de dados: {err}")
    finally:
        pool.release(conn)

# Carregar dados do banco de dados
async def load_db_data(boss_timers, user_stats, user_notifications):
    conn = await connect_db()
    if conn is None:
        return
    
    try:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Carregar timers de boss
            await cursor.execute("SELECT * FROM boss_timers")
            timers = await cursor.fetchall()
            
            for timer in timers:
                boss_name = timer['boss_name']
                sala = timer['sala']
                
                if boss_name in boss_timers and sala in boss_timers[boss_name]:
                    boss_timers[boss_name][sala] = {
                        'death_time': timer['death_time'].replace(tzinfo=brazil_tz),
                        'respawn_time': timer['respawn_time'].replace(tzinfo=brazil_tz),
                        'closed_time': timer['closed_time'].replace(tzinfo=brazil_tz),
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
                user_notifications[user_id].append(boss_name)
            
            print("Dados carregados do banco de dados com sucesso!")
    except Exception as err:
        print(f"Erro ao carregar dados do banco: {err}")
    finally:
        pool.release(conn)

# Salvar dados no banco de dados
async def save_timer(boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified=False):
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
            
            print(f"Timer salvo: {boss_name} (Sala {sala})")
    except Exception as err:
        print(f"Erro ao salvar timer: {err}")
    finally:
        pool.release(conn)

async def save_user_stats(user_id, username, count, last_recorded):
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
    except Exception as err:
        print(f"Erro ao salvar estatísticas do usuário: {err}")
    finally:
        pool.release(conn)

async def clear_timer(boss_name, sala=None):
    conn = await connect_db()
    if conn is None:
        return
    
    try:
        async with conn.cursor() as cursor:
            if sala is None:
                await cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s", (boss_name,))
            else:
                await cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s AND sala = %s", (boss_name, sala))
    except Exception as err:
        print(f"Erro ao limpar timer: {err}")
    finally:
        pool.release(conn)

async def add_user_notification(user_id, boss_name):
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
            
            return True
    except Exception as err:
        print(f"Erro ao adicionar notificação: {err}")
        return False
    finally:
        pool.release(conn)

async def remove_user_notification(user_id, boss_name):
    conn = await connect_db()
    if conn is None:
        return False
    
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("""
            DELETE FROM user_notifications
            WHERE user_id = %s AND boss_name = %s
            """, (user_id, boss_name))
            
            return cursor.rowcount > 0
    except Exception as err:
        print(f"Erro ao remover notificação: {err}")
        return False
    finally:
        pool.release(conn)

async def get_user_notifications(user_id):
    conn = await connect_db()
    if conn is None:
        return []
    
    try:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
            SELECT boss_name FROM user_notifications
            WHERE user_id = %s
            """, (user_id,))
            
            return [row['boss_name'] for row in await cursor.fetchall()]
    except Exception as err:
        print(f"Erro ao obter notificações: {err}")
        return []
    finally:
        pool.release(conn)

# Funções para backup do banco de dados
async def create_backup():
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_{timestamp}.json"
        
        conn = await connect_db()
        if conn is None:
            return None
            
        try:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
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
        finally:
            pool.release(conn)
            
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None

async def restore_backup(backup_file):
    try:
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
            
        conn = await connect_db()
        if conn is None:
            return False
            
        try:
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
                
                print(f"Backup restaurado com sucesso: {backup_file}")
                return True
        finally:
            pool.release(conn)
            
    except Exception as e:
        print(f"Erro ao restaurar backup: {e}")
        return False