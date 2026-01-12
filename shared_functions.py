from datetime import datetime, timedelta
import pytz
from typing import Optional, Tuple, Dict, List, Any

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
    "erohim": "ero"
}

def format_time_remaining(target_time: datetime) -> str:
    """Formata o tempo restante para HHh MMm"""
    now = datetime.now(brazil_tz)
    if not isinstance(target_time, datetime) or target_time < now:
        return "00h 00m"
    
    delta = target_time - now
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:02d}h {minutes:02d}m"

def get_boss_by_abbreviation(abbrev: str, boss_timers: Dict) -> Optional[str]:
    """Encontra o nome completo do boss a partir de uma abreviação"""
    abbrev = abbrev.lower()
    
    # Verifica primeiro no mapeamento oficial
    for boss, abbr in BOSS_ABBREVIATIONS.items():
        if abbr.lower() == abbrev:
            for b in boss_timers.keys():
                if b.lower() == boss:
                    return b
    
    # Busca por correspondência parcial
    for boss in boss_timers.keys():
        if abbrev in boss.lower():
            return boss
    
    return None

def get_next_bosses(boss_timers: Dict) -> List[Dict[str, Any]]:
    """Retorna os próximos bosses a abrir e os que já estão abertos"""
    now = datetime.now(brazil_tz)
    upcoming_bosses = []
    open_bosses = []
    
    for boss, salas in boss_timers.items():
        for sala, timers in salas.items():
            if not timers or 'respawn_time' not in timers:
                continue
                
            respawn_time = timers['respawn_time']
            closed_time = timers.get('closed_time')
            
            if not isinstance(respawn_time, datetime):
                continue
                
            if now >= respawn_time and closed_time and now < closed_time:
                open_bosses.append({
                    'boss': boss,
                    'sala': sala,
                    'respawn_time': respawn_time,
                    'closed_time': closed_time,
                    'time_left': format_time_remaining(closed_time),
                    'recorded_by': timers.get('recorded_by'),
                    'status': 'open'
                })
            elif now < respawn_time:
                upcoming_bosses.append({
                    'boss': boss,
                    'sala': sala,
                    'respawn_time': respawn_time,
                    'time_left': format_time_remaining(respawn_time),
                    'recorded_by': timers.get('recorded_by'),
                    'status': 'upcoming'
                })
    
    upcoming_bosses.sort(key=lambda x: x['respawn_time'])
    open_bosses.sort(key=lambda x: x['closed_time'])
    
    # CORREÇÃO: Retornar uma lista combinada corretamente
    # Primeiro os bosses abertos (status: open), depois os próximos (status: upcoming)
    all_bosses = []
    
    # Adiciona bosses abertos (se houver)
    if open_bosses:
        all_bosses.extend(open_bosses[:5])
    
    # Adiciona próximos bosses (se houver)
    if upcoming_bosses:
        all_bosses.extend(upcoming_bosses[:5])
    
    return all_bosses

def parse_time_input(time_str: str) -> Optional[Tuple[int, int]]:
    """Converte uma string de tempo em hora e minuto"""
    time_str = time_str.strip().lower()
    
    # Formato HH:MM
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                return None
    
    # Formato HHhMM
    if 'h' in time_str:
        parts = time_str.split('h')
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                return None
    
    # Apenas hora
    try:
        return int(time_str), 0
    except ValueError:
        return None

def validate_time(hour: int, minute: int) -> bool:
    """Valida se a hora e minuto são válidos"""
    return 0 <= hour <= 23 and 0 <= minute <= 59