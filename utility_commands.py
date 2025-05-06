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

async def setup_utility_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID,
                               create_boss_embed_func, update_table_func, create_next_bosses_embed_func,
                               create_ranking_embed_func, create_history_embed_func, create_unrecorded_embed_func):
    
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

    async def create_unrecorded_embed():
        conn = await connect_db()
        if conn is None:
            return discord.Embed(title="Erro", description="Não foi possível conectar ao banco de dados", color=discord.Color.red())
        
        try:
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
                
                if not unrecorded:
                    return discord.Embed(
                        title="Bosses Fechados Recentemente",
                        description="Nenhum boss foi fechado recentemente.",
                        color=discord.Color.blue()
                    )
                
                embed = discord.Embed(
                    title="🔴 Últimos Bosses Fechados",
                    description="Estes bosses foram fechados recentemente:",
                    color=discord.Color.red()
                )
                
                for idx, record in enumerate(unrecorded, 1):
                    embed.add_field(
                        name=f"{idx}. {record['boss_name']} (Sala {record['sala']})",
                        value=(
                            f"⏱ Morte registrada: {record['death_time'].strftime('%d/%m %H:%M')}\n"
                            f"🔄 Período aberto: {record['respawn_time'].strftime('%d/%m %H:%M')} "
                            f"até {record['closed_time'].strftime('%d/%m %H:%M')}\n"
                            f"👤 Registrado por: {record['recorded_by'] or 'Ninguém'}"
                        ),
                        inline=False
                    )
                
                return embed
                
        except Exception as e:
            print(f"Erro ao buscar bosses fechados: {e}")
            return discord.Embed(
                title="Erro",
                description="Ocorreu um erro ao buscar os bosses fechados",
                color=discord.Color.red()
            )
        finally:
            await conn.ensure_closed()

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

    async def create_history_embed():
        conn = await connect_db()
        if conn is None:
            return discord.Embed(title="Erro", description="Não foi possível conectar ao banco de dados", color=discord.Color.red())
        
        try:
            async with conn.cursor() as cursor:
                await cursor.execute("""
                SELECT boss_name, sala, death_time, respawn_time, recorded_by 
                FROM boss_timers 
                WHERE death_time IS NOT NULL
                ORDER BY death_time DESC 
                LIMIT 10
                """)
                
                history = await cursor.fetchall()
                
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
            await conn.ensure_closed()

    # Comandos
    @bot.command(name='ranking')
    async def ranking_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
            return
        
        embed = await create_ranking_embed()
        await ctx.send(embed=embed)

    @bot.command(name='notify')
    async def notify_command(ctx, boss_name: str = None, action: str = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
            return
        
        if boss_name is None or action is None:
            await ctx.send(
                "Uso: `!notify <boss> <add/rem>`\n"
                "Exemplo: `!notify Hydra add` - Para receber DM quando Hydra abrir\n"
                "`!notify Hydra rem` - Para parar de receber notificações\n\n"
                "Bosses disponíveis: " + ", ".join(boss_timers.keys()),
                ephemeral=True
            )
            return
        
        full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers)
        if full_boss_name is None:
            await ctx.send(
                f"Boss inválido. Bosses disponíveis: {', '.join(boss_timers.keys())}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
                ephemeral=True
            )
            return
        
        boss_name = full_boss_name
        user_id = str(ctx.author.id)
        
        if action.lower() in ['add', 'adicionar', 'a']:
            if user_id not in user_notifications:
                user_notifications[user_id] = []
            
            if boss_name not in user_notifications[user_id]:
                if await add_user_notification(user_id, boss_name):
                    user_notifications[user_id].append(boss_name)
                    await ctx.send(
                        f"✅ Você será notificado quando **{boss_name}** estiver disponível!",
                        ephemeral=True
                    )
                else:
                    await ctx.send(
                        "❌ Ocorreu um erro ao salvar sua preferência. Tente novamente.",
                        ephemeral=True
                    )
            else:
                await ctx.send(
                    f"ℹ Você já está sendo notificado para **{boss_name}**.",
                    ephemeral=True
                )
        
        elif action.lower() in ['rem', 'remover', 'r']:
            if user_id in user_notifications and boss_name in user_notifications[user_id]:
                if await remove_user_notification(user_id, boss_name):
                    user_notifications[user_id].remove(boss_name)
                    await ctx.send(
                        f"✅ Você NÃO será mais notificado para **{boss_name}**.",
                        ephemeral=True
                    )
                else:
                    await ctx.send(
                        "❌ Ocorreu um erro ao remover sua notificação. Tente novamente.",
                        ephemeral=True
                    )
            else:
                await ctx.send(
                    f"ℹ Você não tinha notificação ativa para **{boss_name}**.",
                    ephemeral=True
                )
        else:
            await ctx.send(
                "Ação inválida. Use 'add' para adicionar ou 'rem' para remover.",
                ephemeral=True
            )

    @bot.command(name='mynotifications')
    async def my_notifications_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
            return
        
        user_id = str(ctx.author.id)
        notifications = user_notifications.get(user_id, [])
        
        if not notifications:
            await ctx.send("Você não tem notificações ativas para nenhum boss.", ephemeral=True)
        else:
            await ctx.send(
                f"🔔 **Suas notificações ativas:**\n"
                + "\n".join(f"- {boss}" for boss in notifications)
                + "\n\nUse `!notify <boss> rem` para remover notificações.",
                ephemeral=True
            )

    @bot.command(name='historico')
    async def history_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
            return
        
        embed = await create_history_embed()
        await ctx.send(embed=embed)

    @bot.command(name='naoanotados')
    async def unrecorded_command(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
            return
        
        embed = await create_unrecorded_embed()
        await ctx.send(embed=embed)

    @bot.command(name='backup')
    async def backup_command(ctx, action: str = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
            return
        
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Apenas administradores podem usar este comando.", ephemeral=True)
            return
        
        if action is None:
            await ctx.send("Uso: `!backup create` ou `!backup restore`", ephemeral=True)
            return
        
        if action.lower() == 'create':
            backup_file = await create_backup()
            if backup_file:
                try:
                    with open(backup_file, 'rb') as f:
                        await ctx.send(
                            f"✅ Backup criado com sucesso!",
                            file=discord.File(f, filename=backup_file),
                            ephemeral=True
                        )
                except Exception as e:
                    await ctx.send(
                        f"✅ Backup criado, mas erro ao enviar arquivo: {e}",
                        ephemeral=True
                    )
            else:
                await ctx.send("❌ Falha ao criar backup!", ephemeral=True)
        
        elif action.lower() == 'restore':
            backup_files = [f for f in os.listdir() if f.startswith('backup_') and f.endswith('.json')]
            if not backup_files:
                await ctx.send("Nenhum arquivo de backup encontrado.", ephemeral=True)
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
                        f"❌ Falha ao restaurar backup **{backup_file}**!",
                        ephemeral=True
                    )
            
            select.callback = restore_selected
            view.add_item(select)
            
            await ctx.send("Selecione o backup para restaurar:", view=view, ephemeral=True)
        
        else:
            await ctx.send("Ação inválida. Use `create` ou `restore`", ephemeral=True)

    @bot.command(name='bosshelp')
    async def boss_help(ctx):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!", ephemeral=True)
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

    # Tasks
    @tasks.loop(hours=24)
    async def daily_backup():
        try:
            backup_file = await create_backup()
            if backup_file:
                print(f"Backup diário realizado com sucesso: {backup_file}")
            else:
                print("Falha ao realizar backup diário")
        except Exception as e:
            print(f"Erro na rotina de backup: {e}")

    daily_backup.start()

    # Adicionar a view persistente
    bot.add_view(BossControlView(
        bot, 
        boss_timers, 
        user_stats, 
        user_notifications, 
        table_message, 
        NOTIFICATION_CHANNEL_ID,
        update_table_func,
        create_next_bosses_embed_func,
        create_ranking_embed,
        create_history_embed,
        create_unrecorded_embed
    ))