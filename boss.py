import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import os
import pytz
import mysql.connector
from flask import Flask
from threading import Thread
from collections import defaultdict
import random
import traceback

# Configurações do Flask para keep-alive
app = Flask('')

@app.route('/')
def home():
    return "Bot está rodando!"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/status')
def status():
    if bot.is_ready():
        return "Bot is online", 200
    else:
        return "Bot is connecting", 503

def run():
    app.run(host='0.0.0.0', port=8080, threaded=True)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Conexão com o banco de dados MySQL
def connect_db():
    try:
        conn = mysql.connector.connect(
            host="localhost",
            user="thia5326_tohell",
            password="Thi@goba1102@@",
            database="thia5326_tohell_bot"
        )
        return conn
    except mysql.connector.Error as err:
        print(f"Erro ao conectar ao banco de dados: {err}")
        return None

# Inicializar o banco de dados
def init_db():
    conn = connect_db()
    if conn is None:
        return
    
    try:
        cursor = conn.cursor()
        
        # Tabela de timers de boss
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS boss_timers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            boss_name VARCHAR(50) NOT NULL,
            sala INT NOT NULL,
            death_time DATETIME NOT NULL,
            respawn_time DATETIME NOT NULL,
            closed_time DATETIME NOT NULL,
            recorded_by VARCHAR(50) NOT NULL,
            opened_notified BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY boss_sala (boss_name, sala)
        )
        """)
        
        # Tabela de estatísticas de usuários
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id VARCHAR(20) PRIMARY KEY,
            username VARCHAR(50) NOT NULL,
            count INT DEFAULT 0,
            last_recorded DATETIME,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)
        
        conn.commit()
        print("Banco de dados inicializado com sucesso!")
    except mysql.connector.Error as err:
        print(f"Erro ao inicializar banco de dados: {err}")
    finally:
        conn.close()

# Carregar dados do banco de dados
def load_db_data():
    conn = connect_db()
    if conn is None:
        return
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Carregar timers de boss
        cursor.execute("SELECT * FROM boss_timers")
        timers = cursor.fetchall()
        
        for timer in timers:
            boss_name = timer['boss_name']
            sala = timer['sala']
            
            if boss_name in boss_timers and sala in boss_timers[boss_name]:
                boss_timers[boss_name][sala] = {
                    'death_time': timer['death_time'].replace(tzinfo=brazil_tz),
                    'respawn_time': timer['respawn_time'].replace(tzinfo=brazil_tz),
                    'closed_time': timer['closed_time'].replace(tzinfo=brazil_tz),
                    'recorded_by': timer['recorded_by'],
                    'opened_notified': timer['opened_notified']
                }
        
        # Carregar estatísticas de usuários
        cursor.execute("SELECT * FROM user_stats")
        stats = cursor.fetchall()
        
        for stat in stats:
            user_stats[stat['user_id']] = {
                'count': stat['count'],
                'last_recorded': stat['last_recorded'].replace(tzinfo=brazil_tz) if stat['last_recorded'] else None
            }
        
        print("Dados carregados do banco de dados com sucesso!")
    except mysql.connector.Error as err:
        print(f"Erro ao carregar dados do banco: {err}")
    finally:
        conn.close()

# Salvar dados no banco de dados
def save_timer(boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified=False):
    conn = connect_db()
    if conn is None:
        return
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO boss_timers (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            death_time = VALUES(death_time),
            respawn_time = VALUES(respawn_time),
            closed_time = VALUES(closed_time),
            recorded_by = VALUES(recorded_by),
            opened_notified = VALUES(opened_notified)
        """, (boss_name, sala, death_time, respawn_time, closed_time, recorded_by, opened_notified))
        
        conn.commit()
    except mysql.connector.Error as err:
        print(f"Erro ao salvar timer: {err}")
    finally:
        conn.close()

def save_user_stats(user_id, username, count, last_recorded):
    conn = connect_db()
    if conn is None:
        return
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO user_stats (user_id, username, count, last_recorded)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            username = VALUES(username),
            count = VALUES(count),
            last_recorded = VALUES(last_recorded)
        """, (user_id, username, count, last_recorded))
        
        conn.commit()
    except mysql.connector.Error as err:
        print(f"Erro ao salvar estatísticas do usuário: {err}")
    finally:
        conn.close()

def clear_timer(boss_name, sala=None):
    conn = connect_db()
    if conn is None:
        return
    
    try:
        cursor = conn.cursor()
        
        if sala is None:
            cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s", (boss_name,))
        else:
            cursor.execute("DELETE FROM boss_timers WHERE boss_name = %s AND sala = %s", (boss_name, sala))
        
        conn.commit()
    except mysql.connector.Error as err:
        print(f"Erro ao limpar timer: {err}")
    finally:
        conn.close()

# Variáveis de configuração
BOSSES = [
    "Super Red Dragon",
    "Hell Maine",
    "Illusion of Kundun",
    "Death Beam Knight",
    "Genocider",
    "Phoenix of Darkness",
    "Hydra",
    "Rei Kundun"
]

SALAS = [1, 2, 3, 4, 5, 6, 7, 8]

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

# Estrutura de dados para armazenar os timers
boss_timers = {
    boss: {
        sala: {
            'death_time': None,
            'respawn_time': None,
            'closed_time': None,
            'recorded_by': None,
            'opened_notified': False
        } for sala in SALAS
    } for boss in BOSSES
}

user_stats = defaultdict(lambda: {'count': 0, 'last_recorded': None})

# DEFINA AQUI O ID DO CANAL DESEJADO
NOTIFICATION_CHANNEL_ID = 1364594212280078457  # ← Alterar este valor

# Variável para armazenar a mensagem da tabela com botões
table_message = None

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
            for b in BOSSES:
                if b.lower() == boss:
                    return b
    
    for boss in BOSSES:
        if abbrev in boss.lower():
            return boss
    
    return None

def create_boss_embed(compact=False):
    now = datetime.now(brazil_tz)
    
    embed = discord.Embed(
        title=f"BOSS TIMER - {now.strftime('%d/%m/%Y %H:%M:%S')} BRT",
        color=discord.Color.gold()
    )
    
    for boss in BOSSES:
        boss_info = []
        for sala in SALAS:
            timers = boss_timers[boss][sala]
            
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
        
        last_recorded = stats['last_recorded'].strftime("%d/%m %H:%M") if stats['last_recorded'] else "Nunca"
        ranking_text.append(
            f"**{idx+1}.** {username} - {stats['count']} anotações\n"
            f"Última: {last_recorded}"
        )
    
    embed.description = "\n\n".join(ranking_text)
    return embed

async def update_table(channel):
    global table_message
    
    try:
        embed = create_boss_embed()
        view = BossControlView()
        
        if table_message:
            try:
                await table_message.edit(embed=embed, view=view)
                return
            except:
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

    for boss in BOSSES:
        for sala in SALAS:
            timers = boss_timers[boss][sala]
            respawn_time = timers['respawn_time']
            closed_time = timers['closed_time']
            
            if respawn_time is not None:
                if now >= respawn_time and closed_time is not None and now < closed_time:
                    if not timers.get('opened_notified', False):
                        recorded_by = f"\nAnotado por: {timers['recorded_by']}" if timers['recorded_by'] else ""
                        notifications.append(f"🟢 **{boss} (Sala {sala})** está disponível AGORA! (aberto até {closed_time:%d/%m %H:%M} BRT){recorded_by}")
                        boss_timers[boss][sala]['opened_notified'] = True
                        save_timer(boss, sala, timers['death_time'], respawn_time, closed_time, timers['recorded_by'], True)
                
                elif now >= (respawn_time - timedelta(minutes=5)) and now < respawn_time and closed_time is not None:
                    time_left = format_time_remaining(respawn_time)
                    recorded_by = f"\nAnotado por: {timers['recorded_by']}" if timers['recorded_by'] else ""
                    notifications.append(f"🟡 **{boss} (Sala {sala})** estará disponível em {time_left} ({respawn_time:%d/%m %H:%M} BRT){recorded_by}")
                
                elif closed_time is not None and now >= closed_time:
                    if not timers.get('opened_notified', False):
                        notifications.append(f"🔴 **{boss} (Sala {sala})** FECHOU sem nenhuma anotação durante o período aberto!")
                    else:
                        notifications.append(f"🔴 **{boss} (Sala {sala})** FECHOU!")
                    
                    boss_timers[boss][sala] = {
                        'death_time': None,
                        'respawn_time': None,
                        'closed_time': None,
                        'recorded_by': None,
                        'opened_notified': False
                    }
                    clear_timer(boss, sala)

    if notifications:
        message = "**Notificações de Boss:**\n" + "\n".join(notifications)
        await channel.send(message)
    
    await update_table(channel)

@tasks.loop(minutes=30)
async def periodic_table_update():
    # Aleatorizar o intervalo entre 30 e 60 minutos
    periodic_table_update.change_interval(minutes=random.randint(30, 60))
    
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        embed = create_boss_embed()
        await channel.send("**Atualização periódica dos horários de boss:**", embed=embed)

class BossControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Anotar Horário", style=discord.ButtonStyle.green, custom_id="boss_control:anotar", emoji="📝")
    async def boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Criamos a view primeiro
            view = discord.ui.View(timeout=180)
            
            select_boss = discord.ui.Select(
                placeholder="Selecione o Boss",
                options=[
                    discord.SelectOption(label="Rei Kundun", value="rei", emoji="👑"),
                    discord.SelectOption(label="Phoenix of Darkness", value="phoenix", emoji="🦅"),
                    discord.SelectOption(label="Illusion of Kundun", value="illusion", emoji="👻"),
                    discord.SelectOption(label="Death Beam Knight", value="dbk", emoji="⚔️"),
                    discord.SelectOption(label="Genocider", value="geno", emoji="💀"),
                    discord.SelectOption(label="Hell Maine", value="hell", emoji="🔥"),
                    discord.SelectOption(label="Super Red Dragon", value="red", emoji="🐉"),
                    discord.SelectOption(label="Hydra", value="hydra", emoji="🐍")
                ]
            )
            
            select_sala = discord.ui.Select(
                placeholder="Selecione a Sala",
                options=[discord.SelectOption(label=f"Sala {sala}", value=str(sala)) for sala in SALAS]
            )
            
            ontem_btn = discord.ui.Button(
                label="Foi Ontem?",
                style=discord.ButtonStyle.gray,
                emoji="⬜",
                custom_id="ontem_btn"
            )
            
            cancel_btn = discord.ui.Button(
                label="Cancelar",
                style=discord.ButtonStyle.red,
                emoji="❌",
                custom_id="cancel_btn"
            )
            
            selected_boss = None
            selected_sala = None
            foi_ontem = False
            
            async def boss_select_callback(interaction: discord.Interaction):
                nonlocal selected_boss
                selected_boss = select_boss.values[0]
                await interaction.response.defer()
            
            async def sala_select_callback(interaction: discord.Interaction):
                nonlocal selected_sala
                selected_sala = int(select_sala.values[0])
                await interaction.response.defer()
            
            async def ontem_callback(interaction: discord.Interaction):
                nonlocal foi_ontem
                foi_ontem = not foi_ontem
                ontem_btn.emoji = "✅" if foi_ontem else "⬜"
                ontem_btn.style = discord.ButtonStyle.green if foi_ontem else discord.ButtonStyle.gray
                await interaction.response.edit_message(view=view)
            
            async def cancel_callback(interaction: discord.Interaction):
                await interaction.response.edit_message(content="Operação cancelada", view=None)
            
            async def submit_callback(interaction: discord.Interaction):
                nonlocal selected_boss, selected_sala, foi_ontem
                
                if not selected_boss or not selected_sala:
                    await interaction.followup.send("Selecione o boss e a sala primeiro!", ephemeral=True)
                    return
                
                class TimeInputModal(discord.ui.Modal, title="Informe o Horário"):
                    time_input = discord.ui.TextInput(
                        label="Horário da morte (HH:MM)",
                        placeholder="Ex: 14:30",
                        required=True,
                        max_length=5
                    )
                    
                    async def on_submit(self, interaction: discord.Interaction):
                        try:
                            hora, minuto = map(int, self.time_input.value.split(':'))
                            now = datetime.now(brazil_tz)
                            death_time = now.replace(hour=hora, minute=minuto, second=0, microsecond=0)
                            
                            if foi_ontem:
                                death_time -= timedelta(days=1)
                            elif death_time > now:
                                death_time -= timedelta(days=1)
                            
                            respawn_time = death_time + timedelta(hours=8)
                            recorded_by = interaction.user.name
                            
                            boss_map = {
                                'red': 'Super Red Dragon',
                                'hell': 'Hell Maine',
                                'illusion': 'Illusion of Kundun',
                                'dbk': 'Death Beam Knight',
                                'geno': 'Genocider',
                                'phoenix': 'Phoenix of Darkness',
                                'hydra': 'Hydra',
                                'rei': 'Rei Kundun'
                            }
                            
                            boss_name = boss_map[selected_boss]
                            
                            boss_timers[boss_name][selected_sala] = {
                                'death_time': death_time,
                                'respawn_time': respawn_time,
                                'closed_time': respawn_time + timedelta(hours=4),
                                'recorded_by': recorded_by,
                                'opened_notified': False
                            }
                            
                            user_id = str(interaction.user.id)
                            user_stats[user_id]['count'] += 1
                            user_stats[user_id]['last_recorded'] = now
                            
                            save_timer(boss_name, selected_sala, death_time, respawn_time, respawn_time + timedelta(hours=4), recorded_by)
                            save_user_stats(user_id, interaction.user.name, user_stats[user_id]['count'], now)
                            
                            await interaction.response.send_message(
                                f"✅ **{boss_name} (Sala {selected_sala})** registrado por {recorded_by}:\n"
                                f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                                f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                                f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT",
                                ephemeral=True
                            )
                            
                            await update_table(interaction.channel)
                            
                        except ValueError:
                            await interaction.response.send_message(
                                "Formato de hora inválido. Use HH:MM (ex: 14:30)",
                                ephemeral=True
                            )
                
                await interaction.response.send_modal(TimeInputModal())
            
            select_boss.callback = boss_select_callback
            select_sala.callback = sala_select_callback
            ontem_btn.callback = ontem_callback
            cancel_btn.callback = cancel_callback
            
            view.add_item(select_boss)
            view.add_item(select_sala)
            view.add_item(ontem_btn)
            
            submit_btn = discord.ui.Button(
                label="Enviar",
                style=discord.ButtonStyle.green,
                emoji="✅",
                custom_id="submit_btn"
            )
            submit_btn.callback = submit_callback
            
            # Adicionamos os botões diretamente na view principal
            view.add_item(cancel_btn)
            view.add_item(submit_btn)
            
            # Respondemos à interação apenas uma vez
            await interaction.response.send_message(
                "📝 **Anotar Horário de Boss**\nSelecione o boss, sala e marque se foi ontem:",
                view=view,
                ephemeral=False
            )
            
        except Exception as e:
            print(f"ERRO DETALHADO no botão de anotar: {str(e)}")
            traceback.print_exc()
            try:
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
            except Exception as e:
                print(f"Erro ao enviar mensagem de erro: {e}")
    
    @discord.ui.button(label="Limpar Boss", style=discord.ButtonStyle.red, custom_id="boss_control:limpar", emoji="❌")
    async def clear_boss_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()
            
            view = discord.ui.View(timeout=180)
            
            select_boss = discord.ui.Select(
                placeholder="Selecione um boss",
                options=[discord.SelectOption(label=boss) for boss in BOSSES]
            )
            
            select_sala = discord.ui.Select(
                placeholder="Selecione uma sala",
                options=[]
            )
            
            async def boss_selected(interaction: discord.Interaction):
                boss_name = select_boss.values[0]
                
                salas_com_timer = [
                    sala for sala in SALAS 
                    if boss_timers[boss_name][sala]['death_time'] is not None
                ]
                
                if not salas_com_timer:
                    await interaction.response.send_message(f"Nenhum timer ativo para {boss_name}", ephemeral=True)
                    return
                    
                select_sala.options = [
                    discord.SelectOption(label=f"Sala {sala}", value=str(sala))
                    for sala in salas_com_timer
                ]
                
                await interaction.response.edit_message(
                    content=f"Selecione a sala de {boss_name} para limpar:",
                    view=view
                )
            
            async def sala_selected(interaction: discord.Interaction):
                boss_name = select_boss.values[0]
                sala = int(select_sala.values[0])
                
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
                
                await update_table(interaction.channel)
            
            select_boss.callback = boss_selected
            select_sala.callback = sala_selected
            view.add_item(select_boss)
            view.add_item(select_sala)
            
            await interaction.followup.send(
                "Selecione o boss para limpar:",
                view=view,
                ephemeral=True
            )
        except Exception as e:
            print(f"ERRO DETALHADO no botão de limpar: {str(e)}")
            traceback.print_exc()
            try:
                await interaction.followup.send("Ocorreu um erro ao processar sua solicitação.", ephemeral=True)
            except:
                pass
    
    @discord.ui.button(label="Ranking", style=discord.ButtonStyle.blurple, custom_id="boss_control:ranking", emoji="🏆")
    async def ranking_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = await create_ranking_embed()
            await interaction.response.send_message(embed=embed, ephemeral=False)
        except Exception as e:
            print(f"ERRO DETALHADO no botão de ranking: {str(e)}")
            traceback.print_exc()
            await interaction.response.send_message("Ocorreu um erro ao gerar o ranking.", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user.name}')
    print(f'Canal de notificação configurado para ID: {NOTIFICATION_CHANNEL_ID}')
    await bot.change_presence(activity=discord.Game(name="!bosshelp para ajuda"))
    
    # Registrar a view persistentemente
    bot.add_view(BossControlView())
    
    # Inicializar banco de dados
    init_db()
    load_db_data()
    
    check_boss_respawns.start()
    live_table_updater.start()
    periodic_table_update.start()
    
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        await update_table(channel)

@bot.command(name='boss')
async def boss_command(ctx, boss_name: str = None, sala: int = None, hora_morte: str = None):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return

    if boss_name is None or sala is None or hora_morte is None:
        await ctx.send("Por favor, use: `!boss <nome_do_boss> <sala> HH:MM`\nExemplo: `!boss Hydra 8 14:30`\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
        return
    
    if sala not in SALAS:
        await ctx.send(f"Sala inválida. Salas disponíveis: {', '.join(map(str, SALAS))}")
        return
    
    full_boss_name = get_boss_by_abbreviation(boss_name)
    if full_boss_name is None:
        await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(BOSSES)}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
        return
    
    boss_name = full_boss_name
    
    try:
        hora, minuto = map(int, hora_morte.split(':'))
        now = datetime.now(brazil_tz)
        death_time = now.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        
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
        
        await update_table(ctx.channel)
    except ValueError:
        await ctx.send("Formato de hora inválido. Use HH:MM (ex: 14:30)")

@bot.command(name='bosses')
async def bosses_command(ctx, mode: str = None):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return
    
    compact = mode and mode.lower() in ['compact', 'c', 'resumo']
    embed = create_boss_embed(compact=compact)
    view = BossControlView()
    await ctx.send(embed=embed, view=view)

@bot.command(name='clearboss')
async def clear_boss(ctx, boss_name: str, sala: int = None):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return
    
    full_boss_name = get_boss_by_abbreviation(boss_name)
    if full_boss_name is None:
        await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(BOSSES)}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
        return
    
    boss_name = full_boss_name
    
    if sala is None:
        for s in SALAS:
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
        if sala not in SALAS:
            await ctx.send(f"Sala inválida. Salas disponíveis: {', '.join(map(str, SALAS))}")
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
        value="Registra a morte de um boss no horário especificado\nExemplo: `!boss Hydra 8 14:30`\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
        inline=False
    )
    embed.add_field(
        name="Botões de Controle",
        value="Use os botões abaixo da tabela para:\n- 📝 Anotar boss derrotado\n- ❌ Limpar timer de boss\n- 🏆 Ver ranking de anotações",
        inline=False
    )
    embed.add_field(
        name="!bosses [compact]",
        value="Mostra a tabela com os horários (adicione 'compact' para ver apenas bosses ativos)",
        inline=False
    )
    embed.add_field(
        name="!clearboss <nome> [sala]",
        value="Reseta o timer de um boss (opcional: especifique a sala, senão limpa todas)",
        inline=False
    )
    embed.add_field(
        name="!ranking",
        value="Mostra o ranking de quem mais anotou bosses",
        inline=False
    )
    embed.add_field(
        name="!setupboss",
        value="Recria a tabela com botões de controle",
        inline=False
    )
    embed.add_field(
        name="Bosses disponíveis",
        value="\n".join(BOSSES),
        inline=False
    )
    embed.add_field(
        name="Salas disponíveis",
        value=", ".join(map(str, SALAS)),
        inline=False
    )
    
    await ctx.send(embed=embed)

# Iniciar o bot
keep_alive()
token = os.getenv('DISCORD_TOKEN')
if not token:
    print("ERRO: Token não encontrado! Verifique as Secrets do Replit.")
    print("Certifique-se que a chave é 'DISCORD_TOKEN'")
else:
    print("Token encontrado, iniciando bot...")
    bot.run(token)