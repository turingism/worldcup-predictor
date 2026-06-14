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


def disp(en: str) -> str:
    """英文队名 -> 显示串「🇦🇷 阿根廷」；未收录回退英文原名。"""
    if en in CN:
        zh, flag = CN[en]
        return f"{flag} {zh}"
    return en


# 反查表：英文 / 小写英文 / 中文 / 显示串 -> 英文
_R: dict[str, str] = {}
for _en, (_zh, _flag) in CN.items():
    _R[_en] = _en
    _R[_en.lower()] = _en
    _R[_zh] = _en
    _R[f"{_flag} {_zh}"] = _en


def to_en(s: str) -> str | None:
    """把中文/显示串/英文统一解析回英文队名；无法识别返回 None。"""
    if not s:
        return None
    s = s.strip()
    return _R.get(s) or _R.get(s.lower())


def all_labels(en_list) -> list[str]:
    """给一组英文队名返回排序后的显示串列表（按中文/英文）。"""
    return sorted((disp(t) for t in en_list), key=lambda x: x)
