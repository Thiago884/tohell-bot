from datetime import datetime, timedelta
import pytz
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select, Modal
from discord import TextStyle, app_commands
from collections import defaultdict
import random
import traceback
import re
import json
import os
import asyncio
from typing import Optional
from database import (
    save_timer, save_user_stats, clear_timer,
    add_user_notification, remove_user_notification, get_user_notifications,
    create_backup, restore_backup, connect_db, load_db_data
)
from shared_functions import get_boss_by_abbreviation, format_time_remaining, parse_time_input, validate_time, get_next_bosses
from views import BossControlView

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

async def send_notification_dm(bot, user_id, boss_name, sala, respawn_time, closed_time):
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
        print(f"Usuário {user_id} bloqueou DMs ou não aceita mensagens")
    except discord.HTTPException as e:
        if e.status == 429:
            retry_after = e.retry_after
            print(f"Rate limit atingido. Tentando novamente em {retry_after} segundos")
            await asyncio.sleep(retry_after)
            return await send_notification_dm(bot, user_id, boss_name, sala, respawn_time, closed_time)
        else:
            print(f"Erro ao enviar DM para {user_id}: {e}")
    except Exception as e:
        print(f"Erro ao enviar DM para {user_id}: {e}")
    
    return False

async def create_history_embed(bot, boss_timers):
    """Cria embed com histórico de anotações (versão corrigida)"""
    conn = None
    try:
        print("Iniciando busca por histórico...")
        conn = await connect_db()
        if conn is None:
            print("Erro: Não foi possível conectar ao banco de dados")
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
            print(f"Histórico encontrado: {len(history)} registros")
            
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
        print(f"Erro detalhado ao buscar histórico: {str(e)}")
        traceback.print_exc()
        return discord.Embed(
            title="Erro",
            description=f"Ocorreu um erro ao buscar o histórico: {str(e)}",
            color=discord.Color.red()
        )
    finally:
        if conn:
            await conn.ensure_closed()

async def create_unrecorded_embed(bot, boss_timers):
    """Cria embed com bosses que fecharam sem registro (versão corrigida)"""
    conn = None
    try:
        print("Iniciando busca por bosses não anotados...")
        conn = await connect_db()
        if conn is None:
            print("Erro: Não foi possível conectar ao banco de dados")
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
            print(f"Bosses não anotados encontrados: {len(unrecorded)} registros")
            
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
        print(f"Erro detalhado ao buscar bosses fechados: {str(e)}")
        traceback.print_exc()
        return discord.Embed(
            title="Erro",
            description=f"Ocorreu um erro ao buscar os bosses fechados: {str(e)}",
            color=discord.Color.red()
        )
    finally:
        if conn:
            await conn.ensure_closed()

async def setup_boss_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID):
    async def create_ranking_embed():
        """Cria embed com o ranking de usuários que mais registraram bosses"""
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

    def create_boss_embed(compact=False):
        """Cria embed com a tabela de timers de boss"""
        now = datetime.now(brazil_tz)
        
        embed = discord.Embed(
            title=f"BOSS TIMER - {now.strftime('%d/%m/%Y %H:%M:%S')} BRT",
            color=discord.Color.gold()
        )
        
        for boss in boss_timers:
            boss_info = []
            for sala in boss_timers[boss]:
                timers = boss_timers[boss][sala]
                
                # Pular bosses que já fecharam e não foram registrados
                if timers['closed_time'] and now >= timers['closed_time'] and timers['death_time'] is None:
                    continue
                    
                if compact and timers['death_time'] is None:
                    continue
                    
                death_time = timers['death_time'].strftime("%d/%m %H:%M") if timers['death_time'] else "--/-- --:--"
                respawn_time = timers['respawn_time'].strftime("%H:%M") if timers['respawn_time'] else "--:--"
                closed_time = timers['closed_time'].strftime("%H:%M") if timers['closed_time'] else "--:--"
                recorded_by = f" ({timers['recorded_by']})" if timers['recorded_by'] else ""
                
                status = ""
                if timers['respawn_time']:
                    if now >= timers['respawn_time']:
                        if timers['closed_time'] and now >= timers['closed_time']:
                            status = "❌"  # Boss fechado
                        else:
                            status = "✅"  # Boss aberto
                    else:
                        time_left = format_time_remaining(timers['respawn_time'])
                        status = f"🕒 ({time_left})"  # Boss agendado
                else:
                    status = "❌"  # Sem registro
                
                boss_info.append(
                    f"Sala {sala}: {death_time} [de {respawn_time} até {closed_time}] {status}{recorded_by}"
                )
            
            if not boss_info and compact:
                continue
                
            if boss_info:
                embed.add_field(
                    name=f"**{boss}**",
                    value="\n".join(boss_info) if boss_info else "Nenhum horário registrado",
                    inline=False
                )
        
        return embed

    async def create_next_bosses_embed(boss_timers):
        """Cria embed com os próximos bosses a abrir"""
        next_bosses = get_next_bosses(boss_timers)
        
        embed = discord.Embed(
            title="⏳ PRÓXIMOS BOSSES E BOSSES ABERTOS",
            color=discord.Color.blue()
        )
        
        if not next_bosses:
            embed.description = "Nenhum boss programado para abrir em breve ou atualmente aberto."
            return embed
        
        boss_info = []
        for boss in next_bosses:
            recorded_by = f" (Anotado por: {boss['recorded_by']})" if boss['recorded_by'] else ""
            
            if boss['status'] == 'open':
                boss_info.append(
                    f"🟢 **{boss['boss']} (Sala {boss['sala']})** - ABERTO AGORA!\n"
                    f"⏳ Fecha em: {boss['time_left']} ({boss['closed_time'].strftime('%d/%m %H:%M')} BRT){recorded_by}"
                )
            else:
                boss_info.append(
                    f"🟡 **{boss['boss']} (Sala {boss['sala']})** - ABRE EM {boss['time_left']}\n"
                    f"⏰ Horário: {boss['respawn_time'].strftime('%d/%m %H:%M')} BRT{recorded_by}"
                )
        
        embed.description = "\n\n".join(boss_info)
        return embed

    async def update_table(channel):
        """Atualiza a mensagem da tabela de bosses"""
        nonlocal table_message
        
        try:
            embed = create_boss_embed()
            view = BossControlView(
                bot, 
                boss_timers, 
                user_stats, 
                user_notifications, 
                table_message, 
                NOTIFICATION_CHANNEL_ID,
                update_table,
                create_next_bosses_embed,
                create_ranking_embed,
                lambda: create_history_embed(bot, boss_timers),
                lambda: create_unrecorded_embed(bot, boss_timers)
            )
            
            if table_message:
                try:
                    await asyncio.sleep(1)  # Delay para evitar rate limit
                    await table_message.edit(embed=embed, view=view)
                    return
                except discord.NotFound:
                    table_message = None
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = e.retry_after
                        print(f"Rate limit ao editar tabela. Tentando novamente em {retry_after} segundos")
                        await asyncio.sleep(retry_after)
                        return await update_table(channel)
                    else:
                        print(f"Erro HTTP ao editar mensagem da tabela: {e}")
                        table_message = None
                except Exception as e:
                    print(f"Erro ao editar mensagem da tabela: {e}")
                    table_message = None
            
            if not table_message:
                async for message in channel.history(limit=50):
                    if message.author == bot.user and message.embeds and "BOSS TIMER" in message.embeds[0].title:
                        try:
                            await asyncio.sleep(1)  # Delay para evitar rate limit
                            await message.edit(embed=embed, view=view)
                            table_message = message
                            return
                        except:
                            continue
            
            await asyncio.sleep(1)  # Delay para evitar rate limit
            table_message = await channel.send(embed=embed, view=view)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit ao enviar tabela. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
                return await update_table(channel)
            else:
                print(f"Erro HTTP ao atualizar tabela: {e}")
        except Exception as e:
            print(f"Erro ao atualizar tabela: {e}")
            try:
                await asyncio.sleep(1)  # Delay para evitar rate limit
                table_message = await channel.send(embed=create_boss_embed(), view=BossControlView(
                    bot, 
                    boss_timers, 
                    user_stats, 
                    user_notifications, 
                    table_message, 
                    NOTIFICATION_CHANNEL_ID,
                    update_table,
                    create_next_bosses_embed,
                    create_ranking_embed,
                    lambda: create_history_embed(bot, boss_timers),
                    lambda: create_unrecorded_embed(bot, boss_timers)
                ))
            except Exception as e:
                print(f"Erro ao enviar nova mensagem de tabela: {e}")

    # Tasks
    @tasks.loop(seconds=60)  # Alterado de 30 para 60 segundos para reduzir rate limits
    async def live_table_updater():
        """Atualiza a tabela periodicamente"""
        try:
            channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel:
                await update_table(channel)
        except Exception as e:
            print(f"Erro na task de atualização de tabela: {e}")

    @tasks.loop(minutes=1)
    async def check_boss_respawns():
        """Verifica os respawns de boss e envia notificações"""
        try:
            channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel is None:
                print(f"Erro: Canal com ID {NOTIFICATION_CHANNEL_ID} não encontrado!")
                return

            now = datetime.now(brazil_tz)
            notifications = []
            dm_notifications = []

            for boss in boss_timers:
                for sala in boss_timers[boss]:
                    timers = boss_timers[boss][sala]
                    respawn_time = timers['respawn_time']
                    closed_time = timers['closed_time']
                    
                    if respawn_time is not None:
                        # Notificação de pré-abertura (5 minutos antes)
                        if now >= (respawn_time - timedelta(minutes=5)) and now < respawn_time:
                            time_left = format_time_remaining(respawn_time)
                            recorded_by = f"\nAnotado por: {timers['recorded_by']}" if timers['recorded_by'] else ""
                            notifications.append(f"🟡 **{boss} (Sala {sala})** estará disponível em {time_left} ({respawn_time:%d/%m %H:%M} BRT){recorded_by}")
                        
                        # Notificação de abertura
                        if now >= respawn_time and closed_time is not None and now < closed_time:
                            if not timers.get('opened_notified', False):
                                recorded_by = f"\nAnotado por: {timers['recorded_by']}" if timers['recorded_by'] else ""
                                notifications.append(f"🟢 **{boss} (Sala {sala})** está disponível AGORA! (aberto até {closed_time:%d/%m %H:%M} BRT){recorded_by}")
                                boss_timers[boss][sala]['opened_notified'] = True
                                await save_timer(boss, sala, timers['death_time'], respawn_time, closed_time, timers['recorded_by'], True)
                                
                                for user_id in user_notifications:
                                    if boss in user_notifications[user_id]:
                                        dm_notifications.append({
                                            'user_id': user_id,
                                            'boss_name': boss,
                                            'sala': sala,
                                            'respawn_time': respawn_time,
                                            'closed_time': closed_time
                                        })
                        
                        # Notificação de fechamento
                        if closed_time is not None and abs((now - closed_time).total_seconds()) < 60:
                            message = f"🔴 **{boss} (Sala {sala})** FECHOU"
                            if not timers.get('opened_notified', False):
                                message += " sem nenhuma anotação durante o período aberto!"
                            else:
                                message += "!"

                            notifications.append(message)
                            
                            # Apenas marca que foi fechado, sem apagar os horários
                            boss_timers[boss][sala]['opened_notified'] = False

                            # Atualiza no banco com os mesmos dados (para manter integridade)
                            await save_timer(
                                boss,
                                sala,
                                timers['death_time'],
                                timers['respawn_time'],
                                timers['closed_time'],
                                timers['recorded_by'],
                                False
                            )

            if notifications:
                message = "**Notificações de Boss:**\n" + "\n".join(notifications)
                try:
                    await asyncio.sleep(1)  # Delay para evitar rate limit
                    await channel.send(message)
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = e.retry_after
                        print(f"Rate limit nas notificações. Tentando novamente em {retry_after} segundos")
                        await asyncio.sleep(retry_after)
                        await channel.send(message[:2000])  # Envia mensagem truncada se necessário
                    else:
                        print(f"Erro HTTP ao enviar notificações: {e}")
            
            if dm_notifications:
                for notification in dm_notifications:
                    await send_notification_dm(
                        bot,
                        notification['user_id'],
                        notification['boss_name'],
                        notification['sala'],
                        notification['respawn_time'],
                        notification['closed_time']
                    )
                    await asyncio.sleep(1)  # Delay entre notificações DM
            
            await asyncio.sleep(1)  # Delay antes de atualizar a tabela
            await update_table(channel)
        
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit na verificação de respawns. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
            else:
                print(f"Erro HTTP na verificação de respawns: {e}")
        except Exception as e:
            print(f"Erro na verificação de respawns: {e}")

    @tasks.loop(minutes=30)
    async def periodic_table_update():
        """Atualiza a tabela periodicamente com novo post"""
        try:
            channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel:
                # Enviar nova mensagem com a tabela atualizada
                embed = create_boss_embed()
                view = BossControlView(
                    bot, 
                    boss_timers, 
                    user_stats, 
                    user_notifications, 
                    table_message, 
                    NOTIFICATION_CHANNEL_ID,
                    update_table,
                    create_next_bosses_embed,
                    create_ranking_embed,
                    lambda: create_history_embed(bot, boss_timers),
                    lambda: create_unrecorded_embed(bot, boss_timers)
                )
                await asyncio.sleep(1)  # Delay para evitar rate limit
                await channel.send(embed=embed, view=view)
            
            # Ajustar o intervalo para um valor aleatório entre 30 e 60 minutos
            periodic_table_update.change_interval(minutes=random.randint(30, 60))
        
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit na atualização periódica. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
            else:
                print(f"Erro HTTP na atualização periódica: {e}")
        except Exception as e:
            print(f"Erro na atualização periódica: {e}")

    # Comandos Slash
    async def boss_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        bosses = list(boss_timers.keys())
        return [
            app_commands.Choice(name=boss, value=boss)
            for boss in bosses if current.lower() in boss.lower()
        ][:25]

    async def sala_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        salas = list(boss_timers[list(boss_timers.keys())[0]].keys())
        return [
            app_commands.Choice(name=f"Sala {sala}", value=sala)
            for sala in salas if current in str(sala)
        ][:25]

    @bot.tree.command(name="boss", description="Registra a morte de um boss")
    @app_commands.autocomplete(boss_name=boss_autocomplete, sala=sala_autocomplete)
    @app_commands.describe(
        boss_name="Nome do boss",
        sala="Número da sala (1-8)",
        hora_morte="Horário da morte (formato HH:MM ou HHhMM)",
        foi_ontem="Se a morte foi ontem (padrão: não)"
    )
    async def boss_slash(
        interaction: discord.Interaction,
        boss_name: str,
        sala: int,
        hora_morte: str,
        foi_ontem: bool = False
    ):
        """Registra a morte de um boss via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers)
            if full_boss_name is None:
                await interaction.response.send_message(
                    f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}",
                    ephemeral=True
                )
                return
            
            boss_name = full_boss_name
            
            if sala not in boss_timers[boss_name]:
                await interaction.response.send_message(
                    f"Sala inválida. Salas disponíveis: {', '.join(map(str, boss_timers[boss_name].keys()))}",
                    ephemeral=True
                )
                return
            
            time_parts = parse_time_input(hora_morte)
            if not time_parts:
                await interaction.response.send_message(
                    "Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)",
                    ephemeral=True
                )
                return
            
            hour, minute = time_parts
            
            if not validate_time(hour, minute):
                await interaction.response.send_message(
                    "Horário inválido. Hora deve estar entre 00-23 e minutos entre 00-59.",
                    ephemeral=True
                )
                return
            
            now = datetime.now(brazil_tz)
            death_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            if foi_ontem or death_time > now:
                death_time -= timedelta(days=1)
            
            respawn_time = death_time + timedelta(hours=8)
            recorded_by = interaction.user.name
            
            boss_timers[boss_name][sala] = {
                'death_time': death_time,
                'respawn_time': respawn_time,
                'closed_time': respawn_time + timedelta(hours=4),
                'recorded_by': recorded_by,
                'opened_notified': False
            }
            
            user_id = str(interaction.user.id)
            if user_id not in user_stats:
                user_stats[user_id] = {'count': 0, 'last_recorded': None}
            user_stats[user_id]['count'] += 1
            user_stats[user_id]['last_recorded'] = now
            
            await save_timer(boss_name, sala, death_time, respawn_time, respawn_time + timedelta(hours=4), recorded_by)
            await save_user_stats(user_id, interaction.user.name, user_stats[user_id]['count'], now)
            
            await interaction.response.send_message(
                f"✅ **{boss_name} (Sala {sala})** registrado por {recorded_by}:\n"
                f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT",
                ephemeral=False
            )
            
            # Atualiza a tabela
            embed = create_boss_embed(boss_timers)
            view = BossControlView(
                bot,
                boss_timers,
                user_stats,
                user_notifications,
                table_message,
                NOTIFICATION_CHANNEL_ID,
                update_table,
                create_next_bosses_embed,
                create_ranking_embed,
                lambda: create_history_embed(bot, boss_timers),
                lambda: create_unrecorded_embed(bot, boss_timers)
            )
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Erro no comando slash boss: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar seu comando.",
                ephemeral=True
            )

    @bot.tree.command(name="clearboss", description="Limpa o timer de um boss")
    @app_commands.autocomplete(boss_name=boss_autocomplete)
    @app_commands.describe(
        boss_name="Nome do boss",
        sala="Número da sala (opcional, deixe em branco para limpar todas)"
    )
    async def clearboss_slash(
        interaction: discord.Interaction,
        boss_name: str,
        sala: Optional[int] = None
    ):
        """Limpa o timer de um boss via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers)
            if full_boss_name is None:
                await interaction.response.send_message(
                    f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}",
                    ephemeral=True
                )
                return
            
            boss_name = full_boss_name
            
            if sala is None:
                for s in boss_timers[boss_name]:
                    boss_timers[boss_name][s] = {
                        'death_time': None,
                        'respawn_time': None,
                        'closed_time': None,
                        'recorded_by': None,
                        'opened_notified': False
                    }
                await clear_timer(boss_name)
                await interaction.response.send_message(
                    f"✅ Todos os timers do boss **{boss_name}** foram resetados.",
                    ephemeral=True
                )
            else:
                if sala not in boss_timers[boss_name]:
                    await interaction.response.send_message(
                        f"Sala inválida. Salas disponíveis: {', '.join(map(str, boss_timers[boss_name].keys()))}",
                        ephemeral=True
                    )
                    return
                
                boss_timers[boss_name][sala] = {
                    'death_time': None,
                    'respawn_time': None,
                    'closed_time': None,
                    'recorded_by': None,
                    'opened_notified': False
                }
                await clear_timer(boss_name, sala)
                await interaction.response.send_message(
                    f"✅ Timer do boss **{boss_name} (Sala {sala})** foi resetado.",
                    ephemeral=True
                )
            
            # Atualiza a tabela
            embed = create_boss_embed(boss_timers)
            view = BossControlView(
                bot,
                boss_timers,
                user_stats,
                user_notifications,
                table_message,
                NOTIFICATION_CHANNEL_ID,
                update_table,
                create_next_bosses_embed,
                create_ranking_embed,
                lambda: create_history_embed(bot, boss_timers),
                lambda: create_unrecorded_embed(bot, boss_timers)
            )
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Erro no comando slash clearboss: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar seu comando.",
                ephemeral=True
            )

    @bot.tree.command(name="nextboss", description="Mostra os próximos bosses a abrir")
    async def nextboss_slash(interaction: discord.Interaction):
        """Mostra os próximos bosses via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            embed = await create_next_bosses_embed(boss_timers)
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Erro no comando slash nextboss: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao buscar os próximos bosses.",
                ephemeral=True
            )

    @bot.tree.command(name="setupboss", description="Recria a tabela de bosses com botões de controle")
    async def setup_boss_slash(interaction: discord.Interaction):
        """Recria a tabela de bosses via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
                
            embed = create_boss_embed()
            view = BossControlView(
                bot, 
                boss_timers, 
                user_stats, 
                user_notifications, 
                table_message, 
                NOTIFICATION_CHANNEL_ID,
                update_table,
                create_next_bosses_embed,
                create_ranking_embed,
                lambda: create_history_embed(bot, boss_timers),
                lambda: create_unrecorded_embed(bot, boss_timers)
            )
            await interaction.response.send_message(embed=embed, view=view)
        
        except Exception as e:
            print(f"Erro no comando slash setupboss: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao recriar a tabela.",
                ephemeral=True
            )

    # Iniciar as tasks
    check_boss_respawns.start()
    live_table_updater.start()
    periodic_table_update.start()

    # Retornar as funções necessárias para o utility_commands.py
    return (
        create_boss_embed,
        update_table,
        create_next_bosses_embed,
        create_ranking_embed,
        lambda: create_history_embed(bot, boss_timers),
        lambda: create_unrecorded_embed(bot, boss_timers)
    )