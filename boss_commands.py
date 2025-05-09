from datetime import datetime, timedelta
import pytz
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select, Modal
from discord import TextStyle
from collections import defaultdict
import random
import traceback
import re
import json
import os
import asyncio
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
                            status = "❌"
                        else:
                            status = "✅"
                    else:
                        time_left = format_time_remaining(timers['respawn_time'])
                        status = f"🕒 ({time_left})"
                else:
                    status = "❌"
                
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
                            
                            # Manter apenas o horário da morte para histórico
                            boss_timers[boss][sala]['respawn_time'] = None
                            boss_timers[boss][sala]['closed_time'] = None
                            boss_timers[boss][sala]['opened_notified'] = False
                            await save_timer(boss, sala, timers['death_time'], None, None, timers['recorded_by'], False)

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

    # Comandos
    @bot.command(name='boss')
    async def boss_command(ctx, boss_name: str = None, sala: int = None, hora_morte: str = None):
        """Registra a morte de um boss"""
        try:
            if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
                await asyncio.sleep(1)  # Delay para evitar rate limit
                await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", delete_after=10)
                return

            if boss_name is None or sala is None or hora_morte is None:
                await asyncio.sleep(1)  # Delay para evitar rate limit
                await ctx.send(
                    "Por favor, use: `!boss <nome_do_boss> <sala> HH:MM`\n"
                    "Exemplo: `!boss Hydra 8 14:30`\n"
                    "Abreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno\n"
                    "Formatos de hora aceitos: HH:MM ou HHhMM",
                    delete_after=30
                )
                return
            
            if sala not in boss_timers.get(list(boss_timers.keys())[0], {}).keys():
                await asyncio.sleep(1)  # Delay para evitar rate limit
                await ctx.send(
                    f"Sala inválida. Salas disponíveis: {', '.join(map(str, boss_timers.get(list(boss_timers.keys())[0], {}).keys()))}",
                    delete_after=20
                )
                return

            full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers)
            if full_boss_name is None:
                await asyncio.sleep(1)  # Delay para evitar rate limit
                await ctx.send(
                    f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\n"
                    "Abreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                    delete_after=30
                )
                return
            
            boss_name = full_boss_name
            
            try:
                time_parts = parse_time_input(hora_morte)
                if not time_parts:
                    await asyncio.sleep(1)  # Delay para evitar rate limit
                    await ctx.send(
                        "Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)",
                        delete_after=20
                    )
                    return
                
                hour, minute = time_parts
                
                if not validate_time(hour, minute):
                    await asyncio.sleep(1)  # Delay para evitar rate limit
                    await ctx.send(
                        "Horário inválido. Hora deve estar entre 00-23 e minutos entre 00-59.",
                        delete_after=20
                    )
                    return
                
                now = datetime.now(brazil_tz)
                death_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                if death_time > now:
                    death_time -= timedelta(days=1)
                
                respawn_time = death_time + timedelta(hours=8)
                recorded_by = ctx.author.name
                
                boss_timers[boss_name][sala] = {
                    'death_time': death_time,
                    'respawn_time': respawn_time,
                    'closed_time': respawn_time + timedelta(hours=4),
                    'recorded_by': recorded_by,
                    'opened_notified': False
                }
                
                user_id = str(ctx.author.id)
                if user_id not in user_stats:
                    user_stats[user_id] = {'count': 0, 'last_recorded': None}
                user_stats[user_id]['count'] += 1
                user_stats[user_id]['last_recorded'] = now
                
                await save_timer(boss_name, sala, death_time, respawn_time, respawn_time + timedelta(hours=4), recorded_by)
                await save_user_stats(user_id, ctx.author.name, user_stats[user_id]['count'], now)
                
                await asyncio.sleep(1)  # Delay para evitar rate limit
                await ctx.send(
                    f"✅ **{boss_name} (Sala {sala})** registrado por {recorded_by}:\n"
                    f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT",
                    delete_after=60
                )
                
                # Enviar a tabela atualizada com delay
                await asyncio.sleep(2)
                await bosses_command(ctx)
                    
            except ValueError:
                await asyncio.sleep(1)  # Delay para evitar rate limit
                await ctx.send(
                    "Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)",
                    delete_after=20
                )
        
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit atingido. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
                await boss_command(ctx, boss_name, sala, hora_morte)
            else:
                print(f"Erro HTTP no comando boss: {e}")
                traceback.print_exc()
        except Exception as e:
            print(f"Erro no comando boss: {e}")
            traceback.print_exc()

    @bot.command(name='bosses')
    async def bosses_command(ctx, mode: str = None):
        """Mostra a tabela de timers de boss"""
        try:
            if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
                await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return
            
            compact = mode and mode.lower() in ['compact', 'c', 'resumo']
            embed = create_boss_embed(compact=compact)
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
            await ctx.send(embed=embed, view=view)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit no comando bosses. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
                await bosses_command(ctx, mode)
            else:
                print(f"Erro HTTP no comando bosses: {e}")
        except Exception as e:
            print(f"Erro no comando bosses: {e}")

    @bot.command(name='nextboss')
    async def next_boss_command(ctx):
        """Mostra os próximos bosses a abrir"""
        try:
            if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
                await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return
            
            embed = await create_next_bosses_embed(boss_timers)
            await ctx.send(embed=embed)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit no comando nextboss. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
                await next_boss_command(ctx)
            else:
                print(f"Erro HTTP no comando nextboss: {e}")
        except Exception as e:
            print(f"Erro no comando nextboss: {e}")

    @bot.command(name='clearboss')
    async def clear_boss(ctx, boss_name: str, sala: int = None):
        """Limpa o timer de um boss"""
        try:
            if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
                await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return
            
            full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers)
            if full_boss_name is None:
                await ctx.send(
                    f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
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
                await ctx.send(f"✅ Todos os timers do boss **{boss_name}** foram resetados.", ephemeral=True)
            else:
                if sala not in boss_timers[boss_name]:
                    await ctx.send(
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
                await ctx.send(f"✅ Timer do boss **{boss_name} (Sala {sala})** foi resetado.", ephemeral=True)
            
            # Enviar a tabela atualizada
            await asyncio.sleep(1)
            await bosses_command(ctx)
        
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit no comando clearboss. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
                await clear_boss(ctx, boss_name, sala)
            else:
                print(f"Erro HTTP no comando clearboss: {e}")
        except Exception as e:
            print(f"Erro no comando clearboss: {e}")

    @bot.command(name='setupboss')
    async def setup_boss(ctx):
        """Recria a tabela de bosses com botões de controle"""
        try:
            if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
                await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
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
            await ctx.send(embed=embed, view=view)
        
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit no comando setupboss. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
                await setup_boss(ctx)
            else:
                print(f"Erro HTTP no comando setupboss: {e}")
        except Exception as e:
            print(f"Erro no comando setupboss: {e}")

    @bot.command(name='resettable')
    async def reset_table(ctx):
        """Reseta a referência da tabela principal"""
        try:
            if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
                return
            
            global table_message
            table_message = None
            await update_table(ctx.channel)
            await ctx.send("✅ Tabela recriada com sucesso!", delete_after=5)
        
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after
                print(f"Rate limit no comando resettable. Tentando novamente em {retry_after} segundos")
                await asyncio.sleep(retry_after)
                await reset_table(ctx)
            else:
                print(f"Erro HTTP no comando resettable: {e}")
        except Exception as e:
            print(f"Erro no comando resettable: {e}")

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