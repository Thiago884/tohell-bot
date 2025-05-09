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
            await user.send(
                f"🔔 **Notificação de Boss** 🔔\n"
                f"O boss **{boss_name} (Sala {sala})** que você marcou está disponível AGORA!\n"
                f"✅ Aberto até: {closed_time.strftime('%d/%m %H:%M')} BRT\n"
                f"Corra para pegar seu loot! 🏆"
            )
            return True
    except discord.Forbidden:
        print(f"Usuário {user_id} bloqueou DMs ou não aceita mensagens")
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
                
                # Mostra apenas se houver registro de morte
                if timers['death_time'] is None:
                    continue
                    
                death_time = timers['death_time'].strftime("%d/%m %H:%M") if timers['death_time'] else "--/-- --:--"
                respawn_time = timers['respawn_time'].strftime("%H:%M") if timers['respawn_time'] else "--:--"
                closed_time = timers['closed_time'].strftime("%H:%M") if timers['closed_time'] else "--:--"
                recorded_by = f" ({timers['recorded_by']})" if timers['recorded_by'] else ""
                
                status = "✅" if (timers['respawn_time'] and now >= timers['respawn_time'] and 
                                timers['closed_time'] and now < timers['closed_time']) else "❌"
                
                boss_info.append(
                    f"Sala {sala}: {death_time} [de {respawn_time} até {closed_time}] {status}{recorded_by}"
                )
            
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
                    await table_message.edit(embed=embed, view=view)
                    return
                except discord.NotFound:
                    table_message = None
                except Exception as e:
                    print(f"Erro ao editar mensagem da tabela: {e}")
                    table_message = None
            
            if not table_message:
                async for message in channel.history(limit=50):
                    if message.author == bot.user and message.embeds and "BOSS TIMER" in message.embeds[0].title:
                        try:
                            await message.edit(embed=embed, view=view)
                            table_message = message
                            return
                        except:
                            continue
            
            table_message = await channel.send(embed=embed, view=view)
        except Exception as e:
            print(f"Erro ao atualizar tabela: {e}")
            try:
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
    @tasks.loop(seconds=30)
    async def live_table_updater():
        """Atualiza a tabela periodicamente"""
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            await update_table(channel)

    @tasks.loop(minutes=1)
    async def check_boss_respawns():
        """Verifica os respawns de boss e envia notificações"""
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
            await channel.send(message)
        
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
        
        await update_table(channel)

    @tasks.loop(minutes=30)
    async def periodic_table_update():
        """Atualiza a tabela periodicamente com novo post"""
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
            await channel.send(embed=embed, view=view)
        
        # Ajustar o intervalo para um valor aleatório entre 30 e 60 minutos
        periodic_table_update.change_interval(minutes=random.randint(30, 60))

    # Comandos
    @bot.command(name='boss')
    async def boss_command(ctx, boss_name: str = None, sala: int = None, *, hora_morte: str = None):
        """Registra a morte de um boss"""
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return

        if boss_name is None or sala is None or hora_morte is None:
            await ctx.send("Por favor, use: `!boss <nome_do_boss> <sala> HH:MM`\nExemplo: `!boss Hydra 8 14:30`\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno\nFormatos de hora aceitos: HH:MM ou HHhMM")
            return
        
        if sala not in boss_timers.get(list(boss_timers.keys())[0], {}).keys():
            await ctx.send(f"Sala inválida. Salas disponíveis: {', '.join(map(str, boss_timers.get(list(boss_timers.keys())[0], {}).keys()))}")
            return

        full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers)
        if full_boss_name is None:
            await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
            return
        
        boss_name = full_boss_name
        
        try:
            time_parts = parse_time_input(hora_morte)
            if not time_parts:
                await ctx.send("Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)")
                return
            
            hour, minute = time_parts
            
            if not validate_time(hour, minute):
                await ctx.send("Horário inválido. Hora deve estar entre 00-23 e minutos entre 00-59.")
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
            
            await ctx.send(
                f"✅ **{boss_name} (Sala {sala})** registrado por {recorded_by}:\n"
                f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT"
            )
            
            # Enviar a tabela atualizada
            await update_table(ctx.channel)
                
        except ValueError:
            await ctx.send("Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)")

    @bot.command(name='bosses')
    async def bosses_command(ctx, mode: str = None):
        """Mostra a tabela de timers de boss"""
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
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

    @bot.command(name='nextboss')
    async def next_boss_command(ctx):
        """Mostra os próximos bosses a abrir"""
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        embed = await create_next_bosses_embed(boss_timers)
        await ctx.send(embed=embed)

    @bot.command(name='clearboss')
    async def clear_boss(ctx, boss_name: str, sala: int = None):
        """Limpa o timer de um boss"""
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers)
        if full_boss_name is None:
            await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
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
            await ctx.send(f"✅ Todos os timers do boss **{boss_name}** foram resetados.")
        else:
            if sala not in boss_timers[boss_name]:
                await ctx.send(f"Sala inválida. Salas disponíveis: {', '.join(map(str, boss_timers[boss_name].keys()))}")
                return
            
            boss_timers[boss_name][sala] = {
                'death_time': None,
                'respawn_time': None,
                'closed_time': None,
                'recorded_by': None,
                'opened_notified': False
            }
            await clear_timer(boss_name, sala)
            await ctx.send(f"✅ Timer do boss **{boss_name} (Sala {sala})** foi resetado.")
        
        # Enviar a tabela atualizada
        await update_table(ctx.channel)

    @bot.command(name='setupboss')
    async def setup_boss(ctx):
        """Recria a tabela de bosses com botões de controle"""
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
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

    @bot.command(name='resettable')
    async def reset_table(ctx):
        """Reseta a referência da tabela principal"""
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            return
        
        global table_message
        table_message = None
        await update_table(ctx.channel)
        await ctx.send("✅ Tabela recriada com sucesso!", delete_after=5)

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