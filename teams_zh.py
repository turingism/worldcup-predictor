# Repository summary: World Cup prediction analytics module.
"""
球队英文名 -> (中文名, 国旗 emoji) 映射 + 显示/反查辅助。

数据源里队名是英文，这里做本地化：网页显示「🇦🇷 阿根廷」，输入也接受中文/英文。
未收录的球队回退为英文原名（不影响功能）。
"""
from __future__ import annotations

# 英文 -> (中文, 国旗)
CN: dict[str, tuple[str, str]] = {
    # —— 2026 世界杯 48 强 ——
    "Algeria": ("阿尔及利亚", "🇩🇿"),
    "Argentina": ("阿根廷", "🇦🇷"),
    "Australia": ("澳大利亚", "🇦🇺"),
    "Austria": ("奥地利", "🇦🇹"),
    "Belgium": ("比利时", "🇧🇪"),
    "Bosnia and Herzegovina": ("波黑", "🇧🇦"),
    "Brazil": ("巴西", "🇧🇷"),
    "Canada": ("加拿大", "🇨🇦"),
    "Cape Verde": ("佛得角", "🇨🇻"),
    "Colombia": ("哥伦比亚", "🇨🇴"),
    "Croatia": ("克罗地亚", "🇭🇷"),
    "Curaçao": ("库拉索", "🇨🇼"),
    "Czech Republic": ("捷克", "🇨🇿"),
    "DR Congo": ("刚果（金）", "🇨🇩"),
    "Ecuador": ("厄瓜多尔", "🇪🇨"),
    "Egypt": ("埃及", "🇪🇬"),
    "England": ("英格兰", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "France": ("法国", "🇫🇷"),
    "Germany": ("德国", "🇩🇪"),
    "Ghana": ("加纳", "🇬🇭"),
    "Haiti": ("海地", "🇭🇹"),
    "Iran": ("伊朗", "🇮🇷"),
    "Iraq": ("伊拉克", "🇮🇶"),
    "Ivory Coast": ("科特迪瓦", "🇨🇮"),
    "Japan": ("日本", "🇯🇵"),
    "Jordan": ("约旦", "🇯🇴"),
    "Mexico": ("墨西哥", "🇲🇽"),
    "Morocco": ("摩洛哥", "🇲🇦"),
    "Netherlands": ("荷兰", "🇳🇱"),
    "New Zealand": ("新西兰", "🇳🇿"),
    "Norway": ("挪威", "🇳🇴"),
    "Panama": ("巴拿马", "🇵🇦"),
    "Paraguay": ("巴拉圭", "🇵🇾"),
    "Portugal": ("葡萄牙", "🇵🇹"),
    "Qatar": ("卡塔尔", "🇶🇦"),
    "Saudi Arabia": ("沙特阿拉伯", "🇸🇦"),
    "Scotland": ("苏格兰", "🏴󠁧󠁢󠁳󠁣󠁴󠁿"),
    "Senegal": ("塞内加尔", "🇸🇳"),
    "South Africa": ("南非", "🇿🇦"),
    "South Korea": ("韩国", "🇰🇷"),
    "Spain": ("西班牙", "🇪🇸"),
    "Sweden": ("瑞典", "🇸🇪"),
    "Switzerland": ("瑞士", "🇨🇭"),
    "Tunisia": ("突尼斯", "🇹🇳"),
    "Turkey": ("土耳其", "🇹🇷"),
    "United States": ("美国", "🇺🇸"),
    "Uruguay": ("乌拉圭", "🇺🇾"),
    "Uzbekistan": ("乌兹别克斯坦", "🇺🇿"),
    # —— 其它强队 / 常见对手 ——
    "Denmark": ("丹麦", "🇩🇰"),
    "Italy": ("意大利", "🇮🇹"),
    "Greece": ("希腊", "🇬🇷"),
    "Russia": ("俄罗斯", "🇷🇺"),
    "Nigeria": ("尼日利亚", "🇳🇬"),
    "Ukraine": ("乌克兰", "🇺🇦"),
    "Mali": ("马里", "🇲🇱"),
    "Poland": ("波兰", "🇵🇱"),
    "Serbia": ("塞尔维亚", "🇷🇸"),
    "Kosovo": ("科索沃", "🇽🇰"),
    "Venezuela": ("委内瑞拉", "🇻🇪"),
    "Chile": ("智利", "🇨🇱"),
    "Hungary": ("匈牙利", "🇭🇺"),
    "Wales": ("威尔士", "🏴󠁧󠁢󠁷󠁬󠁳󠁿"),
    "Romania": ("罗马尼亚", "🇷🇴"),
    "Slovenia": ("斯洛文尼亚", "🇸🇮"),
    "Georgia": ("格鲁吉亚", "🇬🇪"),
    "Republic of Ireland": ("爱尔兰", "🇮🇪"),
    "Cameroon": ("喀麦隆", "🇨🇲"),
    "Israel": ("以色列", "🇮🇱"),
    "Slovakia": ("斯洛伐克", "🇸🇰"),
    "Peru": ("秘鲁", "🇵🇪"),
    "Albania": ("阿尔巴尼亚", "🇦🇱"),
    "China PR": ("中国", "🇨🇳"),
    "Costa Rica": ("哥斯达黎加", "🇨🇷"),
    "Finland": ("芬兰", "🇫🇮"),
    "Iceland": ("冰岛", "🇮🇸"),
    "Bolivia": ("玻利维亚", "🇧🇴"),
    "Northern Ireland": ("北爱尔兰", "🏴"),
    "Basque Country": ("巴斯克", "🏴"),
}

# 俱乐部（多赛事扩展 P2：五大联赛近 7 季全部 144 队，键=football-data.co.uk 拼写）。
# 独立于 CN——国家队与俱乐部命名空间分开（"Monaco" 等潜在撞名），旗帜=联赛归属国。
CLUB: dict[str, tuple[str, str]] = {
    # —— 英超（含近年升降级队）——
    "Arsenal": ("阿森纳", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Aston Villa": ("阿斯顿维拉", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Bournemouth": ("伯恩茅斯", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Brentford": ("布伦特福德", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Brighton": ("布莱顿", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Burnley": ("伯恩利", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Cardiff": ("卡迪夫城", "🏴󠁧󠁢󠁷󠁬󠁳󠁿"), "Chelsea": ("切尔西", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Crystal Palace": ("水晶宫", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Everton": ("埃弗顿", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Fulham": ("富勒姆", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Huddersfield": ("哈德斯菲尔德", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Ipswich": ("伊普斯维奇", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Leeds": ("利兹联", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Leicester": ("莱斯特城", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Liverpool": ("利物浦", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Luton": ("卢顿", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Man City": ("曼城", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Man United": ("曼联", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Newcastle": ("纽卡斯尔", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Norwich": ("诺维奇", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Nott'm Forest": ("诺丁汉森林", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Sheffield United": ("谢菲尔德联", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Sunderland": ("桑德兰", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Southampton": ("南安普顿", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Tottenham": ("热刺", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "Watford": ("沃特福德", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "West Brom": ("西布朗", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"), "West Ham": ("西汉姆联", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    "Wolves": ("狼队", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"),
    # —— 西甲 ——
    "Alaves": ("阿拉维斯", "🇪🇸"), "Almeria": ("阿尔梅里亚", "🇪🇸"),
    "Ath Bilbao": ("毕尔巴鄂竞技", "🇪🇸"), "Ath Madrid": ("马德里竞技", "🇪🇸"),
    "Barcelona": ("巴塞罗那", "🇪🇸"), "Betis": ("皇家贝蒂斯", "🇪🇸"),
    "Cadiz": ("加的斯", "🇪🇸"), "Celta": ("塞尔塔", "🇪🇸"),
    "Eibar": ("埃瓦尔", "🇪🇸"), "Elche": ("埃尔切", "🇪🇸"),
    "Espanol": ("西班牙人", "🇪🇸"), "Getafe": ("赫塔费", "🇪🇸"),
    "Girona": ("赫罗纳", "🇪🇸"), "Granada": ("格拉纳达", "🇪🇸"),
    "Huesca": ("韦斯卡", "🇪🇸"), "Las Palmas": ("拉斯帕尔马斯", "🇪🇸"),
    "Leganes": ("莱加内斯", "🇪🇸"), "Levante": ("莱万特", "🇪🇸"),
    "Mallorca": ("马略卡", "🇪🇸"), "Osasuna": ("奥萨苏纳", "🇪🇸"), "Oviedo": ("奥维耶多", "🇪🇸"),
    "Real Madrid": ("皇家马德里", "🇪🇸"), "Sevilla": ("塞维利亚", "🇪🇸"),
    "Sociedad": ("皇家社会", "🇪🇸"), "Valencia": ("瓦伦西亚", "🇪🇸"),
    "Valladolid": ("巴利亚多利德", "🇪🇸"), "Vallecano": ("巴列卡诺", "🇪🇸"),
    "Villarreal": ("比利亚雷亚尔", "🇪🇸"),
    # —— 意甲 ——
    "Atalanta": ("亚特兰大", "🇮🇹"), "Benevento": ("贝内文托", "🇮🇹"),
    "Bologna": ("博洛尼亚", "🇮🇹"), "Brescia": ("布雷西亚", "🇮🇹"),
    "Cagliari": ("卡利亚里", "🇮🇹"), "Chievo": ("切沃", "🇮🇹"),
    "Como": ("科莫", "🇮🇹"), "Cremonese": ("克雷莫纳", "🇮🇹"),
    "Crotone": ("克罗托内", "🇮🇹"), "Empoli": ("恩波利", "🇮🇹"),
    "Fiorentina": ("佛罗伦萨", "🇮🇹"), "Frosinone": ("弗罗西诺内", "🇮🇹"),
    "Genoa": ("热那亚", "🇮🇹"), "Inter": ("国际米兰", "🇮🇹"),
    "Juventus": ("尤文图斯", "🇮🇹"), "Lazio": ("拉齐奥", "🇮🇹"),
    "Lecce": ("莱切", "🇮🇹"), "Milan": ("AC米兰", "🇮🇹"),
    "Monza": ("蒙扎", "🇮🇹"), "Napoli": ("那不勒斯", "🇮🇹"),
    "Parma": ("帕尔马", "🇮🇹"), "Pisa": ("比萨", "🇮🇹"), "Roma": ("罗马", "🇮🇹"),
    "Salernitana": ("萨勒尼塔纳", "🇮🇹"), "Sampdoria": ("桑普多利亚", "🇮🇹"),
    "Sassuolo": ("萨索洛", "🇮🇹"), "Spal": ("斯帕尔", "🇮🇹"),
    "Spezia": ("斯佩齐亚", "🇮🇹"), "Torino": ("都灵", "🇮🇹"),
    "Udinese": ("乌迪内斯", "🇮🇹"), "Venezia": ("威尼斯", "🇮🇹"),
    "Verona": ("维罗纳", "🇮🇹"),
    # —— 德甲 ——
    "Augsburg": ("奥格斯堡", "🇩🇪"), "Bayern Munich": ("拜仁慕尼黑", "🇩🇪"),
    "Bielefeld": ("比勒费尔德", "🇩🇪"), "Bochum": ("波鸿", "🇩🇪"),
    "Darmstadt": ("达姆施塔特", "🇩🇪"), "Dortmund": ("多特蒙德", "🇩🇪"),
    "Ein Frankfurt": ("法兰克福", "🇩🇪"), "FC Koln": ("科隆", "🇩🇪"),
    "Fortuna Dusseldorf": ("杜塞尔多夫", "🇩🇪"), "Freiburg": ("弗赖堡", "🇩🇪"),
    "Greuther Furth": ("菲尔特", "🇩🇪"), "Hannover": ("汉诺威96", "🇩🇪"),
    "Heidenheim": ("海登海姆", "🇩🇪"), "Hertha": ("柏林赫塔", "🇩🇪"),
    "Hamburg": ("汉堡", "🇩🇪"), "Hoffenheim": ("霍芬海姆", "🇩🇪"), "Holstein Kiel": ("基尔", "🇩🇪"),
    "Leverkusen": ("勒沃库森", "🇩🇪"), "M'gladbach": ("门兴格拉德巴赫", "🇩🇪"),
    "Mainz": ("美因茨", "🇩🇪"), "Nurnberg": ("纽伦堡", "🇩🇪"),
    "Paderborn": ("帕德博恩", "🇩🇪"), "RB Leipzig": ("RB莱比锡", "🇩🇪"),
    "Schalke 04": ("沙尔克04", "🇩🇪"), "St Pauli": ("圣保利", "🇩🇪"),
    "Stuttgart": ("斯图加特", "🇩🇪"), "Union Berlin": ("柏林联合", "🇩🇪"),
    "Werder Bremen": ("云达不莱梅", "🇩🇪"), "Wolfsburg": ("沃尔夫斯堡", "🇩🇪"),
    # —— 法甲 ——
    "Ajaccio": ("阿雅克肖", "🇫🇷"), "Amiens": ("亚眠", "🇫🇷"),
    "Angers": ("昂热", "🇫🇷"), "Auxerre": ("欧塞尔", "🇫🇷"),
    "Bordeaux": ("波尔多", "🇫🇷"), "Brest": ("布雷斯特", "🇫🇷"),
    "Caen": ("卡昂", "🇫🇷"), "Clermont": ("克莱蒙", "🇫🇷"),
    "Dijon": ("第戎", "🇫🇷"), "Guingamp": ("甘冈", "🇫🇷"),
    "Le Havre": ("勒阿弗尔", "🇫🇷"), "Lens": ("朗斯", "🇫🇷"),
    "Lille": ("里尔", "🇫🇷"), "Lorient": ("洛里昂", "🇫🇷"),
    "Lyon": ("里昂", "🇫🇷"), "Marseille": ("马赛", "🇫🇷"),
    "Metz": ("梅斯", "🇫🇷"), "Monaco": ("摩纳哥", "🇲🇨"),
    "Montpellier": ("蒙彼利埃", "🇫🇷"), "Nantes": ("南特", "🇫🇷"),
    "Nice": ("尼斯", "🇫🇷"), "Nimes": ("尼姆", "🇫🇷"),
    "Paris FC": ("巴黎FC", "🇫🇷"), "Paris SG": ("巴黎圣日耳曼", "🇫🇷"), "Reims": ("兰斯", "🇫🇷"),
    "Rennes": ("雷恩", "🇫🇷"), "St Etienne": ("圣埃蒂安", "🇫🇷"),
    "Strasbourg": ("斯特拉斯堡", "🇫🇷"), "Toulouse": ("图卢兹", "🇫🇷"),
    "Troyes": ("特鲁瓦", "🇫🇷"),
}


def disp(en: str) -> str:
    """英文队名 -> 显示串「🇦🇷 阿根廷」/「🏴󠁧󠁢󠁥󠁮󠁧󠁿 利物浦」；未收录回退英文原名。"""
    hit = CN.get(en) or CLUB.get(en)
    if hit:
        zh, flag = hit
        return f"{flag} {zh}"
    return en


# 反查表：英文 / 小写英文 / 中文 / 显示串 -> 英文（国家队优先注册，俱乐部不覆盖已有键）
_R: dict[str, str] = {}
for _src in (CN, CLUB):
    for _en, (_zh, _flag) in _src.items():
        for _k in (_en, _en.lower(), _zh, f"{_flag} {_zh}"):
            _R.setdefault(_k, _en)


def to_en(s: str) -> str | None:
    """把中文/显示串/英文统一解析回英文队名；无法识别返回 None。"""
    if not s:
        return None
    s = s.strip()
    return _R.get(s) or _R.get(s.lower())


def all_labels(en_list) -> list[str]:
    """给一组英文队名返回排序后的显示串列表（按中文/英文）。"""
    return sorted((disp(t) for t in en_list), key=lambda x: x)
