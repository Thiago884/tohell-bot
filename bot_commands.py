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
    create_backup, restore_backup, connect_db
)

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Mapeamento de abreviações
BOSS_ABBREVIATIONS = {
    "super red dragon": "red",
    "hell maine": "hell",
    "illusion of kundun": "illusion",
    "death beam knight": "dbk",
    "phoenix of darkness": "phoenix",
    "rei kundun": "rei",
    "genocider": "geno",
}

def setup_boss_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID):
    # Funções auxiliares
    def format_time_remaining(target_time):
        now = datetime.now(brazil_tz)
        if target_time < now:
            return "00h 00m"
        delta = target_time - now
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}h {minutes:02d}m"

    def get_boss_by_abbreviation(abbrev):
        abbrev = abbrev.lower()
        for boss, abbr in BOSS_ABBREVIATIONS.items():
            if abbr.lower() == abbrev:
                for b in boss_timers.keys():
                    if b.lower() == boss:
                        return b
        
        for boss in boss_timers.keys():
            if abbrev in boss.lower():
                return boss
        
        return None

    def create_boss_embed(compact=False):
        now = datetime.now(brazil_tz)
        
        embed = discord.Embed(
            title=f"BOSS TIMER - {now.strftime('%d/%m/%Y %H:%M:%S')} BRT",
            color=discord.Color.gold()
        )
        
        for boss in boss_timers:
            boss_info = []
            for sala in boss_timers[boss]:
                timers = boss_timers[boss][sala]
                
                # Não mostrar bosses que já fecharam e não têm novo horário registrado
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

    def get_next_bosses():
        now = datetime.now(brazil_tz)
        upcoming_bosses = []
        open_bosses = []
        
        for boss in boss_timers:
            for sala in boss_timers[boss]:
                timers = boss_timers[boss][sala]
                respawn_time = timers['respawn_time']
                closed_time = timers['closed_time']
                
                if respawn_time is not None:
                    if now >= respawn_time and closed_time is not None and now < closed_time:
                        time_left = format_time_remaining(closed_time)
                        open_bosses.append({
                            'boss': boss,
                            'sala': sala,
                            'respawn_time': respawn_time,
                            'closed_time': closed_time,
                            'time_left': time_left,
                            'recorded_by': timers['recorded_by'],
                            'status': 'open'
                        })
                    elif now < respawn_time:
                        upcoming_bosses.append({
                            'boss': boss,
                            'sala': sala,
                            'respawn_time': respawn_time,
                            'time_left': format_time_remaining(respawn_time),
                            'recorded_by': timers['recorded_by'],
                            'status': 'upcoming'
                        })
        
        upcoming_bosses.sort(key=lambda x: x['respawn_time'])
        open_bosses.sort(key=lambda x: x['closed_time'])
        
        return upcoming_bosses[:5] + open_bosses[:5]

    def parse_time_input(time_str):
        time_str = time_str.strip().lower()
        
        if ':' in time_str:
            parts = time_str.split(':')
            if len(parts) == 2:
                try:
                    hour = int(parts[0])
                    minute = int(parts[1])
                    return hour, minute
                except ValueError:
                    return None
        
        if 'h' in time_str:
            parts = time_str.split('h')
            if len(parts) == 2:
                try:
                    hour = int(parts[0])
                    minute = int(parts[1])
                    return hour, minute
                except ValueError:
                    return None
        
        try:
            hour = int(time_str)
            return hour, 0
        except ValueError:
            return None

    def validate_time(hour, minute):
        if hour < 0 or hour > 23:
            return False
        if minute < 0 or minute > 59:
            return False
        return True

    async def update_table(channel):
        nonlocal table_message
        
        try:
            embed = create_boss_embed()
            view = BossControlView()
            
            if table_message:
                try:
                    await table_message.edit(embed=embed, view=view)
                    return
                except discord.NotFound:
                    table_message = await channel.send(embed=embed, view=view)
                    return
                except Exception as e:
                    print(f"Erro ao editar mensagem da tabela: {e}")
                    table_message = await channel.send(embed=embed, view=view)
                    return
            
            async for message in channel.history(limit=50):
                if message.author == bot.user and message.embeds and message.embeds[0].title.startswith("BOSS TIMER"):
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
                table_message = await channel.send(embed=create_boss_embed(), view=BossControlView())
            except:
                pass

    # Modals
    class AnotarBossModal(discord.ui.Modal, title="Anotar Horário do Boss"):
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

        async def on_submit(self, interaction: discord.Interaction):
            try:
                boss_name = get_boss_by_abbreviation(self.boss.value)
                if boss_name is None:
                    await interaction.response.send_message(
                        f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                        ephemeral=True
                    )
                    return
                
                try:
                    sala = int(self.sala.value)
                    if sala not in boss_timers[boss_name].keys():
                        await interaction.response.send_message(
                            f"Sala inválida. Salas disponíveis: {', '.join(map(str, boss_timers[boss_name].keys()))}",
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
                    
                    boss_timers[boss_name][sala] = {
                        'death_time': death_time,
                        'respawn_time': respawn_time,
                        'closed_time': respawn_time + timedelta(hours=4),
                        'recorded_by': recorded_by,
                        'opened_notified': False
                    }
                    
                    user_id = str(interaction.user.id)
                    user_stats[user_id]['count'] += 1
                    user_stats[user_id]['last_recorded'] = now
                    
                    save_timer(boss_name, sala, death_time, respawn_time, respawn_time + timedelta(hours=4), recorded_by)
                    save_user_stats(user_id, interaction.user.name, user_stats[user_id]['count'], now)
                    
                    await interaction.response.send_message(
                        f"✅ **{boss_name} (Sala {sala})** registrado por {recorded_by}:\n"
                        f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                        f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                        f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT",
                        ephemeral=False
                    )
                    
                    channel = interaction.channel
                    if channel:
                        embed = create_boss_embed()
                        view = BossControlView()
                        await channel.send("**Tabela atualizada:**", embed=embed, view=view)
                        await update_table(channel)
                        
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

    class LimparBossModal(discord.ui.Modal, title="Limpar Boss"):
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

        async def on_submit(self, interaction: discord.Interaction):
            try:
                boss_name = get_boss_by_abbreviation(self.boss.value)
                if boss_name is None:
                    await interaction.response.send_message(
                        f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                        ephemeral=True
                    )
                    return
                
                sala = self.sala.value.strip()
                
                if not sala:
                    for s in boss_timers[boss_name]:
                        boss_timers[boss_name][s] = {
                            'death_time': None,
                            'respawn_time': None,
                            'closed_time': None,
                            'recorded_by': None,
                            'opened_notified': False
                        }
                    clear_timer(boss_name)
                    await interaction.response.send_message(
                        f"✅ Todos os timers do boss **{boss_name}** foram resetados.",
                        ephemeral=True
                    )
                else:
                    try:
                        sala = int(sala)
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
                        clear_timer(boss_name, sala)
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
                
                await update_table(interaction.channel)
                
            except Exception as e:
                print(f"Erro no modal de limpar boss: {str(e)}")
                traceback.print_exc()
                await interaction.response.send_message(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )

    # Comandos
    @bot.command(name='boss')
    async def boss_command(ctx, boss_name: str = None, sala: int = None, hora_morte: str = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return

        if boss_name is None or sala is None or hora_morte is None:
            await ctx.send("Por favor, use: `!boss <nome_do_boss> <sala> HH:MM`\nExemplo: `!boss Hydra 8 14:30`\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno\nFormatos de hora aceitos: HH:MM ou HHhMM")
            return
        
        if sala not in boss_timers.get(list(boss_timers.keys())[0], {}).keys():
            await ctx.send(f"Sala inválida. Salas disponíveis: {', '.join(map(str, boss_timers.get(list(boss_timers.keys())[0], {}).keys()))}")
            return
        
        full_boss_name = get_boss_by_abbreviation(boss_name)
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
            user_stats[user_id]['count'] += 1
            user_stats[user_id]['last_recorded'] = now
            
            save_timer(boss_name, sala, death_time, respawn_time, respawn_time + timedelta(hours=4), recorded_by)
            save_user_stats(user_id, ctx.author.name, user_stats[user_id]['count'], now)
            
            await ctx.send(
                f"✅ **{boss_name} (Sala {sala})** registrado por {recorded_by}:\n"
                f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT"
            )
            
            channel = ctx.channel
            if channel:
                embed = create_boss_embed()
                view = BossControlView()
                await channel.send("**Tabela atualizada:**", embed=embed, view=view)
                await update_table(channel)
                
        except ValueError:
            await ctx.send("Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)")

    @bot.command(name='bosses')
    async def bosses_command(ctx, mode: str = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        compact = mode and mode.lower() in ['compact', 'c', 'resumo']
        embed = create_boss_embed(compact=compact)
        view = BossControlView()
        await ctx.send(embed=embed, view=view)

    @bot.command(name='nextboss')
    async def next_boss_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        embed = await create_next_bosses_embed()
        await ctx.send(embed=embed)

    @bot.command(name='clearboss')
    async def clear_boss(ctx, boss_name: str, sala: int = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        full_boss_name = get_boss_by_abbreviation(boss_name)
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
            clear_timer(boss_name)
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
            clear_timer(boss_name, sala)
            await ctx.send(f"✅ Timer do boss **{boss_name} (Sala {sala})** foi resetado.")
        
        await update_table(ctx.channel)

    @bot.command(name='setupboss')
    async def setup_boss(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
            
        embed = create_boss_embed()
        view = BossControlView()
        await ctx.send(embed=embed, view=view)

    # Tasks
    @tasks.loop(seconds=30)
    async def live_table_updater():
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            await update_table(channel)

    @tasks.loop(minutes=1)
    async def check_boss_respawns():
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
                            save_timer(boss, sala, timers['death_time'], respawn_time, closed_time, timers['recorded_by'], True)
                            
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
                        save_timer(boss, sala, timers['death_time'], None, None, timers['recorded_by'], False)

        if notifications:
            message = "**Notificações de Boss:**\n" + "\n".join(notifications)
            await channel.send(message)
        
        if dm_notifications:
            for notification in dm_notifications:
                await send_notification_dm(
                    notification['user_id'],
                    notification['boss_name'],
                    notification['sala'],
                    notification['respawn_time'],
                    notification['closed_time']
                )
        
        await update_table(channel)

    @tasks.loop(minutes=30)
    async def periodic_table_update():
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            embed = create_boss_embed()
            view = BossControlView()
            await channel.send("**Atualização periódica dos horários de boss:**", embed=embed, view=view)
        
        periodic_table_update.change_interval(minutes=random.randint(30, 60))

    # Views
    class BossControlView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
        
        @discord.ui.button(label="Anotar Horário", style=discord.ButtonStyle.green, custom_id="boss_control:anotar", emoji="📝")
        async def boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
            try:
                if not interaction.response.is_done():
                    modal = AnotarBossModal()
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
        
        @discord.ui.button(label="Limpar Boss", style=discord.ButtonStyle.red, custom_id="boss_control:limpar", emoji="❌")
        async def clear_boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
            try:
                if not interaction.response.is_done():
                    modal = LimparBossModal()
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
                if not interaction.response.is_done():
                    await interaction.response.defer()
                embed = await create_next_bosses_embed()
                await interaction.followup.send(embed=embed)
            except Exception as e:
                print(f"ERRO DETALHADO no botão de próximos bosses: {str(e)}")
                traceback.print_exc()
                try:
                    await interaction.followup.send("Ocorreu um erro ao buscar os próximos bosses.", ephemeral=True)
                except:
                    pass

    # Iniciar as tasks
    check_boss_respawns.start()
    live_table_updater.start()
    periodic_table_update.start()

    # Adicionar a view persistente
    bot.add_view(BossControlView())