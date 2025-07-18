# slash_commands.py
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import pytz
from typing import Optional, List
import os
import traceback
from shared_functions import get_boss_by_abbreviation, format_time_remaining, parse_time_input, validate_time
from database import save_timer, save_user_stats, clear_timer, add_user_notification, remove_user_notification, load_db_data, add_sala_to_all_bosses, remove_sala_from_all_bosses
from views import BossControlView
from discord.app_commands import CommandAlreadyRegistered

brazil_tz = pytz.timezone('America/Sao_Paulo')

async def setup_slash_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID,
                             create_boss_embed_func, update_table_func, create_next_bosses_embed_func,
                             create_ranking_embed_func, create_history_embed_func, create_unrecorded_embed_func):
    
    # Autocomplete para nomes de bosses
    async def boss_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        bosses = list(boss_timers.keys())
        return [
            app_commands.Choice(name=boss, value=boss)
            for boss in bosses if current.lower() in boss.lower()
        ][:25]
    
    # Autocomplete para salas
    async def sala_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[int]]:
        salas = list(boss_timers[list(boss_timers.keys())[0]].keys())
        return [
            app_commands.Choice(name=f"Sala {sala}", value=sala)
            for sala in salas if current in str(sala)
        ][:25]
    
    # Comando para mostrar tabela completa de bosses
    @bot.tree.command(name="bosses", description="Mostra a tabela completa de bosses com controles")
    async def bosses_slash(interaction: discord.Interaction):
        """Mostra a tabela completa de bosses via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            
            embed = create_boss_embed_func(boss_timers)
            view = BossControlView(
                bot,
                boss_timers,
                user_stats,
                user_notifications,
                table_message,
                NOTIFICATION_CHANNEL_ID,
                update_table_func,
                create_next_bosses_embed_func,
                create_ranking_embed_func,
                create_history_embed_func,
                create_unrecorded_embed_func
            )
            
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Erro no comando slash bosses: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao exibir a tabela de bosses.",
                ephemeral=True
            )
    
    # Comando para registrar boss (COM CORREÇÃO)
    @bot.tree.command(name="boss", description="Registra a morte de um boss")
    @app_commands.autocomplete(boss_name=boss_autocomplete, sala=sala_autocomplete)
    @app_commands.describe(
        boss_name="Nome do boss",
        sala="Número da sala (1-20)",
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
            
            if sala < 1 or sala > 20:
                await interaction.response.send_message(
                    "❌ Número de sala inválido. Deve ser entre 1 e 20.",
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
            
            # Verificação corrigida - só impede se o boss estiver agendado (ainda não abriu)
            timers = boss_timers[boss_name][sala]
            now = datetime.now(brazil_tz)
            
            if timers['respawn_time'] and now < timers['respawn_time']:  # Boss agendado e ainda não abriu
                await interaction.response.send_message(
                    f"⚠ O boss **{boss_name} (Sala {sala})** já está agendado e ainda não abriu!\n"
                    f"Status atual: 🕒 Abre em {format_time_remaining(timers['respawn_time'])}\n"
                    f"Para registrar um novo horário, primeiro use `/clearboss {boss_name} {sala}`",
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
            embed = create_boss_embed_func(boss_timers)
            view = BossControlView(
                bot,
                boss_timers,
                user_stats,
                user_notifications,
                table_message,
                NOTIFICATION_CHANNEL_ID,
                update_table_func,
                create_next_bosses_embed_func,
                create_ranking_embed_func,
                create_history_embed_func,
                create_unrecorded_embed_func
            )
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Erro no comando slash boss: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar seu comando.",
                ephemeral=True
            )
            
    # Comando para limpar boss (mantido original)
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
            
            if sala is not None and (sala < 1 or sala > 20):
                await interaction.response.send_message(
                    "❌ Número de sala inválido. Deve ser entre 1 e 20.",
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
            embed = create_boss_embed_func(boss_timers)
            view = BossControlView(
                bot,
                boss_timers,
                {},  # user_stats não é usado na view
                {},  # user_notifications não é usado na view
                table_message,
                NOTIFICATION_CHANNEL_ID,
                update_table_func,
                create_next_bosses_embed_func,
                create_ranking_embed_func,
                create_history_embed_func,
                create_unrecorded_embed_func
            )
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Erro no comando slash clearboss: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar seu comando.",
                ephemeral=True
            )
    
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
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⚠ Comandos só são aceitos no canal designado!",
                        ephemeral=True
                    )
                return
            
            # Verificação de permissão antes de qualquer outra verificação
            if not interaction.user.guild_permissions.administrator:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Apenas administradores podem usar este comando.",
                        ephemeral=True
                    )
                return
            
            if sala < 1 or sala > 20:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Número de sala inválido. Deve ser entre 1 e 20.",
                        ephemeral=True
                    )
                return
            
            modified = False
            
            if action == 'add':
                # Verificar se sala já existe para todos os bosses
                sala_exists = all(sala in boss_timers[boss] for boss in boss_timers)
                if sala_exists:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            f"ℹ A sala {sala} já existe em todos os bosses.",
                            ephemeral=True
                        )
                    return
                
                # Adicionar no banco de dados primeiro
                success = await add_sala_to_all_bosses(sala)
                if not success:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "❌ Erro ao adicionar sala no banco de dados.",
                            ephemeral=True
                        )
                    return
                
                # Adicionar na memória
                for boss in boss_timers:
                    # Apenas adicionar sala 20 para bosses específicos
                    if sala == 20 and boss not in ["Genocider", "Super Red Dragon", "Hell Maine", "Death Beam Knight", "Erohim"]:
                        continue
                        
                    if sala not in boss_timers[boss]:
                        boss_timers[boss][sala] = {
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
                sala_exists = any(sala in boss_timers[boss] for boss in boss_timers)
                if not sala_exists:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            f"ℹ A sala {sala} não existe em nenhum boss.",
                            ephemeral=True
                        )
                    return
                
                # Remover do banco de dados primeiro
                success = await remove_sala_from_all_bosses(sala)
                if not success:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "❌ Erro ao remover sala do banco de dados.",
                            ephemeral=True
                        )
                    return
                
                # Remover da memória
                for boss in boss_timers:
                    if sala in boss_timers[boss]:
                        del boss_timers[boss][sala]
                
                modified = True
                message = f"✅ Sala {sala} removida de todos os bosses!"
            else:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Ação inválida. Use 'add' para adicionar ou 'rem' para remover.",
                        ephemeral=True
                    )
                return
            
            if modified:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        message,
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        message,
                        ephemeral=True
                    )
                    
                # Atualiza a tabela
                embed = create_boss_embed_func(boss_timers)
                view = BossControlView(
                    bot,
                    boss_timers,
                    {},  # user_stats não é usado na view
                    {},  # user_notifications não é usado na view
                    table_message,
                    NOTIFICATION_CHANNEL_ID,
                    update_table_func,
                    create_next_bosses_embed_func,
                    create_ranking_embed_func,
                    create_history_embed_func,
                    create_unrecorded_embed_func
                )
                await interaction.channel.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Erro no comando slash managesalas: {e}")
            traceback.print_exc()
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
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ Apenas administradores podem usar este comando.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer(ephemeral=True)
            
            from database import migrate_fix_sala_20
            success = await migrate_fix_sala_20()
            
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
            print(f"Erro no comando migrate: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao executar a migração.",
                ephemeral=True
            )
    
    # Comando para mostrar próximos bosses (mantido original)
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
            embed = await create_next_bosses_embed_func(boss_timers)
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Erro no comando slash nextboss: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao buscar os próximos bosses.",
                ephemeral=True
            )
    
    # Comando para mostrar ranking (mantido original)
    @bot.tree.command(name="ranking", description="Mostra ranking de anotações")
    async def ranking_slash(interaction: discord.Interaction):
        """Mostra ranking via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            embed = await create_ranking_embed_func()
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Erro no comando slash ranking: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao gerar o ranking.",
                ephemeral=True
            )
    
    # Comando para gerenciar notificações (mantido original)
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
            user_id = str(interaction.user.id)
            
            if action.lower() in ['add', 'adicionar', 'a']:
                if user_id not in user_notifications:
                    user_notifications[user_id] = []
                
                if boss_name not in user_notifications[user_id]:
                    if await add_user_notification(user_id, boss_name):
                        user_notifications[user_id].append(boss_name)
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
                        f"ℹ Você já está sendo notificado para **{boss_name}.",
                        ephemeral=True
                    )
            
            elif action.lower() in ['rem', 'remover', 'r']:
                if user_id in user_notifications and boss_name in user_notifications[user_id]:
                    if await remove_user_notification(user_id, boss_name):
                        user_notifications[user_id].remove(boss_name)
                        await interaction.response.send_message(
                            f"✅ Você NÃO será mais notificado para **{boss_name}.",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            "❌ Ocorreu um erro ao remover sua notificação. Tente novamente.",
                            ephemeral=True
                        )
                else:
                    await interaction.response.send_message(
                        f"ℹ Você não tinha notificação ativa para **{boss_name}.",
                        ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    "Ação inválida. Use 'add' para adicionar ou 'rem' para remover.",
                    ephemeral=True
                )
                
        except Exception as e:
            print(f"Erro no comando slash notify: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar sua solicitação.",
                ephemeral=True
            )
    
    # Comando para mostrar notificações do usuário (mantido original)
    @bot.tree.command(name="mynotifications", description="Mostra suas notificações ativas")
    async def mynotifications_slash(interaction: discord.Interaction):
        """Mostra notificações do usuário via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            user_id = str(interaction.user.id)
            notifications = user_notifications.get(user_id, [])
            
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
            print(f"Erro no comando slash mynotifications: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao buscar suas notificações.",
                ephemeral=True
            )
    
    # Comando para mostrar histórico (mantido original)
    @bot.tree.command(name="historico", description="Mostra histórico de anotações")
    async def historico_slash(interaction: discord.Interaction):
        """Mostra histórico via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            embed = await create_history_embed_func()
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Erro no comando slash historico: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao buscar o histórico.",
                ephemeral=True
            )
    
    # Comando para mostrar bosses não anotados (mantido original)
    @bot.tree.command(name="naoanotados", description="Mostra bosses que fecharam sem registro")
    async def naoanotados_slash(interaction: discord.Interaction):
        """Mostra bosses não anotados via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer()
            embed = await create_unrecorded_embed_func()
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            print(f"Erro no comando slash naoanotados: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao buscar os bosses não anotados.",
                ephemeral=True
            )
    
    # Comando para backup (apenas admins) (mantido original)
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
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return
            
            # Verificação de permissão antes de qualquer outra verificação
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ Apenas administradores podem usar este comando.",
                    ephemeral=True
                )
                return
            
            if action == "create":
                await interaction.response.defer(ephemeral=True)
                backup_file = await create_backup()
                if backup_file:
                    try:
                        with open(backup_file, 'rb') as f:
                            await interaction.followup.send(
                                f"✅ Backup criado com sucesso!",
                                file=discord.File(f, filename=backup_file),
                                ephemeral=True
                            )
                    except Exception as e:
                        await interaction.followup.send(
                            f"✅ Backup criado, mas erro ao enviar arquivo: {e}",
                            ephemeral=True
                        )
                else:
                    await interaction.followup.send(
                        "❌ Falha ao criar backup!",
                        ephemeral=True
                    )
            
            elif action == "restore":
                await interaction.response.defer(ephemeral=True)
                backup_files = [f for f in os.listdir() if f.startswith('backup_') and f.endswith('.json')]
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
                        await load_db_data(boss_timers, user_stats, user_notifications)
                        
                        await interaction.followup.send(
                            f"✅ Backup **{backup_file}** restaurado com sucesso!",
                            ephemeral=True
                        )
                        
                        await update_table_func(interaction.channel)
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
                await interaction.response.send_message(
                    "Ação inválida. Use 'create' ou 'restore'",
                    ephemeral=True
                )
                
        except Exception as e:
            print(f"Erro no comando slash backup: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar o backup.",
                ephemeral=True
            )
    
    # Comando de ajuda (mantido original)
    @bot.tree.command(name="bosshelp", description="Mostra ajuda com todos os comandos disponíveis")
    async def bosshelp_slash(interaction: discord.Interaction):
        """Mostra ajuda via comando slash"""
        try:
            if interaction.channel.id != NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message(
                    "⚠ Comandos só são aceitos no canal designado!",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="📚 Ajuda do Boss Timer",
                description=f"Todos os comandos devem ser usados neste canal (ID: {NOTIFICATION_CHANNEL_ID})",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="/bosses",
                value="Mostra a tabela completa de bosses com todos os controles",
                inline=False
            )
            
            embed.add_field(
                name="/boss <nome> <sala> <hora_morte> [foi_ontem]",
                value="Registra a morte de um boss no horário especificado\nExemplo: `/boss Hydra 8 14:30`\nBosses disponíveis: " + ", ".join(boss_timers.keys()),
                inline=False
            )
            
            embed.add_field(
                name="/agendarboss <nome> <sala> <hora_morte> [dia]",
                value="Agenda um boss para ser registrado automaticamente no futuro\nExemplo: `/agendarboss Hydra 8 14:30 1` (para amanhã)",
                inline=False
            )
            
            embed.add_field(
                name="/clearboss <nome> [sala]",
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
            
            embed.add_field(
                name="Salas disponíveis",
                value=", ".join(map(str, boss_timers.get(list(boss_timers.keys())[0], {}).keys())),
                inline=False
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            print(f"Erro no comando slash bosshelp: {e}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao exibir a ajuda.",
                ephemeral=True
            )