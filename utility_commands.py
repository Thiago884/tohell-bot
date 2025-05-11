# utility_commands.py
from datetime import datetime, timedelta
import pytz
import discord
import asyncio
import random
import json
import os
import traceback
import logging
from database import (
    save_timer, save_user_stats, clear_timer,
    add_user_notification, remove_user_notification, get_user_notifications,
    create_backup, restore_backup, connect_db, load_db_data
)
from shared_functions import get_boss_by_abbreviation, format_time_remaining, parse_time_input, validate_time
from views import BossControlView

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Configuração de logging
logger = logging.getLogger(__name__)

async def send_notification_dm(bot, user_id, boss_name, sala, respawn_time, closed_time):
    """Envia notificação por DM quando um boss abre"""
    try:
        user = await bot.fetch_user(int(user_id))
        if user:
            await asyncio.sleep(1)  # Delay para evitar rate limit
            await user.send(
                f"🔔 **Notificação de Boss** 🔔\n"
                f"O boss **{boss_name} (Sala {sala})** que você marcou está disponível AGORA!\n"
                f"✅ Aberto até: {closed_time.strftime('%d/%m %H:%M')} BRT\n"
                f"Corra para pegar seu loot! 🏆"
            )
            return True
    except discord.Forbidden:
        logger.warning(f"Usuário {user_id} bloqueou DMs ou não aceita mensagens")
    except discord.HTTPException as e:
        if e.status == 429:
            retry_after = e.retry_after
            logger.warning(f"Rate limit ao enviar DM. Tentando novamente em {retry_after} segundos")
            await asyncio.sleep(retry_after)
            return await send_notification_dm(bot, user_id, boss_name, sala, respawn_time, closed_time)
        else:
            logger.error(f"Erro ao enviar DM para {user_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Erro ao enviar DM para {user_id}: {e}", exc_info=True)
    return False

async def create_history_embed(bot, boss_timers):
    """Cria embed com histórico de anotações"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return discord.Embed(
                title="Erro de Conexão",
                description="Não foi possível conectar ao banco de dados",
                color=discord.Color.red()
            )
        
        async with conn.cursor() as cursor:
            await cursor.execute("""
            SELECT boss_name, sala, death_time, respawn_time, recorded_by 
            FROM boss_timers 
            WHERE death_time IS NOT NULL
            ORDER BY death_time DESC 
            LIMIT 10
            """)
            
            history = await cursor.fetchall()
            
            if not history:
                return discord.Embed(
                    title="📜 Histórico de Anotações",
                    description="Nenhuma anotação registrada ainda.",
                    color=discord.Color.blue()
                )
            
            embed = discord.Embed(
                title="📜 Histórico das Últimas Anotações",
                color=discord.Color.gold()
            )
            
            for idx, record in enumerate(history, 1):
                death_time = record[2].astimezone(brazil_tz) if record[2] else None
                respawn_time = record[3].astimezone(brazil_tz) if record[3] else None
                
                embed.add_field(
                    name=f"{idx}. {record[0]} (Sala {record[1]})",
                    value=(
                        f"⏱ Morte: {death_time.strftime('%d/%m %H:%M') if death_time else 'N/A'}\n"
                        f"🔄 Abriu: {respawn_time.strftime('%d/%m %H:%M') if respawn_time else 'N/A'}\n"
                        f"👤 Por: {record[4] or 'Desconhecido'}"
                    ),
                    inline=False
                )
            
            return embed
            
    except Exception as e:
        logger.error(f"Erro ao buscar histórico: {str(e)}", exc_info=True)
        return discord.Embed(
            title="Erro",
            description=f"Ocorreu um erro ao buscar o histórico: {str(e)}",
            color=discord.Color.red()
        )
    finally:
        if conn:
            await conn.ensure_closed()

async def create_unrecorded_embed(bot, boss_timers):
    """Cria embed com bosses que fecharam sem registro"""
    conn = None
    try:
        conn = await connect_db()
        if conn is None:
            return discord.Embed(
                title="Erro de Conexão",
                description="Não foi possível conectar ao banco de dados",
                color=discord.Color.red()
            )
        
        async with conn.cursor() as cursor:
            await cursor.execute("""
            SELECT 
                boss_name, 
                sala, 
                death_time, 
                respawn_time, 
                closed_time,
                recorded_by
            FROM 
                boss_timers
            WHERE 
                closed_time IS NOT NULL AND
                closed_time < NOW() AND
                death_time IS NOT NULL
            ORDER BY 
                closed_time DESC 
            LIMIT 10
            """)
            
            unrecorded = await cursor.fetchall()
            
            if not unrecorded:
                return discord.Embed(
                    title="🔴 Bosses Fechados Recentemente",
                    description="Nenhum boss foi fechado recentemente sem registro.",
                    color=discord.Color.blue()
                )
            
            embed = discord.Embed(
                title="🔴 Últimos Bosses Fechados",
                description="Estes bosses foram fechados recentemente:",
                color=discord.Color.red()
            )
            
            for idx, record in enumerate(unrecorded, 1):
                death_time = record[2].astimezone(brazil_tz) if record[2] else None
                respawn_time = record[3].astimezone(brazil_tz) if record[3] else None
                closed_time = record[4].astimezone(brazil_tz) if record[4] else None
                
                embed.add_field(
                    name=f"{idx}. {record[0]} (Sala {record[1]})",
                    value=(
                        f"⏱ Morte registrada: {death_time.strftime('%d/%m %H:%M') if death_time else 'N/A'}\n"
                        f"🔄 Período aberto: {respawn_time.strftime('%d/%m %H:%M') if respawn_time else 'N/A'} "
                        f"até {closed_time.strftime('%d/%m %H:%M') if closed_time else 'N/A'}\n"
                        f"👤 Registrado por: {record[5] or 'Ninguém'}"
                    ),
                    inline=False
                )
            
            return embed
            
    except Exception as e:
        logger.error(f"Erro ao buscar bosses fechados: {str(e)}", exc_info=True)
        return discord.Embed(
            title="Erro",
            description=f"Ocorreu um erro ao buscar os bosses fechados: {str(e)}",
            color=discord.Color.red()
        )
    finally:
        if conn:
            await conn.ensure_closed()

async def create_ranking_embed(bot, user_stats):
    """Cria embed com o ranking de usuários que mais registraram bosses"""
    try:
        sorted_users = sorted(user_stats.items(), key=lambda x: x[1]['count'], reverse=True)
        
        embed = discord.Embed(
            title="🏆 RANKING DE ANOTAÇÕES",
            color=discord.Color.gold()
        )
        
        if not sorted_users:
            embed.description = "Nenhuma anotação registrada ainda."
            return embed
        
        ranking_text = []
        for idx, (user_id, stats) in enumerate(sorted_users[:10]):
            try:
                user = await bot.fetch_user(int(user_id))
                username = user.name
            except:
                username = stats.get('username', f"Usuário {user_id}")
            
            medal = ""
            if idx == 0:
                medal = "🥇 "
            elif idx == 1:
                medal = "🥈 "
            elif idx == 2:
                medal = "🥉 "
            
            last_recorded = stats['last_recorded'].strftime("%d/%m %H:%M") if stats['last_recorded'] else "Nunca"
            ranking_text.append(
                f"{medal}**{idx+1}.** {username} - {stats['count']} anotações\n"
                f"Última: {last_recorded}"
            )
        
        embed.description = "\n\n".join(ranking_text)
        return embed
    except Exception as e:
        logger.error(f"Erro ao criar ranking embed: {e}", exc_info=True)
        return discord.Embed(
            title="Erro",
            description="Ocorreu um erro ao gerar o ranking",
            color=discord.Color.red()
        )

async def run_daily_backup():
    """Executa o backup diário com tratamento robusto de erros"""
    conn = None
    try:
        logger.info("Iniciando backup diário...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_{timestamp}.json"
        
        conn = await connect_db()
        if conn is None:
            logger.error("Não foi possível conectar ao banco para backup")
            return False
            
        async with conn.cursor() as cursor:
            # Backup dos timers de boss
            await cursor.execute("""
            SELECT boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified 
            FROM boss_timers
            """)
            boss_timers_data = []
            for row in await cursor.fetchall():
                boss_timers_data.append({
                    'boss_name': row[0],
                    'sala': row[1],
                    'death_time': row[2].isoformat() if row[2] else None,
                    'respawn_time': row[3].isoformat() if row[3] else None,
                    'closed_time': row[4].isoformat() if row[4] else None,
                    'recorded_by': row[5],
                    'opened_notified': bool(row[6])
                })
            
            # Backup das estatísticas de usuários
            await cursor.execute("""
            SELECT user_id, username, count, last_recorded 
            FROM user_stats
            """)
            user_stats_data = []
            for row in await cursor.fetchall():
                user_stats_data.append({
                    'user_id': row[0],
                    'username': row[1],
                    'count': row[2],
                    'last_recorded': row[3].isoformat() if row[3] else None
                })
            
            # Backup das notificações personalizadas
            await cursor.execute("""
            SELECT user_id, boss_name 
            FROM user_notifications
            """)
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
        return True
        
    except Exception as e:
        logger.error(f"Erro no backup diário: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await conn.ensure_closed()

async def backup_task_loop():
    """Loop para executar o backup diário com tratamento de erros"""
    while True:
        try:
            await asyncio.sleep(24 * 3600)  # Espera 24 horas entre backups
            success = await run_daily_backup()
            
            if not success:
                logger.warning("Backup falhou. Tentando novamente em 1 hora...")
                await asyncio.sleep(3600)  # Espera 1 hora se falhar
            
        except Exception as e:
            logger.error(f"Erro no loop de backup: {e}", exc_info=True)
            await asyncio.sleep(3600)  # Espera 1 hora se ocorrer erro inesperado