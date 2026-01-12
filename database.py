# database.py
import asyncmy
import pytz
from datetime import datetime, timedelta
import json
import os
from typing import Optional, Dict, List, Any, Tuple
import logging

# Configuração do logger
logger = logging.getLogger(__name__)

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

async def connect_db():
    """Estabelece conexão com o banco de dados MySQL"""
    try:
        conn = await asyncmy.connect(
            host="br92.hostgator.com.br",
            user="thia5326_tohell",
            password="Thi#goba1102@@",
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
            # Tabela de configurações por servidor (NOVO)
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS server_configs (
                guild_id BIGINT PRIMARY KEY,
                notification_channel_id BIGINT,
                table_channel_id BIGINT,
                table_message_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # Tabela de timers de boss (MODIFICADA para multi-guild)
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS boss_timers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                boss_name VARCHAR(50) NOT NULL,
                sala INT NOT NULL,
                death_time DATETIME,
                respawn_time DATETIME,
                closed_time DATETIME,
                recorded_by VARCHAR(50),
                opened_notified BOOLEAN DEFAULT FALSE,
                updated_by VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_guild_boss (guild_id, boss_name),
                UNIQUE KEY boss_sala_guild (guild_id, boss_name, sala)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # Tabela de estatísticas de usuários (MODIFICADA para multi-guild)
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                id INT AUTO_INCREMENT PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id VARCHAR(20) NOT NULL,
                username VARCHAR(50) NOT NULL,
                count INT DEFAULT 0,
                last_recorded DATETIME,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_guild_user (guild_id, user_id),
                UNIQUE KEY user_guild (guild_id, user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # Tabela de notificações de usuários (MODIFICADA para multi-guild)
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_notifications (
                guild_id BIGINT NOT NULL,
                user_id VARCHAR(20) NOT NULL,
                boss_name VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id, boss_name),
                INDEX idx_guild_user (guild_id, user_id)
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

async def migrate_database_to_multitenant():
    """
    Atualiza as tabelas existentes para suportar múltiplos servidores (Multi-Guild).
    Define o ID do servidor atual para os dados já existentes.
    """
    current_guild_id = 1152651838651371520  # O TEU ID DO MAIN.PY
    
    conn = await connect_db()
    if not conn:
        return
    
    try:
        async with conn.cursor() as cursor:
            logger.info("Iniciando migração do banco de dados...")

            # 1. Criar tabela de configurações por servidor
            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS server_configs (
                guild_id BIGINT PRIMARY KEY,
                notification_channel_id BIGINT,
                table_channel_id BIGINT,
                table_message_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            # 2. Adicionar coluna guild_id em boss_timers
            try:
                await cursor.execute("ALTER TABLE boss_timers ADD COLUMN guild_id BIGINT")
                # Atualiza dados antigos para o servidor atual
                await cursor.execute("UPDATE boss_timers SET guild_id = %s WHERE guild_id IS NULL", (current_guild_id,))
                # Adiciona índice para performance
                await cursor.execute("CREATE INDEX idx_guild_boss ON boss_timers(guild_id, boss_name)")
                logger.info("Tabela boss_timers migrada com sucesso.")
            except Exception as e:
                if "Duplicate column" in str(e):
                    logger.info("Coluna guild_id já existe em boss_timers.")
                else:
                    logger.error(f"Erro em boss_timers: {e}")

            # 3. Adicionar coluna guild_id em user_stats
            try:
                await cursor.execute("ALTER TABLE user_stats ADD COLUMN guild_id BIGINT")
                await cursor.execute("UPDATE user_stats SET guild_id = %s WHERE guild_id IS NULL", (current_guild_id,))
                # A chave primária composta deve mudar, mas por enquanto vamos apenas adicionar o índice
                await cursor.execute("CREATE INDEX idx_guild_user ON user_stats(guild_id, user_id)")
                logger.info("Tabela user_stats migrada com sucesso.")
            except Exception as e:
                if "Duplicate column" in str(e): 
                    pass
                else: 
                    logger.error(f"Erro em user_stats: {e}")

            # 4. Adicionar coluna guild_id em user_notifications
            try:
                await cursor.execute("ALTER TABLE user_notifications ADD COLUMN guild_id BIGINT")
                await cursor.execute("UPDATE user_notifications SET guild_id = %s WHERE guild_id IS NULL", (current_guild_id,))
                logger.info("Tabela user_notifications migrada com sucesso.")
            except Exception as e:
                if "Duplicate column" in str(e): 
                    pass
                else: 
                    logger.error(f"Erro em user_notifications: {e}")

            await conn.commit()
            logger.info("✅ Migração concluída! O banco agora suporta múltiplos servidores.")

    except Exception as e:
        logger.error(f"Erro fatal na migração: {e}", exc_info=True)
    finally:
        if conn:
            await conn.ensure_closed()

async def load_db_data(boss_timers: Dict, user_stats: Dict, user_notifications: Dict, guild_id: Optional[int] = None):
    """Carrega dados do banco de dados para as estruturas em memória"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            logger.error("Não foi possível conectar ao banco para carregar dados")
            return False
        
        async with conn.cursor() as cursor:
            # Se guild_id especificado, carrega apenas dados desse servidor
            if guild_id:
                # Carregar timers de boss - NÃO LIMPAR A ESTRUTURA EXISTENTE
                await cursor.execute("""
                    SELECT boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified 
                    FROM boss_timers
                    WHERE guild_id = %s
                    ORDER BY boss_name, sala
                """, (guild_id,))
            else:
                # Carregar todos os timers de boss
                await cursor.execute("""
                    SELECT boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified 
                    FROM boss_timers
                    ORDER BY guild_id, boss_name, sala
                """)
            
            timers = await cursor.fetchall()
            
            for timer in timers:
                boss_name = timer[0]
                sala = timer[1]
                
                # Garante que o boss existe na estrutura
                if boss_name not in boss_timers:
                    boss_timers[boss_name] = {}
                
                # Adiciona a sala ao boss com os dados do banco
                boss_timers[boss_name][sala] = {
                    'death_time': timer[2].replace(tzinfo=brazil_tz) if timer[2] else None,
                    'respawn_time': timer[3].replace(tzinfo=brazil_tz) if timer[3] else None,
                    'closed_time': timer[4].replace(tzinfo=brazil_tz) if timer[4] else None,
                    'recorded_by': timer[5],
                    'opened_notified': bool(timer[6])
                }
            
            # Carregar estatísticas de usuários - LIMPAR E RECARREGAR
            user_stats.clear()
            if guild_id:
                await cursor.execute("""
                    SELECT user_id, username, count, last_recorded 
                    FROM user_stats
                    WHERE guild_id = %s
                """, (guild_id,))
            else:
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
            
            # Carregar notificações personalizadas - LIMPAR E RECARREGAR
            user_notifications.clear()
            if guild_id:
                await cursor.execute("""
                    SELECT user_id, boss_name 
                    FROM user_notifications
                    WHERE guild_id = %s
                    ORDER BY user_id, boss_name
                """, (guild_id,))
            else:
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

async def save_timer(guild_id: int, boss_name: str, sala: int, death_time: Optional[datetime], 
                    respawn_time: Optional[datetime], closed_time: Optional[datetime], 
                    recorded_by: str, opened_notified: bool = False) -> bool:
    """Salva ou atualiza um timer de boss no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            # Verifica se já existe registo para este Boss nesta Sala neste Servidor
            await cursor.execute("""
                SELECT id FROM boss_timers 
                WHERE guild_id = %s AND boss_name = %s AND sala = %s
            """, (guild_id, boss_name, sala))
            
            result = await cursor.fetchone()
            
            if result:
                # Atualiza existente
                await cursor.execute("""
                    UPDATE boss_timers 
                    SET death_time = %s,
                        respawn_time = %s,
                        closed_time = %s,
                        recorded_by = %s,
                        opened_notified = %s,
                        updated_by = %s
                    WHERE guild_id = %s AND boss_name = %s AND sala = %s
                """, (death_time, respawn_time, closed_time, recorded_by, opened_notified, 
                      recorded_by, guild_id, boss_name, sala))
            else:
                # Insere novo
                await cursor.execute("""
                    INSERT INTO boss_timers 
                    (guild_id, boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (guild_id, boss_name, sala, death_time, respawn_time, closed_time, 
                      recorded_by, opened_notified, recorded_by))
            
            await conn.commit()
        return True
    except Exception as err:
        logger.error(f"Erro ao salvar timer (Guild: {guild_id}, Boss: {boss_name}): {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def save_user_stats(guild_id: int, user_id: str, username: str, count: int, last_recorded: datetime) -> bool:
    """Salva ou atualiza estatísticas de usuário no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            await cursor.execute("""
            INSERT INTO user_stats (guild_id, user_id, username, count, last_recorded)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                username = VALUES(username),
                count = VALUES(count),
                last_recorded = VALUES(last_recorded)
            """, (guild_id, user_id, username, count, last_recorded))
            
            await conn.commit()
        return True
    except Exception as err:
        logger.error(f"Erro ao salvar estatísticas do usuário (Guild: {guild_id}, User: {user_id}): {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def clear_timer(guild_id: int, boss_name: str, sala: Optional[int] = None) -> bool:
    """Remove um timer de boss do banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            if sala is None:
                await cursor.execute("DELETE FROM boss_timers WHERE guild_id = %s AND boss_name = %s", (guild_id, boss_name))
            else:
                await cursor.execute("DELETE FROM boss_timers WHERE guild_id = %s AND boss_name = %s AND sala = %s", (guild_id, boss_name, sala))
            
            await conn.commit()
        return True
    except Exception as err:
        logger.error(f"Erro ao limpar timer (Guild: {guild_id}, Boss: {boss_name}): {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def add_user_notification(guild_id: int, user_id: str, boss_name: str) -> bool:
    """Adiciona uma notificação de boss para um usuário"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            await cursor.execute("""
            INSERT INTO user_notifications (guild_id, user_id, boss_name)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                boss_name = VALUES(boss_name)
            """, (guild_id, user_id, boss_name))
            
            await conn.commit()
        return True
    except Exception as err:
        logger.error(f"Erro ao adicionar notificação (Guild: {guild_id}, User: {user_id}, Boss: {boss_name}): {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def remove_user_notification(guild_id: int, user_id: str, boss_name: str) -> bool:
    """Remove uma notificação de boss de um usuário"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
        
        async with conn.cursor() as cursor:
            await cursor.execute("""
            DELETE FROM user_notifications
            WHERE guild_id = %s AND user_id = %s AND boss_name = %s
            """, (guild_id, user_id, boss_name))
            
            await conn.commit()
        return cursor.rowcount > 0
    except Exception as err:
        logger.error(f"Erro ao remover notificação (Guild: {guild_id}, User: {user_id}, Boss: {boss_name}): {err}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def get_user_notifications(guild_id: int, user_id: str) -> List[str]:
    """Obtém a lista de bosses que um usuário quer ser notificado"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return []
        
        async with conn.cursor() as cursor:
            await cursor.execute("""
            SELECT boss_name FROM user_notifications
            WHERE guild_id = %s AND user_id = %s
            """, (guild_id, user_id))
            
            return [row[0] for row in await cursor.fetchall()]
    except Exception as err:
        logger.error(f"Erro ao obter notificações (Guild: {guild_id}, User: {user_id}): {err}", exc_info=True)
        return []
    finally:
        if conn:
            await conn.ensure_closed()

async def set_server_config(guild_id: int, notif_channel_id: int, table_channel_id: int, table_msg_id: int):
    """Salva as configurações de canais do servidor"""
    conn = await connect_db()
    if not conn: 
        return False
    
    try:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO server_configs (guild_id, notification_channel_id, table_channel_id, table_message_id)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                notification_channel_id = VALUES(notification_channel_id),
                table_channel_id = VALUES(table_channel_id),
                table_message_id = VALUES(table_message_id)
            """, (guild_id, notif_channel_id, table_channel_id, table_msg_id))
            await conn.commit()
            return True
    except Exception as e:
        logger.error(f"Erro ao salvar config do servidor {guild_id}: {e}")
        return False
    finally:
        await conn.ensure_closed()

async def get_server_config(guild_id: int):
    """Retorna um dicionário com as configs do servidor"""
    conn = await connect_db()
    if not conn: 
        return None
    
    try:
        async with conn.cursor(cursor=asyncmy.cursors.DictCursor) as cursor:
            await cursor.execute("SELECT * FROM server_configs WHERE guild_id = %s", (guild_id,))
            return await cursor.fetchone()
    except Exception as e:
        logger.error(f"Erro ao obter config do servidor {guild_id}: {e}")
        return None
    finally:
        await conn.ensure_closed()

async def get_all_server_configs():
    """Retorna configs de TODOS os servidores (para o loop de atualização)"""
    conn = await connect_db()
    if not conn: 
        return []
    
    try:
        async with conn.cursor(cursor=asyncmy.cursors.DictCursor) as cursor:
            await cursor.execute("SELECT * FROM server_configs")
            return await cursor.fetchall()
    except Exception as e:
        logger.error(f"Erro ao obter todas as configs: {e}")
        return []
    finally:
        await conn.ensure_closed()

async def load_all_server_data():
    """
    Carrega TODOS os dados do banco organizados por servidor.
    Retorno: Dict[guild_id, Dict[boss_name, Dict[sala, dados]]]
    """
    conn = await connect_db()
    if not conn:
        return {}
    
    data = {}
    
    try:
        async with conn.cursor(cursor=asyncmy.cursors.DictCursor) as cursor:
            # Carregar Timers
            await cursor.execute("SELECT * FROM boss_timers")
            rows = await cursor.fetchall()
            
            for row in rows:
                guild_id = row['guild_id']
                boss = row['boss_name']
                sala = row['sala']
                
                # Garante estrutura: Guild -> Boss -> Sala
                if guild_id not in data: 
                    data[guild_id] = {}
                if boss not in data[guild_id]: 
                    data[guild_id][boss] = {}
                
                # Converte timestamps para aware (fuso horário correto) se necessário
                if row['respawn_time'] and row['respawn_time'].tzinfo is None:
                    row['respawn_time'] = brazil_tz.localize(row['respawn_time'])
                if row['closed_time'] and row['closed_time'].tzinfo is None:
                    row['closed_time'] = brazil_tz.localize(row['closed_time'])
                    
                data[guild_id][boss][sala] = row

            logger.info(f"Dados carregados para {len(data)} servidores.")
            return data
            
    except Exception as e:
        logger.error(f"Erro ao carregar dados do DB: {e}", exc_info=True)
        return {}
    finally:
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
                    'guild_id': row[1],
                    'boss_name': row[2],
                    'sala': row[3],
                    'death_time': row[4].isoformat() if row[4] else None,
                    'respawn_time': row[5].isoformat() if row[5] else None,
                    'closed_time': row[6].isoformat() if row[6] else None,
                    'recorded_by': row[7],
                    'opened_notified': bool(row[8]),
                    'updated_by': row[9]
                })
            
            # Backup das estatísticas de usuários
            await cursor.execute("SELECT * FROM user_stats")
            user_stats_data = []
            for row in await cursor.fetchall():
                user_stats_data.append({
                    'guild_id': row[1],
                    'user_id': row[2],
                    'username': row[3],
                    'count': row[4],
                    'last_recorded': row[5].isoformat() if row[5] else None
                })
            
            # Backup das notificações personalizadas
            await cursor.execute("SELECT * FROM user_notifications")
            user_notifications_data = []
            for row in await cursor.fetchall():
                user_notifications_data.append({
                    'guild_id': row[0],
                    'user_id': row[1],
                    'boss_name': row[2]
                })
            
            # Backup das configurações de servidor
            await cursor.execute("SELECT * FROM server_configs")
            server_configs_data = []
            for row in await cursor.fetchall():
                server_configs_data.append({
                    'guild_id': row[0],
                    'notification_channel_id': row[1],
                    'table_channel_id': row[2],
                    'table_message_id': row[3]
                })
            
            backup_data = {
                'boss_timers': boss_timers_data,
                'user_stats': user_stats_data,
                'user_notifications': user_notifications_data,
                'server_configs': server_configs_data,
                'timestamp': timestamp,
                'version': 2.0  # Versão atualizada para multi-guild
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
            await cursor.execute("DELETE FROM server_configs")
            
            # Restaurar timers de boss
            for timer in backup_data['boss_timers']:
                await cursor.execute("""
                INSERT INTO boss_timers (guild_id, boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    timer['guild_id'],
                    timer['boss_name'],
                    timer['sala'],
                    timer['death_time'],
                    timer['respawn_time'],
                    timer['closed_time'],
                    timer['recorded_by'],
                    timer['opened_notified'],
                    timer.get('updated_by', timer['recorded_by'])
                ))
            
            # Restaurar estatísticas de usuários
            for stat in backup_data['user_stats']:
                await cursor.execute("""
                INSERT INTO user_stats (guild_id, user_id, username, count, last_recorded)
                VALUES (%s, %s, %s, %s, %s)
                """, (
                    stat['guild_id'],
                    stat['user_id'],
                    stat['username'],
                    stat['count'],
                    stat['last_recorded']
                ))
            
            # Restaurar notificações personalizadas
            for notification in backup_data['user_notifications']:
                await cursor.execute("""
                INSERT INTO user_notifications (guild_id, user_id, boss_name)
                VALUES (%s, %s, %s)
                """, (
                    notification['guild_id'],
                    notification['user_id'],
                    notification['boss_name']
                ))
            
            # Restaurar configurações de servidor (se existirem)
            if 'server_configs' in backup_data:
                for config in backup_data['server_configs']:
                    await cursor.execute("""
                    INSERT INTO server_configs (guild_id, notification_channel_id, table_channel_id, table_message_id)
                    VALUES (%s, %s, %s, %s)
                    """, (
                        config['guild_id'],
                        config['notification_channel_id'],
                        config['table_channel_id'],
                        config['table_message_id']
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

async def get_all_salas_from_db(guild_id: Optional[int] = None) -> List[int]:
    """Obtém todas as salas únicas existentes no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return []
        
        async with conn.cursor() as cursor:
            if guild_id:
                await cursor.execute("SELECT DISTINCT sala FROM boss_timers WHERE guild_id = %s ORDER BY sala", (guild_id,))
            else:
                await cursor.execute("SELECT DISTINCT sala FROM boss_timers ORDER BY sala")
            
            salas = await cursor.fetchall()
            return [sala[0] for sala in salas] if salas else []
    except Exception as e:
        logger.error(f"Erro ao buscar salas do banco: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await conn.ensure_closed()

async def add_sala_to_all_bosses(guild_id: int, sala: int) -> bool:
    """Adiciona uma sala a todos os bosses no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
            
        async with conn.cursor() as cursor:
            # Definir quais bosses podem ter a sala 20
            if sala == 20:
                bosses_with_sala_20 = ["Genocider", "Super Red Dragon", "Hell Maine", "Death Beam Knight", "Erohim"]
            else:
                bosses_with_sala_20 = ["Genocider", "Super Red Dragon", "Hell Maine", "Death Beam Knight", "Erohim", 
                                     "Hydra", "Phoenix of Darkness", "Illusion of Kundun", "Rei Kundun"]
            
            for boss in bosses_with_sala_20:
                # Verifica se já existe para evitar duplicação
                await cursor.execute("""
                SELECT COUNT(*) FROM boss_timers 
                WHERE guild_id = %s AND boss_name = %s AND sala = %s
                """, (guild_id, boss, sala))
                
                exists = (await cursor.fetchone())[0] > 0
                
                if not exists:
                    await cursor.execute("""
                    INSERT INTO boss_timers (guild_id, boss_name, sala)
                    VALUES (%s, %s, %s)
                    """, (guild_id, boss, sala))
                    
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"Erro ao adicionar sala {sala} (Guild: {guild_id}): {e}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def remove_sala_from_all_bosses(guild_id: int, sala: int) -> bool:
    """Remove uma sala de todos os bosses no banco de dados"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
            
        async with conn.cursor() as cursor:
            await cursor.execute("""
            DELETE FROM boss_timers 
            WHERE guild_id = %s AND sala = %s
            """, (guild_id, sala))
            
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"Erro ao remover sala {sala} (Guild: {guild_id}): {e}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def migrate_remove_sala_20_from_wrong_bosses(guild_id: int) -> bool:
    """Migração para remover sala 20 de bosses que não deveriam tê-la"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return False
            
        async with conn.cursor() as cursor:
            # Remove sala 20 de bosses que não deveriam tê-la
            await cursor.execute("""
            DELETE FROM boss_timers 
            WHERE guild_id = %s AND sala = 20 
            AND boss_name NOT IN ('Genocider', 'Super Red Dragon', 'Hell Maine', 'Death Beam Knight', 'Erohim')
            """, (guild_id,))
            
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"Erro na migração (Guild: {guild_id}): {e}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def migrate_fix_sala_20(guild_id: int) -> bool:
    """Migração para corrigir salas 20"""
    return await migrate_remove_sala_20_from_wrong_bosses(guild_id)