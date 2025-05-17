# views.py
import discord
from discord.ui import Button, View, Modal, Select
from discord import TextStyle
from datetime import datetime, timedelta
import pytz
import traceback
import os
import random
from shared_functions import get_boss_by_abbreviation, format_time_remaining, parse_time_input, validate_time
from database import save_timer, save_user_stats, clear_timer, add_user_notification, remove_user_notification, create_backup, restore_backup, load_db_data

brazil_tz = pytz.timezone('America/Sao_Paulo')

def create_boss_embed(boss_timers, compact=False):
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

class AnotarBossModal(Modal, title="Anotar Horário do Boss"):
    boss = discord.ui.TextInput(
        label="Nome do Boss",
        placeholder="Ex: Hydra, Hell Maine, Red Dragon...",
        required=True
    )
    
    sala = discord.ui.TextInput(
        label="Sala (1-8)",
        placeholder="Digite um número de 1 a 8",
        required=True,
        max_length=1
    )
    
    horario = discord.ui.TextInput(
        label="Horário da morte",
        placeholder="Ex: 14:30 ou 14h30",
        required=True,
        max_length=5
    )
    
    foi_ontem = discord.ui.TextInput(
        label="Foi ontem? (S/N)",
        placeholder="Digite S para sim ou N para não",
        required=False,
        max_length=1
    )

    def __init__(self, bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID, update_table_func, create_next_bosses_embed_func, create_ranking_embed_func, create_history_embed_func, create_unrecorded_embed_func):
        super().__init__()
        self.bot = bot
        self.boss_timers = boss_timers
        self.user_stats = user_stats
        self.user_notifications = user_notifications
        self.table_message = table_message
        self.NOTIFICATION_CHANNEL_ID = NOTIFICATION_CHANNEL_ID
        self.update_table_func = update_table_func
        self.create_next_bosses_embed_func = create_next_bosses_embed_func
        self.create_ranking_embed_func = create_ranking_embed_func
        self.create_history_embed_func = create_history_embed_func
        self.create_unrecorded_embed_func = create_unrecorded_embed_func

    async def on_submit(self, interaction: discord.Interaction):
        try:
            boss_name = get_boss_by_abbreviation(self.boss.value, self.boss_timers)
            if boss_name is None:
                await interaction.response.send_message(
                    f"Boss inválido. Bosses disponíveis: {', '.join(self.boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                    ephemeral=True
                )
                return
            
            # Verificar se já existe um timer ativo para este boss/sala
            sala = int(self.sala.value)
            timers = self.boss_timers[boss_name][sala]
            now = datetime.now(brazil_tz)
            
            if timers['respawn_time'] and timers['closed_time']:
                if now < timers['closed_time']:  # Boss ainda não fechou
                    await interaction.response.send_message(
                        f"⚠ O boss **{boss_name} (Sala {sala})** já está anotado e ainda não fechou!\n"
                        f"Status atual: {'✅ Aberto' if now >= timers['respawn_time'] else f'🕒 Abre em {format_time_remaining(timers["respawn_time"])}'}\n"
                        f"Para registrar um novo horário, primeiro use o botão 'Limpar Boss'",
                        ephemeral=True
                    )
                    return
            
            try:
                sala = int(self.sala.value)
                if sala not in self.boss_timers[boss_name].keys():
                    await interaction.response.send_message(
                        f"Sala inválida. Salas disponíveis: {', '.join(map(str, self.boss_timers[boss_name].keys()))}",
                        ephemeral=True
                    )
                    return
            except ValueError:
                await interaction.response.send_message(
                    "Sala inválida. Digite um número entre 1 e 8.",
                    ephemeral=True
                )
                return
            
            try:
                time_parts = parse_time_input(self.horario.value)
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
                
                if self.foi_ontem.value.lower() == 's':
                    death_time -= timedelta(days=1)
                elif death_time > now:
                    death_time -= timedelta(days=1)
                
                respawn_time = death_time + timedelta(hours=8)
                recorded_by = interaction.user.name
                
                self.boss_timers[boss_name][sala] = {
                    'death_time': death_time,
                    'respawn_time': respawn_time,
                    'closed_time': respawn_time + timedelta(hours=4),
                    'recorded_by': recorded_by,
                    'opened_notified': False
                }
                
                user_id = str(interaction.user.id)
                if user_id not in self.user_stats:
                    self.user_stats[user_id] = {'count': 0, 'last_recorded': None}
                self.user_stats[user_id]['count'] += 1
                self.user_stats[user_id]['last_recorded'] = now
                
                await save_timer(boss_name, sala, death_time, respawn_time, respawn_time + timedelta(hours=4), recorded_by)
                await save_user_stats(user_id, interaction.user.name, self.user_stats[user_id]['count'], now)
                
                await interaction.response.send_message(
                    f"✅ **{boss_name} (Sala {sala})** registrado por {recorded_by}:\n"
                    f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT",
                    ephemeral=False
                )
                
                # Enviar a tabela atualizada
                embed = create_boss_embed(self.boss_timers)
                view = BossControlView(
                    self.bot,
                    self.boss_timers,
                    self.user_stats,
                    self.user_notifications,
                    self.table_message,
                    self.NOTIFICATION_CHANNEL_ID,
                    self.update_table_func,
                    self.create_next_bosses_embed_func,
                    self.create_ranking_embed_func,
                    self.create_history_embed_func,
                    self.create_unrecorded_embed_func
                )
                await interaction.followup.send(embed=embed, view=view)
                
            except ValueError:
                await interaction.response.send_message(
                    "Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)",
                    ephemeral=True
                )
                
        except Exception as e:
            print(f"Erro no modal de anotação: {str(e)}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar sua anotação.",
                ephemeral=True
            )

class AgendarBossModal(Modal, title="Agendar Boss Futuro"):
    boss = discord.ui.TextInput(
        label="Nome do Boss",
        placeholder="Ex: Hydra, Hell Maine, Red Dragon...",
        required=True
    )
    
    sala = discord.ui.TextInput(
        label="Sala (1-8)",
        placeholder="Digite um número de 1 a 8",
        required=True,
        max_length=1
    )
    
    horario = discord.ui.TextInput(
        label="Horário da morte (futuro)",
        placeholder="Ex: 14:30 ou 14h30",
        required=True,
        max_length=5
    )
    
    dias = discord.ui.TextInput(
        label="Dias no futuro (0=hoje, 1=amanhã)",
        placeholder="Digite o número de dias no futuro",
        required=True,
        max_length=2
    )

    def __init__(self, bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID, update_table_func, create_next_bosses_embed_func, create_ranking_embed_func, create_history_embed_func, create_unrecorded_embed_func):
        super().__init__()
        self.bot = bot
        self.boss_timers = boss_timers
        self.user_stats = user_stats
        self.user_notifications = user_notifications
        self.table_message = table_message
        self.NOTIFICATION_CHANNEL_ID = NOTIFICATION_CHANNEL_ID
        self.update_table_func = update_table_func
        self.create_next_bosses_embed_func = create_next_bosses_embed_func
        self.create_ranking_embed_func = create_ranking_embed_func
        self.create_history_embed_func = create_history_embed_func
        self.create_unrecorded_embed_func = create_unrecorded_embed_func

    async def on_submit(self, interaction: discord.Interaction):
        try:
            boss_name = get_boss_by_abbreviation(self.boss.value, self.boss_timers)
            if boss_name is None:
                await interaction.response.send_message(
                    f"Boss inválido. Bosses disponíveis: {', '.join(self.boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                    ephemeral=True
                )
                return
            
            # Verificar se já existe um timer ativo para este boss/sala
            sala = int(self.sala.value)
            timers = self.boss_timers[boss_name][sala]
            now = datetime.now(brazil_tz)
            
            if timers['respawn_time'] and timers['closed_time']:
                if now < timers['closed_time']:  # Boss ainda não fechou
                    await interaction.response.send_message(
                        f"⚠ O boss **{boss_name} (Sala {sala})** já está anotado e ainda não fechou!\n"
                        f"Status atual: {'✅ Aberto' if now >= timers['respawn_time'] else f'🕒 Abre em {format_time_remaining(timers["respawn_time"])}'}\n"
                        f"Para registrar um novo horário, primeiro use o botão 'Limpar Boss'",
                        ephemeral=True
                    )
                    return
            
            try:
                sala = int(self.sala.value)
                if sala not in self.boss_timers[boss_name]:
                    await interaction.response.send_message(
                        f"Sala inválida. Salas disponíveis: {', '.join(map(str, self.boss_timers[boss_name].keys()))}",
                        ephemeral=True
                    )
                    return
            except ValueError:
                await interaction.response.send_message(
                    "Sala inválida. Digite um número entre 1 e 8.",
                    ephemeral=True
                )
                return
            
            try:
                time_parts = parse_time_input(self.horario.value)
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
                
                try:
                    dias = int(self.dias.value)
                    if dias < 0:
                        await interaction.response.send_message(
                            "Dias inválidos. Digite um número positivo (0 para hoje, 1 para amanhã).",
                            ephemeral=True
                        )
                        return
                except ValueError:
                    await interaction.response.send_message(
                        "Dias inválidos. Digite um número (0 para hoje, 1 para amanhã).",
                        ephemeral=True
                    )
                    return
                
                now = datetime.now(brazil_tz)
                death_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=dias)
                
                # Verificar se o horário já passou hoje
                if dias == 0 and death_time < now:
                    await interaction.response.send_message(
                        "Horário já passou para hoje. Use dias=1 para agendar para amanhã ou um horário futuro.",
                        ephemeral=True
                    )
                    return
                
                respawn_time = death_time + timedelta(hours=8)
                recorded_by = f"{interaction.user.name} (Agendado)"
                
                self.boss_timers[boss_name][sala] = {
                    'death_time': death_time,
                    'respawn_time': respawn_time,
                    'closed_time': respawn_time + timedelta(hours=4),
                    'recorded_by': recorded_by,
                    'opened_notified': False
                }
                
                user_id = str(interaction.user.id)
                if user_id not in self.user_stats:
                    self.user_stats[user_id] = {'count': 0, 'last_recorded': None}
                self.user_stats[user_id]['count'] += 1
                self.user_stats[user_id]['last_recorded'] = now
                
                await save_timer(boss_name, sala, death_time, respawn_time, respawn_time + timedelta(hours=4), recorded_by)
                await save_user_stats(user_id, interaction.user.name, self.user_stats[user_id]['count'], now)
                
                await interaction.response.send_message(
                    f"⏳ **{boss_name} (Sala {sala})** agendado por {interaction.user.name}:\n"
                    f"- Morte programada: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Abrirá: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                    f"- Fechará: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT",
                    ephemeral=False
                )
                
                # Enviar a tabela atualizada
                embed = create_boss_embed(self.boss_timers)
                view = BossControlView(
                    self.bot,
                    self.boss_timers,
                    self.user_stats,
                    self.user_notifications,
                    self.table_message,
                    self.NOTIFICATION_CHANNEL_ID,
                    self.update_table_func,
                    self.create_next_bosses_embed_func,
                    self.create_ranking_embed_func,
                    self.create_history_embed_func,
                    self.create_unrecorded_embed_func
                )
                await interaction.followup.send(embed=embed, view=view)
                
            except ValueError:
                await interaction.response.send_message(
                    "Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)",
                    ephemeral=True
                )
                
        except Exception as e:
            print(f"Erro no modal de agendamento: {str(e)}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar seu agendamento.",
                ephemeral=True
            )

class LimparBossModal(Modal, title="Limpar Boss"):
    boss = discord.ui.TextInput(
        label="Nome do Boss",
        placeholder="Ex: Hydra, Hell Maine, Red Dragon...",
        required=True
    )
    
    sala = discord.ui.TextInput(
        label="Sala (1-8) - Opcional",
        placeholder="Deixe em branco para limpar todas",
        required=False,
        max_length=1
    )

    def __init__(self, bot, boss_timers, table_message, NOTIFICATION_CHANNEL_ID, update_table_func, create_next_bosses_embed_func, create_ranking_embed_func, create_history_embed_func, create_unrecorded_embed_func):
        super().__init__()
        self.bot = bot
        self.boss_timers = boss_timers
        self.table_message = table_message
        self.NOTIFICATION_CHANNEL_ID = NOTIFICATION_CHANNEL_ID
        self.update_table_func = update_table_func
        self.create_next_bosses_embed_func = create_next_bosses_embed_func
        self.create_ranking_embed_func = create_ranking_embed_func
        self.create_history_embed_func = create_history_embed_func
        self.create_unrecorded_embed_func = create_unrecorded_embed_func

    async def on_submit(self, interaction: discord.Interaction):
        try:
            boss_name = get_boss_by_abbreviation(self.boss.value, self.boss_timers)
            if boss_name is None:
                await interaction.response.send_message(
                    f"Boss inválido. Bosses disponíveis: {', '.join(self.boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                    ephemeral=True
                )
                return
            
            sala = self.sala.value.strip()
            
            if not sala:
                for s in self.boss_timers[boss_name]:
                    self.boss_timers[boss_name][s] = {
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
                try:
                    sala = int(sala)
                    if sala not in self.boss_timers[boss_name]:
                        await interaction.response.send_message(
                            f"Sala inválida. Salas disponíveis: {', '.join(map(str, self.boss_timers[boss_name].keys()))}",
                            ephemeral=True
                        )
                        return
                    
                    self.boss_timers[boss_name][sala] = {
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
                except ValueError:
                    await interaction.response.send_message(
                        "Sala inválida. Digite um número entre 1 e 8 ou deixe em branco para limpar todas.",
                        ephemeral=True
                    )
                    return
            
            # Enviar a tabela atualizada
            embed = create_boss_embed(self.boss_timers)
            view = BossControlView(
                self.bot,
                self.boss_timers,
                {},  # user_stats não é usado na view
                {},  # user_notifications não é usado na view
                self.table_message,
                self.NOTIFICATION_CHANNEL_ID,
                self.update_table_func,
                self.create_next_bosses_embed_func,
                self.create_ranking_embed_func,
                self.create_history_embed_func,
                self.create_unrecorded_embed_func
            )
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            print(f"Erro no modal de limpar boss: {str(e)}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar sua solicitação.",
                ephemeral=True
            )

class NotificationModal(Modal, title="Gerenciar Notificações"):
    boss = discord.ui.TextInput(
        label="Nome do Boss",
        placeholder="Ex: Hydra, Hell Maine, Red Dragon...",
        required=True
    )
    
    action = discord.ui.TextInput(
        label="Ação (adicionar/remover)",
        placeholder="Digite 'add' para adicionar ou 'rem' para remover",
        required=True,
        max_length=3
    )

    def __init__(self, boss_timers, user_notifications):
        super().__init__()
        self.boss_timers = boss_timers
        self.user_notifications = user_notifications

    async def on_submit(self, interaction: discord.Interaction):
        try:
            boss_name = get_boss_by_abbreviation(self.boss.value, self.boss_timers)
            if boss_name is None:
                await interaction.response.send_message(
                    f"Boss inválido. Bosses disponíveis: {', '.join(self.boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                    ephemeral=True
                )
                return
            
            user_id = str(interaction.user.id)
            action = self.action.value.lower()
            
            if action in ['add', 'adicionar', 'a']:
                if user_id not in self.user_notifications:
                    self.user_notifications[user_id] = []
                if boss_name not in self.user_notifications[user_id]:
                    if await add_user_notification(user_id, boss_name):
                        self.user_notifications[user_id].append(boss_name)
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
            
            elif action in ['rem', 'remover', 'r']:
                if user_id in self.user_notifications and boss_name in self.user_notifications[user_id]:
                    if await remove_user_notification(user_id, boss_name):
                        self.user_notifications[user_id].remove(boss_name)
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
            print(f"Erro no modal de notificações: {str(e)}")
            traceback.print_exc()
            await interaction.response.send_message(
                "Ocorreu um erro ao processar sua solicitação.",
                ephemeral=True
            )

class BossControlView(View):
    def __init__(self, bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID, update_table_func, create_next_bosses_embed_func, create_ranking_embed_func, create_history_embed_func, create_unrecorded_embed_func):
        super().__init__(timeout=None)
        self.bot = bot
        self.boss_timers = boss_timers
        self.user_stats = user_stats
        self.user_notifications = user_notifications
        self.table_message = table_message
        self.NOTIFICATION_CHANNEL_ID = NOTIFICATION_CHANNEL_ID
        self.update_table_func = update_table_func
        self.create_next_bosses_embed_func = create_next_bosses_embed_func
        self.create_ranking_embed_func = create_ranking_embed_func
        self.create_history_embed_func = create_history_embed_func
        self.create_unrecorded_embed_func = create_unrecorded_embed_func
    
    @discord.ui.button(label="Anotar Horário", style=discord.ButtonStyle.green, custom_id="boss_control:anotar", emoji="📝")
    async def boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                modal = AnotarBossModal(
                    self.bot,
                    self.boss_timers,
                    self.user_stats,
                    self.user_notifications,
                    self.table_message,
                    self.NOTIFICATION_CHANNEL_ID,
                    self.update_table_func,
                    self.create_next_bosses_embed_func,
                    self.create_ranking_embed_func,
                    self.create_history_embed_func,
                    self.create_unrecorded_embed_func
                )
                await interaction.response.send_modal(modal)
            else:
                await interaction.followup.send("Por favor, tente novamente.", ephemeral=True)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de anotar: {str(e)}")
            traceback.print_exc()
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Ocorreu um erro ao abrir o formulário.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Ocorreu um erro ao abrir o formulário.",
                        ephemeral=True
                    )
            except Exception as e:
                print(f"Erro ao enviar mensagem de erro: {e}")
    
    @discord.ui.button(label="Agendar Boss", style=discord.ButtonStyle.green, custom_id="boss_control:agendar", emoji="⏰")
    async def schedule_boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                modal = AgendarBossModal(
                    self.bot,
                    self.boss_timers,
                    self.user_stats,
                    self.user_notifications,
                    self.table_message,
                    self.NOTIFICATION_CHANNEL_ID,
                    self.update_table_func,
                    self.create_next_bosses_embed_func,
                    self.create_ranking_embed_func,
                    self.create_history_embed_func,
                    self.create_unrecorded_embed_func
                )
                await interaction.response.send_modal(modal)
            else:
                await interaction.followup.send("Por favor, tente novamente.", ephemeral=True)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de agendar: {str(e)}")
            traceback.print_exc()
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Ocorreu um erro ao abrir o formulário de agendamento.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Ocorreu um erro ao abrir o formulário de agendamento.",
                        ephemeral=True
                    )
            except Exception as e:
                print(f"Erro ao enviar mensagem de erro: {e}")
    
    @discord.ui.button(label="Limpar Boss", style=discord.ButtonStyle.red, custom_id="boss_control:limpar", emoji="❌")
    async def clear_boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                modal = LimparBossModal(
                    self.bot,
                    self.boss_timers,
                    self.table_message,
                    self.NOTIFICATION_CHANNEL_ID,
                    self.update_table_func,
                    self.create_next_bosses_embed_func,
                    self.create_ranking_embed_func,
                    self.create_history_embed_func,
                    self.create_unrecorded_embed_func
                )
                await interaction.response.send_modal(modal)
            else:
                await interaction.followup.send("Por favor, tente novamente.", ephemeral=True)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de limpar: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )
            except:
                pass
    
    @discord.ui.button(label="Próximos", style=discord.ButtonStyle.blurple, custom_id="boss_control:proximos", emoji="⏳")
    async def next_bosses_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                await interaction.response.defer()
            
            embed = await self.create_next_bosses_embed_func(self.boss_timers)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de próximos bosses: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao buscar os próximos bosses.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Ranking", style=discord.ButtonStyle.blurple, custom_id="boss_control:ranking", emoji="🏆")
    async def ranking_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                await interaction.response.defer()
            
            embed = await self.create_ranking_embed_func()
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de ranking: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao gerar o ranking.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Notificações", style=discord.ButtonStyle.gray, custom_id="boss_control:notificacoes", emoji="🔔")
    async def notifications_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                modal = NotificationModal(self.boss_timers, self.user_notifications)
                await interaction.response.send_modal(modal)
            else:
                await interaction.followup.send("Por favor, tente novamente.", ephemeral=True)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de notificações: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )
            except:
                pass
    
    @discord.ui.button(label="Histórico", style=discord.ButtonStyle.gray, custom_id="boss_control:historico", emoji="📜")
    async def history_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                await interaction.response.defer()
            
            embed = await self.create_history_embed_func()
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de histórico: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao buscar o histórico.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Não Anotados", style=discord.ButtonStyle.red, custom_id="boss_control:nao_anotados", emoji="❌")
    async def unrecorded_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                await interaction.response.defer()
            
            embed = await self.create_unrecorded_embed_func()
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de não anotados: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao buscar os bosses não anotados.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Backup", style=discord.ButtonStyle.gray, custom_id="boss_control:backup", emoji="💾")
    async def backup_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.channel.id != self.NOTIFICATION_CHANNEL_ID:
                await interaction.response.send_message("⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
                return

            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            else:
                await interaction.followup.send("Processando backup...", ephemeral=True)
            
            if not interaction.user.guild_permissions.administrator:
                await interaction.followup.send("❌ Apenas administradores podem usar esta função.", ephemeral=True)
                return
            
            view = discord.ui.View(timeout=60)
            
            backup_button = discord.ui.Button(label="Criar Backup", style=discord.ButtonStyle.green)
            restore_button = discord.ui.Button(label="Restaurar Backup", style=discord.ButtonStyle.red)
            
            async def backup_callback(interaction: discord.Interaction):
                if not interaction.response.is_done():
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
            
            async def restore_callback(interaction: discord.Interaction):
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                
                backup_files = [f for f in os.listdir() if f.startswith('backup_') and f.endswith('.json')]
                if not backup_files:
                    await interaction.followup.send("Nenhum arquivo de backup encontrado.", ephemeral=True)
                    return
                
                select_view = discord.ui.View(timeout=120)
                select = discord.ui.Select(
                    placeholder="Selecione um backup para restaurar",
                    options=[discord.SelectOption(label=f) for f in backup_files]
                )
                
                async def restore_selected(interaction: discord.Interaction):
                    if not interaction.response.is_done():
                        await interaction.response.defer(ephemeral=True)
                    backup_file = select.values[0]
                    
                    if await restore_backup(backup_file):
                        await load_db_data(self.boss_timers, self.user_stats, self.user_notifications)
                        
                        await interaction.followup.send(
                            f"✅ Backup **{backup_file}** restaurado com sucesso!",
                            ephemeral=True
                        )
                        
                        await self.update_table_func(interaction.channel)
                    else:
                        await interaction.followup.send(
                            f"❌ Falha ao restaurar backup **{backup_file}**!",
                            ephemeral=True
                        )
                
                select.callback = restore_selected
                select_view.add_item(select)
                
                await interaction.followup.send(
                    "Selecione o backup para restaurar:",
                    view=select_view,
                    ephemeral=True
                )
            
            backup_button.callback = backup_callback
            restore_button.callback = restore_callback
            view.add_item(backup_button)
            view.add_item(restore_button)
            
            await interaction.followup.send(
                "Selecione uma opção de backup:",
                view=view,
                ephemeral=True
            )
        except Exception as e:
            print(f"ERRO DETALHADO no botão de backup: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )
            except:
                pass