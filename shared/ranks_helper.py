import re

from shared.string_helper import convert_full_to_half
from shared.constants import (
    RANK_NAMES,
    RANK_ABBREVIATION_MAP
)

def extract_ranks_by_regexs(ranks_str: str, regexs: list[str]) -> str:
    if not ranks_str or not regexs:
        return ranks_str

    ranks_str = convert_full_to_half(ranks_str)

    for pattern in regexs:
        if not pattern:
            continue
        match_res = re.search(pattern, ranks_str)
        if match_res:
            try:
                return match_res.group("ranks_text").strip()
            except IndexError:
                return match_res.group(1).strip()
    return ranks_str

def parse_peer_to_peer(ranks_str: str) -> list:
    """第一份：點對點列舉型 (peer_to_peer)"""
    ranks = []
    if not ranks_str:
        return ranks
        
    tokens = re.split(r"[・,、/]", ranks_str)
    for t in tokens:
        t = t.strip()
        norm_t = RANK_ABBREVIATION_MAP.get(t, t)

        # 補字邏輯（如：初 -> 初段）
        if len(norm_t) == 1 and norm_t != "無":
            norm_t += "段"
            
        if norm_t in RANK_NAMES:
            ranks.append(norm_t)
            
    return ranks

def parse_range(ranks_str: str) -> list:
    """第二份：範圍連續型 (range)"""
    ranks = []
    if not ranks_str:
        return ranks
        
    range_symbol = '~'
    match_range = re.sub(r'[~～〜\-]', range_symbol, ranks_str)
    
    if range_symbol in match_range:
        start_part, end_part = match_range.split(range_symbol, 1)
        start_part, end_part = start_part.strip(), end_part.strip()

        is_eligible = False
        for rank in RANK_NAMES:
            if start_part in rank or rank in start_part:
                is_eligible = True

            if is_eligible:
                ranks.append(rank)

            if rank in end_part:
                break
                
    return ranks

def parse_hybrid(ranks_str: str) -> list:
    """第三份（新功能）：混合型 (hybrid)
    例如："無指定・初段～四段" 或 "初段-参段・五段"
    """
    ranks = []
    if not ranks_str:
        return ranks

    # 核心邏輯：先用列舉符號（・、逗號、斜線）切開
    tokens = re.split(r"[・,、/]", ranks_str)
    
    for token in tokens:
        token = token.strip()
        if not token:
            continue
            
        # 檢查該子片段是否包含範圍符號
        if re.search(r'[~～〜\-]', token):
            # 如果包含範圍符號，直接呼叫剛剛寫好的 parse_range 函式
            ranks.extend(parse_range(token))
        else:
            # 如果是單一值，直接呼叫剛剛寫好的 parse_peer_to_peer 函式
            ranks.extend(parse_peer_to_peer(token))
            
    return ranks

def format_parsed_ranks(rank_list: list, rank_names) -> str:
    """第四份：在這裡才轉成 set 做去重，並依照標準順序排序輸出"""
    if not rank_list:
        return ""
        
    # 完成自動去重
    unique_ranks = set(rank_list)

    # 依照標準 RANK_NAMES 的順序進行過濾與排序
    sorted_output = [r for r in rank_names if r in unique_ranks]
    parsed_ranks_str = " | ".join(sorted_output)

    return parsed_ranks_str