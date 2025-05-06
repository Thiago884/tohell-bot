import aiomysql
import pytz
from datetime import datetime, timedelta
import json
import os
import time
from typing import Optional, Dict, List, Any
import asyncio
import traceback

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Pool de conexões global
pool: Optional[aiomysql.Pool] = None

async def create_pool():
    """Cria o pool de conexões global com logs detalhados"""
    global pool
    if pool is None:
        try:
            print("\n" + "="*50)
            print("🔧 Tentando conectar ao banco de dados...")
            print(f"📌 Host: {os.getenv('DB_HOST', '192.185.214.113')}")
            print(f"👤 User: {os.getenv('DB_USER', 'thia5326_tohell')}")
            # Não mostramos a senha por segurança
            print(f"📂 Database: {os.getenv('DB_NAME', 'thia5326_tohell_bot')}")
            print(f"🚪 Port: {os.getenv('DB_PORT', 3306)}")
            
            pool = await aiomysql.create_pool(
                host=os.getenv('DB_HOST', '192.185.214.113'),
                user=os.getenv('DB_USER', 'thia5326_tohell'),
                password=os.getenv('DB_PASSWORD', 'Thi@goba1102@@'),
                db=os.getenv('DB_NAME', 'thia5326_tohell_bot'),
                port=int(os.getenv('DB_PORT', 3306)),
                minsize=1,
                maxsize=10,
                connect_timeout=60,  # Aumentado para 60 segundos
                read_timeout=60,     # Timeout de leitura aumentado
                write_timeout=60,    # Timeout de escrita aumentado
                autocommit=True,
                charset='utf8mb4',   # Suporte a caracteres especiais
                cursorclass=aiomysql.DictCursor
            )
            print("✅ Pool de conexões criado com sucesso!")
            print("="*50 + "\n")
            return pool
        except aiomysql.MySQLError as e:
            print("\n" + "="*50)
            print(f"❌ ERRO AO CONECTAR AO BANCO DE DADOS:")
            print(f"Tipo: {type(e).__name__}")
            print(f"Detalhes: {str(e)}")
            print("="*50 + "\n")
            pool = None
            return None
        except Exception as e:
            print("\n" + "="*50)
            print(f"❌ ERRO INESPERADO AO CRIAR POOL:")
            traceback.print_exc()
            print("="*50 + "\n")
            pool = None
            return None
    return pool

async def get_connection():
    """Obtém uma conexão do pool com logs detalhados"""
    try:
        print("🔌 Obtendo conexão do pool...")
        if pool is None or pool._closed:
            print("⚠ Pool não existe ou está fechado, criando novo...")
            await create_pool()
        
        start_time = time.time()
        conn = await pool.acquire()
        elapsed = time.time() - start_time
        print(f"✅ Conexão obtida com sucesso! (Tempo: {elapsed:.2f}s)")
        return conn
    except Exception as e:
        print("\n" + "="*50)
        print(f"❌ ERRO AO OBTER CONEXÃO:")
        print(f"Tipo: {type(e).__name__}")
        print(f"Detalhes: {str(e)}")
        print("="*50 + "\n")
        return None

async def release_connection(conn):
    """Libera uma conexão de volta para o pool"""
    try:
        if pool and conn:
            print("🔌 Liberando conexão...")
            await pool.release(conn)
            print("✅ Conexão liberada com sucesso!")
    except Exception as e:
        print("\n" + "="*50)
        print(f"❌ ERRO AO LIBERAR CONEXÃO:")
        print(f"Tipo: {type(e).__name__}")
        print(f"Detalhes: {str(e)}")
        print("="*50 + "\n")

async def init_db():
    """Inicializa o banco de dados e cria tabelas se não existirem"""
    conn = None
    try:
        print("\n" + "="*50)
        print("🛠 Inicializando banco de dados...")
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return False
            
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
            
        print("✅ Tabelas criadas/verificadas com sucesso!")
        print("="*50 + "\n")
        return True
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO INICIALIZAR BANCO:")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return False
    finally:
        if conn:
            await release_connection(conn)

async def load_db_data(boss_timers: Dict, user_stats: Dict, user_notifications: Dict) -> bool:
    """Carrega dados do banco de dados para as estruturas em memória"""
    conn = None
    try:
        print("\n" + "="*50)
        print("📥 Carregando dados do banco...")
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return False
            
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Carregar timers de boss
            await cursor.execute("SELECT * FROM boss_timers")
            timers = await cursor.fetchall()
            print(f"📝 {len(timers)} timers de boss encontrados")
            
            for timer in timers:
                boss_name = timer['boss_name']
                sala = timer['sala']
                
                if boss_name not in boss_timers:
                    continue
                    
                if sala not in boss_timers[boss_name]:
                    continue
                    
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
            print(f"👤 {len(stats)} registros de usuários encontrados")
            
            for stat in stats:
                user_stats[stat['user_id']] = {
                    'count': stat['count'],
                    'last_recorded': stat['last_recorded'].replace(tzinfo=brazil_tz) if stat['last_recorded'] else None,
                    'username': stat['username']
                }
            
            # Carregar notificações personalizadas
            await cursor.execute("SELECT * FROM user_notifications")
            notifications = await cursor.fetchall()
            print(f"🔔 {len(notifications)} notificações encontradas")
            
            for notification in notifications:
                user_id = notification['user_id']
                boss_name = notification['boss_name']
                
                if user_id not in user_notifications:
                    user_notifications[user_id] = []
                if boss_name not in user_notifications[user_id]:
                    user_notifications[user_id].append(boss_name)
            
            print(f"✅ Dados carregados com sucesso!")
            print(f"• {len(timers)} timers")
            print(f"• {len(stats)} usuários")
            print(f"• {len(notifications)} notificações")
            print("="*50 + "\n")
            return True
            
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO CARREGAR DADOS:")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return False
    finally:
        if conn:
            await release_connection(conn)

async def save_timer(boss_name: str, sala: int, death_time: datetime, respawn_time: datetime, 
                    closed_time: datetime, recorded_by: str, opened_notified: bool = False) -> bool:
    """Salva ou atualiza um timer de boss no banco de dados"""
    conn = None
    try:
        print(f"💾 Salvando timer: {boss_name} (Sala {sala})")
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
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
            """, (
                boss_name, sala, 
                death_time.astimezone(brazil_tz) if death_time else None,
                respawn_time.astimezone(brazil_tz) if respawn_time else None,
                closed_time.astimezone(brazil_tz) if closed_time else None,
                recorded_by, 
                opened_notified
            ))
            
            print(f"✅ Timer salvo com sucesso: {boss_name} (Sala {sala})")
            return True
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO SALVAR TIMER:")
        print(f"Boss: {boss_name}, Sala: {sala}")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return False
    finally:
        if conn:
            await release_connection(conn)

async def save_user_stats(user_id: str, username: str, count: int, last_recorded: datetime) -> bool:
    """Salva ou atualiza as estatísticas de um usuário no banco de dados"""
    conn = None
    try:
        print(f"💾 Salvando estatísticas do usuário: {username} (ID: {user_id})")
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return False
            
        async with conn.cursor() as cursor:
            await cursor.execute("""
            INSERT INTO user_stats (user_id, username, count, last_recorded)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                username = VALUES(username),
                count = VALUES(count),
                last_recorded = VALUES(last_recorded)
            """, (
                user_id,
                username,
                count,
                last_recorded.astimezone(brazil_tz) if last_recorded else None
            ))
            
            print(f"✅ Estatísticas do usuário salvas com sucesso: {username} (ID: {user_id})")
            return True
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO SALVAR ESTATÍSTICAS DO USUÁRIO:")
        print(f"User ID: {user_id}, Username: {username}")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return False
    finally:
        if conn:
            await release_connection(conn)

async def clear_timer(boss_name: str, sala: int = None) -> bool:
    """Limpa um timer de boss do banco de dados"""
    conn = None
    try:
        print(f"🧹 Limpando timer: {boss_name}" + (f" (Sala {sala})" if sala else ""))
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return False
            
        async with conn.cursor() as cursor:
            if sala is None:
                await cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s", (boss_name,))
            else:
                await cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s AND sala = %s", (boss_name, sala))
            
            print(f"✅ Timer limpo com sucesso: {boss_name}" + (f" (Sala {sala})" if sala else ""))
            return True
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO LIMPAR TIMER:")
        print(f"Boss: {boss_name}, Sala: {sala if sala else 'Todas'}")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return False
    finally:
        if conn:
            await release_connection(conn)

async def add_user_notification(user_id: str, boss_name: str) -> bool:
    """Adiciona uma notificação personalizada para um usuário"""
    conn = None
    try:
        print(f"🔔 Adicionando notificação: {user_id} -> {boss_name}")
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return False
            
        async with conn.cursor() as cursor:
            await cursor.execute("""
            INSERT IGNORE INTO user_notifications (user_id, boss_name)
            VALUES (%s, %s)
            """, (user_id, boss_name))
            
            print(f"✅ Notificação adicionada com sucesso: {user_id} -> {boss_name}")
            return True
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO ADICIONAR NOTIFICAÇÃO:")
        print(f"User ID: {user_id}, Boss: {boss_name}")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return False
    finally:
        if conn:
            await release_connection(conn)

async def remove_user_notification(user_id: str, boss_name: str) -> bool:
    """Remove uma notificação personalizada de um usuário"""
    conn = None
    try:
        print(f"🔕 Removendo notificação: {user_id} -> {boss_name}")
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return False
            
        async with conn.cursor() as cursor:
            await cursor.execute("""
            DELETE FROM user_notifications
            WHERE user_id = %s AND boss_name = %s
            """, (user_id, boss_name))
            
            print(f"✅ Notificação removida com sucesso: {user_id} -> {boss_name}")
            return True
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO REMOVER NOTIFICAÇÃO:")
        print(f"User ID: {user_id}, Boss: {boss_name}")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return False
    finally:
        if conn:
            await release_connection(conn)

async def get_user_notifications(user_id: str) -> List[str]:
    """Obtém todas as notificações personalizadas de um usuário"""
    conn = None
    try:
        print(f"📩 Obtendo notificações do usuário: {user_id}")
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return []
            
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
            SELECT boss_name FROM user_notifications
            WHERE user_id = %s
            """, (user_id,))
            
            results = await cursor.fetchall()
            notifications = [row['boss_name'] for row in results]
            
            print(f"✅ Notificações obtidas com sucesso: {user_id} -> {notifications}")
            return notifications
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO OBTER NOTIFICAÇÕES:")
        print(f"User ID: {user_id}")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return []
    finally:
        if conn:
            await release_connection(conn)

async def create_backup() -> Optional[str]:
    """Cria um backup dos dados em um arquivo JSON"""
    conn = None
    try:
        print("💾 Criando backup do banco de dados...")
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return None
            
        backup_data = {
            'boss_timers': [],
            'user_stats': [],
            'user_notifications': []
        }
        
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Backup dos timers de boss
            await cursor.execute("SELECT * FROM boss_timers")
            backup_data['boss_timers'] = await cursor.fetchall()
            
            # Backup das estatísticas de usuários
            await cursor.execute("SELECT * FROM user_stats")
            backup_data['user_stats'] = await cursor.fetchall()
            
            # Backup das notificações personalizadas
            await cursor.execute("SELECT * FROM user_notifications")
            backup_data['user_notifications'] = await cursor.fetchall()
        
        # Criar nome do arquivo de backup com timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_{timestamp}.json"
        
        # Salvar dados no arquivo JSON
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f, indent=2, default=str)
        
        print(f"✅ Backup criado com sucesso: {backup_file}")
        return backup_file
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO CRIAR BACKUP:")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return None
    finally:
        if conn:
            await release_connection(conn)

async def restore_backup(backup_file: str) -> bool:
    """Restaura um backup a partir de um arquivo JSON"""
    conn = None
    try:
        print(f"🔄 Restaurando backup: {backup_file}")
        
        # Ler dados do arquivo de backup
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
        
        conn = await get_connection()
        if conn is None:
            print("❌ Falha ao obter conexão!")
            return False
            
        async with conn.cursor() as cursor:
            # Limpar tabelas existentes
            await cursor.execute("TRUNCATE TABLE boss_timers")
            await cursor.execute("TRUNCATE TABLE user_stats")
            await cursor.execute("TRUNCATE TABLE user_notifications")
            
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
                    timer.get('opened_notified', False)
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
        
        print(f"✅ Backup restaurado com sucesso: {backup_file}")
        return True
    except Exception as err:
        print("\n" + "="*50)
        print(f"❌ ERRO AO RESTAURAR BACKUP:")
        print(f"Arquivo: {backup_file}")
        print(f"Tipo: {type(err).__name__}")
        print(f"Detalhes: {str(err)}")
        traceback.print_exc()
        print("="*50 + "\n")
        return False
    finally:
        if conn:
            await release_connection(conn)

async def close_pool():
    """Fecha o pool de conexões com logs detalhados"""
    global pool
    if pool:
        print("\n" + "="*50)
        print("🔌 Fechando pool de conexões...")
        try:
            pool.close()
            await pool.wait_closed()
            pool = None
            print("✅ Pool de conexões fechado com sucesso!")
            print("="*50 + "\n")
        except Exception as e:
            print("\n" + "="*50)
            print(f"❌ ERRO AO FECHAR POOL:")
            print(f"Tipo: {type(e).__name__}")
            print(f"Detalhes: {str(e)}")
            traceback.print_exc()
            print("="*50 + "\n")