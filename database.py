import mysql.connector
import pytz
from datetime import datetime, timedelta
import json
import os
import time

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

def connect_db(max_retries=3, retry_delay=5):
    """Tenta conectar ao banco de dados com múltiplas tentativas"""
    for attempt in range(max_retries):
        try:
            conn = mysql.connector.connect(
                host="192.185.214.113",
                user="thia5326_tohell",
                password="Thi@goba1102@@",
                database="thia5326_tohell_bot",
                connect_timeout=10,
                connection_timeout=10
            )
            return conn
        except mysql.connector.Error as err:
            print(f"Tentativa {attempt + 1} de {max_retries} falhou. Erro ao conectar ao banco: {err}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    return None

def init_db():
    """Inicializa o banco de dados e cria tabelas se não existirem"""
    conn = connect_db()
    if conn is None:
        print("❌ Não foi possível conectar ao banco para inicialização")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Tabela de timers de boss
        cursor.execute("""
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
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id VARCHAR(20) PRIMARY KEY,
            username VARCHAR(50) NOT NULL,
            count INT DEFAULT 0,
            last_recorded DATETIME,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)
        
        # Tabela de notificações personalizadas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_notifications (
            user_id VARCHAR(20) NOT NULL,
            boss_name VARCHAR(50) NOT NULL,
            PRIMARY KEY (user_id, boss_name)
        )
        """)
        
        conn.commit()
        print("✅ Tabelas criadas/verificadas com sucesso!")
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao inicializar banco de dados: {err}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def load_db_data(boss_timers, user_stats, user_notifications):
    """Carrega dados do banco de dados para as estruturas em memória"""
    conn = connect_db()
    if conn is None:
        print("❌ Não foi possível conectar ao banco para carregar dados")
        return False
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Carregar timers de boss
        cursor.execute("SELECT * FROM boss_timers")
        timers = cursor.fetchall()
        
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
        cursor.execute("SELECT * FROM user_stats")
        stats = cursor.fetchall()
        
        for stat in stats:
            user_stats[stat['user_id']] = {
                'count': stat['count'],
                'last_recorded': stat['last_recorded'].replace(tzinfo=brazil_tz) if stat['last_recorded'] else None,
                'username': stat['username']
            }
        
        # Carregar notificações personalizadas
        cursor.execute("SELECT * FROM user_notifications")
        notifications = cursor.fetchall()
        
        for notification in notifications:
            user_id = notification['user_id']
            boss_name = notification['boss_name']
            
            if user_id not in user_notifications:
                user_notifications[user_id] = []
            if boss_name not in user_notifications[user_id]:
                user_notifications[user_id].append(boss_name)
        
        print(f"✅ Dados carregados: {len(timers)} timers, {len(stats)} usuários, {len(notifications)} notificações")
        return True
        
    except mysql.connector.Error as err:
        print(f"❌ Erro ao carregar dados do banco: {err}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def save_timer(boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified=False):
    """Salva ou atualiza um timer de boss no banco de dados"""
    conn = connect_db()
    if conn is None:
        return False
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO boss_timers (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            death_time = VALUES(death_time),
            respawn_time = VALUES(respawn_time),
            closed_time = VALUES(closed_time),
            recorded_by = VALUES(recorded_by),
            opened_notified = VALUES(opened_notified)
        """, (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified))
        
        conn.commit()
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao salvar timer: {err}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def save_user_stats(user_id, username, count, last_recorded):
    """Salva ou atualiza estatísticas de usuário no banco de dados"""
    conn = connect_db()
    if conn is None:
        return False
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO user_stats (user_id, username, count, last_recorded)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            username = VALUES(username),
            count = VALUES(count),
            last_recorded = VALUES(last_recorded)
        """, (user_id, username, count, last_recorded))
        
        conn.commit()
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao salvar estatísticas do usuário: {err}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def clear_timer(boss_name, sala=None):
    """Remove um timer de boss do banco de dados"""
    conn = connect_db()
    if conn is None:
        return False
    
    try:
        cursor = conn.cursor()
        
        if sala is None:
            cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s", (boss_name,))
        else:
            cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s AND sala = %s", (boss_name, sala))
        
        conn.commit()
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao limpar timer: {err}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def add_user_notification(user_id, boss_name):
    """Adiciona uma notificação de boss para um usuário"""
    conn = connect_db()
    if conn is None:
        return False
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO user_notifications (user_id, boss_name)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            user_id = VALUES(user_id),
            boss_name = VALUES(boss_name)
        """, (user_id, boss_name))
        
        conn.commit()
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao adicionar notificação: {err}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def remove_user_notification(user_id, boss_name):
    """Remove uma notificação de boss de um usuário"""
    conn = connect_db()
    if conn is None:
        return False
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
        DELETE FROM user_notifications
        WHERE user_id = %s AND boss_name = %s
        """, (user_id, boss_name))
        
        conn.commit()
        return cursor.rowcount > 0
    except mysql.connector.Error as err:
        print(f"❌ Erro ao remover notificação: {err}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def get_user_notifications(user_id):
    """Obtém todas as notificações de um usuário"""
    conn = connect_db()
    if conn is None:
        return []
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
        SELECT boss_name FROM user_notifications
        WHERE user_id = %s
        """, (user_id,))
        
        return [row['boss_name'] for row in cursor.fetchall()]
    except mysql.connector.Error as err:
        print(f"❌ Erro ao obter notificações: {err}")
        return []
    finally:
        if conn.is_connected():
            conn.close()

def create_backup():
    """Cria um backup dos dados em formato JSON"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_{timestamp}.json"
        
        conn = connect_db()
        if conn is None:
            return None
            
        cursor = conn.cursor(dictionary=True)
        
        # Backup dos timers de boss
        cursor.execute("SELECT * FROM boss_timers")
        boss_timers_data = cursor.fetchall()
        
        # Backup das estatísticas de usuários
        cursor.execute("SELECT * FROM user_stats")
        user_stats_data = cursor.fetchall()
        
        # Backup das notificações personalizadas
        cursor.execute("SELECT * FROM user_notifications")
        user_notifications_data = cursor.fetchall()
        
        backup_data = {
            'boss_timers': boss_timers_data,
            'user_stats': user_stats_data,
            'user_notifications': user_notifications_data,
            'timestamp': timestamp
        }
        
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f, indent=4, default=str)
            
        print(f"✅ Backup criado com sucesso: {backup_file}")
        return backup_file
        
    except Exception as e:
        print(f"❌ Erro ao criar backup: {e}")
        return None
    finally:
        if conn and conn.is_connected():
            conn.close()

def restore_backup(backup_file):
    """Restaura um backup dos dados"""
    try:
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
            
        conn = connect_db()
        if conn is None:
            return False
            
        cursor = conn.cursor()
        
        # Limpar tabelas antes de restaurar
        cursor.execute("DELETE FROM boss_timers")
        cursor.execute("DELETE FROM user_stats")
        cursor.execute("DELETE FROM user_notifications")
        
        # Restaurar timers de boss
        for timer in backup_data['boss_timers']:
            cursor.execute("""
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
            cursor.execute("""
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
                cursor.execute("""
                INSERT INTO user_notifications (user_id, boss_name)
                VALUES (%s, %s)
                """, (
                    notification['user_id'],
                    notification['boss_name']
                ))
        
        conn.commit()
        print(f"✅ Backup restaurado com sucesso: {backup_file}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao restaurar backup: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()