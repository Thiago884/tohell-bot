# drops.py
import discord
from discord import Embed
from discord.ext import commands
from shared_functions import get_boss_by_abbreviation
import os

# Dicionário com os drops de cada boss
BOSS_DROPS = {
    "Hydra": {
        "image": "hydra.png",
        "drops": [
            "50% 10x Jewel of Chaos",
            "50% SD Potion (15 unidades) ou Complex Potion (15 unidades)"
        ]
    },
    "Phoenix of Darkness": {
        "image": "Phoenix.png",
        "drops": [
            "40% 1 ~ 4x Loch's Feather",
            "30% 1 ~ 3x Crest of monarch",
            "30% 1 ~ 2x Spirit of Dark Horse ou Spirit of Dark Spirit"
        ]
    },
    "Genocider": {
        "image": "GENOCIDER.png",
        "drops": [
            "20% 1 ~ 10x Jewel of Harmony",
            "80% 5 ~ 10x Gemstone"
        ]
    },
    "Death Beam Knight": {
        "image": "DBK.png",
        "drops": [
            "20% Small Complex Potion +13 (30 ~ 100 unidades)",
            "25% Complex Potion +13 (30 ~ 100 unidades)",
            "20% Small SD Potion +13 (30 ~ 100 unidades)",
            "25% SD Potion +13 (30 ~ 100 unidades)",
            "5% Sign of lord (255 unidades)",
            "5% 5~10x Jewel of Guardian"
        ]
    },
    "Illusion of Kundun": {
        "image": "relics-of-kundun.jpg",
        "drops": [
            "25% Jewel of Bless (pacote 10 unidades)",
            "25% Jewel of Soul (pacote 10 unidades)",
            "5% Jewel of Bless (pacote 20 unidades)",
            "5% Jewel of Soul (pacote 20 unidades)",
            "5% Jewel of Bless (pacote 30 unidades)",
            "5% Jewel of Soul (pacote 30 unidades)",
            "5% SD Potion +13 (100 unidades) ou Complex Potion +13 (100 unidades)",
            "5% SD Potion +13 (50 unidades) ou Complex Potion +13 (50 unidades)",
            "5% 5x Large Healing Potion +13 (100 unidades)",
            "5% 5x Healing Potion +13 (60 unidades)",
            "10% 5x E-Zen"
        ]
    },
    "Hell Maine": {
        "image": "hellmaine.png",
        "drops": [
            "50% Jewel of Bless (pacote 30 ~ 60 unidades)",
            "50% Jewel of Soul (pacote 30 ~ 60 unidades)"
        ]
    },
    "Super Red Dragon": {
        "image": "super-red-dragon.jpg",
        "drops": [
            "50% Jewel of Bless (pacote 30 ~ 60 unidades)",
            "50% Jewel of Soul (pacote 30 ~ 60 unidades)"
        ]
    },
    "Rei Kundun": {
        "image": "Rei_Kundun.jpg",
        "drops": [
            "3x (três sorteios independentes):",
            "100% (por sorteio):",
            "53.85% Jewel of Bless (pacote 10 unidades)",
            "30.77% Jewel of Soul (pacote 10 unidades)",
            "7.69% Jewel of Bless (pacote 20 ~ 60 unidades)",
            "7.69% Jewel of Soul (pacote 20 ~ 60 unidades)",
            "",
            "3x (três sorteios independentes):",
            "100% (por sorteio):",
            "25% Item Ancient Aleatório",
            "75% Sem drop",
            "",
            "Probabilidades combinadas para Itens Ancient:",
            "0 Itens Ancient: 42%",
            "1 Item Ancient: 42%",
            "2 Itens Ancient: 14%",
            "3 Itens Ancient: 2%"
        ]
    }
}

def get_image_url(image_name):
    """Retorna a URL completa da imagem no Render"""
    base_url = os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:10000')
    return f"{base_url}/static/{image_name}"

async def setup_drops_command(bot):
    @bot.command(name='drops')
    async def drops_command(ctx, boss_name: str = None):
        """Mostra os drops de um boss específico"""
        if boss_name is None:
            # Mostrar lista de bosses se nenhum for especificado
            embed = Embed(
                title="📦 Drops de Bosses",
                description="Use `!drops <nome_do_boss>` para ver os drops específicos\n\nBosses disponíveis:",
                color=discord.Color.blue()
            )
            
            for boss in BOSS_DROPS.keys():
                embed.add_field(
                    name=boss,
                    value=f"`!drops {boss.split()[0].lower()}`",
                    inline=True
                )
            
            await ctx.send(embed=embed)
            return
        
        # Encontrar o nome completo do boss usando a abreviação
        full_boss_name = get_boss_by_abbreviation(boss_name, {boss: {} for boss in BOSS_DROPS.keys()})
        if full_boss_name is None:
            await ctx.send(
                f"Boss inválido. Bosses disponíveis: {', '.join(BOSS_DROPS.keys())}\n"
                "Abreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno"
            )
            return
        
        boss_data = BOSS_DROPS.get(full_boss_name)
        if not boss_data:
            await ctx.send("Informações de drops não encontradas para este boss.")
            return
        
        # Criar embed com os drops
        embed = Embed(
            title=f"📦 Drops do {full_boss_name}",
            color=discord.Color.gold()
        )
        
        if boss_data.get('image'):
            image_url = get_image_url(boss_data['image'])
            embed.set_thumbnail(url=image_url)
        
        drops_text = "\n".join(f"• {drop}" for drop in boss_data['drops'])
        embed.description = drops_text
        
        embed.set_footer(text=f"Use !drops sem parâmetros para ver a lista de bosses")
        
        await ctx.send(embed=embed)