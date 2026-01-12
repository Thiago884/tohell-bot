# slash_commands.py
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import pytz
from typing import Optional, List
import os
import traceback
import logging
from pathlib import Path
from shared_functions import get_boss_by_abbreviation, format_time_remaining, parse_time_input, validate_time
from database import (
    save_timer, save_user_stats, clear_timer, 
    add_user_notification, remove_user_notification, load_db_data,
    add_sala_to_all_bosses, remove_sala_from_all_bosses, create_backup, restore_backup,
    set_server_config, get_server_config, get_user_notifications
)
from views import BossControlView
from discord.app_commands import CommandAlreadyRegistered

# Configuração do logger
logger = logging.getLogger(__name__)

# Configuração do diretório de backups
BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)

brazil_tz = pytz.timezone('America/Sao_Paulo')

async def setup_slash_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID,
                             create_boss_embed_func, update_table_func, create_next_bosses_embed_func,
                             create_ranking_embed_func, create_history_embed_func, create_unrecorded_embed_func):
    
    # Autocomplete para nomes de bosses
    async def boss_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        guild_id = interaction.guild_id
        if not guild_id or guild_id not in boss_timers:
            return []
        
        bosses = list(boss_timers[guild_id].keys())
        return [
            app_commands.Choice(name=boss, value=boss)
            for boss in bosses if current.lower() in boss.lower()
        ][:25]
    
    # Autocomplete para salas - CORRIGIDO
    async def sala_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[int]]:
        """Autocomplete de salas baseado no boss selecionado"""
        try:
            guild_id = interaction.guild_id
            if not guild_id or guild_id not in boss_timers:
                return []
            
            # Obter o boss selecionado da interação atual
            options = interaction.data.get('options', [])
            boss_name = None
            
            for option in options:
                if option['name'] == 'boss_name':
                    boss_name = option['value']
                    break
            
            if not boss_name:
                # Se não encontrou o boss, retorna salas padrão do primeiro boss
                bosses = list(boss_timers[guild_id].keys())
                if not bosses:
                    return []
                salas = list(boss_timers[guild_id][bosses[0]].keys())
                return [
                    app_commands.Choice(name=f"Sala {sala}", value=sala)
                    for sala in salas if current in str(sala)
                ][:25]
            
            # Encontrar o nome completo do boss
            full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers[guild_id])
            if not full_boss_name:
                bosses = list(boss_timers[guild_id].keys())
                if not bosses:
                    return []
                salas = list(boss_timers[guild_id][bosses[0]].keys())
                return [
                    app_commands.Choice(name=f"Sala {sala}", value=sala)
                    for sala in salas if current in str(sala)
                ][:25]
            
            # Retornar salas específicas do boss
            salas = list(boss_timers[guild_id][full_boss_name].keys())
            return [
                app_commands.Choice(name=f"Sala {sala}", value=sala)
                for sala in salas if current in str(sala)
            ][:25]
            
        except Exception as e:
            logger.error(f"Erro no autocomplete de salas: {e}")
            return []
    
    # --- NOVO COMANDO: SETUP ---
    @bot.tree.command(name="setup", description="Configura os canais do bot neste servidor")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_slash(interaction: discord.Interaction, canal_tabela: discord.TextChannel, canal_notificacao: discord.TextChannel):
        """Configura os canais do bot no servidor"""
        try:
            await interaction.response.defer(ephemeral=True)
            guild_id = interaction.guild_id
            
            if not guild_id:
                await interaction.followup.send("Este comando deve ser usado em um servidor.")
                return

            # Inicializa estrutura na memória se não existir
            if guild_id not in boss_timers:
                boss_timers[guild_id] = {}
                user_stats[guild_id] = {}
                user_notifications[guild_id] = {}
            
            try:
                # Envia a tabela inicial
                embed = create_boss_embed_func(boss_timers.get(guild_id, {}))
                view = BossControlView(
                    bot,
                    boss_timers[guild_id],
                    user_stats.get(guild_id, {}),
                    user_notifications.get(guild_id, {}),
                    None,
                    canal_notificacao.id,
                    lambda channel: update_table_func(channel, guild_id=guild_id),
                    lambda: create_next_bosses_embed_func(boss_timers.get(guild_id, {})),
                    lambda: create_ranking_embed_func(user_stats.get(guild_id, {})),
                    lambda: create_history_embed_func(bot, boss_timers.get(guild_id, {})),
                    lambda: create_unrecorded_embed_func(bot, boss_timers.get(guild_id, {}))
                )
                msg = await canal_tabela.send(embed=embed, view=view)
                
                # Salva configuração no banco
                success = await set_server_config(guild_id, canal_notificacao.id, canal_tabela.id, msg.id)
                
                if success:
                    await interaction.followup.send(
                        f"✅ Setup concluído!\n"
                        f"📋 Canal Tabela: {canal_tabela.mention}\n"
                        f"🔔 Canal Notificações: {canal_notificacao.mention}"
                    )
                else:
                    await interaction.followup.send("❌ Erro ao salvar configurações no banco de dados.")
                    
            except Exception as e:
                logger.error(f"Erro no comando setup: {e}", exc_info=True)
                await interaction.followup.send(f"❌ Erro no setup: {str(e)}")
                
        except Exception as e:
            logger.error(f"Erro no comando setup: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao configurar o bot.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao configurar o bot.",
                    ephemeral=True
                )
    
    # Comando para mostrar tabela completa de bosses
    @bot.tree.command(name="bosses", description="Mostra a tabela completa de bosses com controles")
    async def bosses_slash(interaction: discord.Interaction):
        """Mostra a tabela completa de bosses via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            # Verifica canal correto
            if interaction.channel_id != config['table_channel_id']:
                await interaction.response.send_message(
                    f"⚠ Comandos só são aceitos no canal designado! "
                    f"Use no canal <#{config['table_channel_id']}>",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            
            embed = create_boss_embed_func(boss_timers.get(guild_id, {}))
            view = BossControlView(
                bot,
                boss_timers.get(guild_id, {}),
                user_stats.get(guild_id, {}),
                user_notifications.get(guild_id, {}),
                None,
                config['table_channel_id'],
                lambda channel: update_table_func(channel, guild_id=guild_id),
                lambda: create_next_bosses_embed_func(boss_timers.get(guild_id, {})),
                lambda: create_ranking_embed_func(user_stats.get(guild_id, {})),
                lambda: create_history_embed_func(bot, boss_timers.get(guild_id, {})),
                lambda: create_unrecorded_embed_func(bot, boss_timers.get(guild_id, {}))
            )
            
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Erro no comando slash bosses: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao exibir a tabela de bosses.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao exibir a tabela de bosses.",
                    ephemeral=True
                )
    
    # Comando para registrar boss (COM CORREÇÃO E MULTI-GUILD)
    @bot.tree.command(name="registro", description="Registra a morte de um boss")
    @app_commands.autocomplete(boss_name=boss_autocomplete, sala=sala_autocomplete)
    @app_commands.describe(
        boss_name="Nome do boss",
        sala="Número da sala",
        hora_morte="Horário da morte (formato HH:MM ou HHhMM)",
        foi_ontem="Se a morte foi ontem (padrão: não)"
    )
    async def registro_slash(
        interaction: discord.Interaction,
        boss_name: str,
        sala: int,
        hora_morte: str,
        foi_ontem: bool = False
    ):
        """Registra a morte de um boss via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            # Verifica canal correto
            if interaction.channel_id != config['notification_channel_id']:
                await interaction.response.send_message(
                    f"⚠ Comandos só são aceitos no canal designado! "
                    f"Use no canal <#{config['notification_channel_id']}>",
                    ephemeral=True
                )
                return
            
            if not interaction.response.is_done():
                await interaction.response.defer(thinking=True)
            
            # Garante que o servidor está nas estruturas de dados
            if guild_id not in boss_timers:
                boss_timers[guild_id] = {}
            if guild_id not in user_stats:
                user_stats[guild_id] = {}
            if guild_id not in user_notifications:
                user_notifications[guild_id] = {}
            
            full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers[guild_id])
            if full_boss_name is None:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers[guild_id].keys())}",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers[guild_id].keys())}",
                        ephemeral=True
                    )
                return
            
            boss_name = full_boss_name
            
            # VALIDAÇÃO CORRIGIDA: Verificar se a sala existe para este boss específico
            if sala not in boss_timers[guild_id][boss_name]:
                available_salas = ', '.join(map(str, sorted(boss_timers[guild_id][boss_name].keys())))
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"❌ Sala {sala} inválida para {boss_name}. Salas disponíveis: {available_salas}",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"❌ Sala {sala} inválida para {boss_name}. Salas disponíveis: {available_salas}",
                        ephemeral=True
                    )
                return
            
            # Verificação corrigida - só impede se o boss estiver agendado (ainda não abriu)
            timers = boss_timers[guild_id][boss_name][sala]
            now = datetime.now(brazil_tz)
            
            if timers['respawn_time'] and now < timers['respawn_time']:  # Boss agendado e ainda não abriu
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"⚠ O boss **{boss_name} (Sala {sala})** já está agendado e ainda não abriu!\n"
                        f"Status atual: 🕒 Abre em {format_time_remaining(timers['respawn_time'])}\n"
                        f"Para registrar um novo horário, primeiro use `/clearboss {boss_name} {sala}`",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"⚠ O boss **{boss_name} (Sala {sala})** já está agendado e ainda não abriu!\n"
                        f"Status atual: 🕒 Abre em {format_time_remaining(timers['respawn_time'])}\n"
                        f"Para registrar um novo horário, primeiro use `/clearboss {boss_name} {sala}`",
                        ephemeral=True
                    )
                return
            
            time_parts = parse_time_input(hora_morte)
            if not time_parts:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)",
                        ephemeral=True
                    )
                return
            
            hour, minute = time_parts
            
            if not validate_time(hour, minute):
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Horário inválido. Hora deve estar entre 00-23 e minutos entre 00-59.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Horário inválido. Hora deve estar entre 00-23 e minutos entre 00-59.",
                        ephemeral=True
                    )
                return
            
            now = datetime.now(brazil_tz)
            death_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            if foi_ontem or death_time > now:
                death_time -= timedelta(days=1)
            
            respawn_time = death_time + timedelta(hours=8)
            closed_time = respawn_time + timedelta(hours=4)
            recorded_by = interaction.user.name
            
            boss_timers[guild_id][boss_name][sala] = {
                'death_time': death_time,
                'respawn_time': respawn_time,
                'closed_time': closed_time,
                'recorded_by': recorded_by,
                'opened_notified': False
            }
            
            user_id = str(interaction.user.id)
            if user_id not in user_stats[guild_id]:
                user_stats[guild_id][user_id] = {'count': 0, 'last_recorded': None, 'username': recorded_by}
            user_stats[guild_id][user_id]['count'] += 1
            user_stats[guild_id][user_id]['last_recorded'] = now
            user_stats[guild_id][user_id]['username'] = recorded_by
            
            # Salva no banco com guild_id
            await save_timer(guild_id, boss_name, sala, death_time, respawn_time, closed_time, recorded_by)
            await save_user_stats(guild_id, user_id, recorded_by, user_stats[guild_id][user_id]['count'], now)
            
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"✅ **{boss_name} (Sala {sala})** registrado por {recorded_by}:\n"
                    f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Fecha: {closed_time.strftime('%d/%m %H:%M')} BRT",
                    ephemeral=False
                )
            else:
                await interaction.followup.send(
                    f"✅ **{boss_name} (Sala {sala})** registrado por {recorded_by}:\n"
                    f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Fecha: {closed_time.strftime('%d/%m %H:%M')} BRT",
                    ephemeral=False
                )
            
            # Atualiza a tabela
            channel = bot.get_channel(config['table_channel_id'])
            if channel:
                await update_table_func(channel, guild_id=guild_id)
            
        except Exception as e:
            logger.error(f"Erro no comando slash registro: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao processar seu comando.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar seu comando.",
                    ephemeral=True
                )
    
    # Comando para limpar boss (adaptado para multi-guild)
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
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            # Verifica canal correto
            if interaction.channel_id != config['notification_channel_id']:
                await interaction.response.send_message(
                    f"⚠ Comandos só são aceitos no canal designado! "
                    f"Use no canal <#{config['notification_channel_id']}>",
                    ephemeral=True
                )
                return
            
            if sala is not None and (sala < 1 or sala > 20):
                await interaction.response.send_message(
                    "❌ Número de sala inválido. Deve ser entre 1 e 20.",
                    ephemeral=True
                )
                return
            
            full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers.get(guild_id, {}))
            if full_boss_name is None:
                await interaction.response.send_message(
                    f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.get(guild_id, {}).keys())}",
                    ephemeral=True
                )
                return
            
            boss_name = full_boss_name
            
            if sala is None:
                for s in boss_timers[guild_id][boss_name]:
                    boss_timers[guild_id][boss_name][s] = {
                        'death_time': None,
                        'respawn_time': None,
                        'closed_time': None,
                        'recorded_by': None,
                        'opened_notified': False
                    }
                await clear_timer(guild_id, boss_name)
                await interaction.response.send_message(
                    f"✅ Todos os timers do boss **{boss_name}** foram resetados.",
                    ephemeral=True
                )
            else:
                if sala not in boss_timers[guild_id][boss_name]:
                    await interaction.response.send_message(
                        f"Sala inválida. Salas disponíveis: {', '.join(map(str, boss_timers[guild_id][boss_name].keys()))}",
                        ephemeral=True
                    )
                    return
                
                boss_timers[guild_id][boss_name][sala] = {
                    'death_time': None,
                    'respawn_time': None,
                    'closed_time': None,
                    'recorded_by': None,
                    'opened_notified': False
                }
                await clear_timer(guild_id, boss_name, sala)
                await interaction.response.send_message(
                    f"✅ Timer do boss **{boss_name} (Sala {sala})** foi resetado.",
                    ephemeral=True
                )
            
            # Atualiza a tabela
            channel = bot.get_channel(config['table_channel_id'])
            if channel:
                await update_table_func(channel, guild_id=guild_id)
            
        except Exception as e:
            logger.error(f"Erro no comando slash clearboss: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao processar seu comando.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar seu comando.",
                    ephemeral=True
                )
    
    # Comando para gerenciar salas (ATUALIZADO para multi-guild)
    @bot.tree.command(name="managesalas", description="Adiciona ou remove salas de todos os bosses (apenas admins)")
    @app_commands.describe(
        action="'add' para adicionar ou 'rem' para remover",
        sala="Número da sala (1-20)"
    )
    async def manage_salas_slash(
        interaction: discord.Interaction,
        action: str,
        sala: int
    ):
        """Gerencia salas via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verificação de permissão
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ Apenas administradores podem usar este comando.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            # Verifica canal correto
            if interaction.channel_id != config['notification_channel_id']:
                await interaction.response.send_message(
                    f"⚠ Comandos só são aceitos no canal designado! "
                    f"Use no canal <#{config['notification_channel_id']}>",
                    ephemeral=True
                )
                return
            
            if sala < 1 or sala > 20:
                await interaction.response.send_message(
                    "❌ Número de sala inválido. Deve ser entre 1 e 20.",
                    ephemeral=True
                )
                return
            
            modified = False
            
            if action == 'add':
                # Verificar se sala já existe para todos os bosses
                sala_exists = all(sala in boss_timers[guild_id][boss] for boss in boss_timers[guild_id])
                if sala_exists:
                    await interaction.response.send_message(
                        f"ℹ A sala {sala} já existe em todos os bosses.",
                        ephemeral=True
                    )
                    return
                
                # Adicionar no banco de dados primeiro
                success = await add_sala_to_all_bosses(guild_id, sala)
                if not success:
                    await interaction.response.send_message(
                        "❌ Erro ao adicionar sala no banco de dados.",
                        ephemeral=True
                    )
                    return
                
                # Adicionar na memória para todos os bosses
                for boss in boss_timers[guild_id]:
                    # Apenas adicionar sala 20 para bosses específicos
                    if sala == 20 and boss not in ["Genocider", "Super Red Dragon", "Hell Maine", "Death Beam Knight", "Erohim"]:
                        continue
                        
                    if sala not in boss_timers[guild_id][boss]:
                        boss_timers[guild_id][boss][sala] = {
                            'death_time': None,
                            'respawn_time': None,
                            'closed_time': None,
                            'recorded_by': None,
                            'opened_notified': False
                        }
                
                modified = True
                message = f"✅ Sala {sala} adicionada aos bosses relevantes!"
            
            elif action == 'rem':
                # Verificar se sala existe em algum boss
                sala_exists = any(sala in boss_timers[guild_id][boss] for boss in boss_timers[guild_id])
                if not sala_exists:
                    await interaction.response.send_message(
                        f"ℹ A sala {sala} não existe em nenhum boss.",
                        ephemeral=True
                    )
                    return
                
                # Remover do banco de dados primeiro
                success = await remove_sala_from_all_bosses(guild_id, sala)
                if not success:
                    await interaction.response.send_message(
                        "❌ Erro ao remover sala do banco de dados.",
                        ephemeral=True
                    )
                    return
                
                # Remover da memória
                for boss in boss_timers[guild_id]:
                    if sala in boss_timers[guild_id][boss]:
                        del boss_timers[guild_id][boss][sala]
                
                modified = True
                message = f"✅ Sala {sala} removida de todos os bosses!"
            else:
                await interaction.response.send_message(
                    "Ação inválida. Use 'add' para adicionar ou 'rem' para remover.",
                    ephemeral=True
                )
                return
            
            if modified:
                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )
                
                # Atualiza a tabela
                channel = bot.get_channel(config['table_channel_id'])
                if channel:
                    await update_table_func(channel, guild_id=guild_id)
            
        except Exception as e:
            logger.error(f"Erro no comando slash managesalas: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao processar seu comando.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar seu comando.",
                    ephemeral=True
                )

    # Comando para executar migrações manualmente
    @bot.tree.command(name="migrate", description="Executa migrações do banco de dados (apenas admins)")
    async def migrate_slash(interaction: discord.Interaction):
        """Executa migrações via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verificação de permissão
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ Apenas administradores podem usar este comando.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer(ephemeral=True)
            
            from database import migrate_fix_sala_20
            success = await migrate_fix_sala_20(guild_id)
            
            if success:
                await interaction.followup.send(
                    "✅ Migração executada com sucesso!",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "❌ Ocorreu um erro durante a migração. Verifique os logs.",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Erro no comando migrate: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao executar a migração.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao executar a migração.",
                    ephemeral=True
                )
    
    # Comando para mostrar próximos bosses (adaptado para multi-guild)
    @bot.tree.command(name="nextboss", description="Mostra os próximos bosses a abrir")
    async def nextboss_slash(interaction: discord.Interaction):
        """Mostra os próximos bosses via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            embed = create_next_bosses_embed_func(boss_timers.get(guild_id, {}))
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Erro no comando slash nextboss: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao buscar os próximos bosses.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao buscar os próximos bosses.",
                    ephemeral=True
                )
    
    # Comando para mostrar ranking (adaptado para multi-guild)
    @bot.tree.command(name="ranking", description="Mostra ranking de anotações")
    async def ranking_slash(interaction: discord.Interaction):
        """Mostra ranking via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            embed = create_ranking_embed_func(user_stats.get(guild_id, {}))
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Erro no comando slash ranking: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao gerar o ranking.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao gerar o ranking.",
                    ephemeral=True
                )
    
    # Comando para gerenciar notificações (adaptado para multi-guild)
    @bot.tree.command(name="notify", description="Gerencia notificações por DM")
    @app_commands.autocomplete(boss_name=boss_autocomplete)
    @app_commands.describe(
        boss_name="Nome do boss",
        action="Adicionar ou remover notificação (add/rem)"
    )
    async def notify_slash(
        interaction: discord.Interaction,
        boss_name: str,
        action: str
    ):
        """Gerencia notificações via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            # Verifica canal correto
            if interaction.channel_id != config['notification_channel_id']:
                await interaction.response.send_message(
                    f"⚠ Comandos só são aceitos no canal designado! "
                    f"Use no canal <#{config['notification_channel_id']}>",
                    ephemeral=True
                )
                return
            
            full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers.get(guild_id, {}))
            if full_boss_name is None:
                await interaction.response.send_message(
                    f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.get(guild_id, {}).keys())}",
                    ephemeral=True
                )
                return
            
            boss_name = full_boss_name
            user_id = str(interaction.user.id)
            
            # Garante que as estruturas existem
            if guild_id not in user_notifications:
                user_notifications[guild_id] = {}
            if user_id not in user_notifications[guild_id]:
                user_notifications[guild_id][user_id] = []
            
            if action.lower() in ['add', 'adicionar', 'a']:
                if boss_name not in user_notifications[guild_id][user_id]:
                    if await add_user_notification(guild_id, user_id, boss_name):
                        user_notifications[guild_id][user_id].append(boss_name)
                        await interaction.response.send_message(
                            f"✅ Você será notificado quando **{boss_name}** estiver disponível!",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            "❌ Ocorreu um erro ao salvar sua preferência. Tente novamente.",
                            ephemeral=True
                        )
                else:
                    await interaction.response.send_message(
                        f"ℹ Você já está sendo notificado para **{boss_name}**.",
                        ephemeral=True
                    )
            
            elif action.lower() in ['rem', 'remover', 'r']:
                if boss_name in user_notifications[guild_id][user_id]:
                    if await remove_user_notification(guild_id, user_id, boss_name):
                        user_notifications[guild_id][user_id].remove(boss_name)
                        await interaction.response.send_message(
                            f"✅ Você NÃO será mais notificado para **{boss_name}**.",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            "❌ Ocorreu um erro ao remover sua notificação. Tente novamente.",
                            ephemeral=True
                        )
                else:
                    await interaction.response.send_message(
                        f"ℹ Você não tinha notificação ativa para **{boss_name}**.",
                        ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    "Ação inválida. Use 'add' para adicionar ou 'rem' para remover.",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Erro no comando slash notify: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )
    
    # Comando para mostrar notificações do usuário (adaptado para multi-guild)
    @bot.tree.command(name="mynotifications", description="Mostra suas notificações ativas")
    async def mynotifications_slash(interaction: discord.Interaction):
        """Mostra notificações do usuário via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            user_id = str(interaction.user.id)
            notifications = user_notifications.get(guild_id, {}).get(user_id, [])
            
            if not notifications:
                await interaction.response.send_message(
                    "Você não tem notificações ativas para nenhum boss.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"🔔 **Suas notificações ativas:**\n"
                    + "\n".join(f"- {boss}" for boss in notifications)
                    + "\n\nUse `/notify <boss> rem` para remover notificações.",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Erro no comando slash mynotifications: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao buscar suas notificações.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao buscar suas notificações.",
                    ephemeral=True
                )
    
    # Comando para mostrar histórico (adaptado para multi-guild)
    @bot.tree.command(name="historico", description="Mostra histórico de anotações")
    async def historico_slash(interaction: discord.Interaction):
        """Mostra histórico via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            embed = await create_history_embed_func(bot, boss_timers.get(guild_id, {}))
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Erro no comando slash historico: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao buscar o histórico.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao buscar o histórico.",
                    ephemeral=True
                )
    
    # Comando para mostrar bosses não anotados (adaptado para multi-guild)
    @bot.tree.command(name="naoanotados", description="Mostra bosses que fecharam sem registro")
    async def naoanotados_slash(interaction: discord.Interaction):
        """Mostra bosses não anotados via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            embed = await create_unrecorded_embed_func(bot, boss_timers.get(guild_id, {}))
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Erro no comando slash naoanotados: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao buscar os bosses não anotados.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao buscar os bosses não anotados.",
                    ephemeral=True
                )
    
    # Comando para backup (apenas admins) - adaptado para multi-guild
    @bot.tree.command(name="backup", description="Gerencia backups do banco de dados (apenas admins)")
    @app_commands.describe(
        action="Ação (create/restore)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="create", value="create"),
        app_commands.Choice(name="restore", value="restore")
    ])
    async def backup_slash(interaction: discord.Interaction, action: str):
        """Gerencia backups via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verificação de permissão
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ Apenas administradores podem usar este comando.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer(ephemeral=True)
            
            if action == "create":
                backup_file = await create_backup()
                if backup_file:
                    try:
                        with open(backup_file, 'rb') as f:
                            await interaction.followup.send(
                                "✅ Backup criado com sucesso!",
                                file=discord.File(f, filename=backup_file),
                                ephemeral=True
                            )
                    except Exception as e:
                        await interaction.followup.send(
                            f"✅ Backup criado, mais erro ao enviar arquivo: {e}",
                            ephemeral=True
                        )
                else:
                    await interaction.followup.send(
                        "❌ Falha ao criar backup!",
                        ephemeral=True
                    )
            
            elif action == "restore":
                backup_files = [f for f in os.listdir(BACKUP_DIR) if f.startswith('backup_') and f.endswith('.json')]
                if not backup_files:
                    await interaction.followup.send(
                        "Nenhum arquivo de backup encontrado.",
                        ephemeral=True
                    )
                    return
                
                view = discord.ui.View(timeout=120)
                select = discord.ui.Select(
                    placeholder="Selecione um backup para restaurar",
                    options=[discord.SelectOption(label=f) for f in backup_files]
                )
                
                async def restore_selected(interaction: discord.Interaction):
                    await interaction.response.defer(ephemeral=True)
                    backup_file = select.values[0]
                    
                    if await restore_backup(backup_file):
                        # Recarrega dados para este servidor específico
                        if guild_id in boss_timers:
                            del boss_timers[guild_id]
                        if guild_id in user_stats:
                            del user_stats[guild_id]
                        if guild_id in user_notifications:
                            del user_notifications[guild_id]
                        
                        # Carrega dados do banco
                        await load_db_data(boss_timers, user_stats, user_notifications, guild_id)
                        
                        await interaction.followup.send(
                            f"✅ Backup **{backup_file}** restaurado com sucesso!",
                            ephemeral=True
                        )
                        
                        # Atualiza a tabela
                        channel = bot.get_channel(config['table_channel_id'])
                        if channel:
                            await update_table_func(channel, guild_id=guild_id)
                    else:
                        await interaction.followup.send(
                            f"❌ Falha ao restaurar backup **{backup_file}!",
                            ephemeral=True
                        )
                
                select.callback = restore_selected
                view.add_item(select)
                
                await interaction.followup.send(
                    "Selecione o backup para restaurar:",
                    view=view,
                    ephemeral=True
                )
            
            else:
                await interaction.followup.send(
                    "Ação inválida. Use 'create' ou 'restore'",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Erro no comando slash backup: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar o backup.",
                    ephemeral=True
                )
            except:
                pass
    
    # Comando de ajuda (adaptado para multi-guild)
    @bot.tree.command(name="bosshelp", description="Mostra ajuda com todos os comandos disponíveis")
    async def bosshelp_slash(interaction: discord.Interaction):
        """Mostra ajuda via comando slash"""
        try:
            guild_id = interaction.guild_id
            if not guild_id:
                await interaction.response.send_message(
                    "Este comando deve ser usado em um servidor.",
                    ephemeral=True
                )
                return
            
            # Verifica se o servidor tem configuração
            config = await get_server_config(guild_id)
            if not config:
                await interaction.response.send_message(
                    "⚠️ Bot não configurado neste servidor! Use `/setup` primeiro.",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="📚 Ajuda do Boss Timer",
                description=f"Todos os comandos devem ser usados nos canais configurados",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="/setup <canal_tabela> <canal_notificacao>",
                value="Configura os canais do bot neste servidor (apenas admins)",
                inline=False
            )
            
            embed.add_field(
                name="/bosses",
                value="Mostra a tabela completa de bosses com todos os controles",
                inline=False
            )
            
            embed.add_field(
                name="/registro <boss> <sala> <hora_morte> [foi_ontem]",
                value="Registra a morte de um boss no horário especificado\nExemplo: `/registro Hydra 8 14:30`\nBosses disponíveis: " + ", ".join(boss_timers.get(guild_id, {}).keys()),
                inline=False
            )
            
            embed.add_field(
                name="/clearboss <boss> [sala]",
                value="Reseta o timer de um boss (opcional: especifique a sala, senão limpa todas)",
                inline=False
            )
            
            embed.add_field(
                name="/managesalas <add/rem> <sala>",
                value="Adiciona ou remove salas de todos os bosses (apenas admins)",
                inline=False
            )
            
            embed.add_field(
                name="/nextboss",
                value="Mostra os próximos bosses que vão abrir e os que já estão abertos",
                inline=False
            )
            
            embed.add_field(
                name="/ranking",
                value="Mostra o ranking de quem mais anotou bosses (com medalhas para o Top 3)",
                inline=False
            )
            
            embed.add_field(
                name="/notify <boss> <add/rem>",
                value="Ativa/desativa notificação por DM quando o boss abrir\nEx: `/notify Hydra add`",
                inline=False
            )
            
            embed.add_field(
                name="/mynotifications",
                value="Mostra seus bosses marcados para notificação",
                inline=False
            )
            
            embed.add_field(
                name="/historico",
                value="Mostra as últimas 10 anotações de bosses",
                inline=False
            )
            
            embed.add_field(
                name="/naoanotados",
                value="Mostra os últimos bosses que fecharam sem registro",
                inline=False
            )
            
            embed.add_field(
                name="/backup <create|restore>",
                value="Cria ou restaura um backup dos dados (apenas admins)",
                inline=False
            )
            
            embed.add_field(
                name="/migrate",
                value="Executa migrações do banco de dados (apenas admins)",
                inline=False
            )
            
            if guild_id in boss_timers and boss_timers[guild_id]:
                bosses = list(boss_timers[guild_id].keys())
                if bosses:
                    embed.add_field(
                        name="Salas disponíveis",
                        value=", ".join(map(str, boss_timers[guild_id][bosses[0]].keys())),
                        inline=False
                    )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Erro no comando slash bosshelp: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ocorreu um erro ao exibir a ajuda.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Ocorreu um erro ao exibir a ajuda.",
                    ephemeral=True
                )