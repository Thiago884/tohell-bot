from datetime import datetime, timedelta
import pytz
import discord
from discord.ext import commands, tasks
from typing import Optional, Dict, List, Any
import asyncio
from database import save_timer, save_user_stats, clear_timer
from shared_functions import get_boss_by_abbreviation, format_time_remaining, get_next_bosses
from utility_commands import create_unrecorded_embed
from views import BossControlView
import random

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

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

async def create_boss_embed(boss_timers: Dict, compact: bool = False) -> discord.Embed:
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

async def create_next_bosses_embed(boss_timers: Dict) -> discord.Embed:
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

async def create_ranking_embed(bot, user_stats: Dict) -> discord.Embed:
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

async def update_table(bot, channel, boss_timers: Dict, user_stats: Dict, 
                      user_notifications: Dict, table_message: discord.Message, 
                      NOTIFICATION_CHANNEL_ID: int):
    """Atualiza a mensagem da tabela de bosses"""
    try:
        embed = await create_boss_embed(boss_timers)
        view = BossControlView(
            bot, 
            boss_timers, 
            user_stats, 
            user_notifications, 
            table_message, 
            NOTIFICATION_CHANNEL_ID,
            lambda: update_table(bot, channel, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID),
            lambda: create_next_bosses_embed(boss_timers),
            lambda: create_ranking_embed(bot, user_stats),
            lambda: create_history_embed(bot, boss_timers),
            lambda: create_unrecorded_embed(bot, boss_timers)
        )
        
        if table_message:
            try:
                await asyncio.sleep(1)  # Delay para evitar rate limit
                await table_message.edit(embed=embed, view=view)
                return table_message
            except discord.NotFound:
                table_message = None
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = e.retry_after
                    print(f"Rate limit ao editar tabela. Tentando novamente em {retry_after} segundos")
                    await asyncio.sleep(retry_after)
                    return await update_table(bot, channel, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID)
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
                        return message
                    except:
                        continue
        
        await asyncio.sleep(1)  # Delay para evitar rate limit
        table_message = await channel.send(embed=embed, view=view)
        return table_message
    except discord.HTTPException as e:
        if e.status == 429:
            retry_after = e.retry_after
            print(f"Rate limit ao enviar tabela. Tentando novamente em {retry_after} segundos")
            await asyncio.sleep(retry_after)
            return await update_table(bot, channel, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID)
        else:
            print(f"Erro HTTP ao atualizar tabela: {e}")
    except Exception as e:
        print(f"Erro ao atualizar tabela: {e}")
        try:
            await asyncio.sleep(1)
            table_message = await channel.send(embed=await create_boss_embed(boss_timers), view=BossControlView(
                bot, 
                boss_timers, 
                user_stats, 
                user_notifications, 
                table_message, 
                NOTIFICATION_CHANNEL_ID,
                lambda: update_table(bot, channel, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID),
                lambda: create_next_bosses_embed(boss_timers),
                lambda: create_ranking_embed(bot, user_stats),
                lambda: create_history_embed(bot, boss_timers),
                lambda: create_unrecorded_embed(bot, boss_timers)
            ))
            return table_message
        except Exception as e:
            print(f"Erro ao enviar nova mensagem de tabela: {e}")
    
    return table_message

async def check_boss_respawns(bot, boss_timers: Dict, user_notifications: Dict, 
                             NOTIFICATION_CHANNEL_ID: int, update_table_func):
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
        await update_table_func()
    
    except discord.HTTPException as e:
        if e.status == 429:
            retry_after = e.retry_after
            print(f"Rate limit na verificação de respawns. Tentando novamente em {retry_after} segundos")
            await asyncio.sleep(retry_after)
        else:
            print(f"Erro HTTP na verificação de respawns: {e}")
    except Exception as e:
        print(f"Erro na verificação de respawns: {e}")

async def setup_boss_commands(bot, boss_timers: Dict, user_stats: Dict, 
                            user_notifications: Dict, table_message: discord.Message, 
                            NOTIFICATION_CHANNEL_ID: int):
    """Configura todas as funcionalidades relacionadas a bosses"""
    
    # Tasks
    @tasks.loop(seconds=60)
    async def live_table_updater():
        """Atualiza a tabela periodicamente"""
        try:
            channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel:
                nonlocal table_message
                table_message = await update_table(
                    bot, channel, boss_timers, user_stats, 
                    user_notifications, table_message, NOTIFICATION_CHANNEL_ID
                )
        except Exception as e:
            print(f"Erro na task de atualização de tabela: {e}")

    @tasks.loop(minutes=1)
    async def check_boss_respawns_task():
        """Task para verificar respawns de bosses"""
        await check_boss_respawns(
            bot, boss_timers, user_notifications, 
            NOTIFICATION_CHANNEL_ID,
            lambda: update_table(
                bot, bot.get_channel(NOTIFICATION_CHANNEL_ID), 
                boss_timers, user_stats, user_notifications, 
                table_message, NOTIFICATION_CHANNEL_ID
            )
        )

    @tasks.loop(minutes=30)
    async def periodic_table_update():
        """Atualiza a tabela periodicamente com novo post"""
        try:
            channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel:
                nonlocal table_message
                table_message = await update_table(
                    bot, channel, boss_timers, user_stats, 
                    user_notifications, table_message, NOTIFICATION_CHANNEL_ID
                )
            
            # Ajustar o intervalo para um valor aleatório entre 30 e 60 minutos
            periodic_table_update.change_interval(minutes=random.randint(30, 60))
        
        except Exception as e:
            print(f"Erro na atualização periódica: {e}")

    # Iniciar as tasks
    check_boss_respawns_task.start()
    live_table_updater.start()
    periodic_table_update.start()

    # Retornar as funções necessárias para outros módulos
    return (
        lambda: create_boss_embed(boss_timers),
        lambda channel: update_table(bot, channel, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID),
        lambda: create_next_bosses_embed(boss_timers),
        lambda: create_ranking_embed(bot, user_stats),
        lambda: create_history_embed(bot, boss_timers),
        lambda: create_unrecorded_embed(bot, boss_timers)
    )