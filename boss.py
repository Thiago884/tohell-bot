import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import os
import pytz
from flask import Flask
from threading import Thread

# Configurações do Flask para keep-alive
app = Flask('')

@app.route('/')
def home():
    return "Bot está rodando!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

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

boss_timers = {boss: {'death_time': None, 'respawn_time': None, 'closed_time': None} for boss in BOSSES}

# DEFINA AQUI O ID DO CANAL DESEJADO
NOTIFICATION_CHANNEL_ID = 1364594212280078457  # ← Alterar este valor

# Variável para armazenar a mensagem da tabela
table_message = None

def format_time_remaining(target_time):
    now = datetime.now(brazil_tz)
    delta = target_time - now
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}h {minutes:02d}m"

def create_boss_table(compact=False):
    now = datetime.now(brazil_tz)
    
    # Sort bosses: open first, then upcoming, then closed
    sorted_bosses = sorted(BOSSES, key=lambda boss: (
        0 if (boss_timers[boss]['respawn_time'] and 
              now >= boss_timers[boss]['respawn_time'] and 
              (not boss_timers[boss]['closed_time'] or now < boss_timers[boss]['closed_time'])) 
        else 1 if (boss_timers[boss]['respawn_time'] and 
                  now < boss_timers[boss]['respawn_time']) 
        else 2
    ))
    
    if compact:
        # Filter only bosses with active timers
        sorted_bosses = [boss for boss in sorted_bosses 
                        if boss_timers[boss]['death_time'] is not None]
        if not sorted_bosses:
            return "```diff\n+ Nenhum boss ativo no momento +\n```"
    
    # Header
    table = "```diff\n"
    table += "+================================================================================+\n"
    table += f"| {'BOSS TIMER - ' + now.strftime('%d/%m/%Y %H:%M:%S') + ' BRT':^80} |\n"
    table += "+================================================================================+\n"
    table += "| BOSS                      |    MORTE      |   ABERTURA    |   FECHAMENTO    | STATUS |\n"
    table += "+---------------------------+---------------+---------------+-----------------+--------+\n"
    
    # Next bosses prediction
    upcoming_bosses = []
    for boss in sorted_bosses:
        timers = boss_timers[boss]
        if timers['respawn_time'] and now < timers['respawn_time']:
            time_left = format_time_remaining(timers['respawn_time'])
            upcoming_bosses.append(f"{boss} (em {time_left})")
    
    for boss in sorted_bosses:
        timers = boss_timers[boss]
        
        # Skip if in compact mode and no timer
        if compact and timers['death_time'] is None:
            continue
            
        # Format times
        death_time = timers['death_time'].strftime("%d/%m %H:%M") if timers['death_time'] else " " * 13
        respawn_time = timers['respawn_time'].strftime("%d/%m %H:%M") if timers['respawn_time'] else " " * 13
        closed_time = timers['closed_time'].strftime("%d/%m %H:%M") if timers['closed_time'] else " " * 15
        
        # Enhanced status with symbols
        status = ""
        if timers['respawn_time']:
            if now >= timers['respawn_time']:
                if timers['closed_time'] and now >= timers['closed_time']:
                    status = "🔴 FECHADO"
                else:
                    status = "🟢 ABERTO"
            else:
                time_left = format_time_remaining(timers['respawn_time'])
                status = f"🟡 EM {time_left}"
        else:
            status = "⚪ LIVRE"
        
        # Add row with Discord-compatible formatting
        table += f"| {boss:<25} | {death_time:^13} | {respawn_time:^13} | {closed_time:^15} | {status:^6} |\n"
    
    # Footer with upcoming bosses
    if upcoming_bosses and not compact:
        table += "+---------------------------+---------------+---------------+-----------------+--------+\n"
        table += f"| PRÓXIMOS BOSSES: {', '.join(upcoming_bosses):<63} |\n"
    
    table += "+================================================================================+\n```"
    
    return table

async def update_table(channel):
    global table_message
    
    try:
        table = create_boss_table()
        
        if table_message:
            try:
                await table_message.edit(content=table)
                return
            except:
                # Se falhar ao editar, cria nova mensagem
                table_message = None
        
        # Procura por mensagens existentes do bot para editar
        async for message in channel.history(limit=50):
            if message.author == bot.user and message.content.startswith("```diff"):
                try:
                    await message.edit(content=table)
                    table_message = message
                    return
                except:
                    continue
        
        # Se não encontrou mensagem para editar, cria nova
        table_message = await channel.send(table)
    except Exception as e:
        print(f"Erro ao atualizar tabela: {e}")
        try:
            table_message = await channel.send(create_boss_table())
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

    for boss, timers in boss_timers.items():
        respawn_time = timers['respawn_time']
        closed_time = timers['closed_time']
        
        if respawn_time is not None:
            if now >= respawn_time and closed_time is None:
                notifications.append(f"🟢 **{boss}** está disponível AGORA! (aberto até {respawn_time + timedelta(hours=4):%d/%m %H:%M} BRT)")
                boss_timers[boss]['closed_time'] = respawn_time + timedelta(hours=4)
            elif closed_time is not None and now >= closed_time:
                notifications.append(f"🔴 **{boss}** FECHADO!")
                boss_timers[boss] = {'death_time': None, 'respawn_time': None, 'closed_time': None}
            elif now >= (respawn_time - timedelta(minutes=5)) and closed_time is None:
                time_left = format_time_remaining(respawn_time)
                notifications.append(f"🟡 **{boss}** estará disponível em {time_left} ({respawn_time:%d/%m %H:%M} BRT)")

    if notifications:
        message = "**Notificações de Boss:**\n" + "\n".join(notifications)
        await channel.send(message)
    
    await update_table(channel)

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user.name}')
    print(f'Canal de notificação configurado para ID: {NOTIFICATION_CHANNEL_ID}')
    await bot.change_presence(activity=discord.Game(name="!bosshelp para ajuda"))
    
    # Inicia as tarefas
    check_boss_respawns.start()
    live_table_updater.start()
    
    # Envia a tabela inicial
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        await update_table(channel)

class BossButtonsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Anotar Boss", style=discord.ButtonStyle.green, custom_id="boss_button")
    async def boss_button_callback(self, interaction, button):
        view = discord.ui.View()
        select = discord.ui.Select(
            placeholder="Selecione um boss",
            options=[discord.SelectOption(label=boss) for boss in BOSSES]
        )
        
        async def select_callback(interaction):
            boss_name = select.values[0]
            modal = TimeInputModal(boss_name)
            await interaction.response.send_modal(modal)
        
        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Selecione o boss que foi derrotado:", view=view, ephemeral=True)

class TimeInputModal(discord.ui.Modal):
    def __init__(self, boss_name):
        super().__init__(title=f"Registrar {boss_name}")
        self.boss_name = boss_name
        
        self.time_input = discord.ui.TextInput(
            label="Horário da morte (HH:MM)",
            placeholder="Ex: 14:30",
            required=True,
            max_length=5
        )
        self.add_item(self.time_input)
    
    async def on_submit(self, interaction):
        try:
            hora, minuto = map(int, self.time_input.value.split(':'))
            now = datetime.now(brazil_tz)
            death_time = now.replace(hour=hora, minute=minuto, second=0, microsecond=0)
            
            if death_time > now:
                death_time -= timedelta(days=1)
            
            respawn_time = death_time + timedelta(hours=8)
            boss_timers[self.boss_name] = {
                'death_time': death_time,
                'respawn_time': respawn_time,
                'closed_time': respawn_time + timedelta(hours=4)
            }
            
            await interaction.response.send_message(
                f"✅ **{self.boss_name}** registrado:\n"
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

@bot.command(name='boss')
async def boss_command(ctx, boss_name: str = None, hora_morte: str = None):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return

    if boss_name is None or hora_morte is None:
        await ctx.send("Por favor, use: `!boss <nome_do_boss> HH:MM`\nExemplo: `!boss Hydra 14:30`")
        return
    
    boss_name = boss_name.title()
    if boss_name not in BOSSES:
        await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(BOSSES)}")
        return
    
    try:
        hora, minuto = map(int, hora_morte.split(':'))
        now = datetime.now(brazil_tz)
        death_time = now.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        
        if death_time > now:
            death_time -= timedelta(days=1)
        
        respawn_time = death_time + timedelta(hours=8)
        boss_timers[boss_name] = {
            'death_time': death_time,
            'respawn_time': respawn_time,
            'closed_time': respawn_time + timedelta(hours=4)
        }
        
        await ctx.send(
            f"✅ **{boss_name}** registrado:\n"
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
    table = create_boss_table(compact=compact)
    await ctx.send(table)

@bot.command(name='clearboss')
@commands.has_permissions(manage_messages=True)
async def clear_boss(ctx, boss_name: str):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return
    
    boss_name = boss_name.title()
    if boss_name not in BOSSES:
        await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(BOSSES)}")
        return
    
    boss_timers[boss_name] = {'death_time': None, 'respawn_time': None, 'closed_time': None}
    await ctx.send(f"✅ Timer do boss **{boss_name}** foi resetado.")
    await update_table(ctx.channel)

@bot.command(name='setupboss')
@commands.has_permissions(administrator=True)
async def setup_boss(ctx):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return
        
    embed = discord.Embed(
        title="Controle de Bosses",
        description="Clique no botão abaixo para anotar um boss derrotado",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed, view=BossButtonsView())
    await update_table(ctx.channel)

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
        name="!boss <nome> HH:MM",
        value="Registra a morte de um boss no horário especificado\nExemplo: `!boss Hydra 14:30`",
        inline=False
    )
    embed.add_field(
        name="Botão 'Anotar Boss'",
        value="Clique no botão para selecionar e registrar um boss derrotado com horário",
        inline=False
    )
    embed.add_field(
        name="!bosses [compact]",
        value="Mostra a tabela com os horários (adicione 'compact' para ver apenas bosses ativos)",
        inline=False
    )
    embed.add_field(
        name="!clearboss <nome>",
        value="(Moderadores) Reseta o timer de um boss",
        inline=False
    )
    embed.add_field(
        name="!setupboss",
        value="(Administradores) Configura o botão de anotação no chat",
        inline=False
    )
    embed.add_field(
        name="Bosses disponíveis",
        value="\n".join(BOSSES),
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