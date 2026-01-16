# boss_commands.py
from datetime import datetime, timedelta
import pytz
import discord
from discord.ext import commands, tasks
from typing import Optional, Dict, List, Any
import asyncio
from database import save_timer, save_user_stats, clear_timer, get_all_server_configs, get_server_config
from shared_functions import get_boss_by_abbreviation, format_time_remaining, get_next_bosses
from utility_commands import create_unrecorded_embed, create_history_embed
from views import BossControlView
import random
import traceback
import logging

# Configuração do logger
logger = logging.getLogger(__name__)

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

def create_boss_embed(boss_timers: Dict, compact: bool = False) -> discord.Embed:
    """Cria embed com a tabela de timers de boss (Versão com Timestamp Dinâmico)"""
    now = datetime.now(brazil_tz)
    
    # Verificar se boss_timers é um dicionário por servidor ou estrutura errada
    if not boss_timers:
        embed = discord.Embed(
            title=f"BOSS TIMER - {now.strftime('%d/%m/%Y %H:%M')} BRT",
            description="Nenhum boss registrado ainda.",
            color=discord.Color.gold()
        )
        return embed
    
    # Verificar estrutura do dicionário para evitar erro de multi-guild na função errada
    if isinstance(boss_timers, dict) and boss_timers:
        first_key = next(iter(boss_timers))
        is_multi_guild = isinstance(first_key, int)  # Se a chave é um ID de guild
        
        if is_multi_guild:
            embed = discord.Embed(
                title="Erro",
                description="Dados em formato incorreto para esta função",
                color=discord.Color.red()
            )
            return embed
    
    embed = discord.Embed(
        title=f"BOSS TIMER - {now.strftime('%d/%m/%Y %H:%M')} BRT",
        description="Os horários abaixo atualizam automaticamente ⏳",
        color=discord.Color.gold()
    )
    
    # Lista de bosses na ordem desejada
    boss_order = [
        "Hydra", "Phoenix of Darkness", "Genocider", "Death Beam Knight",
        "Hell Maine", "Super Red Dragon", "Illusion of Kundun", 
        "Rei Kundun", "Erohim"
    ]
    
    for boss in boss_order:
        if boss not in boss_timers:
            continue  # Pular bosses que não existem nesta instância
            
        boss_info = []
        # Ordenar salas numericamente
        salas_ordenadas = sorted(boss_timers[boss].keys())
        
        for sala in salas_ordenadas:
            timers = boss_timers[boss][sala]
            
            # Formatar os horários
            death_time_str = timers['death_time'].strftime("%d/%m %H:%M") if timers['death_time'] else "--/-- --:--"
            respawn_time_str = timers['respawn_time'].strftime("%H:%M") if timers['respawn_time'] else "--:--"
            closed_time_str = timers['closed_time'].strftime("%H:%M") if timers['closed_time'] else "--:--"
            recorded_by = f" ({timers['recorded_by']})" if timers['recorded_by'] else ""
            
            # Determinar status
            status = "❌"  # Padrão: fechado/sem registro
            
            if timers['respawn_time']:
                # Conversão para Timestamp UNIX
                ts_respawn = int(timers['respawn_time'].timestamp())
                ts_closed = int(timers['closed_time'].timestamp()) if timers['closed_time'] else 0

                if now >= timers['respawn_time']:
                    if timers['closed_time'] and now >= timers['closed_time']:
                        status = "❌"  # Boss fechado
                    else:
                        # Boss aberto: mostra countdown para fechar
                        status = f"✅ Fecha <t:{ts_closed}:R>" 
                else:
                    # Boss agendado: mostra countdown para nascer
                    time_left = format_time_remaining(timers['respawn_time']) # fallback se necessário
                    status = f"🕒 <t:{ts_respawn}:R>"
            
            boss_info.append(
                f"Sala {sala}: {death_time_str} [{respawn_time_str} - {closed_time_str}] {status}{recorded_by}"
            )
        
        # Sempre adicionar o campo do boss, mesmo sem informações
        embed.add_field(
            name=f"**{boss}**",
            value="\n".join(boss_info) if boss_info else "Nenhum horário registrado",
            inline=False
        )
    
    return embed

def create_next_bosses_embed(boss_timers: Dict) -> discord.Embed:
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

def create_ranking_embed(user_stats: Dict) -> discord.Embed:
    """Cria embed com o ranking de usuários que mais registraram bosses (FUNÇÃO SÍNCRONA)"""
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
        # Usamos o username salvo em vez de buscar via API (para ser síncrono)
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
        # Verifica se o canal existe e temos permissão
        if not channel:
            return None
            
        logger.info("Iniciando atualização da tabela de bosses...")
        embed = create_boss_embed(boss_timers)
        view = BossControlView(
            bot, 
            boss_timers, 
            user_stats, 
            user_notifications, 
            table_message, 
            NOTIFICATION_CHANNEL_ID,
            lambda: update_table(bot, channel, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID),
            lambda boss_timers=boss_timers: create_next_bosses_embed(boss_timers),
            lambda: create_ranking_embed(user_stats),
            lambda: create_history_embed(bot, boss_timers),
            lambda: create_unrecorded_embed(bot, boss_timers)
        )
        
        # Se não temos mensagem de tabela, envia uma nova
        if table_message is None:
            logger.info("Nenhuma tabela existente encontrada, enviando nova...")
            try:
                table_message = await channel.send(embed=embed, view=view)
                logger.info("✅ Nova tabela enviada com sucesso!")
                return table_message
            except Exception as e:
                logger.error(f"❌ Erro ao enviar nova tabela: {e}")
                return None
        
        # Tenta editar a mensagem existente
        try:
            await table_message.edit(embed=embed, view=view)
            logger.info("✅ Tabela existente atualizada com sucesso!")
            return table_message
        except discord.NotFound:
            logger.warning("⚠ Tabela anterior não encontrada, enviando nova...")
            table_message = await channel.send(embed=embed, view=view)
            return table_message
        except Exception as e:
            logger.error(f"❌ Erro ao editar tabela existente: {e}")
            return table_message
            
    except Exception as e:
        logger.error(f"❌ Erro crítico na atualização da tabela: {e}", exc_info=True)
        return table_message

async def check_boss_respawns_single_server(bot, boss_timers: Dict, user_notifications: Dict, 
                                          guild_id: int, update_table_func):
    """Verifica os respawns de boss para um servidor específico - CORRIGIDO"""
    try:
        # Busca configuração do servidor
        config = await get_server_config(guild_id)
        if not config or not config.get('notification_channel_id'):
            return
            
        channel = bot.get_channel(config['notification_channel_id'])
        if channel is None:
            logger.error(f"Canal com ID {config['notification_channel_id']} não encontrado para servidor {guild_id}!")
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
                    # CORREÇÃO: Lógica estrita (now < closed_time)
                    if now >= respawn_time and closed_time is not None and now < closed_time:
                        if not timers.get('opened_notified', False):
                            recorded_by = f"\nAnotado por: {timers['recorded_by']}" if timers['recorded_by'] else ""
                            notifications.append(f"🟢 **{boss} (Sala {sala})** está disponível AGORA! (aberto até {closed_time:%d/%m %H:%M} BRT){recorded_by}")
                            
                            boss_timers[boss][sala]['opened_notified'] = True
                            
                            await save_timer(guild_id, boss, sala, timers['death_time'], respawn_time, closed_time, timers['recorded_by'], True)
                            
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
                    # CORREÇÃO: Lógica estrita (now >= closed_time) e flag de controle (closed_processed)
                    if closed_time is not None and now >= closed_time:
                        # Verifica se estamos na janela de 120 segundos após o fechamento para enviar a notificação
                        if (now - closed_time).total_seconds() < 120:
                            # Se ainda não processamos o fechamento em memória
                            if not timers.get('closed_processed', False):
                                message = f"🔴 **{boss} (Sala {sala})** FECHOU"
                                if not timers.get('opened_notified', False):
                                    message += " sem nenhuma anotação durante o período aberto!"
                                else:
                                    message += "!"

                                notifications.append(message)
                                
                                # Atualiza flags em memória
                                boss_timers[boss][sala]['opened_notified'] = False
                                boss_timers[boss][sala]['closed_processed'] = True # Impede spam no próximo loop

                                # Atualiza no banco definindo opened_notified = False (para histórico/reinicialização)
                                await save_timer(
                                    guild_id,
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
                    logger.warning(f"Rate limit nas notificações para servidor {guild_id}. Tentando novamente em {retry_after} segundos")
                    await asyncio.sleep(retry_after)
                    await channel.send(message[:2000])  # Envia mensagem truncada se necessário
                else:
                    logger.error(f"Erro HTTP ao enviar notificações para servidor {guild_id}: {e}")
        
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
        # Atualiza a tabela se tiver função de callback
        if update_table_func:
            await update_table_func()
    
    except discord.HTTPException as e:
        if e.status == 429:
            retry_after = e.retry_after
            logger.warning(f"Rate limit na verificação de respawns para servidor {guild_id}. Tentando novamente em {retry_after} segundos")
            await asyncio.sleep(retry_after)
        else:
            logger.error(f"Erro HTTP na verificação de respawns para servidor {guild_id}: {e}")
    except Exception as e:
        logger.error(f"Erro na verificação de respawns para servidor {guild_id}: {e}", exc_info=True)

async def setup_boss_commands(bot, boss_timers: Dict, user_stats: Dict, 
                            user_notifications: Dict, table_message: discord.Message, 
                            NOTIFICATION_CHANNEL_ID: int):
    """Configura todas as funcionalidades relacionadas a bosses"""
    
    # Verifica se a tabela já foi enviada (Modo Legacy)
    if table_message is None and NOTIFICATION_CHANNEL_ID != 0:
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            table_message = await update_table(
                bot, channel, boss_timers, 
                user_stats, user_notifications, 
                table_message, NOTIFICATION_CHANNEL_ID
            )
    
    # Tasks para servidor específico (mantidas para compatibilidade)
    @tasks.loop(seconds=60)
    async def live_table_updater_legacy():
        """Atualiza a tabela periodicamente para servidor específico"""
        try:
            if NOTIFICATION_CHANNEL_ID == 0: return
            
            channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel:
                nonlocal table_message
                table_message = await update_table(
                    bot, channel, boss_timers, user_stats, 
                    user_notifications, table_message, NOTIFICATION_CHANNEL_ID
                )
        except Exception as e:
            logger.error(f"Erro na task de atualização de tabela (legacy): {e}", exc_info=True)

    @tasks.loop(minutes=1)
    async def check_boss_respawns_task_legacy():
        """Task para verificar respawns de bosses para servidor específico"""
        if NOTIFICATION_CHANNEL_ID == 0: return
        
        await check_boss_respawns_single_server(
            bot, boss_timers, user_notifications, 
            0,  # guild_id placeholder
            lambda: update_table(
                bot, bot.get_channel(NOTIFICATION_CHANNEL_ID), 
                boss_timers, user_stats, user_notifications, 
                table_message, NOTIFICATION_CHANNEL_ID
            )
        )

    @tasks.loop(minutes=60)  # ALTERADO: De 30 para 60 minutos inicial
    async def periodic_table_update_legacy():
        """Atualiza a tabela periodicamente com novo post para servidor específico"""
        try:
            if NOTIFICATION_CHANNEL_ID == 0: return

            logger.info("\nIniciando atualização periódica da tabela (legacy)...")
            channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel:
                logger.info(f"Canal encontrado: {channel.name}")
                nonlocal table_message
                table_message = None  # Força o envio de uma nova mensagem
                table_message = await update_table(
                    bot, channel, boss_timers, user_stats, 
                    user_notifications, table_message, NOTIFICATION_CHANNEL_ID
                )
                logger.info("✅ Tabela atualizada com sucesso!")
            
            # ALTERADO: Define um novo intervalo aleatório entre 60 e 240 minutos
            new_interval = random.randint(60, 240)  # De 30-60 para 60-240
            logger.info(f"Próxima atualização em {new_interval} minutos")
            periodic_table_update_legacy.change_interval(minutes=new_interval)
        
        except Exception as e:
            logger.error(f"Erro na atualização periódica (legacy): {e}", exc_info=True)
            periodic_table_update_legacy.change_interval(minutes=30)

    # Task de Atualização em Tempo Real para TODOS os servidores (NOVO)
    @tasks.loop(seconds=60)
    async def live_table_updater_multi():
        """Atualiza as tabelas de TODOS os servidores periodicamente"""
        try:
            # Busca configs de TODOS os servidores
            all_configs = await get_all_server_configs()
            
            for config in all_configs:
                guild_id = config['guild_id']
                channel_id = config['table_channel_id']
                msg_id = config['table_message_id']
                
                # Pega dados deste servidor
                server_data = boss_timers.get(guild_id, {})
                
                try:
                    channel = bot.get_channel(channel_id)
                    if channel and msg_id:
                        msg = await channel.fetch_message(msg_id)
                        embed = create_boss_embed(server_data)
                        
                        # Cria view com dados do servidor específico
                        server_user_stats = user_stats.get(guild_id, {})
                        server_user_notifications = user_notifications.get(guild_id, {})
                        
                        view = BossControlView(
                            bot,
                            server_data,
                            server_user_stats,
                            server_user_notifications,
                            msg,
                            channel_id,
                            lambda: None,  # Placeholder para update_table_func
                            lambda boss_timers=server_data: create_next_bosses_embed(boss_timers),
                            lambda: create_ranking_embed(server_user_stats),
                            lambda: create_history_embed(bot, server_data),
                            lambda: create_unrecorded_embed(bot, server_data)
                        )
                        
                        await msg.edit(embed=embed, view=view)
                        
                except discord.NotFound:
                    logger.warning(f"Mensagem da tabela não encontrada para servidor {guild_id}")
                except discord.Forbidden:
                    logger.warning(f"Sem permissões para editar mensagem no servidor {guild_id}")
                except Exception as e:
                    logger.error(f"Erro ao atualizar tabela do servidor {guild_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Erro na task de atualização multi-servidor: {e}", exc_info=True)

    # Task de Checagem de Respawns para TODOS os servidores (NOVO)
    @tasks.loop(seconds=30)
    async def check_boss_respawns_task_multi():
        """Verifica respawns de bosses para TODOS os servidores"""
        try:
            # Itera sobre TODOS os servidores carregados na memória
            for guild_id, server_timers in boss_timers.items():
                if not server_timers:
                    continue
                    
                # Pega notificações deste servidor
                server_user_notifications = user_notifications.get(guild_id, {})
                
                # Função de callback para atualizar tabela deste servidor
                async def update_table_for_guild():
                    config = await get_server_config(guild_id)
                    if not config or not config.get('table_channel_id') or not config.get('table_message_id'):
                        return
                    
                    try:
                        channel = bot.get_channel(config['table_channel_id'])
                        if channel:
                            msg = await channel.fetch_message(config['table_message_id'])
                            server_user_stats = user_stats.get(guild_id, {})
                            
                            embed = create_boss_embed(server_timers)
                            view = BossControlView(
                                bot,
                                server_timers,
                                server_user_stats,
                                server_user_notifications,
                                msg,
                                config['table_channel_id'],
                                lambda: None,
                                lambda boss_timers=server_timers: create_next_bosses_embed(boss_timers),
                                lambda: create_ranking_embed(server_user_stats),
                                lambda: create_history_embed(bot, server_timers),
                                lambda: create_unrecorded_embed(bot, server_timers)
                            )
                            
                            await msg.edit(embed=embed, view=view)
                    except Exception as e:
                        logger.error(f"Erro ao atualizar tabela do servidor {guild_id} no callback: {e}")
                
                # Executa verificação para este servidor
                await check_boss_respawns_single_server(
                    bot, 
                    server_timers, 
                    server_user_notifications, 
                    guild_id, 
                    update_table_for_guild
                )
                
                # Pequeno delay entre servidores para evitar rate limit
                await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Erro na task de verificação multi-servidor: {e}", exc_info=True)

    # Task de Atualização Periódica para TODOS os servidores (NOVO)
    @tasks.loop(minutes=60)  # ALTERADO: De 30 para 60 minutos inicial
    async def periodic_table_update_multi():
        """Atualiza tabelas periodicamente com novo post para TODOS os servidores"""
        try:
            logger.info("\nIniciando atualização periódica das tabelas (multi-servidor)...")
            
            # Busca configs de TODOS os servidores
            all_configs = await get_all_server_configs()
            
            for config in all_configs:
                guild_id = config['guild_id']
                channel_id = config['table_channel_id']
                
                if not channel_id:
                    continue
                    
                try:
                    channel = bot.get_channel(channel_id)
                    if not channel:
                        logger.warning(f"Canal {channel_id} não encontrado para servidor {guild_id}")
                        continue
                    
                    # Pega dados deste servidor
                    server_data = boss_timers.get(guild_id, {})
                    server_user_stats = user_stats.get(guild_id, {})
                    server_user_notifications = user_notifications.get(guild_id, {})
                    
                    # Envia nova mensagem
                    embed = create_boss_embed(server_data)
                    view = BossControlView(
                        bot,
                        server_data,
                        server_user_stats,
                        server_user_notifications,
                        None,
                        channel_id,
                        lambda: None,
                        lambda boss_timers=server_data: create_next_bosses_embed(boss_timers),
                        lambda: create_ranking_embed(server_user_stats),
                        lambda: create_history_embed(bot, server_data),
                        lambda: create_unrecorded_embed(bot, server_data)
                    )
                    
                    new_msg = await channel.send(embed=embed, view=view)
                    
                    # Atualiza config no banco com nova mensagem
                    from database import set_server_config
                    await set_server_config(
                        guild_id,
                        config.get('notification_channel_id', channel_id),
                        channel_id,
                        new_msg.id
                    )
                    
                    logger.info(f"✅ Nova tabela enviada para servidor {guild_id}")
                    
                except Exception as e:
                    logger.error(f"Erro ao atualizar tabela do servidor {guild_id}: {e}")
                    # Continua para o próximo servidor
            
            # ALTERADO: Define um novo intervalo aleatório entre 60 e 240 minutos
            new_interval = random.randint(60, 240)  # De 30-60 para 60-240
            logger.info(f"Próxima atualização em {new_interval} minutos")
            periodic_table_update_multi.change_interval(minutes=new_interval)
            
        except Exception as e:
            logger.error(f"Erro na atualização periódica multi-servidor: {e}", exc_info=True)
            # Tenta novamente em 30 minutos se falhar
            periodic_table_update_multi.change_interval(minutes=30)

    # Iniciar as tasks MULTI-SERVIDOR
    live_table_updater_multi.start()
    check_boss_respawns_task_multi.start()
    periodic_table_update_multi.start()

    # Iniciar as tasks LEGACY (para compatibilidade, apenas se ID configurado)
    if NOTIFICATION_CHANNEL_ID != 0:
        check_boss_respawns_task_legacy.start()
        live_table_updater_legacy.start()
        periodic_table_update_legacy.start()

    # Função para cancelar tasks
    async def shutdown_tasks():
        """Cancela todas as tasks do módulo"""
        try:
            # Cancela tasks legacy
            check_boss_respawns_task_legacy.cancel()
            live_table_updater_legacy.cancel()
            periodic_table_update_legacy.cancel()
            
            # Cancela tasks multi-servidor
            live_table_updater_multi.cancel()
            check_boss_respawns_task_multi.cancel()
            periodic_table_update_multi.cancel()
            
            # Aguarda as tasks serem realmente canceladas
            await asyncio.gather(
                check_boss_respawns_task_legacy,
                live_table_updater_legacy,
                periodic_table_update_legacy,
                live_table_updater_multi,
                check_boss_respawns_task_multi,
                periodic_table_update_multi,
                return_exceptions=True
            )
            logger.info("Todas as tasks foram canceladas com sucesso")
        except Exception as e:
            logger.error(f"Erro ao cancelar tasks: {e}", exc_info=True)

    # Adiciona a função de shutdown ao bot para ser chamada no desligamento
    bot.boss_commands_shutdown = shutdown_tasks

    # Função de update_table para multi-servidor (NOVA)
    async def update_table_multi(channel, guild_id=None):
        """Atualiza a tabela em um canal específico para um servidor específico"""
        if not guild_id:
            return
            
        server_timers = boss_timers.get(guild_id, {})
        if not server_timers:
            return
            
        server_user_stats = user_stats.get(guild_id, {})
        server_user_notifications = user_notifications.get(guild_id, {})
        
        # Busca config para saber qual msg editar
        config = await get_server_config(guild_id)
        if not config:
            return

        try:
            msg = await channel.fetch_message(config['table_message_id'])
            embed = create_boss_embed(server_timers)
            
            view = BossControlView(
                bot,
                server_timers,
                server_user_stats,
                server_user_notifications,
                msg,
                config['table_channel_id'],
                lambda: update_table_multi(channel, guild_id),
                lambda boss_timers=server_timers: create_next_bosses_embed(boss_timers),
                lambda: create_ranking_embed(server_user_stats),
                lambda: create_history_embed(bot, server_timers),
                lambda: create_unrecorded_embed(bot, server_timers)
            )
            
            await msg.edit(embed=embed, view=view)
            
        except discord.NotFound:
            logger.error(f"Mensagem da tabela não encontrada para servidor {guild_id}")
        except Exception as e:
            logger.error(f"Erro ao editar mensagem da tabela para servidor {guild_id}: {e}")

    # Retornar as funções necessárias para outros módulos
    return (
        lambda boss_timers=boss_timers: create_boss_embed(boss_timers),
        lambda channel, guild_id=None: update_table_multi(channel, guild_id) if guild_id else update_table(bot, channel, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID),
        lambda boss_timers=boss_timers: create_next_bosses_embed(boss_timers),
        lambda user_stats=user_stats: create_ranking_embed(user_stats),
        lambda boss_timers=boss_timers: create_history_embed(bot, boss_timers),
        lambda boss_timers=boss_timers: create_unrecorded_embed(bot, boss_timers)
    )