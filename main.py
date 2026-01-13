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
    "Hydra", "Rei Kundun", "Erohim"
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

async def initialize_guild_data(guild_id: int):
    """Inicializa os dados de um servidor específico"""
    if guild_id not in boss_timers:
        # Inicializar com todos os bosses
        bosses_list = [
            "Hydra", "Phoenix of Darkness", "Genocider", "Death Beam Knight",
            "Hell Maine", "Super Red Dragon", "Illusion of Kundun", 
            "Rei Kundun", "Erohim"
        ]
        
        boss_timers[guild_id] = {}
        for boss in bosses_list:
            boss_timers[guild_id][boss] = {}
            # Inicializar com salas padrão
            for sala in range(1, 9):
                boss_timers[guild_id][boss][sala] = {
                    'death_time': None,
                    'respawn_time': None,
                    'closed_time': None,
                    'recorded_by': None,
                    'opened_notified': False
                }
    
    if guild_id not in user_stats:
        user_stats[guild_id] = {}
    
    if guild_id not in user_notifications:
        user_notifications[guild_id] = {}

async def load_all_salas_for_guild(guild_id):
    """Carrega todas as salas do banco de dados para um servidor específico"""
    from database import get_all_salas_from_db
    
    default_salas = [1, 2, 3, 4, 5, 6, 7, 8]
    db_salas = await get_all_salas_from_db(guild_id)
    all_salas = sorted(list(set(default_salas + db_salas)))
    
    if guild_id not in boss_timers:
        boss_timers[guild_id] = {}
    
    # Inicializar todos os bosses com estrutura vazia
    bosses_list = [
        "Super Red Dragon", "Hell Maine", "Illusion of Kundun",
        "Death Beam Knight", "Genocider", "Phoenix of Darkness",
        "Hydra", "Rei Kundun", "Erohim"
    ]
    
    for boss in bosses_list:
        if boss not in boss_timers[guild_id]:
            boss_timers[guild_id][boss] = {}
        
        for sala in all_salas:
            # Regras especiais para sala 20
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
        
        # Inicializar os dados do servidor primeiro
        await initialize_guild_data(guild_id)
        
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
        
        # Carregar salas específicas
        await load_all_salas_for_guild(guild_id)
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar servidor {guild_id}: {e}")
        return False

async def initialize_all_servers():
    """Inicializa dados para todos os servidores onde o bot está presente"""
    logger.info("Inicializando dados para todos os servidores...")
    
    # Primeiro, carregar todas as configurações do banco
    all_configs = await get_all_server_configs()
    config_dict = {config['guild_id']: config for config in all_configs}
    
    # Para cada servidor do bot
    for guild in bot.guilds:
        guild_id = guild.id
        
        # Inicializar estruturas de dados se não existirem
        if guild_id not in boss_timers:
            await initialize_guild_data(guild_id)
        
        # Carregar configuração do servidor
        if guild_id in config_dict:
            config = config_dict[guild_id]
            server_configs[guild_id] = {
                'notification_channel_id': config.get('notification_channel_id'),
                'table_channel_id': config.get('table_channel_id'),
                'table_message_id': config.get('table_message_id')
            }
        else:
            server_configs[guild_id] = {
                'notification_channel_id': None,
                'table_channel_id': None,
                'table_message_id': None
            }
    
    # Agora carregar dados do banco
    success = await load_db_data(boss_timers, user_stats, user_notifications)
    if success:
        logger.info(f"Dados carregados para {len(boss_timers)} servidores")
    else:
        logger.error("Falha ao carregar dados do banco")

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
    
    try:
        # 1. Inicialização do banco de dados
        logger.info("\nInicializando banco de dados...")
        await init_db()
        await migrate_database_to_multitenant()
        
        # 2. Inicializar estruturas para todos os servidores
        logger.info("Inicializando estruturas para todos os servidores...")
        for guild in bot.guilds:
            guild_id = guild.id
            
            # Inicializar se não existir
            if guild_id not in boss_timers:
                boss_timers[guild_id] = {}
            
            if guild_id not in user_stats:
                user_stats[guild_id] = {}
            
            if guild_id not in user_notifications:
                user_notifications[guild_id] = {}
        
        # 3. Carregar dados do banco e configs
        logger.info("Carregando dados de todos os servidores...")
        all_configs = await get_all_server_configs()
        
        if all_configs:
            # Inicializa a estrutura base para os servidores configurados
            for config in all_configs:
                guild_id = config['guild_id']
                await initialize_server(guild_id)
        
        # CORREÇÃO: Carregar dados do banco SEMPRE, independente de haver configs ou não
        logger.info("Buscando dados salvos no banco de dados...")
        success = await load_db_data(boss_timers, user_stats, user_notifications)
        if success:
            logger.info(f"Dados carregados para {len(boss_timers)} servidores")
        else:
            logger.error("Falha ao carregar dados do banco")
        
        # 4. Carregar configurações de todos os servidores
        logger.info("Carregando configurações de todos os servidores...")
        for guild_id in boss_timers.keys():
            config = await get_server_config(guild_id)
            if config:
                server_configs[guild_id] = {
                    'notification_channel_id': config.get('notification_channel_id'),
                    'table_channel_id': config.get('table_channel_id'),
                    'table_message_id': config.get('table_message_id')
                }
            else:
                server_configs[guild_id] = {'notification_channel_id': None, 'table_channel_id': None, 'table_message_id': None}
        
        logger.info("✅ Dados carregados com sucesso!")
        
        # 5. Configurar comandos slash
        logger.info("Configurando comandos Slash...")
        
        # Configurar comando drops
        await setup_drops_command(bot)
        
        # CORREÇÃO: Criar função de update_table para cada servidor
        def create_update_table_func_for_guild(guild_id):
            async def update_table_for_guild(channel):
                if not channel or guild_id not in boss_timers:
                    return
                
                config = server_configs.get(guild_id)
                if not config or not config.get('table_channel_id'):
                    return
                
                server_data = boss_timers.get(guild_id, {})
                server_user_stats = user_stats.get(guild_id, {})
                server_user_notifications = user_notifications.get(guild_id, {})
                
                # Buscar mensagem existente ou criar nova
                if config['table_message_id']:
                    try:
                        table_msg = await channel.fetch_message(config['table_message_id'])
                    except discord.NotFound:
                        table_msg = None
                        config['table_message_id'] = None
                else:
                    table_msg = None
                
                embed = create_boss_embed(server_data)
                view = BossControlView(
                    bot,
                    server_data,
                    server_user_stats,
                    server_user_notifications,
                    table_msg,
                    config['table_channel_id'],
                    lambda: update_table_for_guild(channel),
                    lambda: create_next_bosses_embed(server_data),
                    lambda: create_ranking_embed(server_user_stats),
                    lambda: create_history_embed(bot, server_data),
                    lambda: create_unrecorded_embed(bot, server_data)
                )
                
                if table_msg:
                    try:
                        await table_msg.edit(embed=embed, view=view)
                    except discord.NotFound:
                        # Se a mensagem foi deletada, enviar nova
                        new_msg = await channel.send(embed=embed, view=view)
                        config['table_message_id'] = new_msg.id
                        await set_server_config(guild_id, config.get('notification_channel_id'), config['table_channel_id'], new_msg.id)
                else:
                    new_msg = await channel.send(embed=embed, view=view)
                    config['table_message_id'] = new_msg.id
                    await set_server_config(guild_id, config.get('notification_channel_id'), config['table_channel_id'], new_msg.id)
            
            return update_table_for_guild

        # Configurar comandos principais do slash_commands.py
        from slash_commands import setup_slash_commands

        # Para cada servidor, criar função específica
        update_table_functions = {}
        for guild_id in boss_timers.keys():
            update_table_functions[guild_id] = create_update_table_func_for_guild(guild_id)

        # Função genérica que busca a função específica do servidor
        async def update_table_generic(channel, guild_id=None):
            if not guild_id:
                # Se não especificou guild_id, tenta pegar do contexto atual
                if channel and hasattr(channel, 'guild'):
                    guild_id = channel.guild.id
                else:
                    return
            
            if guild_id in update_table_functions:
                await update_table_functions[guild_id](channel)
            else:
                # Se não existir, cria uma nova função
                update_table_functions[guild_id] = create_update_table_func_for_guild(guild_id)
                await update_table_functions[guild_id](channel)

        await setup_slash_commands(
            bot, 
            boss_timers, 
            user_stats, 
            user_notifications,
            None,
            0,
            create_boss_embed,
            update_table_generic,  # AGORA PASSANDO A FUNÇÃO CORRETA
            create_next_bosses_embed,
            create_ranking_embed,
            create_history_embed,
            create_unrecorded_embed
        )
        
        # 6. Sincronizar comandos GLOBALMENTE
        logger.info("Sincronizando comandos com o Discord...")
        
        # Sincronizar globalmente
        synced = await bot.tree.sync()
        logger.info(f"✅ {len(synced)} comandos slash sincronizados globalmente!")
        
        # Sincronizar por servidor também
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                synced_guild = await bot.tree.sync(guild=guild)
                logger.info(f"  ✅ {len(synced_guild)} comandos sincronizados no servidor {guild.name}")
            except Exception as e:
                logger.error(f"  ❌ Erro ao sincronizar no servidor {guild.name}: {e}")
        
        # 7. Iniciar tasks de background
        logger.info("\nIniciando tasks de background...")
        await setup_boss_commands(
            bot, 
            boss_timers,
            user_stats, 
            user_notifications, 
            None, 
            0
        )
        logger.info("✅ Tasks de background iniciadas.")
        
        # SOLUÇÃO RECOMENDADA: Remover as linhas problemáticas que tentavam importar periodic_table_update_multi
        # As tasks são iniciadas automaticamente dentro de setup_boss_commands
        logger.info("✅ Task de atualização periódica da tabela iniciada (intervalo: 60-240 minutos)")
        
        # Atualizar presença
        await bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(bot.guilds)} servidores | /bosshelp"
        ))
        
        logger.info("\n✅ Bot totalmente inicializado e pronto para uso!")
        
    except Exception as e:
        logger.error(f"❌ Erro durante inicialização: {e}")
        traceback.print_exc()

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