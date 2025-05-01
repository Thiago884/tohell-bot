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

async def setup_bot_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID):
    # Funções auxiliares
    def format_time_remaining(target_time):
        now = datetime.now(brazil_tz)
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
                
                # Não mostrar bosses que já fecharam
                if timers['closed_time'] and now >= timers['closed_time']:
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
                
            embed.add_field(
                name=f"**{boss}**",
                value="\n".join(boss_info) if boss_info else "Nenhum horário registrado",
                inline=False
            )
        
        return embed

    async def create_ranking_embed():
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
                username = f"Usuário {user_id}"
            
            # Adiciona medalhas para os top 3
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
        
        # Ordenar por tempo de respawn mais próximo
        upcoming_bosses.sort(key=lambda x: x['respawn_time'])
        open_bosses.sort(key=lambda x: x['closed_time'])
        
        return upcoming_bosses[:5] + open_bosses[:5]  # Retorna os próximos 5 e os 5 abertos mais recentes

    async def create_next_bosses_embed():
        next_bosses = get_next_bosses()
        
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

    async def send_notification_dm(user_id, boss_name, sala, respawn_time, closed_time):
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

    def parse_time_input(time_str):
        """Analisa o input de tempo em vários formatos (HH:MM, HHhMM) e retorna (hora, minuto)"""
        # Remover espaços em branco
        time_str = time_str.strip().lower()
        
        # Tentar formato HH:MM
        if ':' in time_str:
            parts = time_str.split(':')
            if len(parts) == 2:
                try:
                    hour = int(parts[0])
                    minute = int(parts[1])
                    return hour, minute
                except ValueError:
                    return None
        
        # Tentar formato HHhMM
        if 'h' in time_str:
            parts = time_str.split('h')
            if len(parts) == 2:
                try:
                    hour = int(parts[0])
                    minute = int(parts[1])
                    return hour, minute
                except ValueError:
                    return None
        
        # Tentar apenas HH
        try:
            hour = int(time_str)
            return hour, 0
        except ValueError:
            return None

    def validate_time(hour, minute):
        """Verifica se o horário é válido"""
        if hour < 0 or hour > 23:
            return False
        if minute < 0 or minute > 59:
            return False
        return True

    async def create_history_embed():
        conn = connect_db()
        if conn is None:
            return discord.Embed(title="Erro", description="Não foi possível conectar ao banco de dados", color=discord.Color.red())
        
        try:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
            SELECT boss_name, sala, death_time, respawn_time, recorded_by 
            FROM boss_timers 
            WHERE death_time IS NOT NULL
            ORDER BY death_time DESC 
            LIMIT 10
            """)
            
            history = cursor.fetchall()
            
            if not history:
                return discord.Embed(title="Histórico de Anotações", description="Nenhuma anotação registrada ainda.", color=discord.Color.blue())
            
            embed = discord.Embed(
                title="📜 Histórico das Últimas Anotações",
                color=discord.Color.gold()
            )
            
            for idx, record in enumerate(history, 1):
                embed.add_field(
                    name=f"{idx}. {record['boss_name']} (Sala {record['sala']})",
                    value=f"⏱ Morte: {record['death_time'].strftime('%d/%m %H:%M')}\n"
                         f"🔄 Abriu: {record['respawn_time'].strftime('%d/%m %H:%M')}\n"
                         f"👤 Por: {record['recorded_by']}",
                    inline=False
                )
            
            return embed
            
        except Exception as e:
            print(f"Erro ao buscar histórico: {e}")
            return discord.Embed(title="Erro", description="Ocorreu um erro ao buscar o histórico", color=discord.Color.red())
        finally:
            conn.close()

    async def create_unrecorded_embed():
        conn = connect_db()
        if conn is None:
            return discord.Embed(title="Erro", description="Não foi possível conectar ao banco de dados", color=discord.Color.red())
        
        try:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
            SELECT boss_name, sala, death_time, respawn_time, closed_time, recorded_by 
            FROM boss_timers 
            WHERE opened_notified = FALSE AND closed_time IS NOT NULL
            ORDER BY closed_time DESC 
            LIMIT 5
            """)
            
            unrecorded = cursor.fetchall()
            
            if not unrecorded:
                return discord.Embed(title="Bosses Fechados sem Anotações", description="Nenhum boss foi fechado sem anotações recentemente.", color=discord.Color.blue())
            
            embed = discord.Embed(
                title="❌ Últimos Bosses Fechados sem Anotações",
                color=discord.Color.red()
            )
            
            for idx, record in enumerate(unrecorded, 1):
                embed.add_field(
                    name=f"{idx}. {record['boss_name']} (Sala {record['sala']})",
                    value=f"⏱ Morte: {record['death_time'].strftime('%d/%m %H:%M')}\n"
                         f"🔄 Abriu: {record['respawn_time'].strftime('%d/%m %H:%M')}\n"
                         f"🔴 Fechou: {record['closed_time'].strftime('%d/%m %H:%M')}\n"
                         f"👤 Por: {record['recorded_by'] or 'Ninguém'}",
                    inline=False
                )
            
            return embed
            
        except Exception as e:
            print(f"Erro ao buscar bosses não anotados: {e}")
            return discord.Embed(title="Erro", description="Ocorreu um erro ao buscar os bosses não anotados", color=discord.Color.red())
        finally:
            conn.close()

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
                            
                            # Verificar se há usuários para notificar via DM
                            for user_id in user_notifications:
                                if boss in user_notifications[user_id]:
                                    dm_notifications.append({
                                        'user_id': user_id,
                                        'boss_name': boss,
                                        'sala': sala,
                                        'respawn_time': respawn_time,
                                        'closed_time': closed_time
                                    })
                    
                    # Notificação de fechamento (verifica exatamente no minuto do fechamento)
                    if closed_time is not None and abs((now - closed_time).total_seconds()) < 60:
                        message = f"🔴 **{boss} (Sala {sala})** FECHOU"
                        if not timers.get('opened_notified', False):
                            message += " sem nenhuma anotação durante o período aberto!"
                        else:
                            message += "!"
                        
                        notifications.append(message)
                        
                        # Limpar os dados do boss fechado
                        boss_timers[boss][sala]['respawn_time'] = None
                        boss_timers[boss][sala]['closed_time'] = None
                        boss_timers[boss][sala]['opened_notified'] = False
                        save_timer(boss, sala, timers['death_time'], None, None, timers['recorded_by'], False)

        if notifications:
            message = "**Notificações de Boss:**\n" + "\n".join(notifications)
            await channel.send(message)
        
        # Enviar notificações por DM
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
        """Atualização periódica da tabela com intervalo aleatório"""
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            embed = create_boss_embed()
            view = BossControlView()
            await channel.send("**Atualização periódica dos horários de boss:**", embed=embed, view=view)
        
        # Define um intervalo aleatório para a próxima atualização (entre 30 e 60 minutos)
        periodic_table_update.change_interval(minutes=random.randint(30, 60))

    @tasks.loop(hours=24)
    async def daily_backup():
        """Rotina de backup diário"""
        try:
            backup_file = create_backup()
            if backup_file:
                print(f"Backup diário realizado com sucesso: {backup_file}")
            else:
                print("Falha ao realizar backup diário")
        except Exception as e:
            print(f"Erro na rotina de backup: {e}")

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
                    # Analisar o horário em diferentes formatos
                    time_parts = parse_time_input(self.horario.value)
                    if not time_parts:
                        await interaction.response.send_message(
                            "Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)",
                            ephemeral=True
                        )
                        return
                    
                    hour, minute = time_parts
                    
                    # Validar o horário
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
                    
                    # Enviar a tabela atualizada imediatamente após o registro
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
                
                if not sala:  # Se sala estiver vazia, limpar todas as salas
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

    class NotificationModal(discord.ui.Modal, title="Gerenciar Notificações"):
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

        async def on_submit(self, interaction: discord.Interaction):
            try:
                boss_name = get_boss_by_abbreviation(self.boss.value)
                if boss_name is None:
                    await interaction.response.send_message(
                        f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                        ephemeral=True
                    )
                    return
                
                user_id = str(interaction.user.id)
                action = self.action.value.lower()
                
                if action in ['add', 'adicionar', 'a']:
                    if boss_name not in user_notifications[user_id]:
                        if add_user_notification(user_id, boss_name):
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
                            f"ℹ Você já está sendo notificado para **{boss_name}**.",
                            ephemeral=True
                        )
                
                elif action in ['rem', 'remover', 'r']:
                    if boss_name in user_notifications[user_id]:
                        if remove_user_notification(user_id, boss_name):
                            user_notifications[user_id].remove(boss_name)
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
                print(f"Erro no modal de notificações: {str(e)}")
                traceback.print_exc()
                await interaction.response.send_message(
                    "Ocorreu um erro ao processar sua solicitação.",
                    ephemeral=True
                )

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
        
        @discord.ui.button(label="Ranking", style=discord.ButtonStyle.blurple, custom_id="boss_control:ranking", emoji="🏆")
        async def ranking_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
                embed = await create_ranking_embed()
                await interaction.followup.send(embed=embed)
            except Exception as e:
                print(f"ERRO DETALHADO no botão de ranking: {str(e)}")
                traceback.print_exc()
                try:
                    await interaction.followup.send("Ocorreu um erro ao gerar o ranking.", ephemeral=True)
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
        
        @discord.ui.button(label="Notificações", style=discord.ButtonStyle.gray, custom_id="boss_control:notificacoes", emoji="🔔")
        async def notifications_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
            try:
                if not interaction.response.is_done():
                    modal = NotificationModal()
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
                if not interaction.response.is_done():
                    await interaction.response.defer()
                embed = await create_history_embed()
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
                if not interaction.response.is_done():
                    await interaction.response.defer()
                embed = await create_unrecorded_embed()
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
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                else:
                    await interaction.followup.send("Processando backup...", ephemeral=True)
                
                # Verificar se o usuário tem permissão de administrador
                if not interaction.user.guild_permissions.administrator:
                    await interaction.followup.send("❌ Apenas administradores podem usar esta função.", ephemeral=True)
                    return
                
                view = discord.ui.View(timeout=60)
                
                backup_button = discord.ui.Button(label="Criar Backup", style=discord.ButtonStyle.green)
                restore_button = discord.ui.Button(label="Restaurar Backup", style=discord.ButtonStyle.red)
                
                async def backup_callback(interaction: discord.Interaction):
                    if not interaction.response.is_done():
                        await interaction.response.defer(ephemeral=True)
                    backup_file = create_backup()
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
                    
                    # Verificar se há arquivos de backup
                    backup_files = [f for f in os.listdir() if f.startswith('backup_') and f.endswith('.json')]
                    if not backup_files:
                        await interaction.followup.send("Nenhum arquivo de backup encontrado.", ephemeral=True)
                        return
                    
                    # Criar menu de seleção de backup
                    select_view = discord.ui.View(timeout=120)
                    select = discord.ui.Select(
                        placeholder="Selecione um backup para restaurar",
                        options=[discord.SelectOption(label=f) for f in backup_files]
                    )
                    
                    async def restore_selected(interaction: discord.Interaction):
                        if not interaction.response.is_done():
                            await interaction.response.defer(ephemeral=True)
                        backup_file = select.values[0]
                        
                        if restore_backup(backup_file):
                            # Recarregar dados do banco
                            load_db_data(boss_timers, user_stats, user_notifications)
                            
                            await interaction.followup.send(
                                f"✅ Backup **{backup_file}** restaurado com sucesso!",
                                ephemeral=True
                            )
                            
                            # Atualizar tabela
                            await update_table(interaction.channel)
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
            # Analisar o horário em diferentes formatos
            time_parts = parse_time_input(hora_morte)
            if not time_parts:
                await ctx.send("Formato de hora inválido. Use HH:MM ou HHhMM (ex: 14:30 ou 14h30)")
                return
            
            hour, minute = time_parts
            
            # Validar o horário
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
            
            # Enviar a tabela atualizada imediatamente após o registro
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

    @bot.command(name='ranking')
    async def ranking_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        embed = await create_ranking_embed()
        await ctx.send(embed=embed)

    @bot.command(name='notify')
    async def notify_command(ctx, boss_name: str = None, action: str = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        if boss_name is None or action is None:
            await ctx.send(
                "Uso: `!notify <boss> <add/rem>`\n"
                "Exemplo: `!notify Hydra add` - Para receber DM quando Hydra abrir\n"
                "`!notify Hydra rem` - Para parar de receber notificações\n\n"
                "Bosses disponíveis: " + ", ".join(boss_timers.keys())
            )
            return
        
        full_boss_name = get_boss_by_abbreviation(boss_name)
        if full_boss_name is None:
            await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
            return
        
        boss_name = full_boss_name
        user_id = str(ctx.author.id)
        
        if action.lower() in ['add', 'adicionar', 'a']:
            if boss_name not in user_notifications[user_id]:
                if add_user_notification(user_id, boss_name):
                    user_notifications[user_id].append(boss_name)
                    await ctx.send(f"✅ Você será notificado quando **{boss_name}** estiver disponível!")
                else:
                    await ctx.send("❌ Ocorreu um erro ao salvar sua preferência. Tente novamente.")
            else:
                await ctx.send(f"ℹ Você já está sendo notificado para **{boss_name}**.")
        
        elif action.lower() in ['rem', 'remover', 'r']:
            if boss_name in user_notifications[user_id]:
                if remove_user_notification(user_id, boss_name):
                    user_notifications[user_id].remove(boss_name)
                    await ctx.send(f"✅ Você NÃO será mais notificado para **{boss_name}**.")
                else:
                    await ctx.send("❌ Ocorreu um erro ao remover sua notificação. Tente novamente.")
            else:
                await ctx.send(f"ℹ Você não tinha notificação ativa para **{boss_name}**.")
        else:
            await ctx.send("Ação inválida. Use 'add' para adicionar ou 'rem' para remover.")

    @bot.command(name='mynotifications')
    async def my_notifications_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        user_id = str(ctx.author.id)
        notifications = user_notifications.get(user_id, [])
        
        if not notifications:
            await ctx.send("Você não tem notificações ativas para nenhum boss.")
        else:
            await ctx.send(
                f"🔔 **Suas notificações ativas:**\n"
                + "\n".join(f"- {boss}" for boss in notifications)
                + "\n\nUse `!notify <boss> rem` para remover notificações."
            )

    @bot.command(name='historico')
    async def history_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        embed = await create_history_embed()
        await ctx.send(embed=embed)

    @bot.command(name='naoanotados')
    async def unrecorded_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        embed = await create_unrecorded_embed()
        await ctx.send(embed=embed)

    @bot.command(name='backup')
    async def backup_command(ctx, action: str = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
        # Verificar permissões
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Apenas administradores podem usar este comando.")
            return
        
        if action is None:
            await ctx.send("Uso: `!backup create` ou `!backup restore`")
            return
        
        if action.lower() == 'create':
            backup_file = create_backup()
            if backup_file:
                try:
                    with open(backup_file, 'rb') as f:
                        await ctx.send(
                            f"✅ Backup criado com sucesso!",
                            file=discord.File(f, filename=backup_file)
                        )
                except Exception as e:
                    await ctx.send(f"✅ Backup criado, mas erro ao enviar arquivo: {e}")
            else:
                await ctx.send("❌ Falha ao criar backup!")
        
        elif action.lower() == 'restore':
            # Verificar se há arquivos de backup
            backup_files = [f for f in os.listdir() if f.startswith('backup_') and f.endswith('.json')]
            if not backup_files:
                await ctx.send("Nenhum arquivo de backup encontrado.")
                return
            
            # Criar menu de seleção
            view = discord.ui.View(timeout=120)
            select = discord.ui.Select(
                placeholder="Selecione um backup para restaurar",
                options=[discord.SelectOption(label=f) for f in backup_files]
            )
            
            async def restore_selected(interaction: discord.Interaction):
                await interaction.response.defer()
                backup_file = select.values[0]
                
                if restore_backup(backup_file):
                    # Recarregar dados do banco
                    load_db_data(boss_timers, user_stats, user_notifications)
                    
                    await interaction.followup.send(
                        f"✅ Backup **{backup_file}** restaurado com sucesso!"
                    )
                    
                    # Atualizar tabela
                    await update_table(interaction.channel)
                else:
                    await interaction.followup.send(
                        f"❌ Falha ao restaurar backup **{backup_file}**!"
                    )
            
            select.callback = restore_selected
            view.add_item(select)
            
            await ctx.send("Selecione o backup para restaurar:", view=view)
        
        else:
            await ctx.send("Ação inválida. Use `create` ou `restore`")

    @bot.command(name='setupboss')
    async def setup_boss(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
            
        embed = create_boss_embed()
        view = BossControlView()
        await ctx.send(embed=embed, view=view)

    @bot.command(name='bosshelp')
    async def boss_help(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return

        embed = discord.Embed(
            title="📚 Ajuda do Boss Timer",
            description=f"Todos os comandos devem ser usados neste canal (ID: {NOTIFICATION_CHANNEL_ID})",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="!boss <nome> <sala> HH:MM",
            value="Registra a morte de um boss no horário especificado\nExemplo: `!boss Hydra 8 14:30`\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno\nFormatos de hora aceitos: HH:MM ou HHhMM",
            inline=False
        )
        embed.add_field(
            name="Botões de Controle",
            value="Use os botões abaixo da tabela para:\n- 📝 Anotar boss derrotado\n- ❌ Limpar timer de boss\n- 🏆 Ver ranking de anotações\n- ⏳ Ver próximos bosses\n- 🔔 Gerenciar notificações por DM\n- 💾 Backup/Restore (apenas admins)\n- 📜 Ver histórico de anotações\n- ❌ Ver bosses não anotados",
            inline=False
        )
        embed.add_field(
            name="!bosses [compact]",
            value="Mostra a tabela com os horários (adicione 'compact' para ver apenas bosses ativos)",
            inline=False
        )
        embed.add_field(
            name="!nextboss",
            value="Mostra os próximos bosses que vão abrir e os que já estão abertos",
            inline=False
        )
        embed.add_field(
            name="!clearboss <nome> [sala]",
            value="Reseta o timer de um boss (opcional: especifique a sala, senão limpa todas)",
            inline=False
        )
        embed.add_field(
            name="!ranking",
            value="Mostra o ranking de quem mais anotou bosses (com medalhas para o Top 3)",
            inline=False
        )
        embed.add_field(
            name="!notify <boss> <add/rem>",
            value="Ativa/desativa notificação por DM quando o boss abrir\nEx: `!notify Hydra add`",
            inline=False
        )
        embed.add_field(
            name="!mynotifications",
            value="Mostra seus bosses marcados para notificação",
            inline=False
        )
        embed.add_field(
            name="!historico",
            value="Mostra as últimas 10 anotações de bosses",
            inline=False
        )
        embed.add_field(
            name="!naoanotados",
            value="Mostra os últimos bosses que fecharam sem anotações",
            inline=False
        )
        embed.add_field(
            name="!backup <create|restore>",
            value="Cria ou restaura um backup dos dados (apenas admins)",
            inline=False
        )
        embed.add_field(
            name="!setupboss",
            value="Recria a tabela com botões de controle",
            inline=False
        )
        embed.add_field(
            name="Bosses disponíveis",
            value="\n".join(boss_timers.keys()),
            inline=False
        )
        embed.add_field(
            name="Salas disponíveis",
            value=", ".join(map(str, boss_timers.get(list(boss_timers.keys())[0], {}).keys())),
            inline=False
        )
        
        await ctx.send(embed=embed)

    # Iniciar as tasks
    check_boss_respawns.start()
    live_table_updater.start()
    periodic_table_update.start()
    daily_backup.start()

    # Adicionar a view persistente
    bot.add_view(BossControlView())