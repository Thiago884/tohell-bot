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
from shared_functions import (
    get_boss_by_abbreviation, format_time_remaining, 
    parse_time_input, validate_time, get_next_bosses,
    send_notification_dm
)
from views import BossControlView

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

async def setup_utility_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID,
                               create_boss_embed_func, update_table_func, create_next_bosses_embed_func,
                               create_ranking_embed_func, create_history_embed_func, create_unrecorded_embed_func):
    
    # Mapeamento de imagens dos bosses
    BOSS_IMAGES = {
        "Super Red Dragon": f"{os.getenv('PUBLIC_URL', '')}/static/super-red-dragon.jpg",
        "Hell Maine": f"{os.getenv('PUBLIC_URL', '')}/static/hellmaine.png",
        "Illusion of Kundun": f"{os.getenv('PUBLIC_URL', '')}/static/relics-of-kundun.jpg",
        "Death Beam Knight": f"{os.getenv('PUBLIC_URL', '')}/static/DBK.png",
        "Genocider": f"{os.getenv('PUBLIC_URL', '')}/static/GENOCIDER.png",
        "Phoenix of Darkness": f"{os.getenv('PUBLIC_URL', '')}/static/Phoenix.png",
        "Hydra": f"{os.getenv('PUBLIC_URL', '')}/static/hydra.png",
        "Rei Kundun": f"{os.getenv('PUBLIC_URL', '')}/static/Rei_Kundun.jpg"
    }

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
        conn = connect_db()
        if conn is None:
            return discord.Embed(title="Erro", description="Não foi possível conectar ao banco de dados", color=discord.Color.red())
        
        try:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
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
            
            unrecorded = cursor.fetchall()
            
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
            conn.close()

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

    # Mapeamento de drops dos bosses
    BOSS_DROPS = {
        "Super Red Dragon": {
            "abreviações": ["red", "red dragon"],
            "drops": [
                "50% Jewel of Bless (pacote 30 ~ 60 unidades)",
                "50% Jewel of Soul (pacote 30 ~ 60 unidades)"
            ]
        },
        "Hell Maine": {
            "abreviações": ["hell", "hell maine"],
            "drops": [
                "50% Jewel of Bless (pacote 30 ~ 60 unidades)",
                "50% Jewel of Soul (pacote 30 ~ 60 unidades)"
            ]
        },
        "Illusion of Kundun": {
            "abreviações": ["illusion", "kundun", "iok"],
            "drops": [
                "25% Jewel of Bless (pacote 10 unidades)",
                "25% Jewel of Soul (pacote 10 unidades)",
                "5% Jewel of Bless (pacote 20 unidades)",
                "5% Jewel of Soul (pacote 20 unidades)",
                "5% Jewel of Bless (pacote 30 unidades)",
                "5% Jewel of Soul (pacote 30 unidades)",
                "5% SD Potion +13 (100 unidades)",
                "5% Complex Potion +13 (100 unidades)",
                "5% SD Potion +13 (50 unidades)",
                "5% Complex Potion +13 (50 unidades)",
                "5% 5x Large Healing Potion +13 (100 unidades)",
                "5% 5x Healing Potion +13 (60 unidades)",
                "10% 5x E-Zen"
            ]
        },
        "Death Beam Knight": {
            "abreviações": ["dbk", "death beam", "beam knight"],
            "drops": [
                "20% Small Complex Potion +13 (30 ~ 100 unidades)",
                "25% Complex Potion +13 (30 ~ 100 unidades)",
                "20% Small SD Potion +13 (30 ~ 100 unidades)",
                "25% SD Potion +13 (30 ~ 100 unidades)",
                "5% Sign of lord (255 unidades)",
                "5% 5~10x Jewel of Guardian"
            ]
        },
        "Genocider": {
            "abreviações": ["geno", "genocider"],
            "drops": [
                "20% 1 ~ 10x Jewel of Harmony",
                "80% 5 ~ 10x Gemstone"
            ]
        },
        "Phoenix of Darkness": {
            "abreviações": ["phoenix", "dark phoenix"],
            "drops": [
                "40% 1 ~ 4x Loch's Feather",
                "30% 1 ~ 3x Crest of monarch",
                "30% 1 ~ 2x Spirit of Dark Horse / Spirit of Dark Spirit"
            ]
        },
        "Hydra": {
            "abreviações": ["hydra"],
            "drops": [
                "50% 10x Jewel of Chaos",
                "50% SD Potion (15 unidades) / Complex Potion (15 unidades)"
            ]
        },
        "Rei Kundun": {
            "abreviações": ["rei", "rei kundun"],
            "drops": [
                "3x (três vezes os seguintes itens e porcentagem respectiva):",
                "100% Drop garantido",
                "53,85% Jewel of Bless (pacote 10 unidades)",
                "30,77% Jewel of Soul (pacote 10 unidades)",
                "7,69% Jewel of Bless (pacote 20 ~ 60 unidades)",
                "7,69% Jewel of Soul (pacote 20 ~ 60 unidades)",
                "3x (três vezes os seguintes itens e porcentagem respectiva):",
                "100% Drop possível",
                "25% Item Ancient Aleatório",
                "75% Sem drop",
                "Notas adicionais:",
                "Existem 2 tipos de drop no Kundun: joias e/ou Item Ancient.",
                "Para cada tipo é feito o cálculo acima (3 sorteios cada).",
                "Sempre haverá drop de joias, mas nem sempre de Item Ancient.",
                "Probabilidades aproximadas para Item Ancient após os 3 sorteios:",
                "0 Itens Ancient: 42%",
                "1 Item Ancient: 42%",
                "2 Itens Ancient: 14%",
                "3 Itens Ancient: 2%"
            ]
        }
    }

    # Comandos
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
        
        full_boss_name = get_boss_by_abbreviation(boss_name, boss_timers)
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

    @bot.command(name='drops')
    async def drops_command(ctx, boss_name: str = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return

        if boss_name is None:
            # Mostrar lista de bosses com abreviações
            embed = discord.Embed(
                title="📚 Drops dos Bosses",
                description="Use `!drops <nome_do_boss>` para ver informações específicas\nExemplo: `!drops hydra`",
                color=discord.Color.blue()
            )
            
            for boss, info in BOSS_DROPS.items():
                embed.add_field(
                    name=f"**{boss}**",
                    value=f"Abreviações: {', '.join(info['abreviações'])}",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            return

        # Encontrar o boss pelo nome ou abreviação
        boss_found = None
        boss_name_lower = boss_name.lower()
        
        for boss, info in BOSS_DROPS.items():
            if boss_name_lower in [b.lower() for b in info['abreviações']] or boss_name_lower in boss.lower():
                boss_found = boss
                break

        if not boss_found:
            await ctx.send(f"Boss não encontrado. Use `!drops` sem argumentos para ver a lista de bosses.")
            return

        # Criar embed com os drops do boss
        embed = discord.Embed(
            title=f"🎁 Drops do {boss_found}",
            color=discord.Color.green()
        )
        
        # Adicionar thumbnail se existir
        if boss_found in BOSS_IMAGES:
            embed.set_thumbnail(url=BOSS_IMAGES[boss_found])
        
        for drop in BOSS_DROPS[boss_found]['drops']:
            embed.add_field(
                name="\u200b",
                value=f"• {drop}",
                inline=False
            )
        
        embed.set_footer(text=f"Abreviações: {', '.join(BOSS_DROPS[boss_found]['abreviações'])}")
        await ctx.send(embed=embed)

    @bot.command(name='backup')
    async def backup_command(ctx, action: str = None):
        if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
            await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
            return
        
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
            backup_files = [f for f in os.listdir() if f.startswith('backup_') and f.endswith('.json')]
            if not backup_files:
                await ctx.send("Nenhum arquivo de backup encontrado.")
                return
            
            view = discord.ui.View(timeout=120)
            select = discord.ui.Select(
                placeholder="Selecione um backup para restaurar",
                options=[discord.SelectOption(label=f) for f in backup_files]
            )
            
            async def restore_selected(interaction: discord.Interaction):
                await interaction.response.defer()
                backup_file = select.values[0]
                
                if restore_backup(backup_file):
                    load_db_data(boss_timers, user_stats, user_notifications)
                    
                    await interaction.followup.send(
                        f"✅ Backup **{backup_file}** restaurado com sucesso!"
                    )
                    
                    await update_table_func(interaction.channel)
                else:
                    await interaction.followup.send(
                        f"❌ Falha ao restaurar backup **{backup_file}**!"
                    )
            
            select.callback = restore_selected
            view.add_item(select)
            
            await ctx.send("Selecione o backup para restaurar:", view=view)
        
        else:
            await ctx.send("Ação inválida. Use `create` ou `restore`")

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
            name="!drops [boss]",
            value="Mostra os possíveis drops de um boss específico ou lista todos os bosses\nEx: `!drops hydra` ou `!drops` para lista completa",
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
    @tasks.loop(hours=24)
    async def daily_backup():
        try:
            backup_file = create_backup()
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