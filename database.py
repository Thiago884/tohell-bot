import mysql.connector
import pytz
from datetime import datetime, timedelta
import json
import os

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Conexão com o banco de dados MySQL
def connect_db():
    try:
        conn = mysql.connector.connect(
            host="192.185.214.113",
            user="thia5326_tohell",
            password="Thi@goba1102@@",
            database="thia5326_tohell_bot"
        )
        return conn
    except mysql.connector.Error as err:
        print(f"Erro ao conectar ao banco de dados: {err}")
        return None

# Inicializar o banco de dados
def init_db():
    conn = connect_db()
    if conn is None:
        return
    
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
        print("Banco de dados inicializado com sucesso!")
    except mysql.connector.Error as err:
        print(f"Erro ao inicializar banco de dados: {err}")
    finally:
        conn.close()

# Carregar dados do banco de dados
def load_db_data(boss_timers, user_stats, user_notifications):
    conn = connect_db()
    if conn is None:
        return
    
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
                    'death_time': timer['death_time'].replace(tzinfo=brazil_tz),
                    'respawn_time': timer['respawn_time'].replace(tzinfo=brazil_tz),
                    'closed_time': timer['closed_time'].replace(tzinfo=brazil_tz),
                    'recorded_by': timer['recorded_by'],
                    'opened_notified': timer['opened_notified']
                }
        
        # Carregar estatísticas de usuários
        cursor.execute("SELECT * FROM user_stats")
        stats = cursor.fetchall()
        
        for stat in stats:
            user_stats[stat['user_id']] = {
                'count': stat['count'],
                'last_recorded': stat['last_recorded'].replace(tzinfo=brazil_tz) if stat['last_recorded'] else None
            }
        
        # Carregar notificações personalizadas
        cursor.execute("SELECT * FROM user_notifications")
        notifications = cursor.fetchall()
        
        for notification in notifications:
            user_id = notification['user_id']
            boss_name = notification['boss_name']
            
            if user_id not in user_notifications:
                user_notifications[user_id] = []
            user_notifications[user_id].append(boss_name)
        
        print("Dados carregados do banco de dados com sucesso!")
    except mysql.connector.Error as err:
        print(f"Erro ao carregar dados do banco: {err}")
    finally:
        conn.close()

# Salvar dados no banco de dados
def save_timer(boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified=False):
    conn = connect_db()
    if conn is None:
        return
    
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
    except mysql.connector.Error as err:
        print(f"Erro ao salvar timer: {err}")
    finally:
        conn.close()

def save_user_stats(user_id, username, count, last_recorded):
    conn = connect_db()
    if conn is None:
        return
    
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
    except mysql.connector.Error as err:
        print(f"Erro ao salvar estatísticas do usuário: {err}")
    finally:
        conn.close()

def clear_timer(boss_name, sala=None):
    conn = connect_db()
    if conn is None:
        return
    
    try:
        cursor = conn.cursor()
        
        if sala is None:
            cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s", (boss_name,))
        else:
            cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s AND sala = %s", (boss_name, sala))
        
        conn.commit()
    except mysql.connector.Error as err:
        print(f"Erro ao limpar timer: {err}")
    finally:
        conn.close()

def add_user_notification(user_id, boss_name):
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
        print(f"Erro ao adicionar notificação: {err}")
        return False
    finally:
        conn.close()

def remove_user_notification(user_id, boss_name):
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
        print(f"Erro ao remover notificação: {err}")
        return False
    finally:
        conn.close()

def get_user_notifications(user_id):
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
        print(f"Erro ao obter notificações: {err}")
        return []
    finally:
        conn.close()

# Funções para backup do banco de dados
def create_backup():
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
            
        print(f"Backup criado com sucesso: {backup_file}")
        return backup_file
        
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None
    finally:
        if conn:
            conn.close()

def restore_backup(backup_file):
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
                timer['opened_notified']
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
        print(f"Backup restaurado com sucesso: {backup_file}")
        return True
        
    except Exception as e:
        print(f"Erro ao restaurar backup: {e}")
        return False
    finally:
        if conn:
            conn.close()