import asyncmy
import pytz
from datetime import datetime, timedelta
import json
import os
from typing import Optional, Dict, List, Any
import logging

# Configuração do logger
logger = logging.getLogger(__name__)

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

async def connect_db():
    """Estabelece conexão com o banco de dados MySQL"""
    try:
        conn = await asyncmy.connect(
            host="192.185.214.113",
            user="thia5326_tohell",
            password="Thi@goba1102@@",
            database="thia5326_tohell_bot"
        )
        return conn
    except Exception as err:
        logger.error(f"Erro ao conectar ao banco de dados: {err}")
        return None

async def init_db():
    """Inicializa a estrutura do banco de dados, criando tabelas se não existirem"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            logger.error("Não foi possível conectar ao banco para inicialização")
            return False
        
        async with conn.cursor() as cursor:
            # Tabela de timers de boss
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS boss_timers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                boss_name VARCHAR(50) NOT NULL,
                sala INT NOT NULL,
                death_time DATETIME,
                respawn_time DATETIME,
                closed_time DATETIME,
                recorded_by VARCHAR(50),
                opened_notified BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY boss_sala (boss_name, sala)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # Tabela de estatísticas de usuários
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id VARCHAR(20) PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                count INT DEFAULT 0,
                last_recorded DATETIME,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # Tabela de notificações de usuários
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_notifications (
                user_id VARCHAR(20) NOT NULL,
                boss_name VARCHAR(50) NOT NULL,
                PRIMARY KEY (user_id, boss_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            await conn.commit()
        logger.info("Estrutura do banco de dados verificada com sucesso")
        return True
    except Exception as err:
        logger.error(f"Erro ao inicializar banco de dados: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def load_db_data(boss_timers: Dict, user_stats: Dict, user_notifications: Dict):
    """Carrega dados do banco de dados para as estruturas em memória"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            logger.error("Não foi possível conectar ao banco para carregar dados")
            return False
        
        async with conn.cursor() as cursor:
            # Primeiro limpe as salas existentes na memória
            for boss in boss_timers:
                boss_timers[boss].clear()
            
            # Carregar timers de boss
            await cursor.execute("""
                SELECT boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified 
                FROM boss_timers
                ORDER BY boss_name, sala
            """)
            timers = await cursor.fetchall()
            
            for timer in timers:
                boss_name = timer[0]
                sala = timer[1]
                
                # Garante que o boss existe
                if boss_name not in boss_timers:
                    boss_timers[boss_name] = {}
                
                # Adiciona a sala (mesmo que não existisse antes)
                boss_timers[boss_name][sala] = {
                    'death_time': timer[2].replace(tzinfo=brazil_tz) if timer[2] else None,
                    'respawn_time': timer[3].replace(tzinfo=brazil_tz) if timer[3] else None,
                    'closed_time': timer[4].replace(tzinfo=brazil_tz) if timer[4] else None,
                    'recorded_by': timer[5],
                    'opened_notified': bool(timer[6])
                }
            
            # Carregar estatísticas de usuários
            await cursor.execute("""
                SELECT user_id, username, count, last_recorded 
                FROM user_stats
            """)
            stats = await cursor.fetchall()
            
            for stat in stats:
                user_stats[stat[0]] = {
                    'count': stat[2],
                    'last_recorded': stat[3].replace(tzinfo=brazil_tz) if stat[3] else None,
                    'username': stat[1]
                }
            
            # Carregar notificações personalizadas
            await cursor.execute("""
                SELECT user_id, boss_name 
                FROM user_notifications
                ORDER BY user_id, boss_name
            """)
            notifications = await cursor.fetchall()
            
            for notification in notifications:
                user_id = notification[0]
                boss_name = notification[1]
                
                if user_id not in user_notifications:
                    user_notifications[user_id] = []
                if boss_name not in user_notifications[user_id]:
                    user_notifications[user_id].append(boss_name)
        
        logger.info("Dados carregados do banco de dados com sucesso")
        return True
    except Exception as err:
        logger.error(f"Erro ao carregar dados do banco: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def save_timer(boss_name: str, sala: int, death_time: Optional[datetime], 
                    respawn_time: Optional[datetime], closed_time: Optional[datetime], 
                    recorded_by: str, opened_notified: bool = False) -> bool:
    """Salva ou atualiza um timer de boss no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
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
        return True
    except Exception as err:
        logger.error(f"Erro ao salvar timer: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def save_user_stats(user_id: str, username: str, count: int, last_recorded: datetime) -> bool:
    """Salva ou atualiza estatísticas de usuário no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
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
        return True
    except Exception as err:
        logger.error(f"Erro ao salvar estatísticas do usuário: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def clear_timer(boss_name: str, sala: Optional[int] = None) -> bool:
    """Remove um timer de boss do banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            if sala is None:
                await cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s", (boss_name,))
            else:
                await cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s AND sala = %s", (boss_name, sala))
            
            await conn.commit()
        return True
    except Exception as err:
        logger.error(f"Erro ao limpar timer: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def add_user_notification(user_id: str, boss_name: str) -> bool:
    """Adiciona uma notificação de boss para um usuário"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
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
        logger.error(f"Erro ao adicionar notificação: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def remove_user_notification(user_id: str, boss_name: str) -> bool:
    """Remove uma notificação de boss de um usuário"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            await cursor.execute("""
            DELETE FROM user_notifications
            WHERE user_id = %s AND boss_name = %s
            """, (user_id, boss_name))
            
            await conn.commit()
        return cursor.rowcount > 0
    except Exception as err:
        logger.error(f"Erro ao remover notificação: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def get_user_notifications(user_id: str) -> List[str]:
    """Obtém a lista de bosses que um usuário quer ser notificado"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return []
        
        async with conn.cursor() as cursor:
            await cursor.execute("""
            SELECT boss_name FROM user_notifications
            WHERE user_id = %s
            """, (user_id,))
            
            return [row[0] for row in await cursor.fetchall()]
    except Exception as err:
        logger.error(f"Erro ao obter notificações: {err}", exc_info=True)
        return []
    finally:
        if conn:
            await conn.ensure_closed()

async def create_backup() -> Optional[str]:
    """Cria um backup completo do banco de dados em formato JSON"""
    conn = None
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_{timestamp}.json"
        
        conn = await connect_db()
        if conn is None:
            return None
            
        async with conn.cursor() as cursor:
            # Backup dos timers de boss
            await cursor.execute("SELECT * FROM boss_timers")
            boss_timers_data = []
            for row in await cursor.fetchall():
                boss_timers_data.append({
                    'boss_name': row[1],
                    'sala': row[2],
                    'death_time': row[3].isoformat() if row[3] else None,
                    'respawn_time': row[4].isoformat() if row[4] else None,
                    'closed_time': row[5].isoformat() if row[5] else None,
                    'recorded_by': row[6],
                    'opened_notified': bool(row[7])
                })
            
            # Backup das estatísticas de usuários
            await cursor.execute("SELECT * FROM user_stats")
            user_stats_data = []
            for row in await cursor.fetchall():
                user_stats_data.append({
                    'user_id': row[0],
                    'username': row[1],
                    'count': row[2],
                    'last_recorded': row[3].isoformat() if row[3] else None
                })
            
            # Backup das notificações personalizadas
            await cursor.execute("SELECT * FROM user_notifications")
            user_notifications_data = []
            for row in await cursor.fetchall():
                user_notifications_data.append({
                    'user_id': row[0],
                    'boss_name': row[1]
                })
            
            backup_data = {
                'boss_timers': boss_timers_data,
                'user_stats': user_stats_data,
                'user_notifications': user_notifications_data,
                'timestamp': timestamp,
                'version': 1.0
            }
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=4)
                
        logger.info(f"Backup criado com sucesso: {backup_file}")
        return backup_file
        
    except Exception as e:
        logger.error(f"Erro ao criar backup: {e}", exc_info=True)
        return None
    finally:
        if conn:
            await conn.ensure_closed()

async def restore_backup(backup_file: str) -> bool:
    """Restaura um backup do banco de dados a partir de um arquivo JSON"""
    conn = None
    try:
        with open(backup_file, 'r', encoding='utf-8') as f:
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
            
            # Restaurar notificações personalizadas
            for notification in backup_data['user_notifications']:
                await cursor.execute("""
                INSERT INTO user_notifications (user_id, boss_name)
                VALUES (%s, %s)
                """, (
                    notification['user_id'],
                    notification['boss_name']
                ))
            
            await conn.commit()
        logger.info(f"Backup restaurado com sucesso: {backup_file}")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao restaurar backup: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def add_sala_to_all_bosses(sala: int) -> bool:
    """Adiciona uma nova sala para todos os bosses no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            # Para cada boss, insira a nova sala com valores nulos
            await cursor.execute("SELECT DISTINCT boss_name FROM boss_timers")
            bosses = [row[0] for row in await cursor.fetchall()]
            
            for boss in bosses:
                await cursor.execute("""
                INSERT INTO boss_timers (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified)
                VALUES (%s, %s, NULL, NULL, NULL, NULL, FALSE)
                ON DUPLICATE KEY UPDATE
                    boss_name = VALUES(boss_name),
                    sala = VALUES(sala)
                """, (boss, sala))
            
            await conn.commit()
        return True
    except Exception as err:
        logger.error(f"Erro ao adicionar sala {sala}: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def remove_sala_from_all_bosses(sala: int) -> bool:
    """Remove uma sala de todos os bosses no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            await cursor.execute("DELETE FROM boss_timers WHERE sala = %s", (sala,))
            await conn.commit()
        return True
    except Exception as err:
        logger.error(f"Erro ao remover sala {sala}: {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()