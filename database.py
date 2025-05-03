import mysql.connector
import pytz
from datetime import datetime, timedelta
import json
import os
from typing import Optional
import traceback

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

def connect_db():
    """Estabelece conexão com o banco de dados MySQL"""
    try:
        conn = mysql.connector.connect(
            host=os.getenv('DB_HOST', '192.185.214.113'),
            user=os.getenv('DB_USER', 'thia5326_tohell'),
            password=os.getenv('DB_PASSWORD', 'Thi@goba1102@@'),
            database=os.getenv('DB_NAME', 'thia5326_tohell_bot'),
            connect_timeout=10
        )
        return conn
    except mysql.connector.Error as err:
        print(f"❌ Erro ao conectar ao banco de dados: {err}")
        traceback.print_exc()
        return None

async def init_db():
    """Inicializa as tabelas do banco de dados"""
    conn = connect_db()
    if conn is None:
        print("⚠ Banco de dados não disponível - usando dados em memória")
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
        print("✅ Tabelas do banco de dados verificadas/criadas")
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao inicializar banco de dados: {err}")
        traceback.print_exc()
        return False
    finally:
        if conn:
            conn.close()

async def load_db_data(boss_timers, user_stats, user_notifications):
    """Carrega dados do banco de dados para as estruturas em memória"""
    conn = connect_db()
    if conn is None:
        print("⚠ Banco de dados não disponível - usando dados em memória")
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

        print("✅ Dados carregados do banco de dados")
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao carregar dados do banco: {err}")
        traceback.print_exc()
        return False
    finally:
        if conn:
            conn.close()

async def save_db_data(boss_timers, user_stats):
    """Salva dados das estruturas em memória para o banco de dados"""
    conn = connect_db()
    if conn is None:
        print("⚠ Banco de dados não disponível - usando dados em memória")
        return False

    try:
        cursor = conn.cursor()

        # Salvar timers de boss
        cursor.execute("DELETE FROM boss_timers")
        for boss_name, salas in boss_timers.items():
            for sala, timer in salas.items():
                cursor.execute("""
                INSERT INTO boss_timers 
                (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    boss_name, sala, timer['death_time'], timer['respawn_time'], 
                    timer['closed_time'], timer['recorded_by'], timer['opened_notified']
                ))

        # Salvar estatísticas de usuários
        cursor.execute("DELETE FROM user_stats")
        for user_id, stat in user_stats.items():
            cursor.execute("""
            INSERT INTO user_stats (user_id, username, count, last_recorded)
            VALUES (%s, %s, %s, %s)
            """, (user_id, stat['username'], stat['count'], stat['last_recorded']))

        conn.commit()
        print("✅ Dados salvos no banco de dados")
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao salvar dados no banco: {err}")
        traceback.print_exc()
        return False
    finally:
        if conn:
            conn.close()

async def clear_db_data():
    """Limpa todos os dados do banco de dados"""
    conn = connect_db()
    if conn is None:
        print("⚠ Banco de dados não disponível - usando dados em memória")
        return False

    try:
        cursor = conn.cursor()

        cursor.execute("DELETE FROM boss_timers")
        cursor.execute("DELETE FROM user_stats")
        cursor.execute("DELETE FROM user_notifications")

        conn.commit()
        print("✅ Dados do banco de dados limpos")
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao limpar dados do banco: {err}")
        traceback.print_exc()
        return False
    finally:
        if conn:
            conn.close()

async def create_backup():
    """Cria um backup dos dados do banco de dados"""
    conn = connect_db()
    if conn is None:
        return None

    try:
        cursor = conn.cursor(dictionary=True)

        backup_data = {}

        # Backup dos timers de boss
        cursor.execute("SELECT * FROM boss_timers")
        backup_data['boss_timers'] = cursor.fetchall()

        # Backup das estatísticas de usuários
        cursor.execute("SELECT * FROM user_stats")
        backup_data['user_stats'] = cursor.fetchall()

        # Backup das notificações de usuários
        cursor.execute("SELECT * FROM user_notifications")
        backup_data['user_notifications'] = cursor.fetchall()

        # Salvar backup em arquivo JSON
        backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=4, default=str)  # Usar default=str para converter datetime

        print(f"✅ Backup criado com sucesso: {backup_file}")
        return backup_file
    except mysql.connector.Error as err:
        print(f"❌ Erro ao criar backup: {err}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()

async def restore_backup(backup_file):
    """Restaura os dados do banco de dados a partir de um arquivo de backup"""
    conn = connect_db()
    if conn is None:
        return False

    try:
        with open(backup_file, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        cursor = conn.cursor()

        # Restaurar timers de boss
        cursor.execute("DELETE FROM boss_timers")
        for timer in backup_data['boss_timers']:
            cursor.execute("""
            INSERT INTO boss_timers 
            (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                timer['boss_name'], timer['sala'], timer['death_time'], 
                timer['respawn_time'], timer['closed_time'], timer['recorded_by'],
                timer['opened_notified']
            ))

        # Restaurar estatísticas de usuários
        cursor.execute("DELETE FROM user_stats")
        for stat in backup_data['user_stats']:
            cursor.execute("""
            INSERT INTO user_stats (user_id, username, count, last_recorded)
            VALUES (%s, %s, %s, %s)
            """, (
                stat['user_id'], stat['username'], stat['count'], 
                stat['last_recorded']
            ))

        # Restaurar notificações personalizadas
        cursor.execute("DELETE FROM user_notifications")
        for notification in backup_data['user_notifications']:
            cursor.execute("""
            INSERT INTO user_notifications (user_id, boss_name)
            VALUES (%s, %s)
            """, (
                notification['user_id'], notification['boss_name']
            ))

        conn.commit()
        print(f"✅ Backup restaurado com sucesso: {backup_file}")
        return True
    except mysql.connector.Error as err:
        print(f"❌ Erro ao restaurar backup: {err}")
        traceback.print_exc()
        return False
    finally:
        if conn:
            conn.close()