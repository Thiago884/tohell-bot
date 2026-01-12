# main.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, HTTPException
import os
import asyncio
from flask import Flask, send_from_directory
from threading import Thread
from collections import defaultdict
import traceback
from datetime import datetime, timedelta
import pytz
import random
# Importações ajustadas para pegar as funções diretamente
from boss_commands import (
    setup_boss_commands, 
    create_boss_embed, 
    create_next_bosses_embed, 
    create_ranking_embed,
    create_history_embed,
    update_table
)
from drops import setup_drops_command
from database import init_db, load_all_server_data, load_db_data, migrate_database_to_multitenant, get_server_config, set_server_config, get_all_server_configs
from utility_commands import create_unrecorded_embed
import logging
from slash_commands import setup_slash_commands

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuração do Flask (keep-alive)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Timers de Boss - Online"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/status')
def status():
    return "Bot is online and ready" if bot.is_ready() else "Bot is connecting", 200

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Configuração do Bot Discord
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

# Estruturas de dados MULTI-SERVIDOR
BOSSES = [
    "Super Red Dragon", "Hell Maine", "Illusion of Kundun",
    "Death Beam Knight", "Genocider", "Phoenix of Darkness",
    "Hydra", "Rei Kundun"
]

# Estrutura: {guild_id: {boss_name: {sala: dados}}}
boss_timers = defaultdict(lambda: {boss: {} for boss in BOSSES})

# Estrutura: {guild_id: {user_id: stats}}
user_stats = defaultdict(lambda: defaultdict(lambda: {
    'count': 0,
    'last_recorded': None,
    'username': 'Unknown'
}))

# Estrutura: {guild_id: {user_id: [boss_names]}}
user_notifications = defaultdict(lambda: defaultdict(list))

# Tabelas por servidor: {guild_id: message_object}
table_messages = {}

# Configurações por servidor
server_configs = {}

async def load_all_salas_for_guild(guild_id):
    """Carrega todas as salas do banco de dados para um servidor específico"""
    from database import get_all_salas_from_db
    
    default_salas = [1, 2, 3, 4, 5, 6, 7, 8]
    db_salas = await get_all_salas_from_db(guild_id)
    all_salas = sorted(list(set(default_salas + db_salas)))
    
    if guild_id not in boss_timers:
        boss_timers[guild_id] = {}
    
    for boss in BOSSES:
        if boss not in boss_timers[guild_id]:
            boss_timers[guild_id][boss] = {}
        
        for sala in all_salas:
            if boss == "Erohim" and sala != 20:
                continue
            if boss not in ["Genocider", "Super Red Dragon", "Hell Maine", "Death Beam Knight", "Erohim"] and sala == 20:
                continue
                
            if sala not in boss_timers[guild_id][boss]:
                boss_timers[guild_id][boss][sala] = {
                    'death_time': None,
                    'respawn_time': None,
                    'closed_time': None,
                    'recorded_by': None,
                    'opened_notified': False
                }

async def initialize_server(guild_id):
    """Inicializa um novo servidor no sistema"""
    try:
        logger.info(f"Inicializando servidor {guild_id}")
        config = await get_server_config(guild_id)
        
        if config:
            server_configs[guild_id] = {
                'notification_channel_id': config['notification_channel_id'],
                'table_channel_id': config['table_channel_id'],
                'table_message_id': config['table_message_id']
            }
        else:
            server_configs[guild_id] = {
                'notification_channel_id': None,
                'table_channel_id': None,
                'table_message_id': None
            }
        
        await load_all_salas_for_guild(guild_id)
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar servidor {guild_id}: {e}")
        return False

async def setup_server_channels(guild):
    """Configura os canais para um novo servidor"""
    try:
        channel_name = "boss-timer"
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        
        if not channel:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(send_messages=False),
                guild.me: discord.PermissionOverwrite(send_messages=True)
            }
            
            channel = await guild.create_text_channel(
                channel_name,
                topic="📋 Timer de Bosses - Use /bosshelp para ver comandos disponíveis",
                overwrites=overwrites
            )
            logger.info(f"Canal '{channel_name}' criado no servidor {guild.name}")
        
        server_configs[guild.id] = {
            'notification_channel_id': channel.id,
            'table_channel_id': channel.id,
            'table_message_id': None
        }
        
        await set_server_config(guild.id, channel.id, channel.id, None)
        
        embed = discord.Embed(
            title="🤖 Boss Timer Bot - Configurado!",
            description=f"O bot foi configurado com sucesso no canal {channel.mention}!\n\nUse `/bosshelp` para ver os comandos.",
            color=discord.Color.green()
        )
        await channel.send(embed=embed)
        return channel
    except Exception as e:
        logger.error(f"Erro ao configurar canais no servidor {guild.name}: {e}")
        return None

@bot.event
async def on_guild_join(guild):
    logger.info(f"🎉 Bot adicionado ao servidor: {guild.name}")
    await initialize_server(guild.id)
    await setup_server_channels(guild)

@bot.event
async def on_guild_remove(guild):
    logger.info(f"🚫 Bot removido do servidor: {guild.name}")
    if guild.id in boss_timers: del boss_timers[guild.id]
    if guild.id in user_stats: del user_stats[guild.id]
    if guild.id in user_notifications: del user_notifications[guild.id]
    if guild.id in server_configs: del server_configs[guild.id]

@bot.event
async def on_ready():
    """Evento disparado quando o bot está pronto"""
    logger.info("\n" + "="*50)
    logger.info(f'✅ Bot conectado como: {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'📊 Servidores: {len(bot.guilds)}')
    logger.info("="*50 + "\n")
    
    # 1. Inicialização do banco de dados e Carga de Dados
    logger.info("\nInicializando banco de dados...")
    try:
        await init_db()
        await migrate_database_to_multitenant()
        
        logger.info("Carregando dados de todos os servidores...")
        all_data = await load_all_server_data()
        
        for guild_id, guild_data in all_data.items():
            boss_timers[guild_id] = guild_data
            await load_db_data(boss_timers, user_stats, user_notifications, guild_id)
            await load_all_salas_for_guild(guild_id)
            
            config = await get_server_config(guild_id)
            if config:
                server_configs[guild_id] = {
                    'notification_channel_id': config['notification_channel_id'],
                    'table_channel_id': config['table_channel_id'],
                    'table_message_id': config['table_message_id']
                }
            else:
                server_configs[guild_id] = {'notification_channel_id': None, 'table_channel_id': None, 'table_message_id': None}
        
        logger.info("✅ Dados carregados com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco de dados: {e}")
        traceback.print_exc()
    
    # Inicializa servidores que o bot está mas não estavam no banco
    for guild in bot.guilds:
        if guild.id not in boss_timers:
            await initialize_server(guild.id)

    # 2. Configuração de Comandos Slash (GLOBAL)
    # Esta etapa deve ocorrer ANTES do sync e FORA do loop de guildas
    logger.info("Configurando comandos Slash globais...")
    try:
        # Wrapper para permitir que o slash command atualize a tabela correta
        # A função update_table original do boss_commands suporta isso se passarmos os argumentos certos
        async def global_update_wrapper(channel, guild_id=None):
            if not guild_id and channel:
                guild_id = channel.guild.id
            
            if guild_id:
                # Recupera a configuração para saber qual mensagem editar
                config = await get_server_config(guild_id)
                msg_obj = None
                
                # Tenta encontrar a mensagem na memória ou buscar no canal
                if config and config.get('table_message_id'):
                    try:
                        if channel:
                            msg_obj = await channel.fetch_message(config['table_message_id'])
                    except:
                        pass
                
                # Chama a função de update original passando os dados corretos
                # Nota: setup_boss_commands retorna lambdas, mas aqui estamos chamando direto
                # Precisamos recriar a lógica de update_table para usar no slash
                from views import BossControlView
                
                server_data = boss_timers.get(guild_id, {})
                server_stats = user_stats.get(guild_id, {})
                server_notif = user_notifications.get(guild_id, {})
                
                embed = create_boss_embed(server_data)
                
                view = BossControlView(
                    bot,
                    server_data,
                    server_stats,
                    server_notif,
                    msg_obj,
                    channel.id if channel else config.get('table_channel_id'),
                    lambda: global_update_wrapper(channel, guild_id),
                    lambda b=server_data: create_next_bosses_embed(b),
                    lambda: create_ranking_embed(server_stats),
                    lambda: create_history_embed(bot, server_data),
                    lambda: create_unrecorded_embed(bot, server_data)
                )
                
                if msg_obj:
                    await msg_obj.edit(embed=embed, view=view)
                elif channel:
                    new_msg = await channel.send(embed=embed, view=view)
                    await set_server_config(guild_id, config.get('notification_channel_id'), channel.id, new_msg.id)

        # Configura os comandos de Drop
        await setup_drops_command(bot)

        # Configura os comandos Slash principais (Setup, Registro, etc)
        # Passamos os dicionários GLOBAIS e as funções helpers
        await setup_slash_commands(
            bot, 
            boss_timers, 
            user_stats, 
            user_notifications,
            None, # table_message global não existe
            None, # channel_id global não existe
            create_boss_embed,
            global_update_wrapper,
            create_next_bosses_embed,
            create_ranking_embed,
            create_history_embed,
            create_unrecorded_embed
        )
        logger.info("✅ Comandos Slash configurados na árvore.")

    except Exception as e:
        logger.error(f"❌ Erro ao configurar comandos Slash: {e}")
        traceback.print_exc()

    # 3. Sincronização de Comandos (Ocorre DEPOIS de adicionar os comandos)
    logger.info("Sincronizando comandos com o Discord...")
    try:
        # Sincroniza globalmente
        synced = await bot.tree.sync()
        logger.info(f"✅ {len(synced)} comandos slash sincronizados globalmente!")
        
        # Opcional: Copiar para guildas específicas para update instantâneo em desenvolvimento
        # Mas para produção, o sync global é suficiente (pode levar até 1h para aparecer globalmente, mas instantâneo se for a primeira vez)
        # Para forçar atualização imediata em todos os servidores:
        for guild in bot.guilds:
             bot.tree.copy_global_to(guild=guild)
             await bot.tree.sync(guild=guild)
        logger.info("✅ Comandos sincronizados em todas as guildas locais.")
        
    except Exception as e:
        logger.error(f"❌ Erro ao sincronizar comandos: {e}")
        traceback.print_exc()
    
    # 4. Inicia Tasks de Background (Atualização de tabelas e respawns)
    logger.info("\nIniciando tasks de background...")
    try:
        # Esta função inicia as tasks de loop para verificar respawns em todos os servidores
        # Passamos dados fictícios apenas para inicializar as tasks, pois elas usam as variáveis globais internamente
        # na implementação do boss_commands.py (versão multi-server)
        
        # Nota: O setup_boss_commands original foi modificado para retornar funções E iniciar tasks
        # Vamos chamá-lo uma vez para iniciar as tasks multi-servidor
        
        # Precisamos garantir que ele pegue os objetos globais corretos
        await setup_boss_commands(
            bot, 
            boss_timers, # Passa o dict global
            user_stats, 
            user_notifications, 
            None, 
            0
        )
        
        logger.info("✅ Tasks de background iniciadas.")
        
    except Exception as e:
        logger.error(f"❌ Erro ao iniciar tasks: {e}")
        traceback.print_exc()
    
    # Atualiza presença do bot
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name=f"{len(bot.guilds)} servidores | /bosshelp"
    ))
    
    logger.info("\n✅ Bot totalmente inicializado e pronto para uso!")

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Sincroniza comandos slash manualmente (apenas dono do bot)"""
    msg = await ctx.send("⏳ Sincronizando...")
    try:
        synced = await bot.tree.sync()
        content = f"✅ {len(synced)} comandos sincronizados globalmente."
        
        if ctx.guild:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced_guild = await bot.tree.sync(guild=ctx.guild)
            content += f"\n✅ {len(synced_guild)} comandos sincronizados neste servidor."
        
        await msg.edit(content=content)
    except Exception as e:
        await msg.edit(content=f"❌ Erro ao sincronizar: {e}")
        traceback.print_exc()

@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    """Comando legado de setup (redireciona para slash)"""
    await ctx.send("Por favor, use o comando `/setup` para configurar o bot.")

@bot.command()
@commands.is_owner()
async def servers(ctx):
    """Mostra informações sobre todos os servidores (apenas dono)"""
    embed = discord.Embed(
        title="📊 Servidores do Bot",
        description=f"Total: {len(bot.guilds)} servidores",
        color=discord.Color.blue()
    )
    
    for guild in bot.guilds:
        config = server_configs.get(guild.id, {})
        channel_info = "Não configurado"
        
        if config.get('notification_channel_id'):
            channel = guild.get_channel(config['notification_channel_id'])
            channel_info = f"#{channel.name}" if channel else "Canal não encontrado"
        
        embed.add_field(
            name=guild.name,
            value=f"ID: {guild.id}\nMembros: {guild.member_count}\nCanal: {channel_info}",
            inline=False
        )
    
    await ctx.send(embed=embed)

def keep_alive():
    """Inicia o servidor Flask"""
    t = Thread(target=run_flask, daemon=True)
    t.start()

async def shutdown_sequence():
    """Executa o desligamento limpo"""
    logger.info("\n🛑 Iniciando sequência de desligamento...")
    
    if hasattr(bot, 'boss_commands_shutdown'):
        await bot.boss_commands_shutdown()
    
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    
    logger.info("✅ Sequência de desligamento concluída")

async def main():
    keep_alive()
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("\n❌ ERRO: Token não encontrado!")
        return
    
    logger.info("\n🔑 Iniciando bot...")
    
    try:
        async with bot:
            await bot.start(token)
    except KeyboardInterrupt:
        logger.info("\n🛑 Desligamento solicitado pelo usuário")
    except Exception as e:
        logger.error(f"\n❌ Erro fatal: {e}", exc_info=True)
    finally:
        await shutdown_sequence()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Execução interrompida pelo usuário")
    except Exception as e:
        logger.error(f"\n❌ Erro fatal: {e}", exc_info=True)